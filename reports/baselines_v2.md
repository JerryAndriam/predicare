# Comparaison aux baselines - version 2

Jeu de test : 10086 factures dont 878 frauduleuses. Meme decoupage temporel et memes variables que le modele. Chaque seuil est arbitre sur la VALIDATION, les metriques sont lues sur le TEST une seule fois.

**Ce qui existait dans le depot avant cette comparaison** : aucune baseline. Le seul objectif `logistic` du code etait `binary:logistic` de XGBoost, qui n'est pas une regression logistique. La Q8 du support de soutenance annoncait donc une comparaison qui n'avait pas ete produite ; ce rapport la produit.

## Les trois baselines, exactement

- **Regles deterministes** : somme des indicateurs binaires 0/1 deja calcules par `predicare.features`. Il n'existe pas de module de regles de fraude autonome dans le depot ; ces variables SONT les regles metier disponibles. Aucune regle n'a ete inventee.
  Regles comptees (12) : `depasse_tarif_max`, `produit_non_remboursable`, `ordonnance_absente_requis`, `ordonnance_expiree`, `incompatibilite_sexe`, `incompatibilite_age`, `prestataire_radie`, `hors_convention`, `soin_jour_ferme`, `soin_hors_horaire`, `prestataire_niveau_tarif_eleve`, `hors_periode_contrat`.
- **Regression logistique** : `StandardScaler` + `LogisticRegression` (`class_weight="balanced"`, `max_iter=1000`), sur les memes variables, sans SMOTE (le `class_weight` traite le desequilibre).
- **Regles + modele** : OU logique. Une regle declenchee force le score a 1.0 (alerte garantie) ; sinon le score du XGBoost est conserve. Le score combine est donc une decision, pas une nouvelle probabilite : ROC-AUC et PR-AUC de cette ligne sont indicatives.

Deux seuils sont affiches par baseline :

- le **seuil du modele de production** (0.2876) ;
- le **seuil qui minimise le cout metier sur la validation**, sans contrainte de rappel. C'est la lecture « cout pur » ; le seuil operationnel du modele, lui, est contraint par `RAPPEL_MINIMAL = 90%`.

Cout metier applique : faux positif = 3 000 ariary, faux negatif = 30 000 ariary.

## Resultats

| baseline | seuil | origine du seuil | ROC-AUC | PR-AUC | rappel | precision | F1 | cout total | VP | FP | FN | VN |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| modele XGBoost | 0.2876 | seuil du modele | 0.9432 | 0.8641 | 0.8838 | 0.4161 | 0.5658 | 6 327 000 | 776 | 1089 | 102 | 8119 |
| modele XGBoost | 0.8001 | cout metier minimal (validation) | 0.9432 | 0.8641 | 0.6913 | 0.9967 | 0.8164 | 8 136 000 | 607 | 2 | 271 | 9206 |
| regles deterministes | 0.2876 | seuil du modele | 0.7030 | 0.2835 | 0.6595 | 0.1558 | 0.2520 | 18 384 000 | 579 | 3138 | 299 | 6070 |
| regles deterministes | 3.0000 | cout metier minimal (validation) | 0.7030 | 0.2835 | 0.0638 | 1.0000 | 0.1199 | 24 660 000 | 56 | 0 | 822 | 9208 |
| regression logistique | 0.2876 | seuil du modele | 0.9123 | 0.7891 | 0.8747 | 0.2386 | 0.3749 | 10 653 000 | 768 | 2451 | 110 | 6757 |
| regression logistique | 0.9988 | cout metier minimal (validation) | 0.9123 | 0.7891 | 0.5182 | 0.9785 | 0.6776 | 12 720 000 | 455 | 10 | 423 | 9198 |
| regles + modele (OU) | 0.2876 | seuil du modele | 0.7488 | 0.1604 | 0.9260 | 0.1801 | 0.3015 | 13 056 000 | 813 | 3702 | 65 | 5506 |
| regles + modele (OU) | 1.0000 | cout metier minimal (validation) | 0.7488 | 0.1604 | 0.6595 | 0.1558 | 0.2520 | 18 384 000 | 579 | 3138 | 299 | 6070 |

## Lecture

- **modele XGBoost** au seuil du modele : rappel 0.8838, precision 0.4161, cout metier 6 327 000 ariary.
- **regles deterministes** au seuil du modele : rappel 0.6595, precision 0.1558, cout metier 18 384 000 ariary.
- **regression logistique** au seuil du modele : rappel 0.8747, precision 0.2386, cout metier 10 653 000 ariary.
- **regles + modele (OU)** au seuil du modele : rappel 0.9260, precision 0.1801, cout metier 13 056 000 ariary.

**Cout metier le plus faible** : `modele XGBoost` au seuil 0.2876 (seuil du modele), 6 327 000 ariary.

Le seuil de cout minimal est arbitre sur la VALIDATION, pas sur le test : il peut paraitre severe (ou tres bas) par rapport au seuil de production, et c'est le comportement attendu d'un seuil mesure sur une autre periode.

## Reponse preparee a la Q8

« La comparaison a ete produite sur le meme decoupage temporel et les memes variables. Les regles deterministes seules sont auditales mais atteignent un rappel insuffisant ; la regression logistique fournit une reference lineaire interpretable ; le modele a arbres est retenu pour son cout metier. Le detail chiffre est dans `reports/baselines_v2.md`, et le modele de production n'a pas ete reentraine pour l'obtenir. »

**Limite a dire** : le modele XGBoost de cette comparaison est re-entraine ici avec les memes hyperparametres et le meme SMOTE que la production, mais ce n'est pas l'artefact `models/` : les scores peuvent differer a la marge. Le seuil de production, lui, est bien celui de `metadata.json`.

Note : modele XGBoost au seuil du modele = rappel 0.8838, precision 0.4161, cout 6 327 000 ariary.
