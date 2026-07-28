"""
telemetry.py
-----------------
Phase 5 de roadmap_technique_option_b.md : observabilite via Application
Insights - latence, volumetrie, taux de "sans reponse", SANS JAMAIS logguer
le texte des questions/reponses (donnees potentiellement sensibles).

Les fonctions de ce module n'acceptent d'ailleurs aucun parametre de type
texte libre (question/reponse) : c'est deliberement impossible d'y logguer
du contenu par erreur, seulement des metriques (duree, compteurs, booleens).

Si APPLICATIONINSIGHTS_CONNECTION_STRING n'est pas definie (ex. en local
sans App Insights configure), le logger reste actif mais n'envoie nulle
part - aucune erreur, juste pas de telemetrie distante.
"""
import logging
import os
import time
from contextlib import contextmanager

logger = logging.getLogger("chatbot_etat_civil.telemetry")
logger.setLevel(logging.INFO)

# Tarifs publics GPT-4o-mini (OpenAI/Azure OpenAI), en $ pour 1M tokens - a
# revoir si CHAT_MODEL change (voir rag_answer.py). Purement indicatif : ne
# remplace pas la facture reelle du fournisseur, sert a estimer le cout par
# question directement dans Application Insights, y compris sans acces admin
# au dashboard platform.openai.com/usage (voir plaquette_prerequis_deploiement_client.md).
GPT4O_MINI_INPUT_COST_PER_1M_USD = 0.15
GPT4O_MINI_OUTPUT_COST_PER_1M_USD = 0.60


def estimate_cost_usd(prompt_tokens, completion_tokens):
    return (
        prompt_tokens / 1_000_000 * GPT4O_MINI_INPUT_COST_PER_1M_USD
        + completion_tokens / 1_000_000 * GPT4O_MINI_OUTPUT_COST_PER_1M_USD
    )

_connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
if _connection_string:
    from opencensus.ext.azure.log_exporter import AzureLogHandler

    logger.addHandler(AzureLogHandler(connection_string=_connection_string))


def log_question_processed(duration_ms, num_results, had_results, top_k, matiere=None,
                            prompt_tokens=0, completion_tokens=0, total_tokens=0):
    """Journalise une question traitee : uniquement des metriques, jamais le
    texte de la question ni de la reponse. Un echec de journalisation ne doit
    jamais faire planter la reponse a l'utilisateur : erreurs avalees.

    prompt_tokens/completion_tokens/total_tokens viennent de completion.usage
    (API OpenAI) - permet de suivre la consommation de tokens au meme endroit
    que la latence, sans dupliquer le dashboard de platform.openai.com/usage
    (qui reste la source de verite pour le cout $ reel)."""
    try:
        logger.info(
            "question_processed",
            extra={
                "custom_dimensions": {
                    "duration_ms": round(duration_ms),
                    "num_results": num_results,
                    "had_results": had_results,
                    "top_k": top_k,
                    "matiere": matiere or "toutes",
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "estimated_cost_usd": round(
                        estimate_cost_usd(prompt_tokens, completion_tokens), 6
                    ),
                }
            },
        )
    except Exception:  # pylint: disable=broad-except
        pass


def log_error(error_type):
    """Journalise qu'une erreur est survenue, par son type uniquement (ex.
    nom de la classe d'exception) - jamais le message d'exception brut, qui
    pourrait accidentellement contenir un fragment de la question."""
    try:
        logger.error(
            "question_error", extra={"custom_dimensions": {"error_type": error_type}}
        )
    except Exception:  # pylint: disable=broad-except
        pass


@contextmanager
def timed():
    """Usage : with timed() as t: ... ; puis t.duration_ms apres le bloc."""

    class _Timer:
        duration_ms = 0.0

    t = _Timer()
    start = time.monotonic()
    try:
        yield t
    finally:
        t.duration_ms = (time.monotonic() - start) * 1000
