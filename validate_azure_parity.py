"""
validate_azure_parity.py
-----------------
Non-regression demandee par roadmap_technique_option_b.md (Phase 1) : verifie
que le retrieval Azure AI Search retrouve les memes passages, dans le meme
ordre, que le retrieval numpy pour le cas de test qui avait revele le bug de
top_k trop bas (question grands-parents / debiteurs d'aliments, reforme de
l'art. 34).

Usage:
    python3 validate_azure_parity.py
"""
import os

from dotenv import load_dotenv
from openai import OpenAI

from rag_answer import EMBEDDING_MODEL, embed_query
from retrieve import Retriever
from retrieve_azure_search import AzureSearchRetriever

load_dotenv()

TEST_QUERIES = [
    "Quelles sont les conditions pour qu'un etranger acquiere la nationalite belge par declaration ?",
    "Un officier de l'etat civil peut-il annuler lui-meme un acte d'etat civil sans passer par le tribunal ?",
]


def main():
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    numpy_retriever = Retriever("embeddings.npz")
    azure_retriever = AzureSearchRetriever()

    for query in TEST_QUERIES:
        print("=" * 70)
        print("QUESTION:", query)
        query_embedding = embed_query(client, query)

        numpy_results = numpy_retriever.search(query_embedding, top_k=10)
        azure_results = azure_retriever.search(query_embedding, top_k=10)

        numpy_ids = [meta["chunk_id"] for _, meta in numpy_results]
        azure_ids = [meta["chunk_id"] for _, meta in azure_results]

        print(f"\n--- numpy (top {len(numpy_ids)}) ---")
        for score, meta in numpy_results:
            print(f"  {score:.3f}  {meta['chunk_id']}")

        print(f"\n--- azure  (top {len(azure_ids)}) ---")
        for score, meta in azure_results:
            print(f"  {score:.3f}  {meta['chunk_id']}")

        same_set = set(numpy_ids) == set(azure_ids)
        same_order = numpy_ids == azure_ids
        print(f"\n>> memes chunk_id (ensemble) : {same_set}")
        print(f">> meme ordre exact           : {same_order}")


if __name__ == "__main__":
    main()
