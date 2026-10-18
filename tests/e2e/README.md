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

## Tests qui exigent la base

Quelques tests d'integration ont besoin d'un PostgreSQL charge
(`tests/test_persistance_ml.py`, fixture `base_de_donnees`). `make test` les
saute proprement, parce que la base vit sur un reseau Docker INTERNE : elle
n'est joignable ni depuis l'hote, ni depuis la CI.

Pour les executer pour de vrai, une seule commande, apres `make up-light` :

```sh
docker compose -f docker-compose.yml run --rm --no-deps --user root \
  -v "$PWD:$PWD:ro" -w "$PWD" \
  -e PYTHONPATH="$PWD/.venv/lib/python3.12/site-packages:$PWD/packages/predicare-core/src:$PWD/apps/api-core/src:$PWD/apps/api-inference/src:$PWD/apps/api-rag/src:$PWD/apps/ml-training/src:$PWD/apps/seed/src" \
  -e PYTHONDONTWRITEBYTECODE=1 \
  api-inference python -m pytest -q -p no:cacheprovider tests/test_persistance_ml.py
```

L'environnement de l'hote est monte dans un conteneur du reseau `core` : les
tests s'executent contre la VRAIE base, avec le venv du depot (l'image de
production ne contient volontairement pas `pytest`).

## Brouillon / TODO

- [ ] `conftest.py` : fixture de pile démarrée, avecignor des services absents
- [ ] Lot de 20 factures inédites, dont au moins 5 invalides
- [ ] Parcours complet : facture → alerte → rapport SHAP → décision
- [ ] Parcours assuré : question RAG → réponse sourcée
- [ ] Vérification de la persistance après `make down` puis `make up`
- [ ] Vérification de la bascule de modèle puis du retour arrière

Propriétaire : Jerry