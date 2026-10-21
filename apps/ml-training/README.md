# Entraînement et évaluation du modèle de fraude

Phase 2 du plan d'action. Ce dossier contient du **code de job**, pas un
service : l'entraînement se lance par `make train`, jamais au démarrage de la
pile. Un modèle s'entraîne une fois, se sert en continu.

## Fichiers

| Fichier | Rôle |
| --- | --- |
| `src/predicare_ml_training/dataset.py` | Lecture des 14 CSV, rejet des factures invalides, assemblage de X / y / segments |
| `src/predicare_ml_training/model.py` | XGBoost, choix du seuil, coût métier, contenu des artefacts |
| `src/predicare_ml_training/train.py` | Découpage temporel, SMOTE, hyperparamètres, écriture des artefacts, audit d'équité |
| `src/predicare_ml_training/evaluate.py` | Comparaison des stratégies de déséquilibre et audit d'équité |
| `notebooks/` | Exploration libre, non utilisée en production |

La featurisation, elle, **n'est pas ici** : elle vit dans
`packages/predicare-core/src/predicare/features.py`, que
`apps/api-inference` appelle aussi. C'est la seule façon de garantir que
l'entraînement et la production produisent exactement les mêmes variables.

## Commandes

```bash
make train VERSION=2   # entraîne et écrit models/2/
make evaluate          # compare SMOTE / scale_pos_weight et audite l'équité
```

Les deux s'exécutent dans l'image Docker partagée : même XGBoost, même SHAP,
même pandas que le service d'inférence. Les jobs escreivent avec l'uid de
l'utilisateur courant, donc les artefacts restent modifiables par la suite.

## Artefacts produits

Écrits dans `/models/<version>/` :

```
model.joblib        modèle XGBoost sérialisé
features.json       ordre des variables, versionné avec le modèle
metadata.json       métriques, seuil, empreinte d'entraînement
referentiels.json   référentiels statiques, versionnés avec le modèle
```

Cet artefact est la source de vérité du service `api-inference`. MLflow, lui,
est un outil de **suivi** (expériences, lineage), pas un service d'inférence :
c'est pourquoi il est dans un profil optionnel et non dans le cœur de la pile.
Le job tente la journalisation et échoue silencieusement si le serveur ne
répond pas : un entraînement complet ne doit pas dépendre du profil `mlops`.

## Le modèle v1, en bref

- **32 variables**, toutes calculables à partir de la facture et des
  référentiels, sans historique. Les agrégats d'historique (surconsommation,
  fractionnement, réutilisation d'ordonnance) sont **volontairement absents** :
  ils exigeraient une requête d'historique à l'inférence, et un modèle
  entraîné avec des agrégats servis à zéro décalerait la production en
  silence. Ils arriveront en v2 avec l'enrichissement SQL.
- **Découpage temporel strict** : entraînement 2024-10 → 2026-03, validation
  2026-04 → 2026-06, test 2026-07 → 2026-10 lu **une seule fois**, après que
  le choix du modèle et du seuil soit figé.
- **SMOTE sur le seul jeu d'entraînement**, jamais avant le découpage :
  appliqué avant, il synthétiserait des points à cheval sur la frontière
  temporelle. `make evaluate` compare à `scale_pos_weight` et à l'absence de
  traitement — SMOTE l'emporte de peu, et le rapport le dit.
- **Seuil calculé** : il minimise le coût métier (3 000 ariary par faux
  positif contre 30 000 par faux négatif) sous contrainte de rappel ≥ 90 %.
  Résultat : **0,2876**, avec un rappel de 0,870 et une précision de 0,597
  sur le test. Le seuil historique de 0,8 est abandonné.

## Limite connue, documentée

Le rappel sur le type `DOUBLON` (0,23) n'est pas une faiblesse du modèle :
sur les 909 factures étiquetées, seules **12** ont une signature métier
répétée et **14** partagent leur `numero_facture`. Les identifiants de ce
type occupent un bloc contigu en fin de plage, sans duplication réelle dans les
données. L'étiquette ne correspond donc à aucun signal observable, et ce
rappel ne s'améliorera pas en réentraînant. La détection des doublons de
soumission relève d'une **règle déterministe** à la réception, pas du modèle.

## Les notebooks d'exploration

`notebooks/` contient deux carnets de reconnaissance et d'exploration
(descouverte des données, distribution des labels, variables discriminantes).
Un notebook ne fait **jamais** partie de la chaîne de production : ce qui
sert à l'entraînement ou à l'inférence vit dans ce package, importable,
testable et exécutable dans Docker. Le CDC est explicite sur ce point : le
résultat attendu est « une plateforme exploitable, et non une collection de
notebooks ou de scripts ».

## Propriétaire : Mirado