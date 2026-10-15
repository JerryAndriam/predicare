# Notebooks d'exploration

Espace de travail libre pour l'analyse exploratoire (Phase 2.1 du plan
d'action) : distribution des labels, déséquilibre de classes, variables
discriminantes.

## Règle

Un notebook ne fait **jamais** partie de la chaîne de production. Ce qui
sert à l'entraînement ou à l'inférence vit dans les scripts de
`apps/ml-training/`, importable, testable et exécutable dans Docker.

Le CDC est explicite sur ce point : le résultat attendu est « une plateforme
exploitable, et non une collection de notebooks ou de scripts ». Les
notebooks servent à comprendre les données ; le code sert à les exploiter.

## Brouillon / TODO

- [ ] Distribution du label de fraude sur les 24 mois
- [ ] Variables discriminantes : corrélations, importance univariée
- [ ] Analyse des cas de doublons de prescription
- [ ] Analyse des incohérences prescription / maladie
- [ ] Hypothèses de surconsommation par acte

Propriétaire : Mirado