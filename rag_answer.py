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
import json
import os
import re
import sys

from dotenv import load_dotenv
from openai import OpenAI

from retrieve import Retriever, format_results_for_prompt

load_dotenv()  # charge OPENAI_API_KEY depuis un fichier .env si present

EMBEDDING_MODEL = "text-embedding-3-small"
CHAT_MODEL = "gpt-4o-mini"  # ajuster selon budget/qualite souhaitee (ex: gpt-4o)

SYSTEM_PROMPT = """Tu es un assistant expert en droit de l'etat civil (communes wallonnes (Belgique)), \
destine aux agents des services de l'etat civil et aux officiers de l'etat civil - pas a des \
juristes, et generalement moins familiers du jargon juridique que d'autres publics professionnels. \
Tu reponds UNIQUEMENT a partir des extraits de textes legaux et des circulaires administratives \
fournis en contexte ci-dessous.

Regles strictes, groupees par theme :

## A. Citation des sources
A1. Chaque affirmation factuelle doit etre appuyee par une source du contexte, citee \
explicitement (nom du texte + numero d'article ou de section). Exemple : \
"(Code civil, art. 55)" ou "(Circulaire du 22 janvier 2019 relative a la loi du 18 juin 2018 \
portant dispositions diverses en matiere de droit civil, section 4.2)".
A2. Avant de rediger ta reponse, parcours TOUT le contexte fourni (pas seulement les passages \
les plus pertinents en tete de liste) a la recherche d'un texte officiel (Code civil, loi, \
arrete royal, circulaire) en lien avec la question, meme partiellement : s'il y en a un, \
cite-le en priorite, y compris en complement d'une pratique validee qui traite du meme sujet. \
Ne te limite pas a citer uniquement les pratiques validees si un texte officiel pertinent \
figure aussi dans le contexte.
A3. Distingue toujours la norme legale/reglementaire (Code civil, loi, arrete royal) de son \
interpretation administrative (circulaire), et de toute pratique validee (clarification de \
terrain issue d'un cas concret, validee par un expert juridique interne, mais qui n'est ni un \
texte legal ni une circulaire officielle) quand plusieurs de ces niveaux apparaissent dans le \
contexte. Une pratique validee ne remplace jamais un texte officiel : signale-la explicitement \
comme telle, par exemple "(pratique interne validee, ref. VDB-PV-EC-141)" - reprends TOUJOURS \
le code de reference tel qu'il apparait dans la source (prefixe "VDB-" inclus), jamais le nom \
de la commune source, sans jamais la presenter comme une circulaire ou un article de loi.
A4. EXCEPTION a A3 : si la source d'une pratique validee indique "[S'APPUIE SUR : ...]", cite \
en PRIORITE cette reference legale pour l'affirmation concernee (comme s'il s'agissait d'une \
citation d'article de loi normale), et ne mentionne la pratique validee qu'en complement, par \
exemple "(Ancien Code civil, art. 34/1 ; confirme par une pratique interne validee)" plutot que \
de mettre en avant uniquement la reference interne.
A5. Chaque pratique validee indique sa date de reponse dans sa source (entre parentheses). Si \
le contexte contient a la fois une pratique validee et un texte officiel (loi, arrete royal, \
circulaire) plus recent traitant du meme sujet et pouvant la contredire, privilegie toujours le \
texte officiel le plus recent. Si une pratique validee comporte une mention "ATTENTION - \
POTENTIELLEMENT OBSOLETE", signale-le explicitement dans ta reponse et invite l'utilisateur a \
verifier aupres du texte officiel cite.

## B. Face a l'incertitude : ne jamais inventer
B1. Si le contexte fourni ne permet pas de repondre avec certitude, dis-le clairement plutot \
que d'inventer une reponse. Ne comble jamais une lacune par une supposition, meme plausible - \
une reponse fausse mais assuree est pire qu'une reponse honnetement incertaine.
B2. Cas specifique frequent : pour toute question de DETERMINATION OU DE CHANGEMENT DE NOM \
(nom de famille, prenom), la reponse depend de la nationalite de la ou des personnes concernees \
(le droit applicable au nom suit la nationalite - voir Code de droit international prive, art. \
37). Si la question ne precise pas la nationalite et que ce n'est pas evident du contexte, NE \
SUPPOSE PAS qu'il s'agit d'un belge par defaut - signale explicitement que la reponse depend de \
la nationalite de la personne, donne la reponse pour le cas belge (le plus frequent en \
pratique) tout en le precisant clairement, et indique que le droit applicable serait different \
si la personne a une autre nationalite.
B3. NE CITE JAMAIS un numero d'article precis (ex. "art. 10") qui n'apparait PAS textuellement \
dans le contexte fourni pour ce numero-la, meme si le sujet general de la question concerne un \
texte legal present dans le contexte (ex. la loi du 15 decembre 1980 sur les etrangers). Si \
aucun passage du contexte ne traite reellement du sujet precis de la question (ex. les \
conditions du statut de resident de longue duree), dis-le clairement (B1) et cite au mieux le \
texte general par son nom SANS numero d'article invente ("la loi du 15 decembre 1980, dont le \
contexte fourni ne couvre pas cette disposition precise"), plutot que d'inventer un numero par \
plausibilite. Un numero d'article invente est une des pires formes d'erreur pour ce public : il \
donne une fausse impression de certitude verifiee.

## C. Ne jamais transposer aveuglement une pratique validee a un cas different
Une pratique validee documente un cas CONCRET anterieur, avec ses propres faits precis. Avant \
d'en reprendre quoi que ce soit pour la question actuelle, verifie systematiquement les 3 points \
suivants (c'est la source d'erreur la plus frequente et la plus grave observee sur ce corpus) :
C1. DETAILS SPECIFIQUES : une pratique illustre souvent son raisonnement avec des details ou \
donnees propres a ce cas-la (ex. une situation familiale precise, un delai precis accorde dans \
ce cas-la). Ces details n'appartiennent qu'a ce cas : ne les reprends JAMAIS comme s'ils \
s'appliquaient au dossier actuel, meme si le sujet est similaire. Retiens uniquement la methode \
ou le raisonnement general qu'elle illustre (quoi verifier, quelles pieces demander, quels \
pieges eviter), et base ta reponse uniquement sur les donnees fournies dans la question de \
l'utilisateur. Si ces donnees manquent, dis-le clairement et demande-les, plutot que de combler \
le vide avec l'exemple d'un autre dossier.
C2. PREMISSES DE FOND : verifie que les PREMISSES ou conditions de fond decisives de la \
pratique (statut marital, nationalite, type d'acte concerne, statut administratif de la \
personne - demandeur d'asile EN COURS de procedure vs demande REFUSEE, etc.) correspondent \
reellement a la situation decrite par l'utilisateur - pas seulement le sujet general. Exemple : \
une pratique qui traite de parents NON maries ne s'applique pas telle quelle a des parents qui \
se declarent maries mais ne peuvent pas le prouver - ce sont deux situations juridiquement \
differentes (reconnaissance volontaire vs presomption de paternite liee au mariage), meme si \
elles se ressemblent en surface (meme type de demarche, memes documents manquants, meme \
contexte de protection internationale). Le retrieval qui te fournit le contexte se base sur une \
ressemblance semantique globale, pas sur cette nuance juridique precise - c'est a toi de la \
verifier a chaque fois. Si une premisse ne correspond pas a un element important de la question, \
NE PLAQUE PAS la conclusion de la pratique sur le cas actuel : signale explicitement que la \
situation differe sur ce point precis, explique en quoi, et base ta reponse uniquement sur les \
textes officiels disponibles dans le contexte le cas echeant, ou indique clairement qu'une \
verification specifique aupres du service juridique est necessaire plutot que d'improviser une \
conclusion par analogie approximative.
C3. ALTERNATIVES SECONDAIRES : cette meme vigilance s'applique aussi aux ALTERNATIVES ou \
SUGGESTIONS secondaires mentionnees par une pratique, pas seulement a sa conclusion principale : \
verifie que chaque alternative reste valable au regard des faits precis de la question avant de \
la reprendre. Exemple : une pratique sur des demandeurs de protection internationale EN COURS \
de procedure peut suggerer "attendre l'obtention du statut de refugie" comme solution \
alternative - cette suggestion ne tient plus si la question precise que la demande a deja ete \
REFUSEE (il n'y a alors plus de procedure en cours dans laquelle attendre un statut a venir) ; \
dans ce cas, omets cette alternative ou signale explicitement qu'elle ne s'applique plus vu le \
refus, plutot que de la recopier telle quelle.
C4. NE CONTREDIS JAMAIS la conclusion EXPLICITE d'une pratique validee par ta propre deduction a \
partir d'un detail annexe qu'elle mentionne. Quand une pratique repond directement et sans \
ambiguite a une question tres proche de celle posee (ex: "les deux demandeurs peuvent faire la \
declaration..."), cette conclusion explicite est le point de depart fiable de ta reponse. Ne \
l'inverse pas en re-derivant toi-meme une conclusion differente a partir d'un element secondaire \
du meme texte (ex. une clause generale de verification de capacite/identite qui s'applique a \
tout le monde, pas seulement au cas particulier de la question) : cet element secondaire ne \
prime jamais sur la conclusion explicite qui l'entoure. En cas de doute entre ce que dit \
explicitement la pratique et ta propre inference, la pratique a toujours raison.
C5. N'ATTRIBUE JAMAIS une affirmation a une reference (VDB-... ou texte officiel) qui ne la \
soutient pas reellement. Si deux sources du contexte traitent d'un sujet voisin mais distinct \
(ex. changement de PRENOM vs changement de NOM), verifie pour chaque affirmation que la source \
citee est bien celle dont le texte contient cette affirmation precise, pas une source voisine \
retrouvee pour le meme cas. Une citation incorrecte (bon raisonnement, mauvaise reference) est \
aussi grave qu'une affirmation inventee : en cas de doute sur la source exacte d'une \
affirmation, cite le texte officiel general plutot qu'une reference precise incertaine, ou \
omets la reference plutot que d'en inventer une.

## D. Structure et ton de la reponse (public non-specialiste)
Le public vise n'est pas a l'aise avec le jargon administratif ou juridique : sois clair et \
pragmatique, mais ne sacrifie jamais la substance a la brievete - une reponse trop seche, sans \
aucune explication ni justification, est un ECHEC meme si elle est courte. Structure chaque \
reponse ainsi :
D1. Une PREMIERE phrase qui donne directement l'essentiel de la reponse, adaptee au TYPE de \
question - ne force JAMAIS un verdict "Oui/Non" sur une question qui n'en appelle pas un :
   - Question fermee (peut-on, doit-on, a-t-on le droit de...) : "Oui, vous pouvez...", "Non, il \
   faut d'abord...", "Cela depend de X : ...".
   - Question ouverte (quelles/quelle est/comment/quand/qui/qu'est-ce que...) : une phrase qui \
   donne directement le coeur de la reponse sans "Oui" ou "Non" artificiel. Exemple pour "Quelles \
   sont les regles pour X ?" : "Les regles applicables sont les suivantes :" ou directement la \
   regle principale, PAS "Oui, il y a des regles...".
D2. Ensuite, explique en quelques phrases normales (pas uniquement des puces) le raisonnement \
ou le pourquoi : sur quelle base legale, quelle logique, quelle condition precise justifie cette \
reponse. Utilise une liste a puces uniquement quand il y a reellement plusieurs elements a \
enumerer (pieces a fournir, conditions, etapes) - chaque puce peut faire une phrase complete si \
besoin, ne la tronque pas artificiellement pour la raccourcir.
D3. Les exceptions ou cas particuliers, s'il y en a, dans une section separee et clairement \
annoncee ("Attention, cas particuliers : ..."), jamais noyees dans la reponse principale.
D4. Phrases courtes et vocabulaire simple, oui - mais chaque phrase doit rester une phrase \
complete et argumentee, pas un fragment telegraphique. La regle A1 (citation systematique des \
sources) s'applique a CHAQUE affirmation, y compris dans les puces de la reponse principale, \
pas seulement dans la section des cas particuliers. Tout terme technique ou juridique peu \
courant doit etre explique en quelques mots entre parentheses des sa premiere apparition.

## E. Format technique
E1. Ne termine PAS ta reponse par un avertissement/disclaimer : celui-ci est ajoute \
automatiquement apres coup par l'application, ne le repete pas toi-meme."""

NO_RESULTS_MESSAGE = (
    "Aucun passage du corpus n'est jugé suffisamment pertinent pour répondre "
    "avec certitude à cette question. Reformule ta question ou vérifie "
    "manuellement les textes concernés."
)

# Rappel affiche a la fin de chaque reponse - ajoute programmatiquement (pas
# genere par le modele) pour garantir un texte et une mise en forme (italique,
# police reduite) strictement identiques a chaque fois. Voir bot_teams.py
# (Adaptive Card) et app.py (st.caption) pour le rendu visuel par canal.
DISCLAIMER_TEXT = (
    "Cette reponse est une aide et ne remplace pas une verification par le "
    "service juridique communal ou une decision individuelle motivee de "
    "l'officier de l'etat civil."
)

# Filet de securite contre les citations d'article fabriquees (regle B3 du
# SYSTEM_PROMPT) : detecte un numero d'article cite dans la reponse ("art.
# N" / "article N") qui ne correspond a AUCUN article officiel present
# parmi les passages retrouves. Ne verifie pas le sens de la citation (un
# numero present mais cite pour un mauvais sujet ne serait pas detecte) -
# c'est un filet minimal contre l'invention pure d'un numero, pas une
# verification semantique complete.
_CITATION_RE = re.compile(
    r"\bart(?:icle)?s?\.?\s*([A-Z]?[0-9]+(?:[/-][0-9]+)*"
    r"(?:bis|ter|quater|quinquies|sexies|septies|octies)?)",
    re.IGNORECASE,
)


def check_citation_integrity(results, answer_text):
    """Retourne la liste (triee) des numeros d'article cites dans
    answer_text qui ne correspondent a aucun article officiel (statut_entree
    != "reference_interne") parmi les passages effectivement fournis au
    modele dans `results`."""
    cited = {m.upper() for m in _CITATION_RE.findall(answer_text)}
    if not cited:
        return []
    available = {
        str(meta["numero"]).strip().upper()
        for _, meta in results
        if meta.get("statut_entree") != "reference_interne" and meta.get("numero")
    }
    return sorted(n for n in cited if n not in available)


# Troisieme garde-fou (complementaire a check_citation_integrity ci-dessus) :
# ajoute suite a un cas reel (2026-08-19) ou le modele a cite un article REEL
# et bien present dans le contexte (donc invisible pour check_citation_integrity,
# qui ne verifie que l'EXISTENCE du numero) mais traitant en realite d'un
# sujet voisin sans rapport avec l'affirmation qu'il etait cense soutenir -
# l'article correct etait pourtant lui aussi present et retenu apres filtre.
# check_citation_integrity ne peut structurellement pas detecter ce cas (voir
# son propre commentaire) ; celui-ci verifie le CONTENU de chaque citation,
# pas seulement sa presence.
CITATION_RELEVANCE_SYSTEM_PROMPT = """Tu verifies, APRES la redaction d'une reponse, si chaque \
citation d'article ou de pratique validee qui y figure soutient REELLEMENT l'affirmation a \
laquelle elle est associee - pas seulement si le numero cite existe parmi les sources, mais si \
son CONTENU dit vraiment ce que la reponse lui fait dire.

Piege frequent a detecter : un article existe reellement et traite d'un sujet VOISIN ou \
SUPERFICIELLEMENT SIMILAIRE (meme theme general, mots-cles partages - ex. meme institution \
juridique, meme tranche d'age, meme type de demarche) mais concerne en realite un point \
different (une autre condition, un autre moment de la procedure, un autre cas de figure) de \
celui evoque par l'affirmation citee. Dans ce cas, la citation est incorrecte meme si le numero \
est parfaitement reel et present dans les sources.

Pour chaque citation numerotee presente dans la reponse, compare son texte integral (fourni \
ci-dessous parmi les sources) a l'affirmation precise qu'elle est censee soutenir. Si le texte \
de la source citee ne soutient PAS reellement cette affirmation precise, signale-le - \
notamment si un AUTRE passage parmi ceux fournis semble plus directement pertinent pour cette \
affirmation. Ne signale PAS une citation simplement parce qu'elle est generale ou incomplete : \
signale uniquement un vrai decalage entre le sujet de la source et l'affirmation qu'elle est \
censee soutenir.

Reponds UNIQUEMENT avec un objet JSON de la forme :
{"citations_douteuses": [{"citation": "<numero ou reference tel que cite dans la reponse>", \
"probleme": "<une phrase courte expliquant pourquoi cette source ne soutient pas l'affirmation>", \
"source_plus_pertinente": "<numero d'une autre source fournie qui semble plus adaptee, ou null>"}]}
Liste vide si toutes les citations sont correctement appliquees."""


def check_citation_relevance(client, query, results, answer_text):
    """Verifie, via un appel LLM dedie, que chaque citation presente dans
    answer_text est bien appliquee a son sujet reel (pas seulement qu'elle
    existe - voir check_citation_integrity pour cette verification
    syntaxique complementaire). Cout : un appel LLM supplementaire par
    reponse - retourne (issues, usage) comme filter_applicable_practices,
    pour que l'appelant puisse inclure ce cout dans sa telemetrie. Robuste
    par construction : toute erreur (reseau, JSON invalide, reponse non
    parsable...) renvoie ([], None) plutot que de bloquer la reponse - un
    faux negatif de cette verification ne doit jamais empecher de repondre
    a l'utilisateur."""
    if not answer_text or not results:
        return [], None

    sources_desc = "\n\n".join(
        f"- reference: {meta.get('numero') or meta.get('chunk_id')}\n"
        f"  titre: {meta.get('titre_contexte') or ''}\n"
        f"  contenu: {meta['text_for_embedding'][:1500]}"
        for _, meta in results
    )
    user_message = (
        f"Question posee : {query}\n\n"
        f"Reponse generee a verifier :\n{answer_text}\n\n"
        f"Sources fournies au moment de la generation :\n\n{sources_desc}"
    )

    try:
        completion = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": CITATION_RELEVANCE_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(completion.choices[0].message.content)
        issues = parsed.get("citations_douteuses", []) if isinstance(parsed, dict) else []
        issues = [i for i in issues if isinstance(i, dict) and i.get("citation")]
        return issues, completion.usage
    except Exception:  # pylint: disable=broad-except
        return [], None


def format_citation_warnings(unverified, relevance_issues):
    """Construit une liste unifiee de messages d'alerte a partir des deux
    garde-fous de citation (check_citation_integrity : numero introuvable ;
    check_citation_relevance : numero reel mais mal applique), pour un
    affichage coherent quel que soit le canal (Teams, Streamlit, terminal).
    Retourne une liste de chaines vide si tout est en ordre."""
    warnings = []
    for numero in unverified or []:
        warnings.append(
            f"Le numero '{numero}' cite dans la reponse n'a pas ete retrouve tel quel "
            f"parmi les sources disponibles - verifiez qu'il n'a pas ete invente."
        )
    for issue in relevance_issues or []:
        msg = (
            f"La source '{issue['citation']}' pourrait ne pas soutenir reellement "
            f"l'affirmation associee : {issue.get('probleme', '')}"
        )
        if issue.get("source_plus_pertinente"):
            msg += f" (une autre source disponible, '{issue['source_plus_pertinente']}', semble plus pertinente)."
        warnings.append(msg)
    return warnings


def embed_query(client, query):
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=[query])
    return resp.data[0].embedding


def build_user_message(context, query):
    return f"""Contexte documentaire :
{context}

---

Question de l'agent de l'etat civil : {query}"""


VERIFICATION_SYSTEM_PROMPT = """Tu verifies, AVANT toute redaction de reponse, si des \
pratiques validees (clarifications de terrain internes, chacune illustrant un cas concret \
anterieur) s'appliquent reellement a une nouvelle question posee par un agent de l'etat civil.

Pour chaque pratique proposee, compare ses PREMISSES/conditions de fond decisives (statut \
marital des parents, nationalite, type d'acte concerne, statut de la personne - refugie, \
demandeur d'asile, etc. - ...) telles qu'elles apparaissent dans son enonce, avec les faits \
decrits dans la question posee. Une pratique n'est "applicable" que si ses premisses \
decisives correspondent aux faits de la question - PAS seulement si le sujet general se \
ressemble (meme type de demarche administrative, memes documents, meme contexte de \
protection internationale...). Exemple : une pratique qui traite explicitement de parents NON \
maries n'est PAS applicable a une question qui concerne des parents maries (meme sans preuve \
du mariage) - ce sont deux situations juridiquement differentes. En cas de doute reel (la \
question ne precise pas un element decisif), considere la pratique comme applicable plutot \
que de la rejeter a tort.

Reponds UNIQUEMENT avec un objet JSON de la forme :
{"verdicts": [{"code": "<code exact fourni>", "applicable": true ou false, "raison": "<une phrase courte>"}, ...]}
Un verdict par pratique candidate recue, dans le meme ordre, sans en omettre aucune."""


def filter_applicable_practices(client, query, results):
    """Deuxieme passage de verification, dedie : avant la generation, verifie
    que les PREMISSES des pratiques validees retrouvees (statut marital,
    nationalite, type d'acte...) correspondent reellement aux faits de la
    question, et ecarte celles qui ne correspondent pas. Les textes officiels
    (articles/circulaires) ne passent pas par ce filtre : une loi s'applique
    de maniere generale, elle n'est pas liee aux faits d'un cas precis comme
    une pratique validee.

    Cout : un appel LLM supplementaire, uniquement s'il y a au moins une
    pratique validee parmi les resultats. Robuste par construction : toute
    erreur (reseau, JSON invalide, code non reconnu...) fait retomber sur les
    resultats non filtres plutot que de bloquer la reponse - un faux negatif
    de la verification ne doit jamais empecher de repondre."""
    practices = [(score, meta) for score, meta in results
                 if meta.get("statut_entree") == "reference_interne" and meta.get("numero")]
    if not practices:
        return results, None

    candidates_desc = "\n\n".join(
        f"- code: {meta['numero']}\n  titre: {meta.get('titre_contexte') or ''}\n"
        f"  contenu: {meta['text_for_embedding'][:1500]}"
        for _, meta in practices
    )
    verification_user_message = (
        f"Question posee par l'agent : {query}\n\n"
        f"Pratiques candidates a verifier :\n\n{candidates_desc}"
    )

    try:
        completion = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": VERIFICATION_SYSTEM_PROMPT},
                {"role": "user", "content": verification_user_message},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(completion.choices[0].message.content)
        verdicts = parsed.get("verdicts", []) if isinstance(parsed, dict) else []
        rejected_codes = {
            v["code"] for v in verdicts
            if isinstance(v, dict) and v.get("applicable") is False and v.get("code")
        }
        usage = completion.usage
    except Exception:  # pylint: disable=broad-except
        return results, None

    filtered = [
        (score, meta) for score, meta in results
        if meta.get("statut_entree") != "reference_interne" or meta.get("numero") not in rejected_codes
    ]

    if not filtered:
        # Garde-fou : si la verification rejette 100% des candidats alors
        # qu'il y en avait au depart, c'est plus probablement un exces de
        # prudence de la verification (elle exige une correspondance parfaite
        # au lieu de tolerer les differences mineures) qu'un signal fiable
        # que rien n'est utilisable. Mieux vaut repondre avec les resultats
        # non filtres (le prompt de generation garde de toute facon sa propre
        # consigne de verification des premisses, groupe C) que de perdre
        # totalement la reponse alors que du contenu pertinent existe.
        return results, usage

    return filtered, usage


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

    results, verif_usage = filter_applicable_practices(client, query, results)
    if verbose and verif_usage:
        print(f"[verification : {len(results)} passages retenus apres filtre de pertinence]\n")

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

    answer = completion.choices[0].message.content
    unverified = check_citation_integrity(results, answer)
    relevance_issues, _relevance_usage = check_citation_relevance(client, query, results, answer)
    if verbose:
        warnings = format_citation_warnings(unverified, relevance_issues)
        for w in warnings:
            print(f"[ATTENTION - {w}]\n")

    return answer


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
