# Tests de bout en bout

Tests qui traversent toute la chaîne : dépôt d'une facture, inférence,
alerte, décision gestionnaire, question au RAG, indicateurs du tableau de
bord.

## Ce qui les distingue des autres tests

Les tests unitaires et d'intégration de `tests/` tournent sur des composants.
Ici, on vérifie que les composants **ensemble** produisent le parcours métier
complet, sur une pile réellement démarrée.

C'est la vérification que le jury fera le jour J : 20 factures inédites,
dont des factures invalides. Une facture rejetée proprement vaut mieux
qu'une facture acceptée à tort : la première se corrige, la seconde envoie
une alerte injustifiée à un gestionnaire.

## Prérequis

La plateforme doit être démarrée. Les tests ignorent proprement les cas dont
le service correspondant n'est pas actif, plutôt que d'échouer.

## Brouillon / TODO

- [ ] `conftest.py` : fixture de pile démarrée, avecignor des services absents
- [ ] Lot de 20 factures inédites, dont au moins 5 invalides
- [ ] Parcours complet : facture → alerte → rapport SHAP → décision
- [ ] Parcours assuré : question RAG → réponse sourcée
- [ ] Vérification de la persistance après `make down` puis `make up`
- [ ] Vérification de la bascule de modèle puis du retour arrière

Propriétaire : Jerry