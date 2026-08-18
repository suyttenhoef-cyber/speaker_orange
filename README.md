# Assistant Etat Civil (POC)

Assistant IA pour les agents des services de l'état civil, construit sur le même socle que
`chatbot_cpas` (voir ce projet pour la documentation historique du premier portage — ce README
ne documente que ce qui est spécifique à l'état civil).

**Documentation complète** (fonctionnelle, technique, installation client) : voir le dossier
[`Doc/`](Doc/) —
[`documentation_fonctionnelle.md`](Doc/documentation_fonctionnelle.md),
[`architecture_technique.md`](Doc/architecture_technique.md),
[`guide_installation_client.md`](Doc/guide_installation_client.md).

## État actuel du projet

- **Socle de code** : retrieval (numpy en local + Azure AI Search en production), génération
  (OpenAI), bot Teams (Bot Framework SDK), télémétrie (Application Insights). Copié depuis
  `chatbot_cpas` puis adapté (voir ci-dessous).
- **Corpus : construit et déployé.** 3 matières (`etat_civil`, `population`, `etrangers`),
  333 articles de textes officiels/notions (dont l'extraction quasi complète de l'Ancien Code
  civil Livre Ier "Des personnes", les art. 154-155 de la Nouvelle loi communale, l'art. 15bis
  de la loi du 15/12/1980 sur le résident de longue durée, et les notions du premier module
  e-learning ingéré), 786 pratiques validées (dont ~530 issues de l'export FAQ Connect et 9
  issues du même module e-learning), 69 documents sources. Fichiers dans `corpus_par_matiere/`.
- **Pipeline de retrieval a 2 etages** : `rag_answer.py` fait d'abord une recherche par
  similarite (embeddings `text-embedding-3-small`), puis une passe de **verification** par un
  second appel LLM (`filter_applicable_practices`) qui rejette les pratiques dont les
  premisses (statut civil, nationalite, procedure en cours/refusee...) ne correspondent pas a
  la question posee — avec un garde-fou anti-sur-rejet (si 100% des candidats sont rejetes,
  on revient aux resultats bruts plutot que de repondre "aucun resultat").
- **Garde-fou anti-citation-fabriquée** : `check_citation_integrity()` compare après génération
  chaque numéro d'article cité dans la réponse aux numéros réellement présents parmi les
  passages retrouvés ; en cas de citation non vérifiée (numéro inventé), un encart d'alerte
  rouge s'affiche dans Teams/l'app Streamlit. Ne détecte pas une citation d'un article réel mais
  utilisé sur le mauvais sujet — voir la règle C5 du `SYSTEM_PROMPT` pour ce cas-là.
- **Infrastructure Azure : déployée et fonctionnelle** (POC), Phases 1 à 5 validées de bout en
  bout (retrieval → bot → Teams → App Service → télémétrie) :
  - Azure AI Search : index dédié `chatbot-etat-civil-chunks` sur le service partagé
    `search-chatbot-cpas-poc` (tier gratuit, 1 service par abonnement, 3 index max).
  - Bot Service `chatbot-etat-civil-bot-poc`, identité (App Registration) et manifeste Teams
    séparés de `chatbot_cpas`.
  - App Service `app-chatbot-etat-civil-poc` (plan `asp-chatbot-etat-civil-poc`, tier F1),
    resource group `rg-chatbot-etat-civil-poc`.
  - Application Insights `appi-chatbot-etat-civil-poc` (télémétrie + estimation de coût
    tokens).
- **Réponses en Adaptive Card dans Teams** : verdict + explication en prose, section "Attention,
  cas particuliers" mise en évidence, disclaimer en petit/italique ajouté par le code (jamais
  par le LLM).
- **Repo GitHub** : https://github.com/suyttenhoef-cyber/chatbot_orange

## Outils de test et de vérification

- `test_questions_batch.py <questions.json> <rapport.json>` : fait tourner une liste de
  questions réelles à travers tout le pipeline (retrieval + vérification + génération) et
  écrit un rapport JSON structuré (résultats bruts, résultats après vérification, réponse) —
  utilisé pour les revues de qualité après chaque évolution notable du corpus ou du prompt.
- `verify_corpus_coverage.py <texte_source.md> <document_id>` : audit de couverture — compare
  les articles présents dans un texte source brut avec ceux réellement indexés dans le corpus
  (détecte un chapitre/titre entier sauté par erreur lors d'une extraction), et recherche les
  références d'articles mortes (`precise_ou_complete` pointant vers un article inexistant).
  À relancer après toute extraction massive de contenu légal, avant de pousser vers Azure
  Search.
- `run_eval.py` / `eval_gold_set.jsonl` : harnais d'évaluation **noté** du pipeline RAG (voir
  mémoire `evaluation_notee_rag` et `retrieval_hybride_semantic_ecartes`). Rejoue un jeu de
  questions "gold" (question, `expected_entry_ids`, `criteres_reussite`) à travers le pipeline
  réel et calcule un taux de rappel objectif (`recall_filtered_pct`), au lieu d'un jugement
  qualitatif "ça semble mieux". Deux modes :
  - `python3 run_eval.py [--backend local|azure] [--mode vector|hybrid|semantic]` : rapide et
    gratuit, mesure uniquement le rappel du retrieval — à utiliser pour comparer deux
    stratégies de retrieval sans regénérer de réponses.
  - `--full` : ajoute la génération de la réponse, `check_citation_integrity()`, et un juge LLM
    qui évalue si la réponse respecte `criteres_reussite` — plus lent/coûteux, réservé aux
    contrôles qualité périodiques.
  À enrichir avec de nouveaux cas au fil des cas réels remontés par les utilisateurs (voir
  mémoire `evaluation_notee_rag` sur le biais de ce premier jeu, auto-écrit donc optimiste).

## Ingestion des modules e-learning (source de corpus)

En plus des textes légaux et de l'export FAQ Connect, le corpus s'enrichit de modules
e-learning de formation (Vanden Broele OrangeConnect, ~30 syllabus annoncés, un par
matière/sujet). Méthodologie validée sur un premier pilote (module "Domicile", matière
`population`, 2026-08-14) :

1. **Un document par module** : `document_id` dédié, `type: "elearning_formation"` (distinct de
   `"faq_export_helpdesk"`/`"faq_formation"`), avec dans `notes` la liste des textes officiels
   que le module synthétise (loi, AR, instructions générales...) — jamais cité par le bot comme
   texte officiel lui-même (règle A3 du `SYSTEM_PROMPT` : formation/pratique, pas norme).
2. **Filtrer le bruit pédagogique** : questions à choix multiples, feedback ("Bravo c'est
   correct"), références vidéo/audio/BD — aucun contenu substantiel, à ignorer entièrement.
3. **Deux types d'entrées extraites** :
   - Chaque **notion ou procédure expliquée** (ex. "résidence principale", "radiation
     d'office") → une entrée `articles[]` avec un `numero` **descriptif** (pas un vrai numéro
     d'article officiel, ex. `"radiation-office"`), `categorie`/`sous_categorie` cohérents avec
     la matière.
   - Chaque **"Mise en situation"** (scénario concret + réponse d'expert, présent dans quasi
     tous les modules) → une nouvelle `pratique_validee`, en continuant la numérotation
     existante de la matière concernée (`PV-EC-`/`PV-POP-`/`PV-ETR-`), `source_validation`
     mentionnant le module e-learning d'origine.
4. **Cross-référencer** les articles de loi déjà indexés que le module cite explicitement (ex.
   art. 108/373 du Code civil) via `articles_lies`, sans les dupliquer.
5. **Traiter un syllabus à la fois** (ou petits lots de 2-3), avec rebuild + test local + push
   Azure après chaque syllabus — pas un gros lot parallèle d'un coup, pour éviter de reproduire
   l'incident de mixup de fichier rencontré lors de l'extraction systématique de l'Ancien Code
   civil (voir mémoire `agent-batch-persist-to-disk` et `verifier-couverture-corpus`).

## Schéma du corpus

Chaque fichier `corpus_par_matiere/corpus_<matiere>.json` suit ce schéma :

```json
{
  "_matiere": "etat_civil",
  "documents": [
    {"document_id": "ancien_code_civil", "titre": "Ancien Code civil", "type": "loi", "statut": "en_vigueur", "notes": "..."}
  ],
  "articles": [
    {"entry_id": "ancien_code_civil#art_370_8_1", "document_id": "ancien_code_civil", "numero": "370/8/1",
     "titre_contexte": "...", "texte": "...", "categorie": "etat_civil", "sous_categorie": "nom_prenom",
     "articles_lies": [...], "exemples": [...]}
  ],
  "sections_circulaire": [...],
  "pratiques_validees": [
    {"entry_id": "pratique_...", "code": "PV-EC-NNN", "titre": "...", "question_origine": "...",
     "texte": "...", "precise_ou_complete": ["ancien_code_civil#art_..."], "categorie": "...", "sous_categorie": "..."}
  ]
}
```

Conventions : pas d'accents français dans `texte`/`titre_contexte` (contrainte d'encodage
historique du pipeline), `code` au format `PV-EC-NNN`/`PV-POP-NNN`/`PV-ETR-NNN` (cité dans les
réponses du bot avec le préfixe `VDB-`), `entry_id` = `pratique_<slug>` ou
`<document_id>#art_<numero_slugifie>`.

## Pipeline

1. Éditer/compléter `corpus_par_matiere/corpus_<matiere>.json`.
2. `python3 chunk_builder.py corpus_par_matiere/ chunks.jsonl` (fusionne les matières, résout
   les références `base_legale_associee` entre pratiques et articles).
3. `python3 embed_chunks.py chunks.jsonl embeddings.npz` (appels OpenAI, nécessite
   `OPENAI_API_KEY`).
4. Tester en local : `python3 rag_answer.py "<question>"` ou `python3 chat_loop.py`.
5. `python3 verify_corpus_coverage.py <texte_source> <document_id>` si le corpus a été
   modifié en masse.
6. Pousser vers la production : `python3 azure_search_setup.py` (recrée/met à jour l'index
   Azure AI Search à partir de `chunks.jsonl`/`embeddings.npz`, sans redéployer le bot — le
   bot lit l'index à chaque requête).

## Limites connues

- Le retrieval par similarité cosinus reste structurellement instable près du seuil de
  pertinence sur les sujets denses du corpus (variance de re-embedding) — accepté comme
  limite du POC, couvert par le disclaimer de fin de réponse.
- Le "nouveau" Code civil (recodification en cours, notamment la cohabitation légale,
  art. 1475/1476) n'a pas encore été obtenu ; les entrées correspondantes restent au statut
  `extraits_cites_source_secondaire`.
