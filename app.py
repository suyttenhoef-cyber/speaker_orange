"""
app.py
-----------------
Interface web (Streamlit) pour l'assistant etat civil. Chat visuel avec
affichage des sources citees pour chaque reponse.

IMPORTANT : fait de vrais appels reseau vers l'API OpenAI. A executer dans
ton environnement (impossible depuis le sandbox Claude).

Prerequis:
    pip install streamlit openai numpy
    (avoir deja lance chunk_builder.py puis embed_chunks.py au prealable
     pour generer embeddings.npz)

Lancement local:
    streamlit run app.py

Partage :
    - Sur le meme reseau (bureau) :
        streamlit run app.py --server.address 0.0.0.0
        puis partager http://<IP_de_ta_machine>:8501 a tes collegues
    - Partage public via Streamlit Community Cloud (gratuit) :
        1. Pousser ce dossier sur un repo GitHub (prive de preference)
        2. Se connecter sur https://share.streamlit.io avec ce repo
        3. Ajouter OPENAI_API_KEY dans les "Secrets" de l'app (jamais dans le code)
        4. Streamlit fournit une URL publique du type https://xxx.streamlit.app
"""
import os

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

from retrieve import Retriever, format_results_for_prompt, DEFAULT_MIN_SCORE
from rag_answer import (
    SYSTEM_PROMPT, EMBEDDING_MODEL, CHAT_MODEL, NO_RESULTS_MESSAGE, DISCLAIMER_TEXT,
    build_user_message, check_citation_integrity, filter_applicable_practices,
)

load_dotenv()  # charge OPENAI_API_KEY depuis un fichier .env si present (dev local)

EMBEDDINGS_PATH = "embeddings.npz"

# Libelles d'affichage pour les matieres connues ; toute nouvelle matiere
# ajoutee au corpus (cf. README) s'affiche automatiquement avec sa cle brute
# tant qu'elle n'a pas ete ajoutee ici. A completer une fois le decoupage
# du corpus etat civil arrete (ex. actes_naissance, actes_mariage,
# actes_deces, nationalite...).
MATIERE_LABELS = {}

st.set_page_config(page_title="Assistant Etat Civil", page_icon="📜", layout="wide")


@st.cache_resource
def load_retriever():
    if not os.path.exists(EMBEDDINGS_PATH):
        return None
    return Retriever(EMBEDDINGS_PATH)


def get_api_key():
    """Priorite : secret Streamlit Cloud > variable d'environnement > saisie manuelle."""
    try:
        if "OPENAI_API_KEY" in st.secrets:
            return st.secrets["OPENAI_API_KEY"]
    except Exception:
        # Aucun fichier secrets.toml present (cas normal en dev local avec .env)
        pass
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    return st.session_state.get("manual_api_key", "")


def main():
    st.title("📜 Assistant Etat Civil")
    st.caption(
        "POC — corpus Vanden Broele et textes officiels (Code civil, circulaires, etc.)"
    )

    retriever = load_retriever()

    with st.sidebar:
        st.header("Configuration")

        api_key = get_api_key()
        if not api_key:
            api_key = st.text_input(
                "Clé API OpenAI",
                type="password",
                help="Ta clé n'est jamais stockée — elle reste en mémoire "
                     "pour cette session uniquement.",
            )
            if api_key:
                st.session_state["manual_api_key"] = api_key

        matieres = retriever.available_matieres() if retriever else []
        matiere_choice = st.selectbox(
            "Matière",
            options=["Toutes les matières"] + matieres,
            format_func=lambda m: MATIERE_LABELS.get(m, m) if m != "Toutes les matières" else m,
            help="Restreindre la recherche à une seule matière évite qu'une "
                 "question sur un domaine ramène des sources d'un autre "
                 "domaine simplement parce qu'elles y ressemblent.",
        )
        matiere_filter = None if matiere_choice == "Toutes les matières" else matiere_choice

        top_k = st.slider("Nombre de passages source à récupérer", 3, 20, 10)
        min_score = st.slider(
            "Seuil de pertinence minimal", 0.0, 0.6, DEFAULT_MIN_SCORE, 0.05,
            help="Les passages dont le score de similarité est sous ce seuil "
                 "sont ignorés, pour éviter de citer des sources hors-sujet. "
                 "Baisser le seuil élargit la recherche (utile si l'assistant "
                 "répond trop souvent qu'il ne trouve rien).",
        )
        show_sources = st.checkbox("Afficher les sources sous chaque réponse", value=True)
        include_historique = st.checkbox(
            "Inclure les textes historiques/abrogés",
            value=False,
            help="Ex. l'ancienne circulaire de 2022 sur les revenus "
                 "professionnels, remplacée depuis 2024. À activer "
                 "uniquement pour traiter un dossier antérieur à 2023.",
        )

        st.divider()
        if st.button("🗑️ Effacer la conversation"):
            st.session_state["messages"] = []
            st.rerun()

        st.divider()
        st.caption(
            "⚠️ Cet assistant est une aide à la décision. Il ne remplace "
            "pas une vérification par le service juridique communal ni une "
            "décision individuelle motivée de l'officier de l'état civil."
        )

    if retriever is None:
        st.error(
            f"Fichier `{EMBEDDINGS_PATH}` introuvable. Lance d'abord "
            "`python3 chunk_builder.py` puis `python3 embed_chunks.py` "
            "pour générer les embeddings avant de démarrer l'application."
        )
        st.stop()

    if not api_key:
        st.warning("Renseigne ta clé API OpenAI dans la barre latérale pour commencer.")
        st.stop()

    client = OpenAI(api_key=api_key)

    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    # Affichage de l'historique
    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant" and msg.get("show_disclaimer"):
                st.caption(f"*{DISCLAIMER_TEXT}*")
            if msg["role"] == "assistant" and msg.get("sources"):
                with st.expander("📚 Sources citées"):
                    for score, meta in msg["sources"]:
                        st.markdown(
                            f"**{meta['document_titre']}**"
                            + (f", art./section {meta['numero']}" if meta.get('numero') else "")
                            + f"  \n*Pertinence : {score:.2f} — "
                            f"statut : {meta.get('statut_entree', 'n/c')}*"
                        )

    query = st.chat_input("Pose ta question sur l'état civil, la population ou les étrangers...")

    if query:
        st.session_state["messages"].append({"role": "user", "content": query})
        with st.chat_message("user"):
            st.markdown(query)

        with st.chat_message("assistant"):
            with st.spinner("Recherche dans le corpus et rédaction de la réponse..."):
                query_embedding = client.embeddings.create(
                    model=EMBEDDING_MODEL, input=[query]
                ).data[0].embedding

                results = retriever.search(
                    query_embedding,
                    top_k=top_k,
                    exclude_historique=not include_historique,
                    matiere=matiere_filter,
                    min_score=min_score,
                )

                if results:
                    results, _verif_usage = filter_applicable_practices(client, query, results)

                if not results:
                    answer = NO_RESULTS_MESSAGE
                else:
                    context = format_results_for_prompt(results)
                    user_message = build_user_message(context, query)

                    history_msgs = [
                        {"role": m["role"], "content": m["content"]}
                        for m in st.session_state["messages"][:-1][-10:]
                    ]

                    completion = client.chat.completions.create(
                        model=CHAT_MODEL,
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPT},
                            *history_msgs,
                            {"role": "user", "content": user_message},
                        ],
                        temperature=0.1,
                    )
                    answer = completion.choices[0].message.content

            st.markdown(answer)
            if results:
                unverified = check_citation_integrity(results, answer)
                if unverified:
                    st.error(
                        f"⚠️ Reference(s) legale(s) non verifiee(s) automatiquement dans les "
                        f"sources : {', '.join(unverified)}. A verifier imperativement."
                    )
                st.caption(f"*{DISCLAIMER_TEXT}*")
            if show_sources and results:
                with st.expander("📚 Sources citées"):
                    for score, meta in results:
                        st.markdown(
                            f"**{meta['document_titre']}**"
                            + (f", art./section {meta['numero']}" if meta.get('numero') else "")
                            + f"  \n*Pertinence : {score:.2f} — "
                            f"statut : {meta.get('statut_entree', 'n/c')}*"
                        )

        st.session_state["messages"].append(
            {"role": "assistant", "content": answer, "sources": results,
             "show_disclaimer": bool(results)}
        )


if __name__ == "__main__":
    main()