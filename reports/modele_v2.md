# Modele de detection de fraude - version 2

## Performance sur le test (periode la plus recente, lue une seule fois)

| Metrique | Valeur |
|---|---|
| ROC-AUC | 0.9507 |
| PR-AUC | 0.8928 |
| Rappel au seuil retenu | 0.8747 |
| Precision au seuil retenu | 0.5977 |
| F1 | 0.7101 |
| Specificite | 0.9439 |
| Seuil applique | 0.2766 |

## Matrice de confusion (jeu de test)

| | fraude reelle | non-fraude reelle |
|---|---|---|
| **alerte (score >= seuil)** | 768 | 517 |
| **pas d'alerte** | 110 | 8691 |

## Cout metier

- Cout au seuil retenu : 4 851 000 ariary
- Cout si toutes les factures etaient traitees comme frauduleuses : 27 624 000 ariary
- **Economie : 22 773 000 ariary**


Le seuil est arbitre sur le jeu de VALIDATION, jamais sur le test, et contraint par une exigence de rappel de 90% fixee par le plan d'action (Module 2). Deux consequences merite d'etre dites au jury :

- **Le rappel atteint sur le test (87.5%) est leggerement inferieur a l'objectif** (90%). Le seuil a ete calcule sur une autre periode que celle du test : c'est le comportement attendu d'un seuil mesure, et l'ecart de quelques points est la mesure honnete de la variabilite temporelle du jeu. Baisser le seuil jusqu'a 0.20 porterait le rappel du test a 0.89, au prix de pres de 1000 faux positifs supplementaires.
- **Le seuil historique de 0.8 n'a pas ete conserve.** Avec 8,7 % de fraude dans la population, il ne laisse passer que les cas les plus evidents : au-dessus de 0.8, la precision est haute mais une part importante des fraudes echappe a l'alerte. Un seuil n'a pas de sens sans le cout qu'il evite et le cout qu'il engendre, d'ou l'arbitrage par cout metier ci-dessus.

Le seuil reste modifiable a chaud depuis l'ecran d'administration (`make threshold VALEUR=...`) : si le gestionnaire prefere limiter la charge de controle, il peut le relever sans reentrainer.

## Donnees d'entrainement

- Factures utilisees : 84593 (rejets par regles d'invalidite : 0)
- Empreinte du jeu : `sha256:e2db12cf9f034467af9a3935c47bd1b61f70765b510542dd86e9f3237add5dc6`
- SMOTE applique : oui
- Validation (pour memoire) : rappel 0.9008, PR-AUC 0.9100

## Hyperparametres retenus

| parametre | valeur |
|---|---|
| `colsample_bytree` | 0.9 |
| `eval_metric` | logloss |
| `learning_rate` | 0.04 |
| `max_depth` | 8 |
| `min_child_weight` | 1 |
| `n_estimators` | 400 |
| `n_jobs` | -1 |
| `objective` | binary:logistic |
| `random_state` | 42 |
| `reg_lambda` | 1.0 |
| `scale_pos_weight` | 1.0 |
| `subsample` | 0.9 |
| `tree_method` | hist |

Grille exploree : 12 configurations, notees sur le jeu de validation (jamais sur le test).
