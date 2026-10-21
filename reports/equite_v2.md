# Audit d'equite du modele

Rappel par segment, sur le jeu de test. Un rappel faible sur un segment suffisamment peuple signale une detection inegale et doit etre explique.

## Par tranche_age

| segment | n | rappel | precision |
|---|---:|---:|---:|
| 0-17 | 3378 | 0.8902 | 0.6651 |
| 18-29 | 927 | 0.8929 | 0.5639 |
| 30-49 | 2638 | 0.8465 | 0.5778 |
| 50-64 | 3009 | 0.8559 | 0.5460 |
| 65+ | 134 | 0.8889 | 0.5333 |
## Par niveau_tarif

| segment | n | rappel | precision |
|---|---:|---:|---:|
| ELEVE | 2623 | 0.9214 | 0.4741 |
| RAISONNABLE | 6593 | 0.8489 | 0.6914 |
| TRES_ELEVE | 870 | 0.7922 | 0.8841 |
## Par type_prestataire

| segment | n | rappel | precision |
|---|---:|---:|---:|
| CABINET_DENTAIRE | 202 | 0.9722 | 0.6481 |
| CABINET_GENERALISTE | 2518 | 0.7622 | 0.4941 |
| CABINET_SPECIALISTE | 535 | 0.9667 | 0.2358 |
| CENTRE_IMAGERIE | 205 | 0.8571 | 0.9474 |
| CLINIQUE | 1922 | 0.8586 | 0.3899 |
| LABORATOIRE | 667 | 0.9216 | 1.0000 |
| OPTICIEN | 80 | 0.8889 | 1.0000 |
| PHARMACIE | 3910 | 0.9011 | 0.9850 |
## Par formule

| segment | n | rappel | precision |
|---|---:|---:|---:|
| CONFORT | 2125 | 0.8556 | 0.5498 |
| ESSENTIEL | 5580 | 0.8733 | 0.5910 |
| PREMIUM | 2381 | 0.8764 | 0.6753 |
## Par type de fraude (jeu de test)

Rappel par famille de fraude : indique quels mecanismes le modele ne detecte pas encore, et donc ou une regle deterministe serait complementaire du modele.

| type de fraude | n | rappel |
|---|---:|---:|
| ACTE_FICTIF | 53 | 1.0000 |
| DOUBLON | 111 | 0.2252 |
| FRACTIONNEMENT | 37 | 0.7838 |
| INCOHERENCE_PROFIL | 33 | 1.0000 |
| LIGNES_NON_PRESCRITES | 87 | 1.0000 |
| ORDONNANCE_EXPIREE | 76 | 1.0000 |
| PRESTATAIRE_RADIE | 55 | 1.0000 |
| QUANTITE_EXCESSIVE | 59 | 0.9153 |
| SUBSTITUTION_PRODUIT | 43 | 1.0000 |
| SURCONSOMMATION | 37 | 1.0000 |
| SURFACTURATION | 165 | 1.0000 |
| UPCODING | 82 | 0.8171 |

### Lecture : DOUBLON est une limite des DONNEES, pas du modele

Le rappel sur `DOUBLON` est de loin le plus bas de la table. L'investigation montre que ce n'est pas une faiblesse du modele : sur les 909 factures etiquettees `DOUBLON`, seules **12** possedent une signature repetee (meme assure, meme prestataire, meme date de soin, meme montant), et seules **14** partagent leur `numero_facture` avec une autre facture.

Autrement dit, 98 % des cas `DOUBLON` n'ont **aucune duplication reelle dans les donnees metier**. Ce sont des factures ordinaires dont l'identifiant est attribue dans un bloc contigu en fin de plage (FAC-00082846 a FAC-00083754, melange avec `ACTE_FICTIF` qui occupe la plage suivante). L'etiquette ne correspond donc a aucun signal observable dans les variables disponibles.

Consequence operationnelle : ce rappel ne s'ameliorera pas en reentrainant. La detection des doublons de soumission doit passer par une **regle deterministe** sur `numero_facture` a la reception, independamment du modele. C'est d'ailleurs l'une des dix regles d'invalidite deja implementees dans `predicare_seed.qualite_donnees` : elles s'appliquent a la soumission, le modele a l'analyse.

Les autres familles sont a des rappels de 0,78 a 1,00. Le modele couvre donc les 13 mecanismes observables ; le quatorzieme n'est pas apprenable a partir de ce jeu.