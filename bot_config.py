"""
bot_config.py
-----------------
Configuration standard du Bot Framework SDK Python (memes noms d'attributs
que l'exemple officiel Microsoft - lus tels quels par
ConfigurationBotFrameworkAuthentication).

En local (test via Bot Framework Emulator, sans enregistrement Azure Bot
Service), APP_ID/APP_PASSWORD peuvent rester vides. Ils devront etre
renseignes (dans .env) a la Phase 3 de roadmap_technique_option_b.md,
une fois le bot enregistre dans Azure Bot Service.
"""
import os


class DefaultConfig:
    PORT = 3978
    APP_ID = os.environ.get("MicrosoftAppId", "")
    APP_PASSWORD = os.environ.get("MicrosoftAppPassword", "")
    APP_TYPE = os.environ.get("MicrosoftAppType", "MultiTenant")
    APP_TENANTID = os.environ.get("MicrosoftAppTenantId", "")
