# =============================================================================
# PrediCare TPA - commandes d'exploitation
# -----------------------------------------------------------------------------
# `make help` liste les cibles disponibles.
# La commande de reference du projet reste `make up` : c'est elle que le jury
# execute sur une machine vierge.
# =============================================================================

SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE      := docker compose

# Un service range dans un profil n'est demarre que si le profil est actif.
# `--profile '*'` sert pour les commandes qui doivent tout arreter ou tout
# construire : sans lui, un conteneur deja lance resterait orphelin.
TOUS_PROFILS := --profile '*'

COMPOSE_CORE  = $(COMPOSE) -f docker-compose.yml
COMPOSE_BI    = $(COMPOSE_CORE) -f docker-compose.bi.yml
COMPOSE_OBS   = $(COMPOSE_CORE) -f docker-compose.observability.yml
COMPOSE_MLOPS = $(COMPOSE_CORE) -f docker-compose.mlops.yml
COMPOSE_OPS   = $(COMPOSE_CORE) -f docker-compose.ops.yml
COMPOSE_ALL   = $(COMPOSE) $(TOUS_PROFILS) -f docker-compose.yml -f docker-compose.ops.yml -f docker-compose.bi.yml -f docker-compose.observability.yml -f docker-compose.mlops.yml

  # Pile de demonstration : ce que lancent `make up` et `make start`.
  #
  # Volontairement differente de COMPOSE_ALL sur deux points :
  #
  #   - pas de `--profile '*'` : ce drapeau activerait aussi le profil
  #     `email` et donc Mailpit, un bac a sable qui intercepte tout le
  #     courrier sortant. Il resterait actif en permanence et masquerait un
  #     envoi reel lors de la demonstration.
  #   - pas de `docker-compose.ops.yml` : le service `backup` est un cron
  #     quotidien, invisible pendant une soutenance et coute un conteneur en
  #     plus. `make up-backup` le demarre a la demande.
  #
  # Les workers, eux, sont inclus : ils font partie du fonctionnement
  # applicatif (ingestion et indexation), ce n'est pas un outillage de confort.
  COMPOSE_STACK = $(COMPOSE) --profile workers -f docker-compose.yml -f docker-compose.bi.yml -f docker-compose.observability.yml -f docker-compose.mlops.yml

  COMPOSE_WORKERS := $(COMPOSE) --profile workers -f docker-compose.yml
COMPOSE_EMAIL   := $(COMPOSE) --profile email -f docker-compose.yml

PY           := uv run --all-packages

# Dossier des 14 CSV de l'encadrement, monte en lecture seule dans le job
# d'entrainement. Il n'est volontairement pas versionne : 44 Mo de donnees de
# sante ne doivent pas entrer dans l'historique Git.
DATA_DIR     ?= ./data/raw

# Les jobs qui ecrivent dans un bind mount (entrainement, rapports) doivent
# tourner avec l'uid de l'utilisateur courant, sinon l'utilisateur non root
# de l'image ne peut pas creer les fichiers et le job echoue en
# `Permission denied`. Exporte dans l'environnement lu par compose.
export HOST_UID := $(shell id -u 2>/dev/null || echo 1000)
export HOST_GID := $(shell id -g 2>/dev/null || echo 1000)
  # Superset et ses deux jobs d'init declarent un `build:` propre : les
  # construire avec le seul `docker-compose.yml` echouerait sur une image
  # manquante.
  DOCKER_BUILD  := $(COMPOSE_STACK) build

.PHONY: help
help: ## Affiche cette aide
	@echo ""
	@echo "PrediCare TPA - commandes disponibles"
	@echo "----------------------------------------"
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""

# =============================================================================
# DEMARRAGE
# =============================================================================
.PHONY: doctor
doctor: ## Verifie que la machine est prete (a lancer avant une demonstration)
	@scripts/doctor.sh

.PHONY: setup
setup: ## Cree le .env et genere les secrets manquants
	@scripts/bootstrap.sh

.PHONY: secrets
secrets: ## Regenere les secrets cryptographiques du .env
	@scripts/bootstrap.sh --secrets-only

.PHONY: up
up: ## Demarre toute la plateforme, tooling de demonstration inclus
	@scripts/bootstrap.sh
	@$(MAKE) --no-print-directory build
	# Une seule invocation `compose` pour le core ET les overlays. Avant, les
	# overlays demarraient par des `make up-*` separes : leurs `depends_on`
	# vers le core (superset -> db: service_healthy) ne pouvaient etre resolus
	# que par le hasard de l'ordre de lancement. Ici Compose orchestre tout.
	@$(COMPOSE_STACK) up -d db redis
	# `migrate` passe par `run --rm` et non par `up -d`.
	#
	# `up -d` NE RELANCE PAS un one-shot deja sorti : Compose le reutilise tant
	# que son `config-hash` correspond, et ce hash couvre la definition du
	# service (YAML, image, environnement) -- pas le contenu de ./db/migrations,
	# monte en lecture seule. Une migration ajoutee apres le premier demarrage
	# restait donc jamais appliquee, sans erreur : `migrate` sortait en 0 et
	# `make wait` concluait que tout allait bien sur un schema perime.
	#
	# `run --rm` cree un conteneur neuf a chaque fois : le bug ne peut plus
	# revenir, et l'ordre reste garanti avant les API (qui dependent de
	# `service_completed_successfully`).
	@$(COMPOSE_STACK) run --rm migrate
	@$(COMPOSE_STACK) up -d
	@$(MAKE) --no-print-directory wait
	# Amorçage n8n : installe les workflows absents sans jamais remplacer
	# ceux deja presents dans l'interface. Sans proprietaire (tout premier
	# demarrage), le script l'explique et rend la main sans erreur.
	@bash scripts/n8n-import.sh --if-missing
	@echo ""
	@echo "Plateforme demarree : http://localhost:$${GATEWAY_PORT:-8080}"
	@echo "  Superset   http://localhost:$${SUPERSET_PORT:-8088}"
	@echo "  Grafana    http://localhost:$${GRAFANA_PORT:-3001}"
	@echo "  Prometheus http://localhost:$${PROMETHEUS_PORT:-9090}"
	@echo "  MLflow     http://localhost:$${MLFLOW_PORT:-5000}"

.PHONY: start
start: ## Demarre SANS reconstruire les images (apres un make down)
	@echo "Images existantes reutilisees : aucune reconstruction."
	@echo "Si tu as modifie du code, lance 'make up' pour reconstruire."
	@scripts/bootstrap.sh
	@$(COMPOSE_STACK) up -d db redis
	@$(COMPOSE_STACK) run --rm migrate
	@$(COMPOSE_STACK) up -d
	@$(MAKE) --no-print-directory wait
	@bash scripts/n8n-import.sh --if-missing
	@echo ""
	@echo "Plateforme demarree : http://localhost:$${GATEWAY_PORT:-8080}"

.PHONY: up-light
up-light: ## Demarre le NOYAU seul, sans Superset/Grafana/Prometheus/MLflow
	@echo "Demarrage minimal (noyau applicatif uniquement)."
	@echo "Si un service de demonstration manque, repasser par 'make start'."
	@scripts/bootstrap.sh
	@$(COMPOSE_CORE) up -d db redis
	@$(COMPOSE_CORE) run --rm migrate
	@$(COMPOSE_CORE) up -d
	@$(MAKE) --no-print-directory wait
	@bash scripts/n8n-import.sh --if-missing
	@echo ""
	@echo "Noyau demarre : http://localhost:$${GATEWAY_PORT:-8080}"

.PHONY: build
build: ## Construit les images sans demarrer
	@$(DOCKER_BUILD)

.PHONY: wait
wait: ## Attend que tous les services soient sains
	@scripts/wait-for-services.sh

.PHONY: down
down: ## Arrete la plateforme (les donnees sont conservees)
	@$(COMPOSE_ALL) down --remove-orphans

.PHONY: clean
clean: ## Arrete tout ET supprime les volumes (donnees perdues)
	@echo "Cette commande SUPPRIME les donnees. Confirmation attendue."
	@read -p "Taper 'oui' pour confirmer : " reponse; \
		if [ "$$reponse" = "oui" ]; then \
			$(COMPOSE_ALL) down -v --remove-orphans; \
			echo "Volumes supprimes."; \
		else \
			echo "Annule."; \
		fi

.PHONY: restart
restart: down start ## Redemarre SANS reconstruire (utilise `make restart up` apres une modif. de code)

# =============================================================================
# PROFILS OPTIONNELS
# =============================================================================
.PHONY: up-bi
up-bi: ## Demarre le pilotage decisionnel (Superset, ~900 Mo)
	@$(COMPOSE_BI) build superset
	@$(COMPOSE_BI) up -d superset superset-init superset-import
	@scripts/attendre-http.sh "http://localhost:$${SUPERSET_PORT:-8088}/health" 180 "Superset"
	@echo "Superset : http://localhost:$${SUPERSET_PORT:-8088}"

.PHONY: up-observability
up-observability: ## Demarre Prometheus et Grafana (~450 Mo)
	@$(COMPOSE_OBS) up -d prometheus grafana
	@echo "Grafana : http://localhost:$${GRAFANA_PORT:-3001}"

.PHONY: up-mlops
up-mlops: ## Demarre MLflow (~640 Mo)
	# `minio-init` n'est plus demande : les artefacts MLflow vivent sur le
	# volume local `./artifacts/mlflow` (`--default-artifact-root`), pas dans un
	# stockage objet. Citer un service inexistant faisait echouer la cible.
	@$(COMPOSE_MLOPS) up -d mlflow
	@echo "MLflow : http://localhost:$${MLFLOW_PORT:-5000}"

.PHONY: up-backup
up-backup: ## Demarre la sauvegarde quotidienne (~96 Mo)
	@$(COMPOSE_OPS) up -d backup

.PHONY: up-workers
up-workers: ## Demarre les workers d'ingestion et d'indexation (~1,1 Go)
	@$(COMPOSE_WORKERS) up -d worker-ingest worker-ai
	@echo "Workers demarres."

.PHONY: up-email
up-email: ## Demarre la boite mail de developpement (~96 Mo)
	@$(COMPOSE_EMAIL) up -d mailpit
	@echo "Mailpit : http://localhost:$${MAILPIT_UI_PORT:-8025}"

.PHONY: up-all
up-all: ## Tout demarrer, bac a sable Mailpit et cron backup inclus
	@$(COMPOSE_ALL) up -d --remove-orphans
	@$(MAKE) --no-print-directory wait

# =============================================================================
# QUALITE
# =============================================================================
.PHONY: sync
sync: ## Installe les dependances Python (workspace uv complet)
	@uv sync --frozen --all-packages

.PHONY: lint
lint: ## Verifie le style et les erreurs statiques
	@$(PY) ruff check .
	@$(PY) ruff format --check .
	@echo "Lint OK"

.PHONY: format
format: ## Corrige automatiquement le style
	@$(PY) ruff check . --fix
	@$(PY) ruff format .

.PHONY: typecheck
typecheck: ## Verifie les types
	@$(PY) mypy packages apps

.PHONY: test
test: ## Lance la suite de tests
	@$(PY) pytest

.PHONY: test-cov
test-cov: ## Lance les tests avec le rapport de couverture
	@$(PY) pytest --cov --cov-report=term-missing --cov-report=html

.PHONY: export-requirements
export-requirements: ## Exporte les versions pip depuis uv.lock (non versionne)
	@uv export --frozen --no-dev --all-packages --no-hashes \
		--output-file requirements.lock \
		--comment "Genere depuis uv.lock par `make export-requirements`. NE PAS INSTALLER : \
		utilisez uv sync --frozen, qui fige aussi les dependances transitives."
	@echo "requirements.lock ecrit. Ne pas le commiter : uv.lock reste la source de verite."

.PHONY: check
check: lint typecheck test readme bi ## Les verifications de la CI

.PHONY: bi
bi: ## Verifie que les vues de la couche semantique compilent
	@for f in db/bi/views/*.sql; do \
		docker compose exec -T db psql -v ON_ERROR_STOP=1 -q \
			-U $${POSTGRES_USER:-predicare} -d $${POSTGRES_DB:-predicare} < "$$f" >/dev/null \
			&& echo "  OK  $$f"; \
	done
	@echo "  Vues BI : $$(ls db/bi/views/*.sql | wc -l) fichier(s) applique(s)."

.PHONY: bi-graphiques
bi-graphiques: ## Verifie que chaque graphique rend une requete reussie
	@uv run python ops/superset/verifier_graphiques.py

.PHONY: readme
readme: ## Verifie que le README documente exactement les commandes de make help
	@python3 scripts/check_readme_commandes.py

# =============================================================================
# EXPLOITATION
# =============================================================================
.PHONY: logs
logs: ## Suit les journaux de la plateforme
	@$(COMPOSE_CORE) logs -f --tail=100

.PHONY: logs-service
logs-service: ## Suit les journaux d'un service (make logs-service S=api-core)
	@$(COMPOSE_ALL) logs -f --tail=100 $(S)

.PHONY: ps
ps: ## Etat des conteneurs, tous profils confondus
	@$(COMPOSE_ALL) ps

.PHONY: health
health: ## Etat de sante de chaque service
	@scripts/check-health.sh

.PHONY: smoke
smoke: ## Parcours de verification de bout en bout
	@scripts/smoke-test.sh

.PHONY: backup
backup: ## Lance une sauvegarde immediate
	@$(COMPOSE_OPS) exec -T backup /backup/pg_dump.sh

.PHONY: restore
restore: ## Restaure la derniere sauvegarde (demande confirmation)
	@$(COMPOSE_OPS) exec -T backup /backup/pg_restore.sh

.PHONY: backups
backups: ## Liste les sauvegardes disponibles
	@ls -lh backups/ 2>/dev/null || echo "Aucune sauvegarde (repertoire vide)"

.PHONY: migrate
migrate: ## Applique les migrations en attente
	@$(COMPOSE_CORE) run --rm migrate

.PHONY: db-status
db-status: ## Compare la version du schema en base et celle attendue par le code
	@scripts/db-status.sh

.PHONY: reload-data
reload-data: ## Recharge les donnees depuis ./data/raw et reapplique la couche BI
	@$(COMPOSE_CORE) up -d db
	@$(COMPOSE_CORE) run --rm seed
	@bash db/bi/load.sh

.PHONY: comptes
comptes: ## Cree les quatre comptes de demonstration (mot de passe: DEMO_PASSWORD)
	@$(COMPOSE_CORE) run --rm -e DEMO_PASSWORD="$${DEMO_PASSWORD:-}" seed \
		python -m predicare_seed.creer_comptes

.PHONY: seed-rag
seed-rag: ## Indexe le corpus de contrats PDF dans pgvector
	@$(COMPOSE_CORE) run --rm -e RAG_CORPUS_DIR="$${RAG_CORPUS_DIR:-/data/rag_corpus}" seed \
		python -m predicare_seed.ingest_rag --apply

.PHONY: shell-db
shell-db: ## Ouvre psql sur la base (ROLE=predicare_ro pour un acces lecture seule)
	@$(COMPOSE_CORE) exec db psql -U $${ROLE:-$${POSTGRES_USER:-predicare}} -d $${POSTGRES_DB:-predicare}

# Exécute une requête ou un fichier SQL.
#
#   make db-sql Q="SELECT count(*) FROM core.facture"
#   make db-sql FILE=analyse.sql
#   cat rapport.sql | make db-sql
#
# `Q=` et non un argument positionnel : Make prend le premier argument comme
# un nom de cible, donc `make db-sql "SELECT 1"` echoue sur « Aucune règle pour
# fabriquer la cible » apres avoir pourtant execute la requete.
#
# Le fichier est lu par l'HOST puis envoye sur l'entree standard, et non par
# `psql -f` : le fichier est sur la machine du developpeur, pas dans le
# conteneur, et `psql -f` le chercherait a l'interieur.
#
# `ON_ERROR_STOP=1` n'est pas décoratif : sans lui, psql émule le shell et
# continue après une erreur en renvoyant 0. Un script à moitié appliqué
# paraîtrait alors réussi.
#
# `ROLE=predicare_ro` bascule vers le compte en lecture seule, ce qui permet de
# vérifier sur un cas réel que le moindre privilège s'applique bien.
FILE ?=
Q ?=
ROLE ?=
PSQL_DB = $(COMPOSE_CORE) exec -T db psql -v ON_ERROR_STOP=1 -U $${ROLE:-$${POSTGRES_USER:-predicare}} -d $${POSTGRES_DB:-predicare}

.PHONY: db-sql
db-sql: ## Execute une requete SQL (Q="...") ou un fichier (FILE=...), ou lit stdin
	@if [ -n "$(FILE)" ]; then \
		if [ ! -r "$(FILE)" ]; then echo "Fichier SQL introuvable : $(FILE)" >&2; exit 1; fi; \
		$(PSQL_DB) < "$(FILE)"; \
	elif [ -n "$(Q)" ]; then \
		printf '%s\n' "$(Q)" | $(PSQL_DB); \
	else \
		$(PSQL_DB); \
	fi

# =============================================================================
# MODELE
# =============================================================================
.PHONY: model-state
model-state: ## Affiche la version active et le seuil courant
	@curl -fsS http://localhost:$${API_INFERENCE_PORT:-8002}/api/inference/modele | $(PY) python -m json.tool

.PHONY: threshold
threshold: ## Change le seuil d'alerte (make threshold VALEUR=0.75)
	@curl -fsS -X PUT http://localhost:$${API_CORE_PORT:-8001}/api/core/admin/seuil \
		-H "Content-Type: application/json" \
		-H "Authorization: Bearer $${ADMIN_TOKEN}" \
		-d '{"seuil": $(VALEUR), "motif": "changement manuel (make threshold)"}' | $(PY) python -m json.tool

.PHONY: train
train: ## Entraine le modele et ecrit models/$(VERSION) (make train VERSION=2)
	@if [ ! -f "$(DATA_DIR)/factures.csv" ]; then \
		echo "Donnees absentes dans $(DATA_DIR)/."; \
		echo "Copiez les 14 CSV de l'encadrement, puis relancez : make train VERSION=$${VERSION:-1}"; \
		exit 1; \
	fi
	@$(COMPOSE_CORE) run --rm -e MODEL_VERSION=$(or $(VERSION),1) train
	@echo "Modele ecrit dans models/$(or $(VERSION),1)"
	@echo "Activez-le sans redemarrage : make model-promote VERSION=$(or $(VERSION),1)"

.PHONY: evaluate
evaluate: ## Compare SMOTE / scale_pos_weight et produit l'audit d'equite (make evaluate)
	@if [ ! -f "$(DATA_DIR)/factures.csv" ]; then \
		echo "Donnees absentes dans $(DATA_DIR)/."; \
		echo "Copiez les 14 CSV de l'encadrement, puis relancez : make evaluate"; \
		exit 1; \
	fi
	@$(COMPOSE_CORE) run --rm evaluate

.PHONY: noter
noter: ## Note en lot les factures historiques pour peupler ml.prediction (make noter LIMITE=500)
	@$(COMPOSE_CORE) run --rm noter \
		python -m predicare_inference_api.noter \
		$(if $(LIMITE),--limite $(LIMITE),) \
		$(if $(REFERENCE),--reference $(REFERENCE),) \
		$(if $(STATUT),--statut $(STATUT),) \
		$(if $(DEPUIS),--depuis $(DEPUIS),) \
		$(if $(DRY_RUN),--dry-run,) \
		$(if $(RESCORER),--rescorer,) \
		$(ARGS)

.PHONY: lot-jury
lot-jury: ## Soumet le lot de 20 factures inedites du CDC (F17) par l'API
	@$(COMPOSE_CORE) run --rm \
		-e DEMO_PASSWORD="$${DEMO_PASSWORD:-}" \
		-e API_CORE_URL="http://api-core:8001" \
		seed python -m predicare_seed.lot_jury $(ARGS)

.PHONY: model-promote
model-promote: ## Bascule la version N en service (make model-promote VERSION=2)
	@curl -fsS -X POST "http://localhost:$${API_INFERENCE_PORT:-8002}/api/inference/modele/candidat?version=$(VERSION)" \
		| $(PY) python -m json.tool
	@curl -fsS -X POST http://localhost:$${API_INFERENCE_PORT:-8002}/api/inference/modele/bascule \
		| $(PY) python -m json.tool

.PHONY: model-rollback
model-rollback: ## Revient a la version N (make model-rollback VERSION=1)
	@curl -fsS -X POST "http://localhost:$${API_INFERENCE_PORT:-8002}/api/inference/modele/retour-arriere?version=$(VERSION)" \
		| $(PY) python -m json.tool

# =============================================================================
# N8N
# =============================================================================
# La fiche d'accès sort du dépôt : elle est écrite à côté du CDC et du plan
# d'action, dans un dossier hors de Git. Aucun secret n'entre donc jamais
# dans l'historique, et il n'y a pas de règle d'exclusion à maintenir.
ACCES_DIR ?= /home/jerry/Documents/predicare
ACCES_FILE ?= $(ACCES_DIR)/ACCES_PREDICARE.md

.PHONY: acces
acces: ## Genere la fiche d'identifiants (hors depot, mode 600)
	@scripts/generate-access-file.sh

.PHONY: n8n-compte
n8n-compte: ## Affiche le compte n8n de cette machine (et la procedure s'il n'existe pas)
	@scripts/n8n-compte.sh

.PHONY: n8n-export
n8n-export: ## Exporte les workflows n8n dans apps/n8n/workflows/
	@scripts/n8n-export.sh

.PHONY: n8n-import
n8n-import: ## Restaure et reactive les workflows n8n
	@scripts/n8n-import.sh