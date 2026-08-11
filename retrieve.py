"""
retrieve.py
-----------------
Recherche par similarite cosinus sur les embeddings pre-calcules.

Pour un POC a cette echelle (~90 chunks), une base vectorielle dediee
(Pinecone, Chroma, pgvector...) est inutile : une simple matrice numpy en
memoire suffit et repond en quelques millisecondes. Si le corpus grandit
significativement (autres matieres ajoutees), il sera temps de
migrer vers une vraie base vectorielle - l'interface ci-dessous (search())
resterait identique cote appelant.

Usage:
    from retrieve import Retriever
    r = Retriever("embeddings.npz")
    results = r.search(query_embedding, top_k=5, exclude_historique=True)
"""
import json

import numpy as np

# Score de similarite cosinus en-dessous duquel un chunk est considere non
# pertinent et ecarte, meme s'il fait partie du top_k. Calibre empiriquement
# sur le corpus initial (~815 chunks) : une question totalement hors-sujet
# plafonne vers 0.25-0.28, alors qu'une question pertinente mais formulee
# differemment du texte legal descend rarement sous 0.45-0.50.
# Abaisse de 0.30 a 0.25 le 2026-07-31 : apres l'ajout massif de 261 articles
# de l'Ancien Code civil (corpus etat_civil passe de 815 a 1081 chunks), un
# cas pertinent mais limite (match proche du seuil, fragile au ré-embedding -
# l'API d'embedding n'est pas parfaitement identique d'un appel a l'autre) a
# bascule sous 0.30 et fait disparaitre une reponse qui fonctionnait avant.
# 0.25 redonne de la marge a ces cas limites, au prix d'un risque legerement
# accru de laisser passer un chunk hors-sujet (voir la calibration ci-dessus,
# qui n'a pas ete rejouee sur le corpus elargi).
DEFAULT_MIN_SCORE = 0.25


class Retriever:
    def __init__(self, embeddings_path="embeddings.npz"):
        data = np.load(embeddings_path, allow_pickle=True)
        self.embeddings = data["embeddings"]  # shape (N, dim)
        self.chunk_ids = list(data["chunk_ids"])

        meta_path = embeddings_path.replace(".npz", "_meta.jsonl")
        self.meta_by_id = {}
        with open(meta_path, encoding="utf-8") as f:
            for line in f:
                m = json.loads(line)
                self.meta_by_id[m["chunk_id"]] = m

        # Normalisation pour que le produit scalaire = similarite cosinus
        norms = np.linalg.norm(self.embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1e-9
        self.normalized = self.embeddings / norms

    def search(self, query_embedding, top_k=5, exclude_historique=True,
               categorie=None, sous_categorie=None, matiere=None,
               min_score=DEFAULT_MIN_SCORE):
        q = np.array(query_embedding, dtype=np.float32)
        q = q / (np.linalg.norm(q) + 1e-9)

        scores = self.normalized @ q  # similarite cosinus pour chaque chunk

        candidates = []
        for idx, score in enumerate(scores):
            cid = self.chunk_ids[idx]
            meta = self.meta_by_id[cid]

            if exclude_historique and meta.get("statut_entree") == "historique_absorbe":
                continue
            if categorie and meta.get("categorie") != categorie:
                continue
            if sous_categorie and meta.get("sous_categorie") != sous_categorie:
                continue
            if matiere and meta.get("matiere") != matiere:
                continue
            if min_score is not None and score < min_score:
                continue

            candidates.append((score, meta))

        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[:top_k]

    def available_matieres(self):
        """Liste triee des matieres presentes dans l'index (pour un selecteur UI)."""
        return sorted({m["matiere"] for m in self.meta_by_id.values() if m.get("matiere")})


def format_results_for_prompt(results):
    """Formate les resultats de recherche en un bloc de contexte pour le LLM,
    avec une citation exacte pour chaque passage : titre du texte + numero
    d'article/section pour un texte officiel, ou reference interne unifiee
    "VDB-<code>" (sans le nom de la commune source) pour une pratique
    validee."""
    blocks = []
    for score, meta in results:
        if meta.get("statut_entree") == "reference_interne":
            source = f"VDB-{meta['numero']}" if meta.get("numero") else "VDB (pratique validee)"
            if meta.get("date_reponse"):
                source += f", {meta['date_reponse']}"
        else:
            source = f"{meta['document_titre']}"
            if meta.get("numero"):
                source += f", art./section {meta['numero']}"
            if meta.get("date_reponse"):
                source += f", {meta['date_reponse']}"
        if meta.get("base_legale_associee"):
            source += f" [S'APPUIE SUR : {meta['base_legale_associee']}]"
        blocks.append(
            f"### Source: {source} (pertinence: {score:.2f})\n{meta['text_for_embedding']}"
        )
    return "\n\n".join(blocks)
