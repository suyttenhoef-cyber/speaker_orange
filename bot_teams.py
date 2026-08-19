"""
bot_teams.py
-----------------
Phase 2 de roadmap_technique_option_b.md : meme logique de retrieval/
generation que chat_loop.py (system prompt, seuil de pertinence, historique
de conversation borne), portee sur le canal Teams via Bot Framework SDK au
lieu du terminal. Retrieval sur Azure AI Search (retrieve_azure_search.py,
Phase 1) au lieu du numpy en memoire.

L'historique de conversation est stocke via ConversationState (memoire du
processus par defaut - a remplacer par une storage persistante, ex. Azure
Blob Storage, avant un vrai deploiement multi-instance en Phase 4).
"""
import os

from botbuilder.core import (
    ActivityHandler, CardFactory, ConversationState, MessageFactory, TurnContext,
)
from openai import OpenAI

from rag_answer import (
    CHAT_MODEL, DISCLAIMER_TEXT, NO_RESULTS_MESSAGE, SYSTEM_PROMPT, build_user_message,
    check_citation_integrity, check_citation_relevance, embed_query, filter_applicable_practices,
    format_citation_warnings,
)
from retrieve import format_results_for_prompt
from retrieve_azure_search import AzureSearchRetriever
from telemetry import log_question_processed, timed

TOP_K = 14

MAX_HISTORY_TURNS = 6  # meme borne que chat_loop.py

# Marqueur exact impose par la regle 4 du SYSTEM_PROMPT (rag_answer.py) pour
# introduire la section des exceptions - sert a l'isoler visuellement dans
# un encart distinct de la Adaptive Card plutot que de la laisser comme un
# simple titre au milieu du texte.
CAS_PARTICULIERS_MARKER = "Attention, cas particuliers"


def build_answer_card(answer_text: str, citation_warnings=None):
    """Adaptive Card avec la reponse, en pleine largeur (msTeams.width=full -
    sans ca, Teams limite la carte a ~400px), suivie du disclaimer en
    italique/police reduite. Si le modele a produit une section "Attention,
    cas particuliers", elle est extraite et affichee dans un encart distinct
    (fond orange) plutot que comme un simple titre au milieu du texte.
    `citation_warnings` (voir rag_answer.format_citation_warnings) regroupe
    les deux garde-fous de citation - numero introuvable
    (check_citation_integrity, regle B3 du SYSTEM_PROMPT) et numero reel mais
    mal applique a l'affirmation (check_citation_relevance) - affiches dans
    un meme encart rouge distinct : filet de securite complementaire, pas une
    garantie absolue."""
    main_text = answer_text
    cas_particuliers_text = None
    marker_idx = answer_text.find(CAS_PARTICULIERS_MARKER)
    if marker_idx != -1:
        # Recule jusqu'au debut de la ligne/section (typiquement un titre
        # markdown "## Attention, cas particuliers : ...") pour ne pas
        # couper au milieu d'un mot ni laisser le titre en double.
        section_start = answer_text.rfind("\n", 0, marker_idx)
        section_start = section_start + 1 if section_start != -1 else 0
        main_text = answer_text[:section_start].rstrip()
        cas_particuliers_text = answer_text[section_start:].strip()

    body = [
        {
            "type": "TextBlock",
            "text": main_text,
            "wrap": True,
        }
    ]
    if cas_particuliers_text:
        body.append({
            "type": "Container",
            "style": "warning",
            "spacing": "Medium",
            "items": [
                {
                    "type": "TextBlock",
                    "text": cas_particuliers_text,
                    "wrap": True,
                }
            ],
        })
    if citation_warnings:
        warnings_text = "\n\n".join(f"- {w}" for w in citation_warnings)
        body.append({
            "type": "Container",
            "style": "attention",
            "spacing": "Medium",
            "items": [
                {
                    "type": "TextBlock",
                    "text": (
                        f"⚠️ Verification automatique des references legales : au moins une "
                        f"citation de cette reponse merite une verification manuelle avant de "
                        f"vous y fier.\n\n{warnings_text}"
                    ),
                    "wrap": True,
                    "weight": "Bolder",
                }
            ],
        })
    body.append({
        "type": "TextBlock",
        "text": f"*{DISCLAIMER_TEXT}*",
        "wrap": True,
        "size": "Small",
        "isSubtle": True,
        "spacing": "Medium",
    })

    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "msTeams": {"width": "full"},
        "body": body,
    }
    return CardFactory.adaptive_card(card)


class EtatCivilAssistantBot(ActivityHandler):
    def __init__(self, conversation_state: ConversationState):
        self.conversation_state = conversation_state
        self.history_accessor = conversation_state.create_property("history")
        self.openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self.retriever = AzureSearchRetriever()

    async def on_message_activity(self, turn_context: TurnContext):
        query = (turn_context.activity.text or "").strip()
        if not query:
            return

        history = await self.history_accessor.get(turn_context, list)
        usage = None
        verif_usage = None
        relevance_usage = None
        unverified_citations = []
        relevance_issues = []

        with timed() as t:
            query_embedding = embed_query(self.openai_client, query)
            results = self.retriever.search(query_embedding, top_k=TOP_K, exclude_historique=True)

            if results:
                results, verif_usage = filter_applicable_practices(
                    self.openai_client, query, results
                )

            if not results:
                answer = NO_RESULTS_MESSAGE
            else:
                context = format_results_for_prompt(results)
                user_message = build_user_message(context, query)

                messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                messages.extend(history[-MAX_HISTORY_TURNS * 2:])
                messages.append({"role": "user", "content": user_message})

                completion = self.openai_client.chat.completions.create(
                    model=CHAT_MODEL,
                    messages=messages,
                    temperature=0.1,
                )
                answer = completion.choices[0].message.content
                usage = completion.usage
                unverified_citations = check_citation_integrity(results, answer)
                relevance_issues, relevance_usage = check_citation_relevance(
                    self.openai_client, query, results, answer
                )

        usages = (usage, verif_usage, relevance_usage)
        prompt_tokens = sum(u.prompt_tokens for u in usages if u)
        completion_tokens = sum(u.completion_tokens for u in usages if u)
        total_tokens = sum(u.total_tokens for u in usages if u)

        log_question_processed(
            duration_ms=t.duration_ms, num_results=len(results), had_results=bool(results),
            top_k=TOP_K,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

        history.append({"role": "user", "content": query})
        history.append({"role": "assistant", "content": answer})
        await self.conversation_state.save_changes(turn_context)

        if results:
            citation_warnings = format_citation_warnings(unverified_citations, relevance_issues)
            await turn_context.send_activity(
                MessageFactory.attachment(build_answer_card(answer, citation_warnings))
            )
        else:
            # NO_RESULTS_MESSAGE est deja lui-meme un avertissement -
            # inutile d'y ajouter le disclaimer/la card.
            await turn_context.send_activity(MessageFactory.text(answer))
