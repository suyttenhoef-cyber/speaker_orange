# Architecture technique — Assistant Etat Civil

*Détail du code, du pipeline de données et de l'infrastructure. Pour la vue fonctionnelle
(objectif, public, garde-fous), voir `documentation_fonctionnelle.md`. Pour l'installation chez
un nouveau client, voir `guide_installation_client.md`.*

## 1. Vue d'ensemble des composants

```
┌─────────────────────┐      ┌──────────────────────┐      ┌────────────────────┐
│ corpus_par_matiere/  │ ───▶ │  chunk_builder.py     │ ───▶ │  chunks.jsonl       │
│ corpus_<matiere>.json│      │  (fusionne matières,  │      │  (une ligne =       │
│ (JSON, édité à la    │      │   résout les refs     │      │   un passage        │
│  main)               │      │   base_legale_assoc.) │      │   indexable)        │
└─────────────────────┘      └──────────────────────┘      └─────────┬──────────┘
                                                                       │
                                                                       ▼
                                                            ┌─────────────────────┐
                                                            │  embed_chunks.py     │
                                                            │  (appel OpenAI       │
                                                            │  text-embedding-3-   │
                                                            │  small, 1536 dim)    │
                                                            └─────────┬───────────┘
                                                                      │
                                          ┌───────────────────────────┴───────────────────────┐
                                          ▼                                                    ▼
                              ┌────────────────────┐                              ┌──────────────────────┐
                              │ embeddings.npz +    │                              │ azure_search_setup.py │
                              │ embeddings_meta.jsonl│                             │ (pousse chunks.jsonl +│
                              │ (retrieval LOCAL,    │                             │  embeddings.npz vers  │
                              │  dev/test uniquement)│                             │  l'index Azure)       │
                              └─────────┬───────────┘                             └──────────┬───────────┘
                                        │                                                     │
                                        ▼                                                     ▼
                              ┌────────────────────┐                              ┌──────────────────────┐
                              │ retrieve.py          │                            │ retrieve_azure_       │
                              │ (Retriever, numpy)   │                            │ search.py             │
                              │ - chat_loop.py        │                           │ (AzureSearchRetriever)│
                              │ - app.py (Streamlit)  │                           │ - bot_teams.py (PROD) │
                              │ - rag_answer.py (CLI) │                           └──────────────────────┘
                              └────────────────────┘
```

Les deux retrievers (`retrieve.py` local en numpy, `retrieve_azure_search.py` en production)
exposent **la même interface** (`search(query_embedding, top_k, exclude_historique, categorie,
sous_categorie, matiere, min_score) -> list[(score, meta)]`), interchangeable côté appelant —
c'est ce qui permet de développer/tester en local sans dépendre d'Azure, avant de pousser vers
l'index de production.

## 2. Schéma du corpus

Chaque fichier `corpus_par_matiere/corpus_<matiere>.json` (un par matière : `etat_civil`,
`population`, `etrangers`) suit ce schéma :

```json
{
  "_matiere": "etat_civil",
  "documents": [
    {"document_id": "ancien_code_civil", "titre": "Ancien Code civil", "type": "loi",
     "statut": "en_vigueur", "notes": "..."}
  ],
  "articles": [
    {"entry_id": "ancien_code_civil#art_370_8_1", "document_id": "ancien_code_civil",
     "numero": "370/8/1", "titre_contexte": "...", "texte": "...",
     "categorie": "etat_civil", "sous_categorie": "nom_prenom",
     "articles_lies": [...], "exemples": [...]}
  ],
  "sections_circulaire": [...],
  "pratiques_validees": [
    {"entry_id": "pratique_...", "code": "PV-EC-NNN", "titre": "...",
     "question_origine": "...", "texte": "...",
     "precise_ou_complete": ["ancien_code_civil#art_..."],
     "categorie": "...", "sous_categorie": "..."}
  ]
}
```

Conventions : pas d'accents français dans `texte`/`titre_contexte` (contrainte d'encodage
historique du pipeline) ; `code` au format `PV-EC-NNN`/`PV-POP-NNN`/`PV-ETR-NNN` (préfixé `VDB-`
dans les réponses du bot) ; `entry_id` = `pratique_<slug>` ou `<document_id>#art_<numéro
slugifié>`. Les modules e-learning suivent la même structure avec un `document_id` dédié
(`type: "elearning_formation"`) et un `numero` **descriptif** pour leurs `articles[]` (pas un
vrai numéro d'article officiel, ex. `"cout-changement-prenom-communal"`).

## 3. Pipeline de requête (retrieval → génération)

Toute la logique métier vit dans `rag_answer.py`, importée par tous les points d'entrée (CLI,
Streamlit, bot Teams, harnais d'évaluation) — un seul endroit à faire évoluer.

1. **Embedding de la question** (`embed_query`) : `text-embedding-3-small`.
2. **Recherche par similarité** (`Retriever.search` / `AzureSearchRetriever.search`) : cosinus,
   filtrée par matière/catégorie si demandé, exclut par défaut les entrées
   `statut_entree="historique_absorbe"`, seuil `DEFAULT_MIN_SCORE=0.25` en dessous duquel un
   passage est écarté même s'il fait partie du top_k. `top_k=14` en production (`bot_teams.py`).
3. **Filtrage de pertinence des pratiques** (`filter_applicable_practices`) : un **second appel
   LLM**, dédié, vérifie que les prémisses de fond des pratiques candidates (celles dont
   `statut_entree == "reference_interne"`) correspondent aux faits de la question — écarte
   celles qui ne correspondent pas. Les textes officiels (articles/circulaires) ne passent
   **jamais** par ce filtre : une loi s'applique de manière générale, elle n'est pas liée aux
   faits d'un cas précis comme une pratique validée. Garde-fou anti-sur-rejet : si 100 % des
   candidats sont rejetés, on revient aux résultats non filtrés plutôt que de perdre la réponse.
4. **Génération** (`build_user_message` + `SYSTEM_PROMPT`) : contexte formaté
   (`format_results_for_prompt`, une citation exacte par passage) + question, envoyés à
   `gpt-4o-mini` (`CHAT_MODEL`), température 0,1 (priorité à la précision factuelle).
5. **Deux vérifications anti-citation, après génération** :
   - `check_citation_integrity` : compare chaque numéro d'article cité dans la réponse (regex
     `_CITATION_RE`, tolère "art."/"article", suffixes bis/ter/quater/quinquies/sexies/septies/
     octies) aux numéros réellement présents parmi les passages **officiels** fournis au modèle.
     Filet purement syntaxique contre l'invention pure d'un numéro — ne détecte pas un numéro
     réel cité sur le mauvais sujet.
   - `check_citation_relevance` (ajouté le 2026-08-19, suite à un cas réel — voir mémoire
     `misapplication_article_reel_voisin_distracteur`) : **un appel LLM dédié** compare le
     contenu intégral de chaque source citée à l'affirmation précise qu'elle est censée
     soutenir, pour détecter le cas où un article *réel et bien retrouvé* traite en fait d'un
     sujet voisin sans rapport (piège que `check_citation_integrity` ne peut structurellement
     pas voir). Retourne, pour chaque citation douteuse, une explication et — quand possible —
     la référence d'une source plus pertinente parmi celles fournies. Robuste par construction
     (toute erreur renvoie une liste vide, jamais de blocage de la réponse), comme
     `filter_applicable_practices`.
   - `format_citation_warnings` fusionne les deux résultats en une liste de messages unique,
     affichée dans un même encart d'alerte (Teams/Streamlit/CLI).

   *Validé empiriquement* : rejouer la réponse fautive du cas réel du 2026-08-19 (citant l'art.
   353-3 hors sujet) à travers `check_citation_relevance` la signale correctement, en suggérant
   l'art. 370/8/1 comme source plus pertinente — sans déclencher de faux positif sur 3 autres
   questions déjà validées. Un test a même détecté un second cas réel (mauvaise application de
   l'art. 40ter à une question sur le regroupement familial) non repéré auparavant.
6. **Disclaimer** : ajouté programmatiquement après coup (jamais généré par le modèle, pour
   garantir un texte et une mise en forme strictement identiques à chaque fois).

### `SYSTEM_PROMPT` — structure en 5 groupes de règles

- **A. Citation des sources** : chaque affirmation appuyée par une source citée explicitement ;
  parcourir tout le contexte avant de rédiger ; distinguer norme légale / circulaire / pratique
  validée ; citer en priorité la référence légale indiquée par `[S'APPUIE SUR : ...]` sur une
  pratique validée ; privilégier le texte officiel le plus récent en cas de contradiction avec
  une pratique plus ancienne, signaler une pratique marquée "potentiellement obsolète".
- **B. Face à l'incertitude : ne jamais inventer** — dont un cas spécifique fréquent (le droit
  applicable au nom suit la nationalité, ne jamais supposer "belge" par défaut) et l'interdiction
  de citer un numéro d'article qui n'apparaît pas textuellement dans le contexte.
- **C. Ne jamais transposer aveuglément une pratique validée à un cas différent** — 5 sous-règles
  (détails spécifiques au cas d'origine, prémisses de fond, alternatives secondaires, ne pas
  contredire une conclusion explicite par une déduction annexe, ne pas attribuer une affirmation
  à la mauvaise source) : la source d'erreur la plus fréquente et la plus grave observée sur ce
  corpus.
- **D. Structure et ton** : première phrase adaptée au type de question (fermée vs ouverte),
  explication du raisonnement, cas particuliers dans une section séparée annoncée "Attention, cas
  particuliers", vocabulaire simple mais phrases complètes.
- **E. Format technique** : ne jamais répéter le disclaimer (ajouté par le code).

## 4. Outillage de construction/vérification du corpus

| Outil | Rôle |
|---|---|
| `chunk_builder.py corpus_par_matiere/ chunks.jsonl` | Fusionne les fichiers de matière, construit le texte embeddable (titre + contexte + texte + exemples), résout `base_legale_associee` pour les pratiques qui référencent un article via `precise_ou_complete`. |
| `embed_chunks.py chunks.jsonl embeddings.npz` | Appels OpenAI par lots (50 chunks), sauvegarde `embeddings.npz` + `embeddings_meta.jsonl` alignés. |
| `azure_search_setup.py` | Crée/met à jour l'index Azure AI Search et y pousse `chunks.jsonl`/`embeddings.npz` — sans redéployer le bot (celui-ci lit l'index à chaque requête). |
| `verify_corpus_coverage.py <texte_source.md> <document_id>` | Audit de couverture : compare les articles d'un texte source brut aux entrées réellement indexées (détecte un chapitre sauté), recherche les références mortes. À relancer après toute extraction massive. |
| `test_questions_batch.py <questions.json> <rapport.json>` | Rejoue une liste de questions réelles à travers tout le pipeline, écrit un rapport structuré (résultats bruts/filtrés/réponse) — revue de qualité qualitative après chaque évolution notable. |
| `run_eval.py` + `eval_gold_set.jsonl` | Harnais d'évaluation **noté** (voir §6) : recall du retrieval objectif, comparaison de stratégies reproductible. |

## 5. Infrastructure Azure actuellement déployée (POC)

| Ressource | Nom | Tier | Notes |
|---|---|---|---|
| Resource group | `rg-chatbot-etat-civil-poc` | — | Séparé de `chatbot_cpas` |
| Azure AI Search | `search-chatbot-cpas-poc` | Free | **Partagé** avec `chatbot_cpas` (limite : 1 service Free par abonnement, 3 index max) — index dédié `chatbot-etat-civil-chunks` |
| App Registration (Entra ID) | `chatbot-etat-civil-bot-poc` | — | Identité séparée de `chatbot_cpas` |
| Azure Bot Service | `chatbot-etat-civil-bot-poc` | F0 (gratuit) | Canal Teams activé |
| App Service Plan | `asp-chatbot-etat-civil-poc` | F1 (gratuit) | Linux, pas de mode "Always On" |
| App Service (Web App) | `app-chatbot-etat-civil-poc` | — | Python, démarré via gunicorn + `aiohttp.worker.GunicornWebWorker` |
| Application Insights | `appi-chatbot-etat-civil-poc` | — | Workspace-based |

Le service Azure AI Search partagé a le **semantic ranker disponible en plan gratuit** (vérifié
via `az search service show` → `semanticSearch: "free"`, quota mensuel limité) — pas besoin
d'upgrader le tier pour l'expérimenter (voir §6).

### Variables d'environnement / secrets requis

En développement local : fichier `.env` (jamais commité). En production App Service : App
Settings Azure (jamais de fichier `.env` déployé).

| Variable | Rôle |
|---|---|
| `OPENAI_API_KEY` | Appels d'embedding et de génération |
| `AZURE_SEARCH_ENDPOINT` | URL du service Azure AI Search |
| `AZURE_SEARCH_ADMIN_KEY` | Clé d'accès à l'index |
| `AZURE_SEARCH_INDEX_NAME` | Nom de l'index (`chatbot-etat-civil-chunks` par défaut) |
| `MicrosoftAppId` / `MicrosoftAppPassword` / `MicrosoftAppType` / `MicrosoftAppTenantId` | Authentification Bot Framework (lues par `bot_config.DefaultConfig`) |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Télémétrie (optionnelle — absente en local, le logger reste actif mais n'envoie nulle part) |

**Piège connu à ne pas reproduire** : `load_dotenv()` doit s'exécuter **avant** tout import qui
lit des variables d'environnement au niveau du module (ex. `bot_config.DefaultConfig`, qui lit
`os.environ` à la définition de la classe, pas à l'instanciation). Un import fait après aurait
capturé un environnement vide — bug réel rencontré sur `chatbot_cpas` (le bot recevait les
messages Teams mais rejetait leur jeton d'authentification, échec silencieux sans erreur
visible). `bot_server.py` appelle `load_dotenv()` avant l'import de `bot_config` précisément pour
cette raison — ne jamais réordonner ces imports.

## 6. Retrieval : ce qui a été testé et le choix retenu

Le retrieval de production est **vectoriel pur** (`retrieve_azure_search.py`,
`search_text=None`). Deux alternatives "standard" ont été testées empiriquement en 2026-08 via
`run_eval.py` sur 44 questions :

| Stratégie | Recall après filtre |
|---|---|
| **Vectoriel pur (retenu)** | **95,1 %** |
| Semantic ranker (cross-encoder sur pool hybride) | 92,7 % |
| Hybride RRF (BM25 + vecteur) | 90,2 % |

Les deux alternatives Azure font **moins bien**, probablement parce que les chunks de ce corpus
sont longs et hétérogènes (jusqu'à ~9000 caractères) — un terrain défavorable au signal BM25
(mots-clés), qui pollue la sélection du pool de candidats avant même qu'un éventuel reranking
n'ait sa chance. Le code des deux alternatives (`search_hybrid`, `search_semantic` dans
`retrieve_azure_search.py`, configuration sémantique dans `azure_search_setup.py`) est laissé en
place pour pouvoir retester facilement si la structure des chunks change, mais **n'est pas appelé
par le pipeline de production**. Détail complet et hypothèse causale : mémoire
`retrieval_hybride_semantic_ecartes` du projet.

## 7. Télémétrie et coûts

`telemetry.py` journalise, vers Application Insights, **uniquement des métriques** — jamais le
texte d'une question ou d'une réponse. Les fonctions `log_question_processed`/`log_error`
n'acceptent structurellement aucun paramètre de type texte libre : impossible d'y logguer du
contenu par erreur future.

Métriques capturées : durée de traitement, nombre de passages retrouvés, présence/absence de
résultat, `top_k` utilisé, matière, tokens consommés (prompt/completion/total), coût estimé en
USD (tarifs GPT-4o-mini codés en dur, `GPT4O_MINI_INPUT_COST_PER_1M_USD` /
`_OUTPUT_COST_PER_1M_USD` — à revoir si `CHAT_MODEL` change). Tout échec de journalisation est
intercepté et ignoré silencieusement : l'observabilité ne doit jamais faire planter une réponse
réelle.

**Coût par question** : jusqu'à 3 appels LLM (embedding mis à part) peuvent avoir lieu par
question — `filter_applicable_practices` (si des pratiques sont candidates),
`check_citation_relevance` (systématique dès qu'une réponse est générée), et la génération
elle-même. `bot_teams.py` additionne les tokens des trois appels dans une même métrique
`question_processed`. L'ajout de `check_citation_relevance` (2026-08-19) augmente le coût par
question d'environ un tiers par rapport au pipeline précédent (2 appels) — jugé justifié au vu du
type d'erreur qu'il détecte (voir §5), mais à surveiller si le volume de questions grandit
significativement.

## 8. Interfaces / points d'entrée

| Fichier | Rôle |
|---|---|
| `bot_server.py` | Serveur aiohttp exposant `/api/messages` (production, canal Teams) |
| `bot_teams.py` | `EtatCivilAssistantBot` : logique de conversation, construction de l'Adaptive Card (texte + encart cas particuliers + encart citation non vérifiée + disclaimer) |
| `bot_config.py` | Config standard Bot Framework SDK (lit les variables d'environnement) |
| `app.py` | Interface Streamlit de démonstration/test (réglages visibles : top_k, seuil, matière, historique inclus ou non) |
| `chat_loop.py` | Chatbot conversationnel en terminal, pour développement/test |
| `rag_answer.py` | CLI une question → une réponse, et bibliothèque partagée par tous les autres points d'entrée |
