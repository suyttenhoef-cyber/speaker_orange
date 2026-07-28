# Assistant Etat Civil (POC)

Assistant IA pour les agents des services de l'état civil, construit sur le même socle que
`chatbot_cpas` (voir ce projet pour la documentation détaillée de l'architecture, de la
roadmap technique et des choix de conception — ce README ne documente que ce qui est
spécifique à l'état civil).

## État actuel du projet

- **Socle de code réutilisé tel quel** : retrieval (numpy + Azure AI Search), génération
  (OpenAI), bot Teams (Bot Framework SDK), télémétrie (Application Insights) — tout est en
  place et fonctionnel, copié depuis `chatbot_cpas` après validation complète sur ce dernier.
- **Prompt système adapté** : `rag_answer.py` cible maintenant les agents/officiers de l'état
  civil, avec les mêmes garde-fous déjà éprouvés sur `chatbot_cpas` (citation systématique,
  distinction texte officiel / circulaire / pratique validée, interdiction de transposer les
  chiffres ou détails d'un cas passé au dossier actuel).
- **Corpus : à construire.** C'est la seule vraie tâche restante avant un premier test — les
  textes de référence (Code civil, circulaires état civil) existent déjà mais sont en
  PDF/Word volumineux, à structurer au format JSON attendu (voir schéma ci-dessous).
- **Infrastructure Azure : pas encore déployée** pour ce projet — à faire une fois le corpus
  prêt, en suivant `roadmap_technique_option_b.md` du projet `chatbot_cpas` (identique étape
  par étape : Azure AI Search, App Registration, Bot Service, App Service, Application
  Insights).

## Schéma du corpus attendu (identique à `chatbot_cpas`)

Chaque fichier `corpus_par_matiere/corpus_<matiere>.json` doit suivre ce schéma :

```json
{
  "_matiere": "actes_naissance",
  "documents": [
    {"document_id": "code_civil", "titre": "Code civil", "type": "loi", "date_texte": "...", "statut": "en_vigueur"}
  ],
  "articles": [
    {"entry_id": "code_civil#art_55", "document_id": "code_civil", "numero": "55",
     "titre_contexte": "Declaration de naissance", "texte": "...", "categorie": "...", "sous_categorie": "..."}
  ],
  "sections_circulaire": [...],
  "pratiques_validees": [...]
}
```

Le decoupage par `_matiere` reste a definir avec le metier (ex. `actes_naissance`,
`actes_mariage`, `actes_deces`, `nationalite`, `changement_de_nom`...) - un fichier par
matiere, comme pour `chatbot_cpas` (aide_sociale_generale, logement, etc.).

## Prochaines étapes

1. Recevoir les documents sources (PDF/Word) et les structurer au format ci-dessus.
2. `python3 chunk_builder.py corpus_par_matiere/ chunks.jsonl`
3. `python3 embed_chunks.py chunks.jsonl embeddings.npz`
4. Tester en local : `python3 chat_loop.py`
5. Suivre la roadmap technique de `chatbot_cpas` pour le déploiement Azure/Teams.
