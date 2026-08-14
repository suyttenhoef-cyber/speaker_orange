"""
test_questions_batch.py
-----------------
Outil de test ponctuel (pas partie de l'application) : fait tourner une
serie de questions predefinies a travers le pipeline complet (retrieval +
verification + generation, exactement comme rag_answer.py) et ecrit un
rapport structure - question, passages retrouves avant/apres verification,
et reponse generee - dans un fichier JSON, pour analyse ulterieure.

IMPORTANT : fait de vrais appels reseau vers l'API OpenAI (embeddings +
generation, potentiellement 2 appels de generation par question si des
pratiques sont retrouvees). Ne peut PAS etre execute dans le sandbox Claude.

Usage:
    python3 test_questions_batch.py chemin/vers/questions.json rapport_test.json
"""
import json
import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

from rag_answer import (
    CHAT_MODEL, NO_RESULTS_MESSAGE, SYSTEM_PROMPT, build_user_message,
    check_citation_integrity, embed_query, filter_applicable_practices,
)
from retrieve import Retriever, format_results_for_prompt

load_dotenv()


def run_one(client, retriever, query, top_k=14):
    query_embedding = embed_query(client, query)
    raw_results = retriever.search(query_embedding, top_k=top_k, exclude_historique=True)

    raw_summary = [
        {"score": round(float(score), 3), "chunk_id": meta["chunk_id"]}
        for score, meta in raw_results
    ]

    if not raw_results:
        return {
            "question": query,
            "resultats_bruts": raw_summary,
            "resultats_apres_verification": [],
            "reponse": NO_RESULTS_MESSAGE,
        }

    filtered_results, _verif_usage = filter_applicable_practices(client, query, raw_results)
    filtered_summary = [
        {"score": round(float(score), 3), "chunk_id": meta["chunk_id"]}
        for score, meta in filtered_results
    ]

    if not filtered_results:
        return {
            "question": query,
            "resultats_bruts": raw_summary,
            "resultats_apres_verification": filtered_summary,
            "reponse": NO_RESULTS_MESSAGE,
        }

    context = format_results_for_prompt(filtered_results)
    user_message = build_user_message(context, query)

    completion = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.1,
    )

    answer = completion.choices[0].message.content
    return {
        "question": query,
        "resultats_bruts": raw_summary,
        "resultats_apres_verification": filtered_summary,
        "reponse": answer,
        "citations_non_verifiees": check_citation_integrity(filtered_results, answer),
    }


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 test_questions_batch.py questions.json rapport.json")
        sys.exit(1)

    questions_path = sys.argv[1]
    out_path = sys.argv[2]

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERREUR: OPENAI_API_KEY manquante.", file=sys.stderr)
        sys.exit(1)

    with open(questions_path, encoding="utf-8") as f:
        questions = json.load(f)

    client = OpenAI(api_key=api_key)
    retriever = Retriever("embeddings.npz")

    results = []
    for i, q in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {q[:80]}...")
        try:
            results.append(run_one(client, retriever, q))
        except Exception as e:  # pylint: disable=broad-except
            print(f"  ERREUR: {e}", file=sys.stderr)
            results.append({"question": q, "erreur": str(e)})

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\nOK - {len(results)} questions traitees, rapport ecrit dans {out_path}")


if __name__ == "__main__":
    main()
