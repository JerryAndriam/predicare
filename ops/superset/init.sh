#!/usr/bin/env bash
# =============================================================================
# Initialisation de la base de metadonnees Superset
# -----------------------------------------------------------------------------
# Job unique, execute une seule fois (le compose le lance puis n'insiste pas).
# Deux etapes, dans cet ordre imperatif :
#
#   1. `superset db upgrade` cree ou met a jour le schema des metadonnees.
#      Sans cette etape, `create-admin` echoue sur des tables absentes.
#   2. `superset fab create-admin` cree le compte d'administration.
#
# Le script est dans un fichier plutot que dans le YAML du compose : les
# chevauchements de guillemets entre YAML, Compose et bash rendent le
# script inline illisible, et une erreur s'y glisse silencieusement.
#
# Ce que ce script ne fait PAS : enregistrer les datasets. C'est le role du
# job `superset-import`, qui s'execute apres celui-ci.
# =============================================================================

set -euo pipefail

log() { printf '\033[36m[superset-init]\033[0m %s\n' "$*"; }

: "${SUPERSET_ADMIN_USERNAME:=admin}"
: "${SUPERSET_ADMIN_PASSWORD:?SUPERSET_ADMIN_PASSWORD est obligatoire}"

log "Mise a jour du schema des metadonnees Superset..."
superset db upgrade
log "  schema a jour"

log "Creation du compte d'administration '${SUPERSET_ADMIN_USERNAME}'..."

# Si le compte existe deja (relancement du job), on ne le recree pas : la
# commande echouerait, et le job serait vu en echec alors que tout va bien.
DEJA_EXISTANT="$(superset fab list-users 2>/dev/null | grep -c "${SUPERSET_ADMIN_USERNAME}" || true)"

if [ "${DEJA_EXISTANT}" -ge 1 ]; then
    log "  compte deja present, rien a faire"
else
    superset fab create-admin \
        --username "${SUPERSET_ADMIN_USERNAME}" \
        --firstname PrediCare \
        --lastname Admin \
        --email admin@predicare.local \
        --password "${SUPERSET_ADMIN_PASSWORD}"
    log "  compte cree"
fi

log "Termine."