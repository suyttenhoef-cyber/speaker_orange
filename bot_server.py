"""
bot_server.py
-----------------
Point d'entree Phase 2 : serveur aiohttp exposant le bot Teams (bot_teams.py)
via /api/messages, structure standard du Bot Framework SDK Python.

Test local (sans Azure Bot Service) :
    1. python3 bot_server.py
    2. Ouvrir Bot Framework Emulator (https://github.com/microsoft/BotFramework-Emulator),
       se connecter a http://localhost:3978/api/messages, laisser App ID/Password vides.

Prerequis : OPENAI_API_KEY, AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_ADMIN_KEY dans .env
(voir azure_search_setup.py pour la creation de l'index correspondant).
"""
import sys
import traceback

# load_dotenv() DOIT s'executer avant l'import de bot_config : DefaultConfig lit
# les variables d'environnement au moment de la definition de la classe (donc a
# l'import), pas a l'instanciation - un import fait apres load_dotenv() aurait
# sinon capture un environnement vide (bug reel rencontre le 2026-07-28 : le
# bot repondait "no reply" dans Teams car APP_ID/APP_PASSWORD restaient vides).
from dotenv import load_dotenv

load_dotenv()

from aiohttp import web
from aiohttp.web import Request, Response, json_response
from botbuilder.core import ConversationState, MemoryStorage, TurnContext
from botbuilder.integration.aiohttp import (
    CloudAdapter,
    ConfigurationBotFrameworkAuthentication,
)
from botbuilder.schema import Activity

from bot_config import DefaultConfig
from bot_teams import EtatCivilAssistantBot
from telemetry import log_error

CONFIG = DefaultConfig()

# MemoryStorage : historique de conversation perdu au redemarrage du process.
# A remplacer par une storage persistante (ex. Azure Blob) en Phase 4/5 si le
# bot doit tourner sur plusieurs instances (App Service avec scale-out).
storage = MemoryStorage()
conversation_state = ConversationState(storage)

adapter = CloudAdapter(ConfigurationBotFrameworkAuthentication(CONFIG))
bot = EtatCivilAssistantBot(conversation_state)


async def on_error(context: TurnContext, error: Exception):
    print(f"\n [on_turn_error] unhandled error: {error}", file=sys.stderr)
    traceback.print_exc()
    log_error(error_type=type(error).__name__)
    await context.send_activity(
        "Une erreur est survenue de mon cote - reessaie dans un instant."
    )


adapter.on_turn_error = on_error


async def messages(req: Request) -> Response:
    if "application/json" not in req.headers.get("Content-Type", ""):
        return Response(status=415)

    body = await req.json()
    activity = Activity().deserialize(body)
    auth_header = req.headers.get("Authorization", "")

    response = await adapter.process_activity(auth_header, activity, bot.on_turn)
    if response:
        return json_response(data=response.body, status=response.status)
    return Response(status=201)


app = web.Application()
app.router.add_post("/api/messages", messages)

if __name__ == "__main__":
    web.run_app(app, host="localhost", port=CONFIG.PORT)
