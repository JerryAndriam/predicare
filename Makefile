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

COMPOSE_WORKERS := $(COMPOSE) --profile workers -f docker-compose.yml
COMPOSE_EMAIL   := $(COMPOSE) --profile email -f docker-compose.yml

PY           := uv run --all-packages
DOCKER_BUILD  := $(COMPOSE_CORE) build

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
up: ## Demarre toute la plateforme (commande du jury)
	@scripts/bootstrap.sh
	@$(MAKE) --no-print-directory build
	# PAS de --remove-orphans ici : cette option supprime tout conteneur qui
	# n'est pas dans le compose principal, donc les services des overlays
	# (Superset, Prometheus, Grafana, MLflow) lancés par un `make up-*`.
	# Les orphelins ne se nettoient que par `make down`.
	@$(COMPOSE_CORE) up -d
	@$(MAKE) --no-print-directory wait
	@echo ""
	@echo "Plateforme demarree : http://localhost:$${GATEWAY_PORT:-8080}"

.PHONY: start
start: ## Demarre SANS reconstruire les images (apres un make down)
	@echo "Images existantes reutilisees : aucune reconstruction."
	@echo "Si tu as modifie du code, lance 'make up' pour reconstruire."
	@scripts/bootstrap.sh
	# PAS de --remove-orphans, pour la meme raison que `up` : cette option
	# supprimerait les services des overlays (Superset, Grafana, MLflow).
	@$(COMPOSE_CORE) up -d
	@$(MAKE) --no-print-directory wait
	@echo ""
	@echo "Plateforme demarree : http://localhost:$${GATEWAY_PORT:-8080}"

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
	@$(COMPOSE_MLOPS) up -d mlflow minio-init
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
up-all: ## Demarre la plateforme complete, profils compris
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
check: lint typecheck test ## Les trois verifications de la CI

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
migrate: ## Applique les migrations de base
	@$(COMPOSE_CORE) run --rm migrate

.PHONY: reload-data
reload-data: ## Recharge les donnees depuis ./data/raw
	@$(COMPOSE_CORE) up -d db
	@$(COMPOSE_CORE) run --rm seed

.PHONY: shell-db
shell-db: ## Ouvre psql sur la base PrediCare
	@$(COMPOSE_CORE) exec db psql -U $${POSTGRES_USER:-predicare} -d $${POSTGRES_DB:-predicare}

# =============================================================================
# MODELE
# =============================================================================
.PHONY: model-state
model-state: ## Affiche la version active et le seuil courant
	@curl -fsS http://localhost:$${API_INFERENCE_PORT:-8002}/modele | $(PY) python -m json.tool

.PHONY: threshold
threshold: ## Change le seuil d'alerte (make threshold VALEUR=0.75)
	@curl -fsS -X PUT http://localhost:$${API_CORE_PORT:-8001}/api/core/admin/seuil \
		-H "Content-Type: application/json" \
		-H "Authorization: Bearer $${ADMIN_TOKEN}" \
		-d '{"seuil": $(VALEUR), "motif": "changement manuel (make threshold)"}' | $(PY) python -m json.tool

.PHONY: train
train: ## Lance l'entrainement du modele (make train VERSION=2)
	@echo "Entrainement du modele version $(or $(VERSION),2) - voir apps/ml-training/README.md"

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