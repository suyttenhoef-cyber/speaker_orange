"""
chat_loop.py
-----------------
Chatbot conversationnel en terminal pour interroger le corpus etat civil.
Garde une memoire des echanges precedents (contexte de conversation).

IMPORTANT : fait de vrais appels reseau vers l'API OpenAI. A executer dans
ton environnement avec OPENAI_API_KEY (impossible depuis le sandbox Claude).

Prerequis:
    pip install openai numpy
    export OPENAI_API_KEY="sk-..."
    (avoir deja lance chunk_builder.py puis embed_chunks.py au prealable)

Usage:
    python3 chat_loop.py
    (puis taper tes questions, "exit" ou "quit" pour arreter)
"""
import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

from retrieve import Retriever, format_results_for_prompt
from rag_answer import (
    SYSTEM_PROMPT, EMBEDDING_MODEL, CHAT_MODEL, NO_RESULTS_MESSAGE,
    embed_query, build_user_message,
)

load_dotenv()  # charge OPENAI_API_KEY depuis un fichier .env si present

MAX_HISTORY_TURNS = 6  # nombre d'echanges (question+reponse) gardes en memoire


def run_chat(embeddings_path="embeddings.npz", top_k=10):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERREUR: variable d'environnement OPENAI_API_KEY manquante.", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=api_key)
    retriever = Retriever(embeddings_path)

    history = []  # liste de {"role": ..., "content": ...}

    print("=" * 70)
    print("Assistant Etat Civil (POC)")
    print("Tape ta question, ou 'exit'/'quit' pour arreter.")
    print("=" * 70)

    while True:
        try:
            query = input("\nToi > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nFin de la session.")
            break

        if not query:
            continue
        if query.lower() in ("exit", "quit", "q"):
            print("Fin de la session.")
            break

        # Recherche du contexte pertinent pour la question posee
        query_embedding = embed_query(client, query)
        results = retriever.search(query_embedding, top_k=top_k, exclude_historique=True)

        if not results:
            answer = NO_RESULTS_MESSAGE
        else:
            context = format_results_for_prompt(results)
            user_message = build_user_message(context, query)

            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            messages.extend(history[-MAX_HISTORY_TURNS * 2:])  # historique recent
            messages.append({"role": "user", "content": user_message})

            completion = client.chat.completions.create(
                model=CHAT_MODEL,
                messages=messages,
                temperature=0.1,
            )
            answer = completion.choices[0].message.content

        print(f"\nAssistant > {answer}")

        # On garde la question "propre" (sans le bloc de contexte) dans
        # l'historique, pour ne pas faire gonfler inutilement les tokens
        # a chaque tour.
        history.append({"role": "user", "content": query})
        history.append({"role": "assistant", "content": answer})


if __name__ == "__main__":
    run_chat()
