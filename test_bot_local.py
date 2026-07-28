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

from bot_teams import CpasAssistantBot

load_dotenv()

TEST_QUESTIONS = [
    "Les grands-parents sont-ils consideres comme des debiteurs d'aliments "
    "pour une personne qui demande le revenu d'integration ?",
    "Quelles sont les conditions pour beneficier du droit a l'integration sociale ?",
]


async def main():
    storage = MemoryStorage()
    conversation_state = ConversationState(storage)
    bot = CpasAssistantBot(conversation_state)
    adapter = TestAdapter(bot.on_turn)

    for question in TEST_QUESTIONS:
        print("=" * 70)
        print("QUESTION:", question)
        await adapter.receive_activity(question)

        while True:
            reply = adapter.get_next_activity()
            if reply is None:
                break
            print("\nBOT >", reply.text)


if __name__ == "__main__":
    asyncio.run(main())
