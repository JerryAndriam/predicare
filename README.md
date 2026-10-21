# Système Intelligent de Détection de Fraudes Médicales, d'Optimisation des Remboursements Santé & d'Assistant Agentique

Trois flux — détection de fraude explicable, assistant documentaire sourcé,
pilotage décisionnel — dans une seule application déployée en une commande,
pour quatre rôles : assuré, professionnel de santé, gestionnaire,
administrateur.

|           |                                                                                                                                   |
| --------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Version   | 1.1                                                                                                                               |
| Date      | 21 octobre 2026                                                                                                                   |
| Périmètre | Plateforme de démonstration : API cœur, détection de fraude, assistant documentaire, interface web, BI, supervision, exploitation |
| Public    | Équipe, jury, personnes en charge de l'exploitation ou de la conformité                                                           |
| Statut    | Version de travail ; revue métier et juridique à compléter                                                                        |

> **Ce document est le point d'entrée de la plateforme.** Il explique ce que le
> système fait, comment le démarrer, comment l'exploiter au quotidien et où
> trouver le détail. Les analyses approfondies (coûts, RGPD, AI Act, équité,
> sécurité) sont dans [`docs/livrables/`](docs/livrables/README.md).

---

## 1. Ce que fait la plateforme

La plateforme est un outil de **tiers payant santé**. Elle reçoit des factures,
les note avec un modèle de détection de fraude, présente les alertes aux
gestionnaires et répond aux questions des assurés sur leurs garanties.

| Flux                           | Ce qu'il produit                                               | Service         |
| ------------------------------ | -------------------------------------------------------------- | --------------- |
| **1 — Détection de fraude**    | Un score par facture et son explication, variable par variable | `api-inference` |
| **2 — Assistant documentaire** | Une réponse sourcée à une question d'assuré                    | `api-rag`       |
| **3 — Pilotage décisionnel**   | La file d'alertes, les décisions, l'administration             | `api-core`      |

Quatre rôles partagent la même interface, avec des périmètres distincts :

| Rôle                       | Ce qu'il fait                                                    | Ce qu'il ne voit pas                    |
| -------------------------- | ---------------------------------------------------------------- | --------------------------------------- |
| **Assuré**                 | Consulter ses remboursements, poser une question sur son contrat | Les dossiers des autres assurés         |
| **Professionnel de santé** | Déposer factures et ordonnances, suivre ses dossiers             | La file d'alertes des autres praticiens |
| **Gestionnaire**           | Traiter les alertes, décider, motiver                            | L'administration                        |
| **Administrateur**         | Comptes, seuil, modèle, RGPD, supervision                        | —                                       |

Le point important : **le score ne décide jamais seul**. Il priorise une file
de contrôle ; un gestionnaire lit l'explication et décide. La décision, son
auteur, son horodatage et son motif sont écrits dans un journal d'audit.

Les chiffres clés du modèle, tous vérifiés le 21 octobre 2026 :

| Indicateur                                             |                 Valeur |
| ------------------------------------------------------ | ---------------------: |
| Seuil d'alerte en service                              |             **0,2876** |
| ROC-AUC                                                |                 0,9500 |
| PR-AUC                                                 |                 0,8913 |
| Rappel                                                 |                 0,8702 |
| Précision                                              |                 0,5969 |
| Variables explicatives                                 |                     32 |
| Factures de test / fraudes                             |           10 086 / 878 |
| Économie de contrôle de fraude (convention historique) |         22 656 000 MGA |
| Coût total de possession, scénario de base             |            108,97 €/an |
| Tests automatisés                                      | 784 passés, 18 ignorés |

Le détail de ces chiffres et leur source : [`docs/livrables/README.md`](docs/livrables/README.md)
§ 4. Le dossier de cadrage destiné au jury est dans
[`docs/cadrage/`](docs/cadrage/README.md).

---

## 2. Installation et démarrage

> **Sur une machine vierge, la commande est `make up` — pas `docker compose up`.**
> Le compose seul n'a pas de `.env` : les mots de passe des rôles SQL en
> lecture seule restent vides, les migrations échouent, et les API ne démarrent
> jamais, puisqu'elles en dépendent.

### 2.1 Prérequis

| Outil                   | Requis | Pourquoi                                                          |
| ----------------------- | :----: | ----------------------------------------------------------------- |
| **Docker** + Compose v2 |  oui   | Lance tout le reste                                               |
| **buildx**              |  oui   | BuildKit, requis par les `RUN --mount=type=cache` des Dockerfiles |
| **make**                |  oui   | Point d'entrée des commandes                                      |
| **curl**                |  oui   | Sondes de santé pendant le démarrage                              |
| bash + coreutils        |  oui   | Déjà présents sur toute machine                                   |

Les secrets sont générés à partir de `/dev/urandom` : ni `openssl` ni
`python3` ne sont nécessaires pour démarrer la plateforme.

```bash
sudo apt install docker-buildx-plugin   # Debian / Ubuntu
sudo pacman -S docker-buildx            # Arch
```

Docker Desktop embarque déjà le plugin. `make doctor` vérifie sa présence.

| Outil         | Requis pour                                        |                  Nécessaire à `make up`                  |
| ------------- | -------------------------------------------------- | :------------------------------------------------------: |
| `uv`          | Développement Python (`lint`, `test`, `typecheck`) |                           non                            |
| `python3`     | `health`, `smoke`, `n8n-import`, `n8n-export`      |                           non                            |
| `git`         | Versionnement, hooks                               |                           non                            |
| `node`, `npm` | —                                                  | **jamais** : le build de l'interface se fait dans Docker |

### 2.2 Première installation

```bash
make doctor   # vérifie que la machine est prête — à lancer en premier
make up       # construit et démarre toute la plateforme
make start    # redémarre sans reconstruire
make down     # arrête tout, les données sont conservées
```

`make up` enchaîne les étapes suivantes, dans cet ordre :

1. la configuration TLS est rendue ;
2. le `.env` est créé à partir de `.env.example` et les secrets manquants sont
   générés ;
3. les images sont construites ;
4. la base et Redis démarrent, les migrations sont appliquées ;
5. les données de `data/raw/` sont chargées ;
6. les workers d'ingestion et d'indexation démarrent ;
7. Superset, Prometheus, Grafana et MLflow démarrent ;
8. les workflows d'automatisation absents sont installés, sans remplacer ceux
   qui existent ;
9. le script attend que tous les services soient sains.

Le démarrage complet prend plusieurs minutes.

### 2.3 Le jour de la démonstration

```bash
make down && make start   # redémarrage propre, sans reconstruction
make health                # chaque service doit répondre
make smoke                 # parcours de vérification de bout en bout
make e2e-n8n               # alerte réelle vers Slack et e-mail, puis échec journalisé
make acces                 # fiche d'identifiants régénérée, hors dépôt, mode 600
make n8n-compte            # état du compte n8n de ce poste
```

`make n8n-compte` n'est pas un détail : depuis la version 1.x, n8n n'a plus
d'authentification basique. Le compte propriétaire se crée au premier lancement
de l'interface, avec l'adresse saisie par le visiteur, et **le mot de passe
n'est écrit dans aucun fichier**. Chaque poste a le sien.

### 2.4 Reconstruire ou pas

`make up` reconstruit systématiquement les images : c'est le bon réflexe sur
une machine vierge et après une modification de code. Mais Compose interroge
malgré tout le réseau pour résoudre les images de base : un `make up` peut
bloquer sur une machine sans internet, alors que la pile est parfaitement
capable de démarrer.

C'est le cas d'usage du jour J, où la démonstration est répétée :

```bash
make down     # arrêt, les données restent
make start    # redémarrage immédiat, aucune reconstruction
```

### 2.5 Mémoire

| Jeu de commandes                                             | Limites configurées | Usage observé |
| ------------------------------------------------------------ | ------------------: | ------------: |
| `make up-light` (noyau seul)                                 |             ~3,5 Go |       ~0,8 Go |
| `make up` / `make start` (noyau + BI + supervision + MLflow) |             ~5,8 Go |       ~2,0 Go |
| `make up-all` (+ Mailpit et cron de sauvegarde)              |             ~8,9 Go |       ~2,1 Go |

Les limites sont les plafonds déclarés dans les fichiers Compose ; l'usage
observé vient de `docker stats` sur la pile complète en fonctionnement. **Un
serveur de 8 Go de RAM suffit** pour la démonstration. Si `make up` échoue
faute de mémoire, `make up-light` conserve un noyau démontrable : seul
l'outillage de pilotage devient indisponible.

---

## 3. Points d'entrée

| Application                        | URL                                   | Lancée par      |
| ---------------------------------- | ------------------------------------- | --------------- |
| Interface web, les quatre rôles    | <http://localhost:8080>               | `make up`       |
| Documentation interactive de l'API | <http://localhost:8080/api/core/docs> | `make up`       |
| Automatisation des workflows       | <http://localhost:5678>               | `make up`       |
| Tableau de bord décisionnel        | <http://localhost:8088>               | `make up`       |
| Supervision, tableaux de bord      | <http://localhost:3001>               | `make up`       |
| Métriques et règles d'alerte       | <http://localhost:9090>               | `make up`       |
| Suivi des entraînements de modèle  | <http://localhost:5000>               | `make up`       |
| Boîte mail de développement        | <http://localhost:8025>               | `make up-email` |
| PostgreSQL et pgvector             | **pas de port** — `make shell-db`     | `make up`       |

`make up` et `make start` démarrent l'ensemble de la plateforme, tableaux de
bord et supervision compris. `make up-light` garde la version économique pour
une machine contrainte.

**PostgreSQL et Redis ne publient aucun port sur la machine hôte, et ce n'est
pas un oubli.** Le réseau `core` est interne : Docker n'active la publication
d'un port que si le conteneur est rattaché à au moins un réseau non interne.
Un `ports:` déclaré sur ces services passerait `docker compose config` tout en
restant inopérant, et produirait un refus de connexion trompeur. L'accès à la
base passe donc par `make shell-db` et `make db-sql`.

---

## 4. Configuration

Tout se règle dans le fichier `.env`, créé automatiquement à partir de
`.env.example`. Aucun secret n'est codé en dur et aucun `.env` n'est versionné.
Le seuil d'alerte, les canaux de notification et l'état de la plateforme sont
aussi modifiables depuis l'écran d'administration, sans redémarrage.

| Groupe            | Variables principales                                                   | Effet                                        |
| ----------------- | ----------------------------------------------------------------------- | -------------------------------------------- |
| Base              | `POSTGRES_PASSWORD`, `PREDICARE_DB_URL`, `PREDICARE_DB_RO_URL`          | Connexion et lecture seule                   |
| Sécurité          | `APP_SECRET_KEY`, `JWT_SECRET_KEY`, `IDENTITY_ENCRYPTION_KEY`           | Pseudonymisation, jetons, identités          |
| Modèle de langage | `LLM_API_KEY`, `EMBEDDING_API_KEY`, `LLM_MODEL`                         | Assistant et vecteurs                        |
| Seuil             | `FRAUD_THRESHOLD`, `MODEL_VERSION`                                      | Décision de notation                         |
| Assistant         | `RAG_TOP_K`, `SESSION_MAX_TURNS`, `SEMANTIC_CACHE_THRESHOLD`            | Coût, fidélité, cache                        |
| Conservation      | `PURGE_PLANIFIEE`                                                       | Active ou coupe la purge automatique         |
| Indexation        | `SEED_RAG_AUTO`                                                         | Indexe l'assistant au chargement des données |
| Tableau de bord   | `SUPERSET_SECRET_KEY`, `SUPERSET_PORT`, `VITE_SUPERSET_URL`             | BI et lien depuis l'interface                |
| Supervision       | `GRAFANA_PASSWORD`, `PROMETHEUS_PORT`                                   | Supervision                                  |
| Sauvegarde        | `BACKUP_RETENTION_DAYS`, `BACKUP_HOUR`, `BACKUP_CLE_FILE`               | Rétention et chiffrement                     |
| TLS               | `PREDICARE_TLS_DOMAIN`, `PREDICARE_TLS_CERTIFICAT`, `PREDICARE_TLS_CLE` | HTTPS                                        |

Quatre règles structurent cette configuration :

- `.env` n'est jamais versionné, et `make doctor` détecte les placeholders et
  les secrets manquants ;
- un changement de secret impose le redémarrage des services concernés ;
- un changement de `IDENTITY_ENCRYPTION_KEY` sans rotation rend les identités
  illisibles ;
- un changement de `MODEL_VERSION` doit être accompagné d'un contrôle du
  registre des modèles.

### 4.1 La purge automatique

La purge supprime les données arrivées au bout de leur durée de conservation :
**3 ans** pour les prédictions, **10 ans** pour les factures, **5 ans** pour le
journal d'audit. Elle est **planifiée** : l'API cœur lance un premier passage
différé, puis un toutes les **24 h**. Chaque exécution réelle écrit une ligne
dans le journal d'audit avec le nombre de lignes supprimées par table, et la
purge est **idempotente** : un second passage ne trouve plus rien à faire.

Elle reste déclenchable à la main (`make purge` affiche l'aperçu,
`make purge ARGS=--appliquer` exécute) et la boucle de fond se coupe avec
`PURGE_PLANIFIEE=0`.

### 4.2 Le seuil d'alerte

Le seuil en service est **0,2876**. Il est modifiable à chaud, sans
redémarrage, et chaque changement est tracé avec son motif. Il a été aligné
le 21 octobre 2026 sur la valeur du rapport de référence
(`reports/modele_v2.md`) : l'artefact du modèle conserve son seuil d'origine
(0,2766), qui reste le point de fonctionnement par défaut du modèle, mais la
plateforme applique bien 0,2876.

> **Deux seuils, un seul système.** Le seuil de **notification** est une autre
> notion : il déclenche une interruption humaine sur les cas très nets. Il
> vient d'un réglage unique — l'audit de paramètres, sinon la configuration de
> la machine, sinon 0,8 — et il ne descend jamais sous le seuil de détection,
> pour ne pas notifier une facture que le modèle n'a pas retenue.

### 4.3 Les deux pièges connus

**Le mot de passe de la base n'est appliqué qu'à la première initialisation
du volume.** Régénérer un `.env` sur une installation qui tourne rend la base
inaccessible. `make up` vous prévient.

**Aucun port TCP n'atteint PostgreSQL ni Redis** (voir § 3).

---

## 5. Opérations quotidiennes

### 5.1 Santé

```bash
curl -sS http://localhost:8080/health
curl -sS http://localhost:8001/health
curl -sS http://localhost:8003/health
```

La sonde de l'assistant est **honnête** : elle distingue une clé réellement
configurée d'un gabarit jamais remplacé. Un `.env` livré tel quel annonce
`degraded` plutôt qu'un `ok` trompeur.

### 5.2 Journaux

```bash
docker compose logs -f --tail=200 api-core
docker compose logs -f --tail=200 api-rag
docker compose logs -f --tail=200 gateway
```

Les journaux sont en JSON, sans noms. Ils peuvent contenir des références de
factures et des identifiants pseudonymisés : **ce sont des données
personnelles**.

### 5.3 Redémarrage

```bash
docker compose restart api-core
docker compose up -d --force-recreate api-rag
```

Un redémarrage de l'assistant vide le cache sémantique en mémoire. Ce n'est pas
une perte : le cache est un accélérateur.

### 5.4 Comptes

Les comptes sont créés et désactivés par l'administrateur. Un compte est
nominatif, rattaché à un dossier assuré ou à un prestataire. **Ne jamais
partager un compte.**

---

## 6. Le modèle en service

Un modèle s'entraîne une fois et se sert en continu : les commandes de cette
section sont des **jobs**, jamais lancés au démarrage de la pile. Elles
s'exécutent dans la même image Docker que les services, donc avec le même
XGBoost, la même version de SHAP et le même pandas — aucune divergence
possible entre ce qui s'entraîne et ce qui sert.

L'entraînement écrit quatre fichiers par version :

```
models/<version>/
├── model.joblib        modèle XGBoost sérialisé
├── features.json       ordre des 32 variables, versionné avec le modèle
├── metadata.json       métriques, seuil, empreinte des données d'entraînement
└── referentiels.json   grilles tarifaires et référentiels, versionnés avec le modèle
```

Le quatrième fichier garantit que l'inférence note avec **la même grille
tarifaire** que celle utilisée à l'entraînement : un changement de tarif
impose un ré-entraînement explicite, plutôt qu'un modèle qui dérive en
silence.

| Commande                        | Ce qu'elle fait                                                                                                                                                                                                                                                                                                       |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `make train VERSION=2`          | Entraîne le modèle et écrit `models/2/` (artefacts et rapports).                                                                                                                                                                                                                                                      |
| `make evaluate`                 | Compare les stratégies de déséquilibre et produit l'audit d'équité.                                                                                                                                                                                                                                                   |
| `make noter LIMITE=500`         | Note en lot l'historique et peuple `ml.prediction`, en process avec le contexte exact (ordonnance, heure de soin). `STATUT=nouvelle` pour alimenter la file, `DRY_RUN=1` pour simuler, `RESCORER=1` pour un diagnostic.                                                                                               |
| `make add-invoices`             | Ajoute des factures par la **même porte que le front** (validation, notation, explication, alerte). Accepte le JSON du lot de démonstration, le CSV et le PDF. Une facture déjà présente est **ignorée**, une facture invalide est **rejetée en nommant le champ**. `ARGS=--fichier <chemin>` pour un fichier précis. |
| `make model-state`              | Version active du modèle et seuil courant.                                                                                                                                                                                                                                                                            |
| `make model-promote VERSION=2`  | Charge la version N en _candidate_, puis bascule — sans redémarrage.                                                                                                                                                                                                                                                  |
| `make model-rollback VERSION=1` | Revient à la version N, sans redémarrage.                                                                                                                                                                                                                                                                             |
| `make threshold VALEUR=0.75`    | Change le seuil d'alerte à chaud, sans redémarrage.                                                                                                                                                                                                                                                                   |
| `make score-historique`         | Rejoue le jeu étiqueté (backfill idempotent, statut `historique`).                                                                                                                                                                                                                                                    |

`make noter` est le seul job qui **écrit en masse** dans `ml.prediction`. Par
défaut il marque ses prédictions `statut = 'archive'` : ce sont des notations
rétrospectives, utiles à la mesure de la qualité du modèle et au volume du
tableau de bord, mais qui n'entrent pas dans la file de travail du
gestionnaire. Sans cette distinction, des milliers d'alertes historiques non
décidées feraient afficher un taux de faux positifs de 100 %.

`make add-invoices` passe par le même chemin que le formulaire : la
validation, la vérification des référentiels, la notation et la persistance.
Le front importe lui aussi des factures, en JSON, en CSV et en **PDF** (une
facture par fichier, vingt fichiers maximum par lot).

Le seuil est **calculé, pas choisi** : il minimise le coût métier sous
contrainte de rappel supérieur ou égal à 90 %. Le seuil historique de 0,8 a été
abandonné — avec 8,7 % de fraude dans la population, il laissait passer une
part importante des vraies fraudes. Le détail de l'arbitrage est dans
[`reports/modele_v2.md`](reports/modele_v2.md), l'audit d'équité dans
[`reports/equite_v2.md`](reports/equite_v2.md) et la comparaison aux autres
bases de décision dans [`reports/baselines_v2.md`](reports/baselines_v2.md).

---

## 7. Sauvegarde, restauration et conservation

| Élément                                      | Valeur                                       |
| -------------------------------------------- | -------------------------------------------- |
| Fréquence                                    | Quotidienne, 03 h 00                         |
| Rétention                                    | 14 jours                                     |
| Format                                       | `pg_dump` compressé, chiffré si clé présente |
| Chiffrement                                  | AES-256-CBC, PBKDF2 200 000 itérations       |
| RPO                                          | ≤ 24 h                                       |
| RTO                                          | Non mesuré                                   |
| Test de restauration en intégration continue | Absent                                       |

| Commande         | Ce qu'elle fait                                          |
| ---------------- | -------------------------------------------------------- |
| `make backup`    | Lance une sauvegarde immédiate.                          |
| `make backups`   | Liste les sauvegardes disponibles.                       |
| `make restore`   | Restaure la dernière sauvegarde — confirmation demandée. |
| `make up-backup` | Démarre la planification quotidienne.                    |

La restauration n'est **jamais** automatique : une restauration déclenchée par
une erreur de script écraserait les données du jour. Le script prend une
sauvegarde de sécurité de la base courante avant de restaurer, et vérifie
ensuite qu'au moins dix tables existent.

La clé de chiffrement est un **fichier**, jamais une option de ligne de
commande. Elle doit être sauvegardée séparément, avec un accès restreint : une
sauvegarde chiffrée avec une clé perdue est une sauvegarde perdue.

---

## 8. Supervision

Prometheus collecte les métriques applicatives : latence, erreurs, tokens,
coût, cache. **Les règles d'alerte et les tableaux de bord sont versionnés
dans le dépôt** : neuf règles dans `ops/prometheus/rules/predicare.yml` et deux
vues Grafana (service et modèle) dans `ops/grafana/provisioning/dashboards/`.

| Alerte                             | Ce qu'elle surveille                         |
| ---------------------------------- | -------------------------------------------- |
| `PredicareApiIndisponible`         | Une API ne répond plus pendant une minute    |
| `PredicareApiTauxErreur5xx`        | Pic d'erreurs serveur                        |
| `PredicareApiLatenceP95`           | Latence p95 des API                          |
| `PredicareInferenceErreurs`        | Erreurs de notation                          |
| `PredicareInferenceLatenceP95`     | Latence p95 de notation                      |
| `PredicareAucunePredictionRecente` | Plus aucune facture notée depuis deux heures |
| `PredicareRagLatenceP95`           | Latence p95 de l'assistant                   |
| `PredicareRagLlmIndisponible`      | Fournisseur de modèle injoignable            |
| `PredicarePartScoresEleves`        | Part anormalement élevée de scores hauts     |

Le suivi des entraînements passe par **MLflow** : chaque exécution de
`make train` est journalisée dans l'expérience `predicare-detection-fraude`,
avec ses paramètres et ses métriques. La reproductibilité devient une preuve
consultable, pas une intention.

> **Ce qui n'est pas calculable aujourd'hui.** Le rapport de dérive (PSI,
> _Population Stability Index_, mesure l'écart entre deux distributions de
> score) **ne peut pas être produit sur cette instance** : le worker journalise
> `derive.donnees_insuffisantes`, faute de population de référence du modèle.
> La surveillance de la dérive repose donc sur un indicateur de substitution
> (part des scores au-dessus de 0,3). C'est un écart connu, écrit dans le
> registre des risques.

---

## 9. Tableau de bord et BI

`make up` démarre le BI, enregistre **treize jeux de données** sur les cinq
vues de la couche sémantique `bi`, puis crée **douze tuiles** et le tableau de
bord « Pilotage mensuel ». La connexion utilise un rôle en lecture stricte :
l'outil ne peut pas modifier une donnée métier.

Le tableau est aussi intégré dans `/pilotage` pour les gestionnaires et les
administrateurs : l'application demande un jeton d'invité court à la plateforme
BI, donc **aucune seconde connexion** n'est nécessaire. La route `/bi` reste
disponible pour ouvrir le tableau de bord directement.

Le tableau suit les cinq indicateurs du pilotage : volumes, montants
économisés, taux de détection, délai de traitement, faux positifs. Deux
d'entre eux restent **vides** tant que le modèle n'a pas tourné et qu'aucune
décision gestionnaire n'est enregistrée : les vues existent, elles sont vides,
et le tableau le dit.

| Commande              | Ce qu'elle fait                                                                                |
| --------------------- | ---------------------------------------------------------------------------------------------- |
| `make bi`             | Vérifie que les vues de la couche sémantique compilent.                                        |
| `make bi-dashboard`   | Réapplique le tableau de bord archivé dans le dépôt (après une manipulation dans l'interface). |
| `make bi-export`      | Archive l'état du tableau de bord (mise en page, filtres natifs) dans le dépôt.                |
| `make bi-requetes`    | Peuple l'historique SQL Lab et les requêtes enregistrées du BI.                                |
| `make bi-compte-demo` | Crée le compte de démonstration, en lecture seule.                                             |
| `make bi-graphiques`  | Vérifie que chaque graphique rend une requête réussie et qu'aucune dérive ne s'est installée.  |

Détail des indicateurs, de leur source et de leur fréquence :
[`db/bi/README.md`](db/bi/README.md). La procédure de création des tuiles
par l'interface est dans
[`ops/superset/creer_tableau_bord.md`](ops/superset/creer_tableau_bord.md).

---

## 10. Automatisation des workflows

| Commande          | Ce qu'elle fait                                                                                       |
| ----------------- | ----------------------------------------------------------------------------------------------------- |
| `make n8n-compte` | Affiche le compte propriétaire de ce poste, et la procédure s'il n'existe pas.                        |
| `make n8n-export` | Exporte les workflows dans `apps/n8n/workflows/`.                                                     |
| `make n8n-import` | Restaure et réactive les workflows.                                                                   |
| `make e2e-n8n`    | Envoie une facture au point d'entrée et vérifie Slack, l'e-mail et l'absence de notification fantôme. |

Trois workflows sont versionnés : l'alerte de fraude interne, l'alerte de
fraude avec re-notation, et la bascule de modèle. La chaîne d'alerte part du
point d'entrée HTTP, compare le score au seuil de notification, puis part
vers Slack et l'e-mail, et **trace l'échec** de la notification quand elle
échoue.

Les workflows se partagent **par Git**, pas à l'intérieur de l'outil : l'édition
Community n'a pas de partage de projet. Détails dans
[`apps/n8n/README.md`](apps/n8n/README.md).

---

## 11. Commandes

`make help` liste les **68 commandes**. Cette section les regroupe par tâche.
Le contrôle `make readme` vérifie que cette liste reste alignée sur
`make help` : une commande ajoutée sans être documentée ici fait échouer la
vérification.

### 11.1 Cycle de vie

| Commande        | Ce qu'elle fait                                                                |
| --------------- | ------------------------------------------------------------------------------ |
| `make help`     | Affiche l'aide.                                                                |
| `make up`       | Démarre tout **en reconstruisant** les images. Commande de référence.          |
| `make start`    | Démarre **sans reconstruire**, après un `make down`.                           |
| `make up-light` | Noyau seul : API, interface, base, workers.                                    |
| `make down`     | Arrêt. **Les données sont conservées.**                                        |
| `make restart`  | Redémarre sans reconstruire.                                                   |
| `make clean`    | Arrêt **et** suppression des volumes — confirmation demandée, données perdues. |
| `make build`    | Construit les images sans démarrer.                                            |
| `make wait`     | Attend que tous les services soient sains.                                     |

### 11.2 Services optionnels

`make up` démarre déjà le BI, la supervision, MLflow et les workers. Ces
commandes servent à démarrer un service **seul**, ou à ajouter ce que le
défaut exclut volontairement.

| Commande                | Ce qu'elle fait                                                                 |
| ----------------------- | ------------------------------------------------------------------------------- |
| `make up-bi`            | Démarre le pilotage décisionnel.                                                |
| `make up-observability` | Démarre Prometheus et Grafana.                                                  |
| `make up-mlops`         | Démarre MLflow.                                                                 |
| `make up-backup`        | Démarre la sauvegarde quotidienne.                                              |
| `make up-workers`       | Démarre les workers d'ingestion et d'indexation.                                |
| `make up-email`         | Démarre la boîte mail de développement.                                         |
| `make up-all`           | Tout démarrer, bac à sable de messagerie et planification de sauvegarde inclus. |

### 11.3 Données et base de données

| Commande           | Ce qu'elle fait                                                                                                                                   |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `make setup`       | Crée le `.env` et génère les secrets manquants.                                                                                                   |
| `make secrets`     | Régénère les secrets cryptographiques.                                                                                                            |
| `make migrate`     | Applique les migrations en attente.                                                                                                               |
| `make db-status`   | Compare la version du schéma en base et celle attendue par le code.                                                                               |
| `make reload-data` | Recharge `data/raw/` : purge puis tables, en une transaction.                                                                                     |
| `make comptes`     | Crée les quatre comptes de démonstration. Le mot de passe vient de `DEMO_PASSWORD` ; sinon il est généré au hasard et **affiché une seule fois**. |
| `make seed-rag`    | Indexe le corpus de contrats PDF dans la base vectorielle.                                                                                        |
| `make shell-db`    | Ouvre un client SQL sur la base. `ROLE=predicare_ro` pour un accès lecture seule.                                                                 |
| `make db-sql`      | Exécute une requête (`Q="SELECT …"`), un fichier (`FILE=…`) ou l'entrée standard.                                                                 |
| `make purge`       | Purge les données hors durées de conservation (aperçu ; `--appliquer` pour exécuter).                                                             |

`make db-status` est le garde-fou le plus utile du projet : le job de migration
étant un one-shot, il n'est pas rejoué spontanément. Sans ce contrôle, une
migration ajoutée après le premier démarrage resterait non appliquée.

`ROLE=predicare_ro` sert à démontrer le moindre privilège sur un cas réel : la
même requête aboutit en `predicare` et se voit refuser sur le schéma d'audit.

### 11.4 Qualité et vérification

| Commande                   | Ce qu'elle fait                                                                                                                                           |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `make sync`                | Installe les dépendances Python (workspace complet).                                                                                                      |
| `make lint`                | Vérifie le style et les erreurs statiques.                                                                                                                |
| `make format`              | Corrige automatiquement le style.                                                                                                                         |
| `make typecheck`           | Vérifie les types.                                                                                                                                        |
| `make test`                | Lance la suite de tests.                                                                                                                                  |
| `make test-cov`            | Lance les tests avec le rapport de couverture.                                                                                                            |
| `make check`               | Les quatre vérifications de l'intégration continue.                                                                                                       |
| `make readme`              | Vérifie que ce README documente exactement les commandes de `make help`.                                                                                  |
| `make export-requirements` | Exporte les versions pip depuis le verrou, non versionné.                                                                                                 |
| `make web-build`           | Compile l'interface : vérification des types puis bundle.                                                                                                 |
| `make web-test`            | Lance les parcours de navigation des quatre rôles.                                                                                                        |
| `make figures`             | Génère les figures de la présentation (modèle, ROI, conformité) à partir des sources de vérité. `SORTIE=<dossier>` pour choisir la destination.           |
| `make captures`            | Capture les écrans de la présentation avec un navigateur réel. `N8N_MDP=<mot de passe> N8N_EMAIL=<adresse>` pour le compte propriétaire d'automatisation. |

Aucun test ne démarre de conteneur ni ne touche PostgreSQL : l'intégration
continue doit tourner sur une proposition de modification sans Docker.

### 11.5 Diagnostic

| Commande                       | Ce qu'elle fait                                            |
| ------------------------------ | ---------------------------------------------------------- |
| `make doctor`                  | Vérifie que la machine est prête. **À lancer en premier.** |
| `make ps`                      | État des conteneurs, tous profils confondus.               |
| `make health`                  | Sonde la santé et les métriques de chaque service.         |
| `make logs`                    | Suit les journaux de la plateforme.                        |
| `make logs-service S=api-core` | Suit le journal d'un service.                              |
| `make smoke`                   | Parcours de vérification de bout en bout.                  |
| `make acces`                   | Génère la fiche d'identifiants, hors dépôt, mode `600`.    |

`make doctor` contrôle les outils de l'hôte, le démon Docker, Compose, buildx,
la présence et la santé du `.env`, l'absence de marqueur de secret en clair, la
fiche d'accès, et le fait que `.env` n'est pas versionné.

---

## 12. Architecture

Trois flux, trois services indépendants, une base de données unique. Chaque
service a ses propres dépendances, sa propre latence et son propre cycle de
vie : un flux se remplace ou se redimensionne sans impacter les autres.

```
                        passerelle (Traefik)  :8080
                        CSP, HSTS, limitation de débit
                                  |
        +------------------------+------------------------+
        |                        |                        |
      interface              api-core                (n8n :5678)
    (nginx, React)      Flux 3 + socle :8001             alerte Slack
    les 4 rôles         auth, factures, décisions,        + rapport
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

   PostgreSQL 16 + pgvector              Redis
   schémas core / ml / audit / bi        sessions et files
   · une seule sauvegarde pour tout
```

| Flux                       | Service               | Dossier                    | Ce qu'il produit                                           |
| -------------------------- | --------------------- | -------------------------- | ---------------------------------------------------------- |
| 1 — Détection de fraude    | `api-inference` :8002 | `apps/api-inference/`      | Score de fraude et contributions d'explication par facture |
| 2 — Assistant documentaire | `api-rag` :8003       | `apps/api-rag/`            | Réponse sourcée à une question d'assuré                    |
| 3 — Pilotage               | `api-core` :8001      | `apps/api-core/`           | File d'alertes, décisions, administration                  |
| Transverse                 | —                     | `packages/predicare-core/` | Configuration, base, sécurité, métriques                   |

**Trois plans réseau.** Le réseau `core` est interne : aucun service
applicatif n'atteint Internet par ce plan. Seul l'assistant sort, pour appeler
le fournisseur de modèle. La passerelle n'a pas accès au démon Docker.

---

## 13. Organisation du dépôt

| Dossier                    | Propriétaire | Utilité                                                                                                                                                                     |
| -------------------------- | :----------: | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/api-core/`           |   Cherica    | **Flux 3 et socle.** Authentification et quatre rôles, factures et ordonnances, file d'alertes, décisions, administration, journal d'audit                                  |
| `apps/api-inference/`      |    Mirado    | **Flux 1.** Validation stricte d'entrée, featurisation, notation, contributions d'explication, dérive, registre de versions                                                 |
| `apps/api-rag/`            |    Mirado    | **Flux 2.** Agent outillé, garde-fous contre l'injection de prompt, outil SQL en lecture seule, recherche vectorielle, cache sémantique                                     |
| `apps/web/`                |   Cherica    | Interface unique React et TypeScript, servie par nginx, les quatre parcours de rôle                                                                                         |
| `apps/ml-training/`        |    Mirado    | Entraînement, choix du seuil, évaluation, audit d'équité. Code de **job**, pas un service                                                                                   |
| `apps/seed/`               |   Cherica    | Chargement initial des 24 mois au premier démarrage. Idempotent                                                                                                             |
| `apps/n8n/`                |    Mirado    | Workflows d'alerte versionnés                                                                                                                                               |
| `packages/predicare-core/` |    Jerry     | Socle transverse : configuration, base, jetons et habilitations, chiffrement, journaux, métriques                                                                           |
| `db/migrations/`           |   Cherica    | Schéma versionné. Trois schémas métier plus la couche BI, rôles SQL en lecture seule                                                                                        |
| `db/seeds/`                |   Cherica    | Référentiels d'actes et données de référence                                                                                                                                |
| `db/backup/`               |    Jerry     | Sauvegarde quotidienne et restauration                                                                                                                                      |
| `ops/`                     |    Jerry     | Passerelle, Prometheus, Grafana, BI, planification des sauvegardes                                                                                                          |
| `scripts/`                 |    Jerry     | Ce qu'on exécute : amorçage, attente, santé, test de fumée, export et import des workflows, figures                                                                         |
| `tests/`                   |    Jerry     | 784 tests : validation d'entrée, sécurité de l'assistant, SQL, habilitations, chiffrement, explications, cache, supervision, workflows, dérive, import PDF, purge planifiée |
| `docs/`                    |    Jerry     | Livrables détaillés, dossier de cadrage, guide d'exploitation, plan de pitch, décisions d'architecture                                                                      |

### 13.1 Dossiers créés à l'exécution

Ces quatre dossiers existent sur la machine mais **ne sont pas versionnés** :
`data/` (données à charger), `models/` (artefacts de modèle), `backups/`
(sauvegardes), `artifacts/` (MLflow).

### 13.2 Fichiers de configuration racine

| Fichier                                           | Rôle                                     |
| ------------------------------------------------- | ---------------------------------------- |
| `docker-compose.yml`                              | Pile principale, lancée par `make up`    |
| `docker-compose.{bi,observability,mlops,ops}.yml` | Profils optionnels                       |
| `pyproject.toml`                                  | Workspace Python, style, types, tests    |
| `uv.lock`                                         | Verrou des dépendances Python, versionné |
| `alembic.ini`                                     | Configuration des migrations             |
| `Makefile`                                        | Toutes les commandes d'exploitation      |
| `.env.example`                                    | Modèle de configuration, versionné       |
| `.github/workflows/ci.yml`                        | Intégration continue                     |

---

## 14. Chargement des données

Le jeu synthétique de l'encadrement est dans `data/raw/`, **non versionné** :
44 Mo de données de santé restent hors du dépôt.

```bash
cp ~/Documents/<source>/dataset/*.csv data/raw/
make reload-data
```

Quatorze fichiers, environ **436 700 lignes** sur 24 mois, vers quatorze tables
réparties entre les schémas `core` (métier), `ml` (modèles et labels) et
`audit`.

Trois points méritent d'être connus :

- **Pseudonymisation.** Les assurés sont pseudonymisés par HMAC-SHA256 ; le
  même assuré donne toujours le même pseudonyme, ce qui permet de relier une
  facture à un dossier sans jamais stocker l'identité. Le fichier des identités
  est le **seul** fichier nominatif : il alimente la table d'identités
  chiffrées, et rien d'autre.
- **Validation bloquante avant écriture.** Un contrôle qui échoue interrompt
  le chargement et nomme le fichier fautif. Les valeurs manquantes ne sont
  pas des anomalies : 44 % des factures n'ont pas d'ordonnance parce que
  beaucoup d'actes n'en exigent pas.
- **Fuite de données.** Le statut de rejet est fortement corrélé à la fraude —
  70 % des factures rejetées sont frauduleuses contre 7 % des payées. Ces
  colonnes restent dans `core`, la validité dérivée atterrit dans `ml` : la
  disposition des tables empêche la featurisation de les utiliser comme
  variables.

Détail complet dans [`db/seeds/README.md`](db/seeds/README.md).

---

## 15. Sécurité et limites assumées

Ce qui est en place et démontré : habilitations par rôle appliquées côté
serveur, filtrage des données par dossier et par prestataire, chiffrement des
identités, pseudonymes stables, sauvegardes chiffrées, journalisation des
connexions, décisions et actions d'administration, test d'intrusion interne,
règles d'alerte et vues de supervision versionnées.

Ce qui n'est pas en place, et que le dossier assume :

| Écart                                           | Conséquence                                                                      |
| ----------------------------------------------- | -------------------------------------------------------------------------------- |
| TLS non activé par défaut                       | À activer en production avec un certificat valide                                |
| Authentification à deux facteurs absente        | À ajouter pour l'administration et la gestion                                    |
| Pas d'isolation au niveau des lignes de la base | L'isolation est portée par l'API et l'outil SQL                                  |
| Population de référence du modèle absente       | Le rapport de dérive n'est pas calculable                                        |
| Test de restauration non automatisé             | Une sauvegarde jamais restaurée n'est pas une sauvegarde prouvée                 |
| Pas de quota par utilisateur pour le modèle     | Un usage intensif peut épuiser le quota du fournisseur                           |
| Alertes de dépendances non vérifiées en local   | L'état des alertes de sécurité reste à confirmer sur la plateforme d'hébergement |

Le détail des contrôles, des preuves et de la feuille de route :
[`docs/livrables/Mecanismes_Securite.pdf`](docs/livrables/Mecanismes_Securite.pdf).

---

## 16. Documentation

| Document                                                                   | Contenu                                                                                                                                               |
| -------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| [`docs/livrables/`](docs/livrables/README.md)                              | Les cinq analyses détaillées : coûts et retour sur investissement, conformité RGPD, AI Act et équité, sécurité, guide d'exploitation et d'utilisation |
| [`docs/cadrage/`](docs/cadrage/README.md)                                  | Le dossier de cadrage destiné au jury, et le registre des risques                                                                                     |
| [`docs/pitch/`](docs/pitch/README.md)                                      | Le plan de la soutenance et les figures projetées                                                                                                     |
| [`docs/adr/`](docs/adr/README.md)                                          | Les décisions d'architecture et leur justification                                                                                                    |
| [`docs/equipe.md`](docs/equipe.md)                                         | Qui fait quoi, et le suivi du projet                                                                                                                  |
| [`ops/superset/creer_tableau_bord.md`](ops/superset/creer_tableau_bord.md) | La procédure de création des tuiles du tableau de bord, par l'interface                                                                               |

---

## 17. Licence

Voir `LICENSE`.
