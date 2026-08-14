LOI du 17 juin 2026 relative au Conseil du contentieux des etrangers (CCE) - NON INTEGREE au corpus

Source : export Vanden Broele Connect, recu le 2026-08-12, colle par l'utilisateur en reponse
a une demande de texte sur les CONDITIONS du statut de resident de longue duree - ce texte-ci
s'est avere etre un document DIFFERENT (voir Loi_15_12_1980_art_15bis_resident_longue_duree.md
pour le texte effectivement pertinent, obtenu ensuite et integre au corpus).

Contenu de cette loi (~40 pages, 351 articles renumerotes en 2.1, 2.2, 2.3... suite a une
recodification recente) : procedure de recours JUDICIAIRE devant le Conseil du contentieux
des etrangers - composition et fonctionnement des chambres, langue de la procedure,
recusation des juges, delais d'introduction d'un recours (art. 2.15 : regle generale de 30
jours, avec de nombreuses exceptions a 10 ou 5 jours selon le type precis de decision
attaquee), instruction du dossier, debats, prononce et notification des arrets, pourvoi en
cassation administrative devant le Conseil d'Etat.

Decision de ne PAS integrer ce texte au corpus (2026-08-12), pour deux raisons :
1. Decalage de public : ce chatbot est destine aux agents communaux de l'etat civil, de la
   population et des etrangers - ils ne plaident pas et n'introduisent pas de recours devant
   le CCE (ce sont les avocats et les administres eux-memes qui le font). Aucune pratique
   validee existante dans corpus_etrangers.json ne recoupe ce contenu de facon substantielle.
2. Risque specifique meme pour l'extrait a priori le plus simple : la regle generale des 30
   jours (art. 2.15) est assortie de nombreuses exceptions (10 ou 5 jours) selon le type de
   decision, la procedure (frontiere, transfert, combinee retour+eloignement, motifs
   specifiques du CGRA...). Extraire uniquement la regle generale creerait un risque concret
   qu'un agent (ou le bot) affirme "30 jours" avec assurance sur un cas ou le vrai delai est 5
   jours - un delai de recours manque est un prejudice plus grave qu'une absence de reponse.

A reconsiderer uniquement si le perimetre du chatbot s'elargit vers une orientation
juridique/procedurale des administres (pas seulement administrative communale) - dans ce cas,
redemander le texte complet a l'utilisateur (il n'est pas reproduit integralement ici) et
prevoir une extraction complete de l'art. 2.15 avec toutes ses exceptions, jamais partielle.
