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

# `superset init` synchronise les roles (Admin, Alpha, Gamma) ET leurs
# permissions sur les vues declarees par l'application.
#
# Son absence ne rappelait sur rien au premier lancement : le compte admin
# etait cree, l'interface s'ouvrait, et l'API repondait « Forbidden » sur
# `/api/v1/dataset/` parce que le role Admin n'avait literally aucune
# permission. Un role sans permission est indistinguishable d'un role
# refuse, et rien dans les journaux du conteneur ne le signalait.
superset init
log "  roles et permissions synchronises"

log "Creation du compte d'administration '${SUPERSET_ADMIN_USERNAME}'..."

# Si le compte existe deja (relancement du job), on ne le recree pas : la
# commande echouerait, et le job serait vu en echec alors que tout va bien.
DEJA_EXISTANT="$(superset fab list-users 2>/dev/null | grep -c "${SUPERSET_ADMIN_USERNAME}" || true)"

if [ "${DEJA_EXISTANT}" -ge 1 ]; then
    # Le compte existe deja : on ne le recree pas, mais on REAPPLIQUE le mot
    # de passe du `.env`. Le `.env` fait foi, et un compte cree lors d'un
    # lancement precedent peut porter un ancien secret. Sans cette remise a
    # niveau, les jobs qui parlent a l'API (dashboard, requetes, export)
    # repondent 401 « Not authorized » et le tableau de bord n'est jamais
    # applique -- alors que `make up` se termine sans erreur visible.
    superset fab reset-password \
        --username "${SUPERSET_ADMIN_USERNAME}" \
        --password "${SUPERSET_ADMIN_PASSWORD}"
    log "  compte deja present, mot de passe resynchronise depuis l'environnement"
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