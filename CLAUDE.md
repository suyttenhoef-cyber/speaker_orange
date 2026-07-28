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

## État actuel de CE projet (chatbot_etat_civil)

- ✅ Socle de code copié et adapté depuis `chatbot_cpas` (retrieval numpy + Azure AI Search,
  bot Teams/Bot Framework, télémétrie Application Insights avec estimation de coût tokens).
- ✅ `rag_answer.py` : `SYSTEM_PROMPT` réécrit pour le public état civil, mêmes garde-fous
  que `chatbot_cpas` (citation systématique des sources, distinction texte officiel /
  circulaire / pratique validée, interdiction de transposer les détails d'un cas passé au
  dossier actuel — ce dernier point a été un vrai bug corrigé sur `chatbot_cpas`, voir le
  roadmap).
- ⏳ **Corpus : à construire** — c'est le principal chantier restant. Les textes de référence
  (Code civil, circulaires état civil) existent en PDF/Word, à structurer au format JSON
  attendu (voir schéma dans `README.md` de ce projet). Le découpage par `_matiere` reste à
  définir avec le métier (ex. `actes_naissance`, `actes_mariage`, `actes_deces`,
  `nationalite`...).
- ⏳ **Infrastructure Azure : pas encore déployée** pour ce projet spécifiquement — à faire
  une fois le corpus prêt, en suivant exactement les mêmes étapes que `chatbot_cpas` (nouvel
  App Registration, nouvelle ressource Bot Service, nouveau manifeste Teams — tout doit être
  une identité séparée, décision déjà prise : bot séparé, pas une matière ajoutée au bot CPAS
  existant).
- Repo git local initialisé (`main`), pas encore poussé sur GitHub (à faire si besoin).

## Prochaine étape concrète

Recevoir les documents sources (PDF/Word) de l'état civil, les analyser, proposer un premier
découpage par matière, puis structurer le contenu au format JSON du corpus (voir schéma dans
`README.md`).
