# Guide d'installation — déploiement chez un nouveau client (commune)

*Ce document décrit les étapes pour installer l'Assistant Etat Civil chez un nouveau client
(une commune ou une intercommunale), à partir du socle déjà validé sur ce projet et sur son
projet frère `chatbot_cpas`. Adapté de `chatbot_cpas/Doc/roadmap_technique_option_b.md` et
`plaquette_prerequis_deploiement_client.md` (procédure déjà exécutée et validée de bout en bout
à deux reprises) — voir ces documents pour le détail historique complet des deux portages.
Pour la vue fonctionnelle, voir `documentation_fonctionnelle.md` ; pour le détail du code, voir
`architecture_technique.md`.*

**Point de départ important** : contrairement à un tout premier portage, le socle technique
(code, logique métier, garde-fous) est **déjà entièrement construit et validé** — un nouveau
déploiement client ne consiste donc **pas** à re-développer quoi que ce soit, mais à :
1. préparer le contenu métier (corpus) propre au client s'il diffère du corpus état civil déjà
   construit,
2. reconfigurer l'infrastructure Azure **dans l'abonnement du client** (jamais sur l'abonnement
   du prestataire — voir §2),
3. rebrancher les mêmes composants de code sur cette nouvelle infrastructure.

## 1. Décisions à prendre AVEC le client, avant tout démarrage technique

| Décision | Options | Impact |
|---|---|---|
| Matière(s) à activer | État civil / Population / Étrangers / les trois | Détermine si le corpus déjà construit convient tel quel ou doit être adapté/étendu |
| Contenu spécifique à la commune | Circulaires internes, pratiques locales propres à cette commune | À ajouter au corpus existant (voir §3) |
| Axe 1 — Hébergement | Autonome (l'IT du client gère) / Délégué (le prestataire gère via Azure Lighthouse) | Qui a la main au quotidien sur l'infrastructure Azure |
| Axe 2 — Contenu | Base (figé après livraison) / Premium (suivi + mise à jour continue à partir des cas réels remontés) | Charge de maintenance récurrente |
| Fournisseur LLM | Azure OpenAI (résidence UE garantie) / Claude (si exigé — réserve de résidence UE à vérifier au moment du déploiement) | Coût, conformité RGPD |
| Canal de lancement | Teams (recommandé — c'est celui déjà validé) / Outlook (add-in séparé, non couvert par ce socle) | Conditionne l'étape 4 ci-dessous |

**Livrable attendu** : une fiche de cadrage signée/validée par le client avant de réserver le
moindre créneau technique.

## 2. Ce que LE CLIENT doit avoir ou obtenir — à vérifier en amont, pas le jour J

- [ ] **Un tenant Microsoft 365 professionnel actif**, avec licences Teams incluses (Business
  Basic/Standard/Premium, ou E1/E3/E5) — **pas** un compte Teams gratuit grand public, qui ne
  permet jamais de charger une app personnalisée. *Piège déjà rencontré* : un tenant Azure créé
  via un essai gratuit personnel n'inclut **jamais** de licence M365/Teams par défaut — ne
  jamais le supposer acquis.
- [ ] **Une personne côté client avec les droits d'administrateur Teams**, disponible pour
  approuver l'installation de l'app dès qu'elle est soumise. La politique de gouvernance Teams de
  nombreux tenants exige une validation admin avant activation — **à planifier explicitement
  dans le rétroplanning**, pas à découvrir en fin de projet (déjà rencontré : un tenant tiers a
  bloqué l'activation pendant plusieurs jours faute d'accès admin disponible).
- [ ] **Son propre abonnement Azure actif** — dans tous les cas, y compris en formule
  **déléguée** : c'est le client qui a son abonnement, géré par le prestataire via Azure
  Lighthouse s'il gère l'hébergement pour son compte. Ne jamais héberger un client sur
  l'abonnement du prestataire (facturation opaque, risque financier cumulé, impossible à
  "arrêter" proprement si le client part).
- [ ] **Le fournisseur LLM facturé sur son propre abonnement** : ressource Azure OpenAI
  provisionnée dans l'abonnement Azure du client, ou sa propre clé Anthropic s'il exige Claude en
  direct. Ne jamais faire tourner plusieurs clients sur une seule clé API partagée.
- [ ] **Le contenu métier spécifique à la commune**, s'il y en a : circulaires internes propres,
  pratiques locales — à distinguer du corpus déjà générique construit pour ce projet.
- [ ] **Une charte de gouvernance validée** : qui a accès aux logs (Application Insights),
  pendant combien de temps (rétention par défaut 90 jours, ajustable), qui valide le contenu du
  corpus, qui peut modifier le prompt système.

## 3. Ce que LE PRESTATAIRE doit avoir prêt avant de démarrer

- [ ] **Le socle de code**, déjà validé et réutilisable tel quel : `bot_config.py`,
  `bot_teams.py`, `bot_server.py`, `rag_answer.py`, `retrieve.py`, `retrieve_azure_search.py`,
  `telemetry.py`, `requirements.txt` — rien à réécrire, juste à reconfigurer pour ce client (voir
  §5, étape 3).
- [ ] **Le corpus prêt** : celui déjà construit pour l'état civil (`corpus_par_matiere/`, 3
  matières) convient tel quel si le client n'a pas de contenu spécifique supplémentaire ; sinon,
  l'enrichir d'abord (édition des fichiers JSON, cf. `architecture_technique.md` §2) et relancer
  le pipeline (`chunk_builder.py` → `embed_chunks.py` → `verify_corpus_coverage.py`) **avant** de
  passer à l'étape Azure.
- [ ] **Une décision claire sur le tier Azure** à utiliser (voir §6) selon ce que le client a
  validé en §1.
- [ ] **Les identifiants du fournisseur LLM choisi** (clé Azure OpenAI, ou clé Anthropic).
- [ ] **Un manifeste Teams générique à personnaliser** (nom, icônes, `packageName`) pour ce
  client avant de le zipper et le soumettre.
- [ ] **Le jeu de test/évaluation** (`eval_gold_set.jsonl`, `test_questions_batch.py`) prêt à
  rejouer une fois l'infrastructure du client en place, pour valider le déploiement avant de le
  considérer terminé (voir §7).

## 4. Étapes techniques, dans l'ordre

Chaque étape ci-dessous a déjà été exécutée et validée de bout en bout à deux reprises (sur
`chatbot_cpas` puis sur ce projet) — voir `chatbot_cpas/Doc/roadmap_technique_option_b.md` pour
le détail historique de chaque validation, y compris les pièges rencontrés et déjà résolus (à ne
pas redécouvrir).

### Étape 1 — Resource group + Azure AI Search (≈1–2 jours pour un client déjà cadré)

1. Créer le resource group dédié au client (ex. `rg-<client>-etatcivil`).
2. Créer le service Azure AI Search (tier selon §6) **dans l'abonnement du client**.
3. Adapter les variables d'environnement (`AZURE_SEARCH_ENDPOINT`, `AZURE_SEARCH_ADMIN_KEY`,
   `AZURE_SEARCH_INDEX_NAME`) pour pointer vers ce nouveau service.
4. Lancer `azure_search_setup.py` : crée l'index (champs filtrables + champ vectoriel 1536 dim
   HNSW cosinus + champs d'affichage) et y pousse `chunks.jsonl`/`embeddings.npz` déjà calculés
   côté prestataire (aucun ré-embedding nécessaire si le corpus n'a pas changé).
5. Valider par une requête de test directe sur l'index (ou `python3 rag_answer.py "<question>"`
   en pointant temporairement `retrieve_azure_search` vers ce nouvel index) avant de passer à la
   suite.

### Étape 2 — Identité + Bot Service (≈1 jour)

1. Créer une App Registration Entra ID **single-tenant**, dédiée à ce client (Microsoft a
   déprécié la création de bots multi-tenant — ce n'est pas bloquant pour un usage Teams sur un
   tenant différent de celui où l'app est enregistrée : le single-tenant ne contraint que
   l'authentification du bot, pas les tenants Teams autorisés à l'installer).
2. Créer la ressource Azure Bot Service correspondante (tier F0 gratuit — voir §6), activer le
   canal Teams.
3. Renseigner `MicrosoftAppId`/`MicrosoftAppPassword`/`MicrosoftAppType`/`MicrosoftAppTenantId`
   dans la configuration (App Settings de l'App Service à l'étape suivante, jamais un fichier
   `.env` déployé).

### Étape 3 — App Service (déploiement du bot) (≈1 jour)

1. Créer l'App Service Plan (tier selon §6) et la Web App (Python, Linux) dans le resource group
   du client.
2. Préparer le **package de déploiement minimal** : seuls les fichiers réellement nécessaires à
   l'exécution du bot sont nécessaires (`bot_config.py`, `bot_teams.py`, `bot_server.py`,
   `rag_answer.py`, `retrieve.py`, `retrieve_azure_search.py`, `telemetry.py`,
   `requirements.txt`) — le corpus, les embeddings et l'app Streamlit ne sont pas nécessaires
   côté bot (tout le retrieval passe par l'index Azure AI Search déjà peuplé à l'étape 1).
3. Configurer le démarrage via **gunicorn** + le worker `aiohttp.worker.GunicornWebWorker`
   (`bot_server.py` expose une app aiohttp, pas une app WSGI classique).
4. Configurer tous les secrets en **App Settings Azure** (jamais de fichier `.env` déployé) :
   `OPENAI_API_KEY`, `AZURE_SEARCH_*`, `MicrosoftAppId/Password/Type/TenantId`, plus
   `SCM_DO_BUILD_DURING_DEPLOYMENT=true` pour qu'Azure installe les dépendances au déploiement
   (build Oryx).
5. Pointer l'endpoint de messagerie du Bot Service (créé à l'étape 2) vers
   `https://<nom-app>.azurewebsites.net/api/messages`.

### Étape 4 — Manifeste Teams (≈quelques heures + délai d'approbation admin variable)

1. Personnaliser le manifeste Teams générique (nom affiché, icônes, `packageName`) pour ce
   client.
2. Zipper le package (manifeste + icônes) et le soumettre au tenant M365 du client.
3. **Prévenir l'administrateur Teams du client en amont** (voir §2) — la politique de
   gouvernance Teams exige souvent une approbation admin avant activation, un délai à anticiper
   dans le planning, pas à découvrir le jour du test.

### Étape 5 — Application Insights + gouvernance (≈1 jour)

1. Créer la ressource Application Insights (workspace-based) et la lier à l'App Service via
   `APPLICATIONINSIGHTS_CONNECTION_STRING`.
2. Créer un budget d'alerte sur le resource group du client (seuil à définir avec lui, ex. 20
   €/mois, notification par e-mail au dépassement de 80 %).
3. Vérifier qu'un message réel dans Teams génère bien un événement `question_processed` dans
   Application Insights, **sans aucune trace du contenu de la question ou de la réponse** —
   condition de conformité non négociable (voir `architecture_technique.md` §7).
4. Documenter dans la charte de gouvernance (voir §2) : accès RBAC aux logs (par défaut, seul le
   propriétaire de l'abonnement Azure y a accès), durée de rétention, qui peut modifier le prompt
   système ou le contenu du corpus.

### Étape 6 — Test réel en conditions d'usage (avant de considérer le déploiement terminé)

Ne jamais considérer un déploiement terminé sur la seule base de tests automatisés. Poser dans
Teams, avec un vrai utilisateur métier si possible, 2 à 3 questions représentatives du
quotidien du client, et vérifier :
- que la réponse cite correctement ses sources,
- que le disclaimer et les encarts (cas particuliers / citation non vérifiée le cas échéant)
  s'affichent bien,
- qu'un événement de télémétrie sans contenu sensible apparaît dans Application Insights.

*Leçon déjà tirée à deux reprises sur ce socle* : un test en conditions réelles a chaque fois
révélé un problème qu'aucun test préalable n'avait détecté (ex. un `top_k` trop bas, un bug de
chargement des variables d'environnement) — ce test n'est pas une formalité.

## 5. Ce qui reste à refaire pour un nouveau client, une fois le socle capitalisé

Les étapes 1 à 4 (retrieval, bot Framework, canal Teams, garde-fous applicatifs) sont
**capitalisées** — le code ne change pas d'un client à l'autre. Pour un nouveau client, il reste
à refaire :
- le **cadrage** (§1),
- la **configuration Azure spécifique** (§4, étapes 1 à 5 — nouvelles ressources, nouveaux
  secrets, mais mêmes commandes/mêmes fichiers de code),
- l'**observabilité et la gouvernance** (§4, étape 5),
- et, si le client a du contenu métier propre, son **ajout au corpus** avant l'étape 1.

C'est ce qui justifie un coût marginal par nouveau client bien inférieur au coût du premier
portage (qui a dû construire tout le socle technique lui-même).

## 6. Choix de tier Azure selon ce que le client attend

| Ressource | Tier économique | Tier robuste | Quand choisir le tier robuste |
|---|---|---|---|
| Azure AI Search | Free (0 €, 50 Mo, 3 index) | Basic (~70 €/mois) | Corpus volumineux (plusieurs centaines de chunks par matière) — **attention** : le tier Free ne permet qu'**un seul service par abonnement** ; deux clients distincts ne peuvent donc pas partager un même tier Free sur le même abonnement (voir §2 : chaque client doit avoir son propre abonnement Azure) |
| App Service | Free F1 (0 €, pas d'"Always On") | Basic B1 (~13 €/mois, "Always On") | Client utilisant le bot en heures de bureau, n'acceptant pas un délai de réveil de quelques secondes sur le premier message de la journée après une période d'inactivité |
| Azure Bot Service | F0 (gratuit) | — | Le tier gratuit suffit dans tous les cas observés jusqu'ici |

Le **semantic ranker** d'Azure AI Search est disponible même en tier Free (quota mensuel limité,
vérifiable via `az search service show` → champ `semanticSearch`) — ne pas supposer qu'il exige
un upgrade payant. Il a néanmoins été testé et écarté sur le corpus état civil (voir
`architecture_technique.md` §6) : ne le réactiver pour un nouveau client que si un nouveau test
sur son corpus spécifique montre un gain réel.

## 7. Grille tarifaire LLM indicative

*Tarifs publics à titre indicatif — à revérifier sur la page tarifaire officielle du fournisseur
au moment de chaque engagement client, ces prix évoluent régulièrement.*

| Fournisseur / modèle | Coût entrée (1M tokens) | Coût sortie (1M tokens) |
|---|---|---|
| Azure OpenAI — GPT-4o-mini (modèle actuellement utilisé, `CHAT_MODEL`) | ~0,15 $ | ~0,60 $ |
| Claude (Azure AI Foundry ou API directe) | Plusieurs fois plus cher au token | Idem |

Le coût mesuré par question dépend surtout de la taille du contexte envoyé (nombre de passages
récupérés × longueur du corpus) et de la longueur de l'historique de conversation inclus — pas
uniquement de la question elle-même. La télémétrie (`telemetry.py`) capture ce coût par question
indépendamment de l'accès (parfois restreint) au dashboard `platform.openai.com/usage`.

## 8. Pièges déjà rencontrés — à ne pas redécouvrir à chaque client

- Un tenant Azure "essai gratuit" n'inclut **jamais** de licence Microsoft 365/Teams par défaut.
- Le programme Microsoft 365 Developer (sandbox gratuit) peut **refuser l'éligibilité** sans
  garantie — ne jamais en dépendre comme unique plan pour obtenir un tenant de test.
- Une politique de gouvernance Teams peut exiger une **approbation admin** avant qu'une app
  chargée soit utilisable — anticiper ce délai dans le planning.
- `load_dotenv()` doit **toujours** s'exécuter avant tout import qui lit des variables
  d'environnement au niveau du module (ex. `bot_config.DefaultConfig`) — sinon les identifiants
  restent vides silencieusement, sans erreur visible, et le bot ne répond simplement pas dans
  Teams.
- Ne jamais faire confiance à un test automatisé seul : toujours prévoir un vrai test en
  conditions réelles (§4, étape 6) avant de considérer un déploiement terminé.
- La recherche hybride et le semantic ranker Azure, présentés comme des améliorations standard,
  ont dégradé la qualité du retrieval sur ce corpus spécifique (chunks longs/hétérogènes) — ne
  pas les activer par réflexe pour un nouveau client sans un test comparatif préalable
  (`run_eval.py --mode hybrid|semantic` contre `--mode vector`).
