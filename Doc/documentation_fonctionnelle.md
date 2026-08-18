# Documentation fonctionnelle — Assistant Etat Civil

*Ce document décrit ce que fait l'assistant, pour qui, comment son contenu est construit et
maintenu, et quelles garanties/limites il offre. Pour le détail technique (code, architecture,
infrastructure), voir `architecture_technique.md`. Pour l'installation chez un nouveau client,
voir `guide_installation_client.md`.*

## 1. Objectif et public

L'Assistant Etat Civil est un chatbot IA destiné aux **agents communaux et officiers de l'état
civil** des communes wallonnes. Il répond, en langage clair, à des questions pratiques sur trois
matières :

- **État civil** : actes de naissance/mariage/décès, filiation, nom et prénom, mariage,
  changement d'enregistrement du sexe, responsabilité de l'officier de l'état civil, BAEC (banque
  de données des actes de l'état civil).
- **Population** : registres de la population, adresse de référence, radiations, permis de
  conduire, cartes d'identité, registre national.
- **Étrangers** : séjour (court/long/permanent), regroupement familial, citoyens européens,
  protection internationale, régularisations.

Le public visé n'est **pas** composé de juristes : les agents sont généralement moins à l'aise
avec le jargon administratif ou juridique que d'autres publics professionnels (contrairement,
par exemple, à `chatbot_cpas`, son projet frère, destiné à des travailleurs sociaux plus habitués
à ce vocabulaire). Le ton et la structure des réponses sont calibrés en conséquence (voir §4).

C'est le **deuxième déploiement** d'un même socle technique, validé une première fois sur
`chatbot_cpas` (aide sociale/CPAS) — même code, même architecture, corpus et prompt système
différents.

## 2. Ce que l'assistant fait — et ne fait pas

**Il fait** :
- Répond à une question posée en langage naturel, dans Microsoft Teams (canal principal) ou via
  une interface web de démonstration (Streamlit).
- Cite systématiquement ses sources : texte de loi/circulaire (nom + numéro d'article ou de
  section), ou "pratique validée" interne (référence `VDB-PV-<matière>-<numéro>`) quand la
  réponse s'appuie sur une clarification de terrain plutôt que sur un texte officiel.
- Distingue explicitement trois niveaux de source dans sa réponse : la norme légale/réglementaire,
  son interprétation administrative (circulaire), et une pratique validée (retour d'expérience
  documenté, mais qui ne fait pas foi au même titre qu'un texte officiel).
- Signale les cas particuliers/exceptions dans un encart séparé plutôt que de les noyer dans la
  réponse principale.
- Garde la mémoire des échanges précédents dans une même conversation (jusqu'à 6 échanges).

**Il ne fait pas** :
- Il ne remplace **jamais** une vérification par le service juridique communal ni une décision
  individuelle motivée de l'officier de l'état civil — un rappel en ce sens est ajouté
  automatiquement (par le code, jamais par le modèle) à la fin de chaque réponse.
- Il n'invente jamais de réponse quand le corpus ne couvre pas la question : il le dit
  explicitement plutôt que de deviner (voir §4, garde-fous).
- Il ne transpose jamais aveuglément un cas passé similaire à la situation actuelle sans vérifier
  que les conditions de fond (nationalité, statut marital, statut administratif...) correspondent
  réellement.

## 3. Comment le corpus est alimenté

Le contenu que l'assistant peut citer vient de **quatre sources**, combinées dans un même
format JSON par matière (voir `architecture_technique.md` pour le schéma exact) :

1. **Textes légaux et réglementaires** : Ancien Code civil (Livre I "Des personnes" — extraction
   quasi complète), loi du 15 décembre 1980 sur les étrangers et son arrêté royal d'exécution,
   Code de droit international privé, Code de la nationalité belge, Nouvelle loi communale
   (articles pertinents à l'état civil uniquement), Code de démocratie locale et de la
   décentralisation (CDLD).
2. **Circulaires administratives** en vigueur, qui interprètent ces textes.
3. **Export FAQ Connect (Vanden Broele)** : plusieurs centaines de questions/réponses réelles
   posées par des communes et validées par un expert juridique interne, devenues des "pratiques
   validées" (`pratiques_validees` dans le corpus).
4. **Modules e-learning de formation** (Vanden Broele OrangeConnect) : une trentaine de syllabus
   de formation (un par sujet — mariage, filiation, nom/prénom, séjour, regroupement familial,
   etc.), dont les notions/procédures expliquées et les mises en situation concrètes sont
   extraites dans le corpus, en filtrant tout le bruit purement pédagogique (QCM, feedback de
   quiz, références vidéo/audio). Ces modules ne sont **jamais** cités comme un texte officiel
   par le bot — uniquement comme formation/pratique.

Chaque type de source garde une trace de son origine dans le corpus, ce qui permet au prompt
système de toujours dire au lecteur *d'où* vient une affirmation : texte officiel, circulaire,
ou pratique interne validée (avec sa date).

**Mise à jour du contenu** : ajouter ou corriger une information dans le corpus est un processus
géré manuellement (édition des fichiers JSON du corpus, puis reconstruction du pipeline de
recherche — voir `architecture_technique.md`, §4). Le mode de fonctionnement établi est :
l'utilisateur remonte un cas réel testé (idéalement avec la correction d'un expert métier), la
cause est diagnostiquée (contenu manquant/incorrect, instabilité de recherche, ou fidélité du
prompt), le corpus ou le prompt est corrigé de façon **générale** — pas seulement pour la
question qui a soulevé le problème — puis le pipeline est relancé et revalidé avant repoussée en
production.

## 4. Garde-fous de fiabilité

Trois garde-fous techniques distincts protègent contre les deux risques principaux d'un
assistant IA de ce type — halluciner une information, ou mal appliquer une information réelle à
un cas différent :

1. **Vérification de pertinence des pratiques (2ᵉ passage LLM)** : avant de rédiger sa réponse,
   un second appel au modèle vérifie que les prémisses de fond des pratiques candidates
   (nationalité, statut marital, statut administratif...) correspondent réellement à la question
   posée, et écarte celles qui ne correspondent pas — avec un garde-fou anti-sur-rejet (si 100 %
   des candidats sont écartés, on revient aux résultats bruts plutôt que de perdre la réponse).
2. **Vérification anti-citation fabriquée (après génération)** : chaque numéro d'article cité
   dans la réponse est comparé automatiquement aux numéros réellement présents dans les passages
   retrouvés. En cas de citation non vérifiée (numéro inventé), un encart d'alerte rouge
   s'affiche — ce garde-fou a été ajouté suite à un cas réel où le bot avait inventé un numéro
   d'article inexistant sur le statut de résident de longue durée, malgré une règle de prompt
   explicite l'interdisant : **le prompt seul ne suffit pas**, un filet technique après coup est
   nécessaire en complément.
3. **Prompt système structuré en 5 groupes de règles** (citation des sources, gestion de
   l'incertitude, non-transposition d'une pratique à un cas différent, structure/ton de la
   réponse, format technique) — voir `architecture_technique.md` pour le détail complet.

## 5. Limites connues et acceptées

- **Fragilité résiduelle du retrieval près du seuil de pertinence**, sur les sujets denses du
  corpus : la recherche par similarité cosinus varie légèrement d'un appel d'API à l'autre
  (ré-embedding non parfaitement déterministe), ce qui peut faire passer un passage pertinent
  juste sous ou juste au-dessus du seuil de retenue selon le moment. Ce n'est pas un bug à
  corriger en boucle cas par cas — c'est une limite structurelle du retrieval par similarité sur
  un corpus dense, couverte par le disclaimer de fin de réponse et par les garde-fous du §4.
  Un harnais d'évaluation objectif (`run_eval.py`) a par ailleurs montré empiriquement, en
  2026-08, que la recherche hybride (mots-clés + vecteur) et le semantic ranker d'Azure — deux
  améliorations "standard" attendues — dégradaient en fait la qualité sur ce corpus (chunks trop
  longs/hétérogènes pour un signal mots-clés utile), et ont donc été écartés au profit du
  retrieval vectoriel pur déjà en place.
- **Recodification du Code civil en cours** (notamment la cohabitation légale) : le "nouveau"
  Code civil n'a pas encore été obtenu ; les entrées correspondantes restent au statut
  `extraits_cites_source_secondaire` (citées via une source secondaire, pas le texte officiel
  définitif).
- **Articles 40bis/40ter de la loi du 15/12/1980** (et plus largement toute référence légale non
  encore indexée comme article officiel dans le corpus) : si le modèle cite un numéro d'article
  qui n'a pas encore d'entrée officielle correspondante dans le corpus, le garde-fou anti-citation
  fabriquée déclenche une alerte même quand la citation est en réalité correcte — un faux positif
  à distinguer d'une vraie invention lors de la revue.

## 6. Canaux d'accès

- **Microsoft Teams** (canal principal, cible de production) : réponses affichées sous forme de
  carte enrichie (Adaptive Card) — texte de la réponse, encart orange distinct pour les cas
  particuliers le cas échéant, encart rouge distinct en cas de citation non vérifiée, puis le
  disclaimer en petit/italique.
- **Interface web Streamlit** (`app.py`) : outil de démonstration/test interne, avec réglages
  visibles (nombre de passages récupérés, seuil de pertinence, filtre par matière, affichage des
  sources) — pas destiné à un déploiement client final, sert surtout aux démonstrations et aux
  tests manuels.
- **Terminal** (`chat_loop.py`, `rag_answer.py`) : outils de développement/test, pas un canal
  destiné à l'utilisateur final.
