"""
test_bot_local.py
-----------------
Validation de la Phase 2 (roadmap_technique_option_b.md) sans Bot Framework
Emulator : utilise TestAdapter (fourni par botbuilder-core, concu justement
pour tester un bot en process sans passer par un vrai canal/HTTP) pour
simuler des activites Teams completes et verifier que CpasAssistantBot
repond correctement de bout en bout (Azure AI Search + generation OpenAI).

Usage:
    python3 test_bot_local.py
"""
import asyncio

from botbuilder.core import ConversationState, MemoryStorage
from botbuilder.core.adapters import TestAdapter
from dotenv import load_dotenv

from bot_teams import EtatCivilAssistantBot

load_dotenv()

TEST_QUESTIONS = [
    "Quelles sont les conditions pour qu'un etranger acquiere la nationalite belge par declaration ?",
    "Un officier de l'etat civil peut-il annuler lui-meme un acte d'etat civil sans passer par le tribunal ?",
]


async def main():
    storage = MemoryStorage()
    conversation_state = ConversationState(storage)
    bot = EtatCivilAssistantBot(conversation_state)
    adapter = TestAdapter(bot.on_turn)

    for question in TEST_QUESTIONS:
        print("=" * 70)
        print("QUESTION:", question)
        await adapter.receive_activity(question)

        while True:
            reply = adapter.get_next_activity()
            if reply is None:
                break
            if reply.text:
                print("\nBOT >", reply.text)
            for attachment in (reply.attachments or []):
                card = attachment.content
                for block in card.get("body", []):
                    print("\nBOT >", block.get("text"))


if __name__ == "__main__":
    asyncio.run(main())
