"""
azure_search_setup.py
----------------------
Phase 1 de la roadmap Option B (roadmap_technique_option_b.md) : cree l'index
Azure AI Search et y pousse les chunks + embeddings deja calcules par
chunk_builder.py / embed_chunks.py, sans recalculer les embeddings.

Reutilise exactement le meme schema de metadonnees que retrieve.py (voir
embeddings_meta.jsonl) - seul le backend de recherche change, la logique de
filtrage (matiere, statut_entree, min_score) est reproduite a l'identique
dans retrieve_azure_search.py.

Usage:
    python3 azure_search_setup.py
"""
import json
import os
import re

import numpy as np
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchIndexingBufferedSender
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)

load_dotenv()

ENDPOINT = os.environ["AZURE_SEARCH_ENDPOINT"]
ADMIN_KEY = os.environ["AZURE_SEARCH_ADMIN_KEY"]
INDEX_NAME = os.environ.get("AZURE_SEARCH_INDEX_NAME", "chatbot-etat-civil-chunks")
EMBEDDING_DIM = 1536  # text-embedding-3-small
SEMANTIC_CONFIG_NAME = "default-semantic-config"

# Champs effectivement utilises par retrieve.py (filtres) et
# format_results_for_prompt (affichage) - voir retrieve.py.
FILTERABLE_STRING_FIELDS = [
    "matiere", "categorie", "sous_categorie", "statut_entree", "document_type",
]
DISPLAY_STRING_FIELDS = [
    "chunk_id", "document_id", "document_titre", "document_date", "numero",
    "titre_contexte", "date_reponse", "alerte_obsolescence", "base_legale_associee",
]


def sanitize_key(chunk_id):
    """Les cles de document Azure Search n'acceptent que lettres/chiffres/_/-/=.
    Nos chunk_id utilisent '::' et '#' (voir chunk_builder.py) - on les
    remplace par un caractere autorise ; le chunk_id d'origine reste
    disponible tel quel dans le champ 'chunk_id'."""
    return re.sub(r"[^A-Za-z0-9_\-=]", "_", chunk_id)


def build_index():
    fields = [
        SimpleField(name="doc_key", type=SearchFieldDataType.String, key=True),
        SearchableField(name="text_for_embedding", type=SearchFieldDataType.String),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=EMBEDDING_DIM,
            vector_search_profile_name="default-vector-profile",
        ),
    ]
    for f in FILTERABLE_STRING_FIELDS:
        fields.append(SimpleField(name=f, type=SearchFieldDataType.String, filterable=True))
    for f in DISPLAY_STRING_FIELDS:
        fields.append(SimpleField(name=f, type=SearchFieldDataType.String, filterable=False))

    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="default-hnsw")],
        profiles=[
            VectorSearchProfile(
                name="default-vector-profile",
                algorithm_configuration_name="default-hnsw",
            )
        ],
    )

    # Semantic ranker (L2 reranking) : disponible en plan gratuit avec quota
    # mensuel limite (verifie via `az search service show` : semanticSearch:
    # "free") - pas besoin d'upgrader le tier du service pour le tester.
    # Contrairement a l'hybride BM25+vecteur (RRF, teste et ecarte -
    # regression sur eval_gold_set.jsonl), c'est un vrai reranking par
    # cross-encoder sur le contenu, pas une fusion de rangs.
    semantic_search = SemanticSearch(
        configurations=[
            SemanticConfiguration(
                name=SEMANTIC_CONFIG_NAME,
                prioritized_fields=SemanticPrioritizedFields(
                    content_fields=[SemanticField(field_name="text_for_embedding")],
                ),
            )
        ],
        default_configuration_name=SEMANTIC_CONFIG_NAME,
    )

    index = SearchIndex(
        name=INDEX_NAME, fields=fields, vector_search=vector_search, semantic_search=semantic_search
    )

    index_client = SearchIndexClient(ENDPOINT, AzureKeyCredential(ADMIN_KEY))
    index_client.create_or_update_index(index)
    print(f"Index '{INDEX_NAME}' cree/mis a jour.")


def load_documents():
    data = np.load("embeddings.npz", allow_pickle=True)
    embeddings = data["embeddings"]
    chunk_ids = list(data["chunk_ids"])

    meta_by_id = {}
    with open("embeddings_meta.jsonl", encoding="utf-8") as f:
        for line in f:
            m = json.loads(line)
            meta_by_id[m["chunk_id"]] = m

    documents = []
    for idx, cid in enumerate(chunk_ids):
        meta = meta_by_id[cid]
        doc = {
            "doc_key": sanitize_key(cid),
            "chunk_id": cid,
            "content_vector": embeddings[idx].tolist(),
        }
        for f in FILTERABLE_STRING_FIELDS + DISPLAY_STRING_FIELDS + ["text_for_embedding"]:
            val = meta.get(f)
            if val is not None:
                doc[f] = str(val)
        documents.append(doc)
    return documents


def upload_documents(documents):
    with SearchIndexingBufferedSender(ENDPOINT, INDEX_NAME, AzureKeyCredential(ADMIN_KEY)) as sender:
        sender.upload_documents(documents=documents)
    print(f"{len(documents)} documents envoyes a l'index '{INDEX_NAME}'.")


if __name__ == "__main__":
    build_index()
    docs = load_documents()
    upload_documents(docs)
