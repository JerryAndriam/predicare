# Comparaison des strategies de desequilibre - version 1

Jeu de test : 10086 factures dont 878 frauduleuses. Seuil arbitre sur la VALIDATION pour chaque strategie, metriques lues sur le TEST une seule fois. Les trois strategies partagent les memes hyperparametres : on ne compare que le traitement du desequilibre.

| strategie | seuil | ROC-AUC | PR-AUC | rappel | precision | F1 | cout total |
|---|---:|---:|---:|---:|---:|---:|---:|
| aucun traitement | 0.05 | 0.9440 | 0.8768 | 0.8747 | 0.4344 | 0.5805 | 6 300 000 |
| scale_pos_weight=10.4 | 0.32 | 0.9459 | 0.8755 | 0.8827 | 0.4158 | 0.5653 | 6 357 000 |
| SMOTE | 0.29 | 0.9437 | 0.8657 | 0.8872 | 0.4181 | 0.5684 | 6 222 000 |

**Retenu** : `SMOTE` (cout metier le plus faible).

## Ce que dit cette comparaison

**Le choix importe peu, et il faut le dire.** Les trois strategies presentent des PR-AUC entre 0.866 et 0.877, et des couts metiers ecartes de 0.1 M ariary. SMOTE est donc retenu parce qu'il est le moins cher, de peu, et parce que le Module 2 du cursus demande de le maitriser : autant etre exact sur la part qui revient a la conformite plutot que d'inventer une superiorite technique que les chiffres ne montrent pas.

Trois lectures a assumer devant le jury :

- **« Aucun traitement » resort au seuil 0.05**, tres bas. Sans traitement, le modele attribue a peine plus de 0.5 a une fraude ; il faut donc descendre tres bas pour tenir le rappel vise. Son cout favorable vient de la compensation d'une precision faible par un tres grand nombre de faux positifs bon marche. C'est le piege que l'arbitrage par cout est cense cadrer, et il faut le dire plutot que de presenter la ligne comme une victoire de la strategie.
- **`scale_pos_weight` est l'option la plus sobre** : elle ne deforme aucune donnee et dit simplement au modele qu'un faux negatif coute dix fois plus cher. Elle est moins bien notee ici, ce qui est un resultat contreditif, pas une erreur : le cout de reference (3 000 contre 30 000) favorise un rappel tres eleve, terrain sur lequel SMOTE fait un peu mieux.
- **Les trois PR-AUC sont proches** (0.86 a 0.88). Le desequilibre de classe n'est pas, sur ce jeu, le facteur limitant. Ce qui limitait la detection, on l'a vu dans l'audit d'equite, c'est le type `DOUBLON`, dont l'etiquette ne correspond a aucun signal metier observable.

## Reponse preparee a l'objection « pourquoi SMOTE ? »

« Nous avons compare les trois traitements sur un decoupage temporel, avec des seuils arbitres de facon identique. Sur ce jeu, SMOTE l'emporte de tres peu et un `scale_pos_weight` serait aussi defendable. Nous le retenons parce que le Module 2 du cursus l'exige et qu'il ne coute rien ici — nous documentons cela plutot que de presenter SMOTE comme une superiorite technique. Sur un jeu de fraude plus heterogene, l'ecart serait probablement plus net. »
