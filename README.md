# PrediCare TPA

Système intelligent de détection de fraude médicale, d'optimisation des
remboursements santé et d'assistant agentique.

Trois flux — détection de fraude explicable, assistant conversationnel
agentique, pilotage décisionnel — dans une seule application déployée en une
commande, pour quatre rôles : assuré, professionnel de santé, gestionnaire,
administrateur.

---

## Démarrage

> **Sur une machine vierge, lancez `make up` — pas `docker compose up`.**
> Le compose seul n'a pas de `.env` : les mots de passe des rôles SQL en
> lecture seule restent vides, les migrations échouent, et les trois API ne
> démarrent jamais puisque toutes dépendent de la migration. `make up` crée
> le `.env`, génère les secrets, applique les migrations, charge `data/raw/`,
> puis attend que tous les services soient sains.

```bash
make doctor   # vérifie que la machine est prête — à lancer en premier
make up       # démarre et construit toute la plateforme
make start    # redémarre sans reconstruire
make down     # arrête tout, les données sont conservées
```

| Cible | Contenu |
| --- | --- |
| `http://localhost:8080` | Interface PrediCare, les quatre rôles |
| `http://localhost:8080/api/core/docs` | Documentation interactive de l'API |

### Prérequis

Ce que la plateforme utilise **sur la machine hôte**, hors conteneurs :

| Outil                          | Requis | Pourquoi                             |
| ------------------------------ | :----: | ------------------------------------ |
| **Docker** + Compose v2        |  oui   | lance tout le reste                  |
| **buildx**                     |  oui   | BuildKit, pour construire les images |
| **make**                       |  oui   | point d'entrée des commandes         |
| **curl**                       |  oui   | sondes de santé pendant le démarrage |
| bash + coreutils               |  oui   | déjà présents sur toute machine      |

C'est tout. Les secrets sont générés par `/dev/urandom`, donc **ni `openssl`
ni `python3` ne sont nécessaires** pour démarrer la plateforme.

`buildx` est le seul prérequis qui ne soit pas évident : les Dockerfiles
utilisent `RUN --mount=type=cache` pour le cache `uv`, or le constructeur
historique de Docker ne sait pas l'exécuter. Sans le plugin, `make up` échoue
sur la première couche `RUN --mount`.

```bash
sudo apt install docker-buildx-plugin   # Debian / Ubuntu
sudo pacman -S docker-buildx            # Arch
```

Docker Desktop l'embarque déjà. `make doctor` vérifie sa présence.

| Outil         | Requis pour                                        |                Nécessaire pour `make up`                 |
| ------------- | -------------------------------------------------- | :------------------------------------------------------: |
| `uv`          | développement Python (`lint`, `test`, `typecheck`) |                           non                            |
| `python3`     | `health`, `smoke`, `n8n-import`, `n8n-export`      |                           non                            |
| `git`         | versionnement, hooks                               |                           non                            |
| `node`, `npm` | —                                                  | **jamais** : le build de l'interface se fait dans Docker |

Si une commande échoue sur une machine vierge, `make doctor` dit quoi
installer.

---

---

## Points d'entrée

| Application                        | URL                                   | Lancée par              |
| ---------------------------------- | ------------------------------------- | ----------------------- |
| Interface PrediCare                | <http://localhost:8080>               | `make up`               |
| Documentation des API              | <http://localhost:8080/api/core/docs> | `make up`               |
| n8n — workflows d'alerte           | <http://localhost:5678>               | `make up`               |
| Superset — pilotage décisionnel    | <http://localhost:8088>               | `make up`               |
| Grafana — supervision              | <http://localhost:3001>               | `make up`               |
| Prometheus — métriques             | <http://localhost:9090>               | `make up`               |
| MLflow — suivi des modèles         | <http://localhost:5000>               | `make up`               |
| Mailpit — e-mails de développement | <http://localhost:8025>               | `make up-email`         |
| PostgreSQL + pgvector              | **pas de port** — `make shell-db`     | `make up`               |

`make up` et `make start` démarrent désormais **toute** la plateforme, Superset,
Grafana, Prometheus et MLflow compris. `make up-light` garde la version économe
(le noyau seul) pour une machine contrainte.

PostgreSQL et Redis ne publient aucun port sur l'hôte, et ce n'est pas un oubli :
le réseau `core` est `internal: true`, or Docker n'active la publication d'un
port que si le conteneur est attaché à au moins un réseau **non** interne. Pour
accéder à la base : `make shell-db`.

---

## Actions récurrentes

Ce tableau répond à la seule question qui compte quand on reprend le projet :
**quand lancer quoi, et pourquoi.**

| Situation | Séquence | Pourquoi |
| --- | --- | --- |
| **Machine vierge** | `make doctor` puis `make up` | Jamais `docker compose up` seul : sans `.env`, les rôles SQL restent sans mot de passe, les migrations échouent et les API ne démarrent pas, puisqu'elles en dépendent. |
| **Après une modification de code** | `make up` puis `make smoke` | `make up` **reconstruit**. `make start` ne le fait pas, et ne le signale nulle part dans l'interface. |
| **Redémarrage rapide** | `make down` puis `make start` | Les données sont conservées. Le second ne reconstruit rien. |
| **Après une modification de `.env`** | `make down` puis `make start` | Les secrets ne sont relus qu'au démarrage des conteneurs. |
| **Après ajout d'une migration** | `make migrate` puis `make db-status` | `make up` applique déjà les migrations. En revanche, `migrate` ne se rejoue pas tout seul si le job a déjà abouti : c'est précisément ce que `db-status` détecte. |
| **Après modification du jeu de données** | déposer les CSV dans `data/raw/` puis `make reload-data` | Rechargement idempotent : `TRUNCATE … RESTART IDENTITY CASCADE` puis 14 tables, en une transaction. |
| **Mémoire insuffisante** | `make up-light` | Le noyau reste démontrable ; seul l'outillage de pilotage manque. |
| **Jour de démonstration** | `make down`, `make start`, `make health`, `make smoke`, `make e2e-n8n`, `make acces`, `make n8n-compte` | Checklist détaillée plus bas. |
| **Incident** | `make health`, puis `make logs-service S=<service>` | `make restore` si la base est corrompue, après confirmation. |

### Le jour de démonstration

```bash
make down && make start   # redémarrage propre, sans reconstruction
make health                # chaque service doit répondre
make smoke                 # parcours de bout en bout
make e2e-n8n               # alerte réelle Slack + e-mail, puis échec journalisé
make acces                 # fiche d'identifiants régénérée, hors dépôt, mode 600
make n8n-compte            # l'état du compte n8n de CE poste
```

`make n8n-compte` n'est pas un détail : n8n n'a plus d'authentification basique
depuis la version 1.x. Le compte propriétaire se crée au premier lancement de
l'interface, avec l'email saisi par le visiteur, et **le mot de passe n'est
écrit dans aucun fichier**. Chaque poste a le sien, qu'il faut avoir noté.

---

## Commandes

`make help` liste les 58 commandes. Cette section les regroupe par tâche.

### Cycle de vie

| Commande | Effet |
| --- | --- |
| `make up` | Démarre tout **en reconstruisant** les images. Commande de référence du projet. |
| `make start` | Démarre **sans reconstruire**, après un `make down`. |
| `make up-light` | Noyau seul : API, web, base, n8n. Pour machine contrainte. |
| `make down` | Arrêt. **Les données sont conservées.** |
| `make restart` | `down` puis `start`, sans reconstruction. |
| `make clean` | Arrêt **et** suppression des volumes — confirmation demandée. |
| `make build` | Construit les images sans démarrer. |
| `make wait` | Attend que tous les services soient sains. |

### Données

| Commande | Effet |
| --- | --- |
| `make reload-data` | Recharge `data/raw/` : purge puis 14 tables, en une transaction. |
| `make seed-rag` | Indexe le corpus de contrats PDF dans pgvector (`core.document_vectorise`). Sans effet si l'index existe déjà ; reconstruire avec `ingest_rag --apply --force` (voir `db/seeds/README.md`). |
| `make comptes` | Crée les quatre comptes de démonstration (assuré, professionnel, gestionnaire, admin). Le mot de passe vient de `DEMO_PASSWORD` ; sinon il est généré au hasard et **affiché une seule fois**. |
| `make migrate` | Applique les migrations en attente. |
| `make db-status` | Compare la version du schéma en base et celle attendue par le code. |

`make comptes` est l'étape qui rend l'interface utilisable : après les
migrations, `core.utilisateur` est vide et **aucun mot de passe n'est codé en
dur dans le dépôt**. Le mot de passe généré n'est affiché qu'une fois — notez-le,
ou fixez-le avec `DEMO_PASSWORD` dans `.env` avant de relancer la commande.

`make db-status` est le garde-fou le plus utile du projet. Le job `migrate`
étant un one-shot, Compose ne le relance pas spontanément : sans ce contrôle,
une migration ajoutée après le premier démarrage resterait non appliquée, et
`make up` annoncerait une plateforme prête sur un schéma périmé.

### Base de données

| Commande | Effet |
| --- | --- |
| `make shell-db` | `psql` interactif. `ROLE=predicare_ro` pour un accès lecture seule. |
| `make db-sql Q="SELECT …"` | Exécute une requête. |
| `make db-sql FILE=analyse.sql` | Exécute un fichier SQL de l'hôte. |
| `make bi` | Vérifie que les vues de la couche sémantique BI compilent. |
| `make bi-dashboard` | Réapplique le tableau de bord archivé dans le dépôt (après une manip dans l'interface). |
| `make bi-export` | Archive les douze tuiles, la mise en page et les filtres natifs dans `ops/superset/dashboards/`. |
| `make bi-requetes` | Peuple l'historique SQL Lab et les requêtes enregistrées de Superset. |
| `make bi-compte-demo` | Crée le compte Superset de démonstration, en lecture seule. |
| `make bi-graphiques` | Exécute la requête de chaque graphique, vérifie qu'elle aboutit et qu'aucune dérive ne s'est installée. |
| `make purge` | Aperçu de la purge des données hors durées de conservation. |
| `make web-build` | Compile le front : vérification des types puis bundle Vite. |
| `make web-test` | Lance les parcours Playwright des quatre rôles. |
| `scripts/test-intrusion.sh` | Vérifie que les surfaces d'attaque connues sont fermées. |
| `cat rapport.sql \| make db-sql` | Idem, par entrée standard. |

Aucun port TCP n'atteint PostgreSQL : tout passe par `docker compose exec`, donc
pas de client graphique. Un `psql localhost:55432` échoue en
`Connection refused`, ce qui n'est pas une panne — voir
[`db/seeds/README.md`](db/seeds/README.md).

`ROLE=predicare_ro` sert à démontrer le moindre privilège sur un cas réel : la
même requête aboutit en `predicare` et se voit refuser sur le schéma `audit`.

### Modèle

Un modèle s'entraîne une fois, se sert en continu : les commandes ci-dessous
sont des **jobs**, jamais lancés au démarrage de la pile. Elles s'exécutent dans
la même image Docker que les services, donc avec le même XGBoost, la même
version de SHAP et le même pandas — aucune divergence possible entre ce qui
s'entraîne et ce qui sert.

| Commande | Effet |
| --- | --- |
| `make train VERSION=2` | Entraîne le modèle et écrit `models/2/` (artefacts + rapports). |
| `make evaluate` | Compare SMOTE / `scale_pos_weight` / aucun traitement et produit l'audit d'équité. |
| `make noter LIMITE=500` | Note en lot l'historique et peuple `ml.prediction`, en process avec le contexte exact (ordonnance, heure de soin). `STATUT=nouvelle` pour alimenter la file, `DRY_RUN=1` pour simuler, `RESCORER=1` pour un diagnostic. |
| `make add-invoices` | Ajoute des factures par la **même porte que le front** (validation, notation, SHAP, alerte). Accepte le JSON du lot du CDC (F17), le CSV du front et le CSV du chargement initial : le format est détecté, pas imposé. Une facture déjà présente est **ignorée**, une facture invalide est **rejetée en nommant le champ**. `ARGS=--fichier <chemin>` (répétable) pour un fichier précis. |
| `make model-state` | Version active du modèle et seuil courant. |
| `make model-promote VERSION=2` | Charge la version N en *candidate*, puis bascule — sans redémarrage. |
| `make model-rollback VERSION=1` | Revient à la version N, sans redémarrage. |
| `make threshold VALEUR=0.75` | Change le seuil d'alerte à chaud, sans redémarrage. |
| `make score-historique` | Rejoue le jeu étiqueté (backfill idempotent, statut `historique`). |

`make noter` est le seul job qui **écrit en masse** dans `ml.prediction`. Par
défaut il marque ses prédictions `statut = 'archive'` : ce sont des notations
rétrospectives, utiles à la mesure de la qualité du modèle et au volume du
tableau de bord, mais qui n'entrent pas dans la file de travail du gestionnaire.
Sans cette distinction, des milliers d'alertes historiques non décidées
feraient afficher un taux de faux positifs de 100 % et un délai de décision de
plusieurs années. `STATUT=nouvelle` force l'entrée en file, pour une
démonstration sur un petit lot.

`make add-invoices` porte le lot de 20 factures du CDC (F17) : il lit
`data/seed/lot_20_factures.json`, source unique et versionnée, et le soumet à
`POST /api/core/factures/soumettre`. Ce n'est pas un raccourci : la validation,
la vérification des référentiels, la notation et la persistance passent par le
même chemin que le formulaire. Le fichier porte le résultat attendu
(`cas_attendu`, `attendu`) ; le job compare la réponse réelle à ce résultat et
sort en erreur au premier écart. Le front, lui, n'importe toujours pas de lot :
c'est un choix explicite, documenté dans
[`docs/analyse_front_vs_cdc.md`](docs/analyse_front_vs_cdc.md).

L'entraînement écrit quatre fichiers par version :

```
models/<version>/
├── model.joblib        modèle XGBoost sérialisé
├── features.json       ordre des 32 variables, versionné avec le modèle
├── metadata.json       métriques, seuil, empreinte des données d'entraînement
└── referentiels.json   grilles tarifaires et référentiels, versionnés avec le modèle
```

Le quatrième fichier est ce qui garantit que l'inférence note avec **la même
grille tarifaire** que celle utilisée à l'entraînement : un changement de
tarif impose un ré-entraînement, explicite, plutôt qu'un modèle qui dérive en
silence.

Résultats du modèle v2 sur le jeu de test (10 086 factures, la période la plus
récente lue une seule fois) :

| Métrique | Valeur |
| --- | --- |
| ROC-AUC | 0,951 |
| PR-AUC | 0,893 |
| Rappel au seuil retenu | 0,875 |
| Précision au seuil retenu | 0,598 |
| Seuil appliqué | 0,2766 |

Le seuil est **calculé, pas choisi** : il minimise le coût métier sous
contrainte de rappel ≥ 90 % (exigence du Module 2). Le seuil historique de 0,8
a été abandonné — avec 8,7 % de fraude dans la population, il laissait passer
une part importante des vraies fraudes. Le détail de l'arbitrage est dans
[`reports/modele_v2.md`](reports/modele_v2.md) et l'audit d'équité dans
[`reports/equite_v2.md`](reports/equite_v2.md).

### n8n

| Commande | Effet |
| --- | --- |
| `make n8n-compte` | Compte propriétaire de ce poste, et procédure s'il n'existe pas. |
| `make n8n-export` | Exporte les workflows dans `apps/n8n/workflows/`. |
| `make n8n-import` | Restaure et publie les workflows après un `down`/`up`. |
| `make e2e-n8n` | Envoie une facture du lot F17 au webhook et vérifie Slack, l'e-mail (Mailpit) et l'absence de notification fantôme. |

Les workflows se partagent **par Git**, pas à l'intérieur de n8n : l'édition
Community n'a pas de partage de projet. Détails dans
[`apps/n8n/README.md`](apps/n8n/README.md).

### Qualité

| Commande | Effet |
| --- | --- |
| `make sync` | Installe les dépendances Python (workspace uv complet). |
| `make lint` | Style et erreurs statiques (ruff). |
| `make format` | Corrige le style automatiquement. |
| `make typecheck` | Vérifie les types (mypy). |
| `make test` | Lance la suite de tests. |
| `make test-cov` | Tests avec le rapport de couverture. |
| `make check` | Les quatre vérifications de la CI. |
| `make readme` | Vérifie que le README documente exactement les commandes de `make help`. |
| `make export-requirements` | Exporte les versions pip depuis `uv.lock`, non versionné. |

Aucun test ne démarre de conteneur ni ne touche PostgreSQL : la CI doit
tourner sur une pull request sans Docker.

### Diagnostic

| Commande | Effet |
| --- | --- |
| `make doctor` | Vérifie que la machine est prête. **À lancer en premier.** |
| `make ps` | État des conteneurs, tous profils confondus. |
| `make health` | Sonde `/health` et `/metrics` de chaque service. |
| `make logs` | Suit les journaux de la plateforme. |
| `make logs-service S=api-core` | Suit le journal d'un service. |
| `make smoke` | Parcours de vérification de bout en bout. |

`make doctor` contrôle les outils de l'hôte, le démon Docker, Compose v2,
buildx, la présence et la santé du `.env`, l'absence de marqueur de secret en
clair, la fiche d'accès, et que `.env` n'est pas versionné.

### Sauvegarde

| Commande | Effet |
| --- | --- |
| `make backup` | Sauvegarde immédiate. |
| `make backups` | Liste les archives disponibles. |
| `make restore` | Restaure la dernière archive — confirmation demandée. |
| `make up-backup` | Démarre la planification quotidienne. |

La restauration n'est **jamais** automatique : une restauration déclenchée par
une erreur de script écraserait les données du jour.

### Accès et configuration

| Commande | Effet |
| --- | --- |
| `make acces` | Génère la fiche d'identifiants, hors dépôt, mode `600`. |
| `make setup` | Crée le `.env` et génère les secrets manquants. |
| `make secrets` | Régénère les secrets cryptographiques. |

### Services optionnels

`make up` démarre déjà Superset, Grafana, Prometheus, MLflow et les workers.
Ces commandes servent à démarrer un service **seul**, ou à ajouter ce que le
défaut exclut volontairement.

| Commande | Contenu |
| --- | --- |
| `make up-bi` | Superset seul. |
| `make up-observability` | Prometheus et Grafana seuls. |
| `make up-mlops` | MLflow seul. |
| `make up-workers` | Workers d'ingestion et d'indexation. |
| `make up-email` | Mailpit, boîte mail de développement. |
| `make up-backup` | Sauvegarde quotidienne planifiée. |
| `make up-all` | Tout, y compris Mailpit et le cron de sauvegarde. |

### Reconstruire ou pas

`make up` reconstruit systématiquement les images : bon réflexe sur une machine
vierge et après une modification de code. Mais Compose interroge malgré tout le
réseau pour résoudre les images de base — un `make up` peut bloquer sur une
machine sans internet, alors que la pile est parfaitement capable de démarrer.

C'est le cas d'usage du jour J, où l'on répète la démonstration :

```bash
make down     # arrêt, les données restent
make start    # redémarrage immédiat, aucune reconstruction
```

---
## Architecture

Trois flux, trois services FastAPI indépendants, une base de données unique.
Chaque service a ses propres dépendances, sa propre latence et son propre
cycle de vie : un flux se remplace ou se redimensionne sans impacter les
autres.

```
                        passerelle (Traefik)  :8080
                        CSP, HSTS, limitation de débit
                                  |
        +------------------------+------------------------+
        |                        |                        |
      interface              api-core                (n8n :5678)
    (nginx, React)      Flux 3 + socle :8001             alerte Slack
    les 4 rôles         auth, factures, décisions,        + rapport SHAP
                       administration, audit
        |
   api-inference :8002          api-rag :8003
   Flux 1 : fraude               Flux 2 : agent ReAct
   validation, XGBoost,         contrats (pgvector),
   SHAP, dérive                 historique (SQL lecture
                                seule), cache sémantique
        |                                |
        +----------- worker-* ----------+
          ingestion et dérive      indexation et cache

   PostgreSQL 16 + pgvector  :55432      Redis :63790
   schémas core / ml / audit · 3 rôles SQL en lecture seule
   · une seule sauvegarde pour tout
```

| Flux                    | Service               | Dossier                    | Ce qu'il produit                            |
| ----------------------- | --------------------- | -------------------------- | ------------------------------------------- |
| 1 — Détection de fraude | `api-inference` :8002 | `apps/api-inference/`      | Score de fraude et rapport SHAP par facture |
| 2 — Assistant agentique | `api-rag` :8003       | `apps/api-rag/`            | Réponse sourcée à une question d'assuré     |
| 3 — Pilotage            | `api-core` :8001      | `apps/api-core/`           | File d'alertes, décisions, administration   |
| Transverse              | —                     | `packages/predicare-core/` | Configuration, base, sécurité, métriques    |

**Trois plans réseau.** `core` est `internal: true` : aucun service
applicatif n'atteint Internet par ce plan. Seul `api-rag` sort, pour appeler
le fournisseur LLM. La passerelle n'a pas accès à `docker.sock`.

---

---

## Organisation du dépôt

| Dossier                    | Propriétaire | Utilité                                                                                                                                                                                         |
| -------------------------- | :----------: | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/api-core/`           |   Cherica    | **Flux 3 + socle.** Authentification et quatre rôles, factures et ordonnances, file d'alertes, décisions gestionnaire, écran d'administration (seuil, canaux, santé, rollback), journal d'audit |
| `apps/api-inference/`      |    Mirado    | **Flux 1.** Validation stricte d'entrée, featurisation, scoring XGBoost, valeurs SHAP, détection de dérive, registre de versions avec bascule à chaud et retour arrière                         |
| `apps/api-rag/`            |    Mirado    | **Flux 2.** Agent ReAct LangChain, garde-fous contre l'injection de prompt, outil SQL en lecture seule, recherche pgvector, cache sémantique                                                    |
| `apps/web/`                |   Cherica    | Interface unique React + Vite + TypeScript, servie par nginx. Les quatre parcours de rôle                                                                                                       |
| `apps/ml-training/`        |    Mirado    | Entraînement, choix du seuil, évaluation, audit d'équité. Code de **job**, pas un service : lancé à la demande, jamais au démarrage                                                             |
| `apps/seed/`               |   Cherica    | Chargement initial des 24 mois au premier démarrage. Idempotent : rejouable sans risque                                                                                                         |
| `apps/n8n/`                |    Mirado    | Workflow d'alerte versionné. L'interface est la source de vérité, Git reçoit l'export                                                                                                           |
| `packages/predicare-core/` |    Jerry     | Socle transverse : configuration, accès base, JWT et RBAC, chiffrement des identités, journaux structurés, métriques. Aucun code de flux                                                        |
| `db/migrations/`           |   Cherica    | Schéma versionné Alembic. Trois schémas (`core`, `ml`, `audit`), rôles SQL en lecture seule                                                                                                     |
| `db/seeds/`                |   Cherica    | Référentiels d'actes et données de référence                                                                                                                                                    |
| `db/backup/`               |    Jerry     | Sauvegarde quotidienne et restauration, scripts                                                                                                                                                 |
| `ops/`                     |    Jerry     | Passerelle Traefik, Prometheus, Grafana, Superset, planification des sauvegardes                                                                                                                |
| `scripts/`                 |    Jerry     | Ce qu'on exécute : bootstrap, attente, santé, test de fumée, export/import n8n, fiche d'accès                                                                                                   |
| `tests/`                   |    Jerry     | pytest : 677 tests, majoritairement sans base ni conteneur — validation d'entrée, sécurité RAG, SQL, RBAC, chiffrement, SHAP, cache, supervision, contrat des workflows n8n, dérive. E2E dans `tests/e2e/` |
| `docs/`                    |    Jerry     | ADR, guide d'exploitation, guide utilisateur, dossier de cadrage                                                                                                                                |

### Dossiers créés à l'exécution

Ces quatre dossiers existent sur votre machine mais **ne sont pas versionnés**
(ils sont dans le `.gitignore`) : `data/` (CSV à charger), `models/`
(artefacts de modèle), `backups/` (sauvegardes), `artifacts/` (MLflow).

### Fichiers de configuration racine

| Fichier                                           | Rôle                                     |
| ------------------------------------------------- | ---------------------------------------- |
| `docker-compose.yml`                              | Pile principale, lance par `make up`     |
| `docker-compose.{bi,observability,mlops,ops}.yml` | Overlays des profils optionnels          |
| `pyproject.toml`                                  | Workspace uv, ruff, mypy, pytest         |
| `uv.lock`                                         | Verrou des dépendances Python, versionné |
| `alembic.ini`                                     | Configuration Alembic                    |
| `Makefile`                                        | Toutes les commandes d'exploitation      |
| `.env.example`                                    | Modèle de configuration, versionné       |
| `.github/workflows/ci.yml`                        | Intégration continue                     |

---

---

## Profils optionnels

`make up` couvre déjà le noyau, Superset, Grafana, Prometheus, MLflow et les
workers — environ 4,5 Go. `make up-light` garde la version économe, environ
1,5 Go, pour tenir dans le budget mémoire d'une machine de démonstration.

| Jeu de commandes | Mémoire |
| --- | --- |
| `make up-light` | ~1,5 Go |
| `make up` / `make start` | ~4,5 Go |
| `make up-all` | ~6,5 Go |

**Si `make up` échoue faute de mémoire**, utilisez `make up-light` : le noyau
reste démontrable, seul l'outillage de pilotage est indisponible. Un service
optionnel qui ne répond pas n'interrompt pas `make up` — le noyau est vérifié
séparément et c'est lui seul qui est bloquant.

### Ce que le défaut exclut, et pourquoi

- **Mailpit** intercepte tout le courrier sortant. Il resterait actif en
  permanence et masquerait un envoi réel pendant la démonstration. Il se lance
  avec `make up-email`.
- **Le cron de sauvegarde** est invisible pendant une soutenance et coûte un
  conteneur en plus. `make up-backup` le démarre.

### Tableau de bord décisionnel

`make up` démarre Superset, enregistre **onze datasets** sur des vues
physiques du schéma `bi`, puis crée **douze graphiques** et le tableau de bord
« Pilotage mensuel ». La connexion BI utilise le rôle `superset_ro`, en lecture
stricte : l'outil ne peut pas modifier une donnée métier.

Le tableau suit les cinq indicateurs de la Phase 7 — volumes, montants
économisés, taux de détection, délai de traitement, faux positifs. Deux
d'entre eux restent **vides** tant que le modèle n'a pas tourné et qu'aucune
décision gestionnaire n'est enregistrée : les vues existent, elles sont vides,
et le tableau le dit. Une brique absente passerait inaperçue ; une brique vide
avec son état se discute.

Détail des indicateurs, de leur source et de leur fréquence : voir
[`db/bi/README.md`](db/bi/README.md).

---

## Chargement des données

Le jeu synthétique de l'encadrement est dans `data/raw/`, **gitignoré** : 44 Mo
de données de santé restent hors du dépôt.

```bash
cp ~/Documents/predicare/CohorteAI_datagen/dataset/*.csv data/raw/
make reload-data
```

14 fichiers, environ **436 700 lignes** sur 24 mois, vers 14 tables réparties
entre les schémas `core` (métier), `ml` (modèles et labels) et `audit`.

Trois points méritent d'être connus :

- **Pseudonymisation.** Les assurés sont pseudonymisés par HMAC-SHA256 ; le
  même assure donne toujours le même pseudonyme, ce qui permet de relier une
  facture à un dossier sans jamais stocker l'identité. `identites_pii.csv` est
  le **seul** fichier nominatif : il alimente `core.identite_chiffree`, chiffré
  en Fernet, et rien d'autre.
- **Validation bloquante avant écriture.** Un contrôle qui échoue interrompt le
  chargement et nomme le fichier fautif. Les valeurs manquantes ne sont pas
  des anomalies : 44 % des factures n'ont pas d'ordonnance parce que beaucoup
  d'actes n'en exigent pas.
- **Fuite de données.** `statut` et `motif_rejet` sont fortement corrélés à la
  fraude — 70 % des factures rejetées sont frauduleuses contre 7 % des payées.
  Ces colonnes restent dans `core`, la validité dérivée atterrit dans `ml` :
  la disposition des tables empêche le feature engineering de les utiliser
  comme variables.

Détail complet dans [`db/seeds/README.md`](db/seeds/README.md).

---

## Dépendances Python

Gestionnaire **uv**, workspace de cinq projets, `uv.lock` versionné.
Les images Docker font `uv sync --frozen --all-packages --no-editable` : une
seule résolution de dépendances pour tous les services, donc aucune divergence
entre l'entraînement et l'inférence.

Il n'y a pas de `requirements.txt`, et c'est délibéré : un requirements ne
fige qu'une liste de versions plates et perd la résolution transitive, alors
que `uv.lock` fige l'état complet. Pour lire les versions sans installer uv :

```bash
make export-requirements   # génère requirements.lock, non versionné
```

```bash
make sync       # uv sync --frozen --all-packages
make lint       # ruff
make typecheck  # mypy
make test       # pytest
make check      # les trois, comme la CI
```

---

---

## Configuration et accès

Tout se règle dans `.env`, créé automatiquement à partir de `.env.example`.
Aucun secret n'est codé en dur et aucun `.env` n'est versionné. Le seuil
d'alerte, les canaux de notification et l'état de la plateforme sont aussi
modifiables depuis l'écran d'administration, sans redémarrage.

La fiche d'identifiants — mots de passe, URL, état de chaque service — est
générée **hors du dépôt**, en mode `600` :

```bash
make acces
```

### Piège connu

`POSTGRES_PASSWORD` n'est appliqué par l'image PostgreSQL qu'à la **première**
initialisation du volume. Régénérer un `.env` sur une installation qui tourne
rend la base inaccessible. `make up` vous prévient désormais.

### Piège sur les ports

Aucun port TCP n'atteint PostgreSQL ni Redis. Le réseau `core` est
`internal: true`, et Docker n'active la publication d'un port que si le
conteneur est attaché à au moins un réseau **non** interne. Un `ports:` déclaré
sur ces services passerait `docker compose config` tout en étant inopérant, et
produirait un `Connection refused` trompeur. La CI vérifie qu'aucun service ne
porte de port sur un réseau entièrement interne.

L'accès à la base passe donc par `make shell-db` et `make db-sql`.

---

Chaque dossier porte un `README.md` listant ses tâches restantes. Le suivi du
projet — qui fait quoi, rattachement aux phases — est dans
[`docs/equipe.md`](docs/equipe.md), et l'index documentaire dans
[`docs/`](docs/README.md).

---

## Licence

Voir `LICENSE`.
