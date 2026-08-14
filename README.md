# Assistant Etat Civil (POC)

Assistant IA pour les agents des services de l'état civil, construit sur le même socle que
`chatbot_cpas` (voir ce projet pour la documentation détaillée de l'architecture, de la
roadmap technique et des choix de conception — ce README ne documente que ce qui est
spécifique à l'état civil).

## État actuel du projet

- **Socle de code** : retrieval (numpy en local + Azure AI Search en production), génération
  (OpenAI), bot Teams (Bot Framework SDK), télémétrie (Application Insights). Copié depuis
  `chatbot_cpas` puis adapté (voir ci-dessous).
- **Corpus : construit et déployé.** 3 matières (`etat_civil`, `population`, `etrangers`),
  313 articles de textes officiels (dont l'extraction quasi complète de l'Ancien Code civil,
  Livre Ier "Des personnes", et les art. 154-155 de la Nouvelle loi communale sur le
  personnel de l'état civil), 777 pratiques validées (dont ~530 issues de l'export FAQ
  Connect), 68 documents sources. Fichiers dans `corpus_par_matiere/`.
- **Pipeline de retrieval a 2 etages** : `rag_answer.py` fait d'abord une recherche par
  similarite (embeddings `text-embedding-3-small`), puis une passe de **verification** par un
  second appel LLM (`filter_applicable_practices`) qui rejette les pratiques dont les
  premisses (statut civil, nationalite, procedure en cours/refusee...) ne correspondent pas a
  la question posee — avec un garde-fou anti-sur-rejet (si 100% des candidats sont rejetes,
  on revient aux resultats bruts plutot que de repondre "aucun resultat").
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
