# Contexte projet — Assistant Etat Civil

## Ce que c'est

Assistant IA (RAG) pour les agents et officiers de l'état civil des communes wallonnes.
C'est le **deuxième déploiement** du socle technique construit et validé sur le projet
frère `chatbot_cpas` (situé dans `c:\dev\chatbot_cpas` sur ce poste) — même architecture,
même code, corpus et prompt système différents (domaine état civil au lieu d'aide sociale
CPAS).

**Contexte business** : ce projet fait partie du même département IA interne Vanden Broele
que `chatbot_cpas` (voir `c:\dev\chatbot_cpas\Doc\synthese_projet_ia_pouvoirs_locaux.md` pour
la stratégie complète). `chatbot_cpas` a servi de pilote pour valider toute la chaîne
technique (Option B : Bot Framework custom + Azure AI Search + Azure App Service, plutôt que
Copilot Studio) ; ce projet est la première vraie duplication de ce socle pour une autre
matière/public.

## Documentation de référence (dans `chatbot_cpas`, à consulter systématiquement)

- `c:\dev\chatbot_cpas\Doc\roadmap_technique_option_b.md` — architecture technique détaillée,
  les 5 phases (retrieval Azure AI Search → app Bot Framework → canal Teams → déploiement
  App Service → observabilité), et surtout les **pièges déjà rencontrés et résolus** (ne pas
  les redécouvrir ici).
- `c:\dev\chatbot_cpas\Doc\plaquette_prerequis_deploiement_client.md` — checklist
  opérationnelle à suivre pour ce déploiement (décisions à prendre, prérequis client, choix
  de tier Azure, grille tarifaire LLM).
- `c:\dev\chatbot_cpas\Doc\explication_phases_1_2.md` — explication pédagogique de
  l'architecture, utile pour re-expliquer le projet à quelqu'un.
- `c:\dev\chatbot_cpas\Doc\catalogue_offres.md` — structure de l'offre commerciale (formation
  + outil + mises à jour, axes autonome/délégué et Base/Premium).

## État actuel de CE projet (chatbot_etat_civil) — mis à jour 2026-08-11

- ✅ Socle de code copié et adapté depuis `chatbot_cpas` (retrieval numpy en local + Azure AI
  Search en production, bot Teams/Bot Framework, télémétrie Application Insights avec
  estimation de coût tokens).
- ✅ `rag_answer.py` : `SYSTEM_PROMPT` réécrit pour le public état civil (public moins à l'aise
  avec le jargon juridique que les travailleurs sociaux CPAS), organisé en groupes A-E
  (citations, gestion de l'incertitude, non-transposition d'une pratique a un autre cas,
  structure/ton). Pipeline de retrieval à 2 étages : recherche par similarité puis
  `filter_applicable_practices()` (second appel LLM qui verifie que les premisses d'une
  pratique retrouvée correspondent bien à la question), avec garde-fou anti-sur-rejet.
- ✅ **Corpus construit** : 3 matières (`etat_civil`, `population`, `etrangers`), 311 articles
  (dont l'extraction quasi complète de l'Ancien Code civil, Livre Ier "Des personnes" — 11
  titres), 777 pratiques validées (dont ~530 issues de l'export FAQ Connect filtré sur
  description non vide), 67 documents sources. Détail et conventions de schéma dans le
  `README.md` de ce projet.
- ✅ **Infrastructure Azure déployée** (POC) : Phases 1 à 5 validées de bout en bout
  (retrieval Azure AI Search → bot Bot Framework → canal Teams → App Service → Application
  Insights). Identité entièrement séparée de `chatbot_cpas` (nouvelle App Registration,
  nouveau Bot Service `chatbot-etat-civil-bot-poc`, nouveau manifeste Teams) — seul le
  service Azure AI Search est partagé (`search-chatbot-cpas-poc`, tier gratuit limité à 1
  service/abonnement) mais avec un index dédié (`chatbot-etat-civil-chunks`).
- ✅ Repo poussé sur GitHub : https://github.com/suyttenhoef-cyber/chatbot_orange
- ✅ Outillage de qualité : `test_questions_batch.py` (test de régression sur questions
  réelles, avec revue déléguée à un agent averti des pièges connus) et
  `verify_corpus_coverage.py` (audit de couverture — détecte un trou d'extraction structurel
  comme celui du chapitre "changement de nom", art. 370/1-370/9, découvert et corrigé le
  2026-08-11 suite à un cas réel remonté par un utilisateur).
- ⏳ Le "nouveau" Code civil (recodification en cours, notamment cohabitation légale,
  art. 1475/1476) n'a pas été obtenu ; ces entrées restent au statut
  `extraits_cites_source_secondaire`.

## Limite connue et acceptée

Le retrieval par similarité cosinus reste structurellement instable près du seuil de
pertinence sur les sujets denses du corpus (variance de re-embedding d'un appel a l'autre) —
ce n'est pas un bug à corriger en boucle par patch cas-par-cas, voir la mémoire
`retrieval_fragilite_residuelle` pour le raisonnement complet.

## Prochaine étape concrète

Pas de chantier bloquant identifié. Le mode de fonctionnement établi est : l'utilisateur
remonte un cas réel testé (idéalement avec une correction d'un expert métier), on diagnostique
la cause (contenu manquant/incorrect vs. instabilité de retrieval vs. fidélité du prompt), on
corrige le corpus ou le prompt de façon **générale** (pas seulement pour la question qui a
soulevé le problème), on relance le pipeline (`chunk_builder` → `embed_chunks` →
`azure_search_setup`), on revalide localement puis en production.
