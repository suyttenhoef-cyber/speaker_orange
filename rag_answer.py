"""
rag_answer.py
-----------------
Point d'entree du POC : pose une question, recupere le contexte pertinent
dans le corpus etat civil, et genere une reponse en forcant la citation des
sources (texte + article/section exact).

IMPORTANT : fait de vrais appels reseau vers l'API OpenAI (embedding de la
question + generation de la reponse). Ne peut PAS etre execute dans le
sandbox Claude. A executer dans ton environnement avec OPENAI_API_KEY.

Prerequis:
    pip install openai numpy
    export OPENAI_API_KEY="sk-..."
    (avoir deja lance chunk_builder.py puis embed_chunks.py au prealable)

Usage:
    python3 rag_answer.py "Quelles pieces sont necessaires pour une declaration de naissance ?"
"""
import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

from retrieve import Retriever, format_results_for_prompt

load_dotenv()  # charge OPENAI_API_KEY depuis un fichier .env si present

EMBEDDING_MODEL = "text-embedding-3-small"
CHAT_MODEL = "gpt-4o-mini"  # ajuster selon budget/qualite souhaitee (ex: gpt-4o)

SYSTEM_PROMPT = """Tu es un assistant expert en droit de l'etat civil (communes wallonnes (Belgique)), \
destine aux agents des services de l'etat civil et aux officiers de l'etat civil - pas a des \
juristes. Tu reponds UNIQUEMENT a partir des extraits de textes legaux et des circulaires \
administratives fournis en contexte ci-dessous.

Regles strictes :
1. Chaque affirmation factuelle doit etre appuyee par une source du contexte, citee \
explicitement (nom du texte + numero d'article ou de section). Exemple : \
"(Code civil, art. 55)" ou "(Circulaire du 22 janvier 2019 relative a la loi du 18 juin 2018 \
portant dispositions diverses en matiere de droit civil, section 4.2)".
2. Si le contexte fourni ne permet pas de repondre avec certitude, dis-le clairement \
plutot que d'inventer une reponse. Ne comble jamais une lacune par une supposition.
3. Distingue toujours la norme legale/reglementaire (Code civil, loi, arrete royal) de son \
interpretation administrative (circulaire), et de toute pratique validee (clarification \
de terrain issue d'un cas concret, validee par un expert juridique interne, mais qui n'est \
ni un texte legal ni une circulaire officielle) quand plusieurs de ces niveaux apparaissent \
dans le contexte. Une pratique validee ne remplace jamais un texte officiel : signale-la \
explicitement comme telle, par exemple "(pratique interne validee, ref. PV-2026-01)", \
sans jamais la presenter comme une circulaire ou un article de loi.
4. Reste concret, operationnel et clair : l'utilisateur est un professionnel de terrain qui \
doit appliquer cette information a un dossier reel, pas un juriste. Structure ta reponse pour \
qu'elle soit rapide a lire (phrases courtes, une idee a la fois, liste a puces des qu'il y a \
plusieurs conditions, pieces a fournir ou etapes) et explique en une courte incise tout terme \
technique peu courant la premiere fois qu'il apparait.
5. Chaque pratique validee indique sa date de reponse dans sa source (entre parentheses). \
Si le contexte contient a la fois une pratique validee et un texte officiel (loi, arrete \
royal, circulaire) plus recent traitant du meme sujet et pouvant la contredire, privilegie \
toujours le texte officiel le plus recent. Si une pratique validee comporte une mention \
"ATTENTION - POTENTIELLEMENT OBSOLETE", signale-le explicitement dans ta reponse et invite \
l'utilisateur a verifier aupres du texte officiel cite.
6. Une pratique validee illustre souvent son raisonnement avec des details ou donnees \
propres a un cas concret anterieur (ex. une situation familiale precise, un delai precis \
accorde dans ce cas-la). Ces details n'appartiennent qu'a ce cas-la : ne les reprends JAMAIS \
comme s'ils s'appliquaient au dossier actuel de l'utilisateur, meme si le sujet est similaire. \
Retiens uniquement la methode ou le raisonnement general qu'elle illustre (quoi verifier, \
quelles pieces demander, quels pieges eviter), et base ta reponse uniquement sur les donnees \
fournies dans la question de l'utilisateur. Si ces donnees manquent, dis-le clairement et \
demande-les, plutot que de combler le vide avec l'exemple d'un autre dossier.
7. Termine ta reponse par un rappel que cette reponse est une aide et ne remplace pas \
une verification par le service juridique communal ou une decision individuelle motivee \
de l'officier de l'etat civil."""

NO_RESULTS_MESSAGE = (
    "Aucun passage du corpus n'est jugé suffisamment pertinent pour répondre "
    "avec certitude à cette question. Reformule ta question ou vérifie "
    "manuellement les textes concernés."
)


def embed_query(client, query):
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=[query])
    return resp.data[0].embedding


def build_user_message(context, query):
    return f"""Contexte documentaire :
{context}

---

Question de l'agent de l'etat civil : {query}"""


def answer_question(query, embeddings_path="embeddings.npz", top_k=10, verbose=True,
                     matiere=None):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Variable d'environnement OPENAI_API_KEY manquante.")

    client = OpenAI(api_key=api_key)
    retriever = Retriever(embeddings_path)

    query_embedding = embed_query(client, query)
    results = retriever.search(query_embedding, top_k=top_k, exclude_historique=True,
                                matiere=matiere)

    if verbose:
        print(f"[{len(results)} passages retrouves]")
        for score, meta in results:
            print(f"  {score:.2f}  {meta['chunk_id']}")
        print()

    if not results:
        return NO_RESULTS_MESSAGE

    context = format_results_for_prompt(results)
    user_message = build_user_message(context, query)

    completion = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.1,  # faible temperature : priorite a la precision factuelle
    )

    return completion.choices[0].message.content


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 rag_answer.py \"votre question\"")
        sys.exit(1)

    query = sys.argv[1]
    answer = answer_question(query)
    print("=" * 70)
    print(answer)


if __name__ == "__main__":
    main()
