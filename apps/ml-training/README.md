# Entrainement et evaluation du modele de fraude

Phase 2 du plan d'action. Ce dossier contient du **code de job**, pas un
service : l'entrainement se lance par `make train`, jamais au demarrage de la
pile. Un modele s'entraine une fois, se sert en continu.

## Fichiers attendus

| Fichier | Role |
| --- | --- |
| `feature_engineering.py` | Agregations par assure, prestataire et acte (Phase 2.2) |
| `train.py` | Decoupage temporel, SMOTE sur le seul entrainement, XGBoost, choix du seuil (Phase 2.3-2.5) |
| `evaluate.py` | Metriques, rappel/precision, rapport d'equite par segment |
| `notebooks/` | Exploration libre, non utilisee en production |

## Artefacts produits

Ecrits dans `/models/<version>/` :

```
model.joblib        modele XGBoost serialise
features.json       ordre des variables, versionne avec le modele
metadata.json       metriques, version des donnees, empreinte d'entrainement
```

Cet artefact est la source de verite du service `api-inference`. MLflow, lui,
est un outil de **suivi** (experiences, lineage), pas de service de
inference : c'est pourquoi il est dans un profil optionnel et non dans le
coeur de la pile.

## Brouillon / TODO

- [ ] `feature_engineering.py` : surconsommation, coherence prescription/maladie,
      doublons de prescription
- [ ] `train.py` : decoupage **temporel** (jamais aleatoire : une facture de
      decembre n'appartient pas au jeu d'entrainement si on teste sur janvier)
- [ ] SMOTE applique au seul jeu d'entrainement, jamais avant le decoupage
- [ ] Optimisation des hyperparametres en validation temporelle
- [ ] Seuil choisi par rappel vise x cout des faux positifs, justifie au jury
- [ ] `evaluate.py` : audit d'equite par age, acte et prestataire (Phase 9.4)
- [ ] Test de robustesse sur factures mal formees et valeurs hors plage

Proprietaire : Mirado