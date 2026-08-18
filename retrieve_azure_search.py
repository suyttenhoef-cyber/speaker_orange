"""
retrieve_azure_search.py
-----------------
Phase 1 de la roadmap Option B : meme interface que retrieve.py (search(),
available_matieres()), mais backend Azure AI Search au lieu de numpy en
memoire. Voir azure_search_setup.py pour la creation/le peuplement de l'index.

Calibration du score : Azure AI Search ne renvoie pas la similarite cosinus
brute pour une recherche vectorielle, mais score_azure = 1 / (2 - cosinus).
Verifie empiriquement sur cet index (2026-07) : requete = embedding exact
d'un chunk existant -> score_azure=1.0 pour le chunk lui-meme (cosinus=1),
puis 0.8572/0.7444 pour les chunks suivants, ce qui correspond exactement a
1/(2-cos) avec cos=0.8334/0.6567 mesures en parallele via numpy. On reconvertit
donc chaque score_azure en cosinus brut pour reappliquer DEFAULT_MIN_SCORE
(calibre sur l'echelle cosinus dans retrieve.py) sans changer son sens, et
pour que l'UI affiche une "pertinence" comparable entre les deux backends.
"""
import os

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery

from retrieve import DEFAULT_MIN_SCORE, format_results_for_prompt  # noqa: F401  (reexport)

SELECT_FIELDS = [
    "chunk_id", "matiere", "categorie", "sous_categorie", "statut_entree",
    "document_titre", "numero", "date_reponse", "text_for_embedding",
    "base_legale_associee",
]

# Doit correspondre a SEMANTIC_CONFIG_NAME dans azure_search_setup.py.
SEMANTIC_CONFIG_NAME = "default-semantic-config"


def azure_score_to_cosine(azure_score):
    """Inverse de score_azure = 1 / (2 - cosinus) -> cosinus = 2 - 1/score_azure."""
    return 2 - 1 / azure_score


def _build_filter(exclude_historique, categorie, sous_categorie, matiere):
    clauses = []
    if exclude_historique:
        clauses.append("statut_entree ne 'historique_absorbe'")
    if categorie:
        clauses.append(f"categorie eq '{categorie}'")
    if sous_categorie:
        clauses.append(f"sous_categorie eq '{sous_categorie}'")
    if matiere:
        clauses.append(f"matiere eq '{matiere}'")
    return " and ".join(clauses) if clauses else None


class AzureSearchRetriever:
    def __init__(self, endpoint=None, index_name=None, admin_key=None):
        endpoint = endpoint or os.environ["AZURE_SEARCH_ENDPOINT"]
        index_name = index_name or os.environ.get("AZURE_SEARCH_INDEX_NAME", "chatbot-etat-civil-chunks")
        admin_key = admin_key or os.environ["AZURE_SEARCH_ADMIN_KEY"]
        self.client = SearchClient(endpoint, index_name, AzureKeyCredential(admin_key))

    def search(self, query_embedding, top_k=5, exclude_historique=True,
               categorie=None, sous_categorie=None, matiere=None,
               min_score=DEFAULT_MIN_SCORE):
        # On sur-echantillonne (k_nearest_neighbors > top_k) car le filtre
        # min_score s'applique cote client, apres coup - sinon on risquerait
        # de renvoyer moins de top_k resultats alors que des candidats
        # pertinents existent juste en-dehors des k plus proches voisins bruts.
        k = max(top_k * 5, 50)
        vector_query = VectorizedQuery(
            vector=list(query_embedding), k_nearest_neighbors=k, fields="content_vector"
        )
        filter_str = _build_filter(exclude_historique, categorie, sous_categorie, matiere)

        results = self.client.search(
            search_text=None,
            vector_queries=[vector_query],
            filter=filter_str,
            select=SELECT_FIELDS,
        )

        candidates = []
        for r in results:
            cosine = azure_score_to_cosine(r["@search.score"])
            if min_score is not None and cosine < min_score:
                continue
            meta = {f: r.get(f) for f in SELECT_FIELDS}
            candidates.append((cosine, meta))

        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[:top_k]

    def search_hybrid(self, query_text, query_embedding, top_k=5, exclude_historique=True,
                       categorie=None, sous_categorie=None, matiere=None):
        """Recherche hybride : combine BM25 (search_text, sur le champ
        'text_for_embedding') et recherche vectorielle - Azure AI Search
        fusionne les deux classements via RRF (Reciprocal Rank Fusion) et
        renvoie un score de fusion, PAS une similarite cosinus. Le seuil
        min_score/DEFAULT_MIN_SCORE (calibre sur l'echelle cosinus) n'a donc
        pas de sens ici : on ne filtre pas par score, on se repose sur top_k
        et sur filter_applicable_practices() en aval pour la precision
        semantique fine."""
        k = max(top_k * 5, 50)
        vector_query = VectorizedQuery(
            vector=list(query_embedding), k_nearest_neighbors=k, fields="content_vector"
        )
        filter_str = _build_filter(exclude_historique, categorie, sous_categorie, matiere)

        results = self.client.search(
            search_text=query_text,
            vector_queries=[vector_query],
            filter=filter_str,
            select=SELECT_FIELDS,
            top=top_k,
        )

        candidates = []
        for r in results:
            meta = {f: r.get(f) for f in SELECT_FIELDS}
            # Score de fusion RRF (pas une similarite cosinus) - conserve tel
            # quel pour information/tri, ne pas le comparer a DEFAULT_MIN_SCORE.
            candidates.append((r["@search.score"], meta))

        return candidates

    def search_semantic(self, query_text, query_embedding, top_k=5, exclude_historique=True,
                         categorie=None, sous_categorie=None, matiere=None):
        """Recherche vectorielle + BM25 pour constituer un pool de candidats,
        puis reranking par le semantic ranker Azure (cross-encoder, pas une
        fusion de rangs comme le RRF de search_hybrid) - le score renvoye est
        le reranker_score du modele, pas une similarite cosinus. Disponible
        en plan gratuit avec quota mensuel limite (verifie via `az search
        service show` : semanticSearch: "free")."""
        k = max(top_k * 5, 50)
        vector_query = VectorizedQuery(
            vector=list(query_embedding), k_nearest_neighbors=k, fields="content_vector"
        )
        filter_str = _build_filter(exclude_historique, categorie, sous_categorie, matiere)

        results = self.client.search(
            search_text=query_text,
            vector_queries=[vector_query],
            filter=filter_str,
            select=SELECT_FIELDS,
            query_type="semantic",
            semantic_configuration_name=SEMANTIC_CONFIG_NAME,
            top=top_k,
        )

        candidates = []
        for r in results:
            meta = {f: r.get(f) for f in SELECT_FIELDS}
            score = r.get("@search.reranker_score")
            if score is None:
                score = r["@search.score"]
            candidates.append((score, meta))

        return candidates

    def available_matieres(self):
        results = self.client.search(search_text="*", select=["matiere"], top=1000)
        return sorted({r["matiere"] for r in results if r.get("matiere")})
