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
> le `.env` et génère les secrets avant de lancer le compose.

```bash
make doctor   # vérifie que la machine est prête — à lancer en premier
make up       # démarre la plateforme
```

`make up` crée le `.env` depuis `.env.example`, génère les secrets,
construit les images, applique les migrations, charge les données de
`./data/raw`, puis attend que tous les services soient sains.

| Cible                                 | Résultat                              |
| ------------------------------------- | ------------------------------------- |
| `http://localhost:8080`               | Interface PrediCare, les quatre rôles |
| `http://localhost:8080/api/core/docs` | Documentation interactive de l'API    |

**Les identifiants sont dans une fiche d'accès générée hors du dépôt** :
`/home/jerry/Documents/predicare/ACCES_PREDICARE.md`. Régénérez-la avec
`make acces`. Aucun secret ne se trouve dans le dépôt Git.

### Prérequis

Ce que la plateforme utilise **sur la machine hôte**, hors conteneurs :

| Outil                   | Requis | Pourquoi                             |
| ----------------------- | :----: | ------------------------------------ |
| **Docker** + Compose v2 |  oui   | lance tout le reste                  |
| **make**                |  oui   | point d'entrée des commandes         |
| **curl**                |  oui   | sondes de santé pendant le démarrage |
| bash + coreutils        |  oui   | déjà présents sur toute machine      |

C'est tout. Les secrets sont générés par `/dev/urandom`, donc **ni `openssl`
ni `python3` ne sont nécessaires** pour démarrer la plateforme.

| Outil         | Requis pour                                        |                Nécessaire pour `make up`                 |
| ------------- | -------------------------------------------------- | :------------------------------------------------------: |
| `uv`          | développement Python (`lint`, `test`, `typecheck`) |                           non                            |
| `python3`     | `health`, `smoke`, `n8n-import`, `n8n-export`      |                           non                            |
| `git`         | versionnement, hooks                               |                           non                            |
| `node`, `npm` | —                                                  | **jamais** : le build de l'interface se fait dans Docker |

Si une commande échoue sur une machine vierge, `make doctor` dit quoi
installer.

---

## Points d'entrée

| Application                        | URL                                   | Lancée par              |
| ---------------------------------- | ------------------------------------- | ----------------------- |
| Interface PrediCare                | <http://localhost:8080>               | `make up`               |
| Documentation des API              | <http://localhost:8080/api/core/docs> | `make up`               |
| n8n — workflows d'alerte           | <http://localhost:5678>               | `make up`               |
| Superset — pilotage décisionnel    | <http://localhost:8088>               | `make up-bi`            |
| Grafana — supervision              | <http://localhost:3001>               | `make up-observability` |
| Prometheus — métriques             | <http://localhost:9090>               | `make up-observability` |
| MLflow — suivi des modèles         | <http://localhost:5000>               | `make up-mlops`         |
| Mailpit — e-mails de développement | <http://localhost:8025>               | `make up-email`         |
| PostgreSQL + pgvector              | `localhost:55432`                     | `make up`               |

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
| `scripts/`                 |    Jerry     | Ce que le jury exécute : bootstrap, attente, santé, test de fumée, export/import n8n, fiche d'accès                                                                                             |
| `tests/`                   |    Jerry     | pytest : tests unitaires et d'intégration par rôle. E2E dans `tests/e2e/`                                                                                                                       |
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

## Répartition du travail

|                       | Jerry                                                   | Cherica                                               | Mirado                                    |
| --------------------- | ------------------------------------------------------- | ----------------------------------------------------- | ----------------------------------------- |
| **Socle partagé**     | `packages/predicare-core/`                              |                                                       |                                           |
| **Flux 1 — fraude**   | Versionnement MLflow, métriques de latence et de dérive | Robustesse sur factures mal formées                   | Entraînement, seuil, SHAP, dérive         |
| **Flux 2 — RAG**      | Supervision, dérive                                     | Tests d'attaque injection                             | Agent ReAct, indexation, cache sémantique |
| **Flux 3 — pilotage** | Ecran d'administration, métriques, rollback             | Authentification, quatre rôles, parcours gestionnaire | —                                         |
| **Interface**         | —                                                       | React, quatre parcours de rôle                        | Vue assured (chat RAG)                    |
| **Données**           | Requêtes d'analyse pour la BI                           | Migrations, chargement initial, nettoyage             | Chargement des factures d'entraînement    |
| **Orchestration**     | —                                                       | —                                                     | Workflow n8n, alerte Slack + rapport SHAP |
| **Exploitation**      | Passerelle, sauvegarde, CI, scripts, docs               | Guide utilisateur                                     | Dossier de cadrage FinOps et conformité   |

### Rattachement aux phases

| Phase              | Jerry                                              | Cherica                                  | Mirado                                                |
| ------------------ | -------------------------------------------------- | ---------------------------------------- | ----------------------------------------------------- |
| 0 — cadrage        | Dépôt, CI, README, ADR                             | —                                        | —                                                     |
| 1 — données        | Requêtes BI, sauvegarde                            | Migrations, chargement, pseudonymisation | —                                                     |
| 2 — modèle         | MLflow                                             | Robustesse                               | EDA, feature engineering, entraînement, seuil, SHAP   |
| 3 — API            | Logs, métriques, dérive, Docker                    | Endpoints, Pydantic, tests               | —                                                     |
| 4 — n8n            | —                                                  | —                                        | Workflow, erreurs, export                             |
| 5 — RAG            | —                                                  | —                                        | Indexation, outils, sécurité, cache, jeu de questions |
| 6 — interface      | Administration                                     | Auth, rôles, parcours                    | Vue assuré                                            |
| 7 — BI             | Indicateurs, tableaux de bord                      | —                                        | —                                                     |
| 8 — exploitation   | Supervision, rollback, persistance, machine vierge | Seuil en direct                          | —                                                     |
| 9 — conformité     | Cartographie, conservation, sécurité               | Recherche de PII résiduelles             | AI Act, audit d'équité                                |
| 10 — documentation | Exploitation, README                               | Guide utilisateur                        | Dossier de cadrage                                    |
| 11 — soutenance    | Lot de 20 factures, démo                           | Slides                                   | Réponses aux objections                               |

### Points de coordination

- **Figer les contrats d'interface avant la Phase 3** : format des prédictions
  et des explications SHAP. C'est le point de dépendance entre les trois.
- Réunion hebdomadaire courte pour synchroniser les dépendances.
- Le seuil d'alerte et le format du rapport SHAP touchent les trois membres :
  à décider ensemble.

---

## Commandes

| Commande                                                                  | Effet                                                        |
| ------------------------------------------------------------------------- | ------------------------------------------------------------ |
| `make help`                                                               | Liste toutes les commandes                                   |
| `make doctor`                                                             | Vérifie que la machine est prête — à lancer en premier       |
| `make up`                                                                 | Démarre la plateforme (commande du jury)                     |
| `make ps`                                                                 | État des conteneurs, tous profils confondus                  |
| `make health`                                                             | Sonde `/health` et `/metrics` de chaque service              |
| `make smoke`                                                              | Parcours de vérification de bout en bout                     |
| `make logs` / `make logs-service S=api-core`                              | Journaux                                                     |
| `make backup` / `make backups` / `make restore`                           | Sauvegarde et restauration                                   |
| `make migrate` / `make reload-data`                                       | Rejouer les migrations ou le chargement                      |
| `make n8n-import` / `make n8n-export`                                     | Installer ou exporter les workflows                          |
| `make acces`                                                              | Régénérer la fiche d'identifiants                            |
| `make threshold VALEUR=0.75`                                              | Changer le seuil d'alerte à chaud                            |
| `make sync` / `make lint` / `make typecheck` / `make test` / `make check` | Développement Python                                         |
| `make down`                                                               | Arrêt, **les données sont conservées**                       |
| `make clean`                                                              | Arrêt **et** suppression des volumes — confirmation demandée |

---

## Profils optionnels

Le cœur démarre seul en ~4,6 Go. Les briques lourdes se lancent à la
demande, ce qui permet de tenir dans le budget mémoire de la machine de
démonstration.

| Commande                | Contenu                                             | Mémoire |
| ----------------------- | --------------------------------------------------- | ------- |
| `make up-workers`       | Workers d'ingestion et d'indexation                 | ~1,1 Go |
| `make up-email`         | Mailpit, boîte mail de développement                | ~0,1 Go |
| `make up-bi`            | Superset + 5 datasets de pilotage, en lecture seule | ~0,9 Go |
| `make up-observability` | Prometheus et Grafana                               | ~0,5 Go |
| `make up-mlops`         | MLflow                                              | ~0,6 Go |
| `make up-backup`        | Sauvegarde quotidienne planifiée                    | ~0,1 Go |
| `make up-all`           | Tout                                                | ~6,5 Go |

### Tableau de bord décisionnel

`make up-bi` démarre Superset et enregistre automatiquement cinq datasets
documentés : volumes traités, taux de détection, montants économisés, délai de
traitement, faux positifs. La connexion BI utilise le rôle `superset_ro`, en
lecture seule stricte — l'outil ne peut pas modifier une donnée métier.

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

## Configuration et accès

Tout se règle dans `.env`, créé automatiquement à partir de `.env.example`.
Aucun secret n'est codé en dur et aucun `.env` n'est versionné. Le seuil
d'alerte, les canaux de notification et l'état de la plateforme sont aussi
modifiables depuis l'écran d'administration, sans redémarrage.

### Piège connu

`POSTGRES_PASSWORD` n'est appliqué par l'image PostgreSQL qu'à la **première**
initialisation du volume. Régénérer un `.env` sur une installation qui
tourne rend la base inaccessible. `make up` vous prévient désormais.

---

## État d'avancement

### En place et vérifié

- Infrastructure complète : `make up` sur machine vierge, 20 tables, pgvector,
  trois rôles SQL en lecture seule
- Trois API opérationnelles avec `/health`, `/metrics` et métriques
  Prometheus ; latence, volume, erreurs, coût LLM, cache sémantique
- Passerelle avec CSP, HSTS, limitation de débit, sans `docker.sock`
- Validation d'entrée : factures invalides rejetées en 422 avec le champ fautif
- Sécurité du RAG : injection de prompt rejetée en 400, compte SQL en
  lecture seule, citations obligatoires
- Sauvegarde et restauration scriptées
- n8n démarré, workflow d'alerte versionné, importé et publié
- Superset démarré avec 5 datasets de pilotage en lecture seule
- CI : ruff, mypy, pytest, construction des images, détection de secrets

### À faire

- **Comptes utilisateurs des 4 rôles** — la table est vide, personne ne peut
  encore se connecter à l'interface
- **Jeu de données** dans `./data/raw` — la base est vide
- **Modèle de fraude entraîné** — sans lui, `api-inference` reste `degraded`
- **Clé LLM** dans `.env` — sans elle, l'assistant RAG ne répond pas
- **Credentials Slack** dans l'interface n8n
- Contenu de `docs/` (ADR, guides, dossier de cadrage)

Chaque dossier porte un `README.md` de brouillon listant ses tâches
restantes.

---

## Licence

Voir `LICENSE`.
