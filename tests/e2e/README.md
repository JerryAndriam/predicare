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

## Le parcours RAG

`tests/e2e/test_rag_parcours.py` couvre le parcours assuré de bout en bout
sur la pile réelle : connexion à api-core, question de garantie avec source
citée, question d'historique dérivée du SQL, question de suivi dans une
session, injection refusée, question répétée servie par le cache sémantique.

Il est marqué `e2e` et **ignoré** tant que `PREDICARE_E2E=1` n'est pas
défini : la suite `pytest` reste verte sans la pile démarrée.

```sh
PREDICARE_E2E=1 uv run --all-packages pytest tests/e2e/test_rag_parcours.py -q
```

Le mot de passe de démonstration vient de `DEMO_PASSWORD` : il n'est codé en
dur nulle part dans le dépôt. `make comptes` en génère un aléatoire et
l'affiche **une seule fois** — sans cette variable, le parcours est ignoré
avec le message qui indique la commande à lancer :

```sh
DEMO_PASSWORD='<mot-de-passe>' make comptes   # ou notez celui affiché
DEMO_PASSWORD='<mot-de-passe>' PREDICARE_E2E=1 \
  uv run --all-packages pytest tests/e2e/test_rag_parcours.py -q
```

Le même parcours existe sous forme de script autonome, utile pour un jury
qui veut voir la trace des vérifications sans pytest :

```sh
DEMO_PASSWORD='<mot-de-passe>' scripts/e2e_rag.sh
```

Le script sort en erreur dès qu'une vérification échoue et affiche un résumé
(`11 réussites, 0 échec(s)`). Il ne code en dur aucun secret : sans
`DEMO_PASSWORD`, il s'arrête avant toute requête avec le message
`DEMO_PASSWORD non defini. Lancez : DEMO_PASSWORD='<mot-de-passe>' make comptes (le mot de passe est affiché une seule fois)`.
Le mot de passe n'est jamais imprimé dans la sortie.

## Le lot de 20 factures (F17)

`tests/e2e/test_lot_jury_e2e.py` soumet `data/seed/lot_20_factures.json` par la
même porte que le front (`POST /api/core/factures/soumettre`), puis vérifie :

- les 15 factures valides sont notées, dont 7 alertes attendues ;
- ces 7 alertes sont visibles dans la file du gestionnaire ;
- les 5 factures invalides sont rejetées en nommant le champ fautif ;
- une alerte parcourt le cycle complet : détail SHAP, décision, historique.

Le job `make add-invoices` exécute la même soumission en exploitation, avec un
rapport lisible et un code de sortie non nul au premier écart.

```sh
DEMO_PASSWORD='<mot-de-passe>' PREDICARE_E2E=1 \
  uv run --all-packages pytest tests/e2e/test_lot_jury_e2e.py -q
```

> Ce parcours **écrit** dans la base de démonstration : c'est le but, le jury
> doit voir les alertes. Ne pas le lancer sur une base de production.

## La chaîne n8n (Slack et e-mail)

La preuve de la chaîne n8n est un **script shell**, pas un test pytest : elle
a besoin de Docker, de la base n8n et de Mailpit, et son journal est
`execution_entity` dans la base `n8n`. Un test pytest devrait shell-out pour
lire ces éléments, ce qui n'apporte rien par rapport à `scripts/e2e_n8n.sh`.

```sh
make e2e-n8n
```

Prérequis : pile démarrée, Mailpit (`make up-email`), `SLACK_WEBHOOK_URL`
renseigné dans `.env`, workflows importés (`make n8n-import`). Le script
vérifie :

- le workflow `PK-Alerte-Fraude` est actif et son webhook enregistré ;
- `FAC-JURY-001` (lot F17) répond 200 avec un score ≥ 0,8 et le rapport SHAP ;
- l'e-mail réel arrive dans Mailpit avec le rapport SHAP lisible ;
- l'exécution n8n est `success` (donc Slack a répondu 2xx) ;
- une facture invalide répond 502, n'ajoute aucun e-mail et laisse l'exécution
  en `error` : l'échec est journalisé, sans notification fantôme.

Il affiche `Resume : X reussite(s), 0 echec(s)` puis `Parcours n8n : SUCCES`.
Un échec de configuration (Slack absent, Mailpit arrêté) sort en code 2 avant
toute requête, avec la commande à lancer.

La chaîne de bascule de modèle (`POST /webhook/bascule-modele`) se prouve avec
un payload `version_avant`/`version_apres` ; elle répond 200 puis notifie
Slack et e-mail. Voir `apps/n8n/README.md`.

## Brouillon / TODO

- [ ] `conftest.py` : fixture de pile démarrée, avec ignor des services absents
- [x] Lot de 20 factures inédites, dont au moins 5 invalides
- [x] Parcours complet : facture → alerte → rapport SHAP → décision
- [x] Parcours assuré : question RAG → réponse sourcée
- [x] Chaîne n8n : alerte réelle Slack + e-mail, échec journalisé sans fantôme
- [ ] Vérification de la persistance après `make down` puis `make up`
- [ ] Vérification de la bascule de modèle puis du retour arrière

Propriétaire : Jerry