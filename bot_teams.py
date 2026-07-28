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

from botbuilder.core import ActivityHandler, ConversationState, MessageFactory, TurnContext
from openai import OpenAI

from rag_answer import (
    CHAT_MODEL, NO_RESULTS_MESSAGE, SYSTEM_PROMPT, build_user_message, embed_query,
)
from retrieve import format_results_for_prompt
from retrieve_azure_search import AzureSearchRetriever
from telemetry import log_question_processed, timed

TOP_K = 10

MAX_HISTORY_TURNS = 6  # meme borne que chat_loop.py


class CpasAssistantBot(ActivityHandler):
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

        with timed() as t:
            query_embedding = embed_query(self.openai_client, query)
            results = self.retriever.search(query_embedding, top_k=TOP_K, exclude_historique=True)

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

        log_question_processed(
            duration_ms=t.duration_ms, num_results=len(results), had_results=bool(results),
            top_k=TOP_K,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
        )

        history.append({"role": "user", "content": query})
        history.append({"role": "assistant", "content": answer})
        await self.conversation_state.save_changes(turn_context)

        await turn_context.send_activity(MessageFactory.text(answer))
