#!/usr/bin/env bash
# =============================================================================
# Export des workflows n8n vers Git
# -----------------------------------------------------------------------------
# L'interface n8n est la source de verite : ce script ne fait que copier son
# etat vers `apps/n8n/workflows/`, pour que le livrable « workflows n8n
# importables (.json) » soit versionne.
#
# On exporte via la CLI n8n et non via son API REST : l'API exige une cle
# creee a la main dans l'interface. L'export CLI fonctionne des la premiere
# minute, sans configuration.
#
# Les CREDENTIALS ne sont PAS exportes : elles contiennent le webhook Slack
# et la cle LLM. La procedure manuelle, chiffree, est decrite dans
# apps/n8n/credentials/README.md.
# =============================================================================

set -uo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RACINE"

CONTENEUR="predicare-n8n"
CIBLE="${RACINE}/apps/n8n/workflows"
DANS_CONTENEUR="/tmp/workflows-export"
# `--output` attend un FICHIER, pas un repertoire : passer un repertoire
# echoue avec « must be a writeable file », sans message plus explicite.
SORTIE_CONTENEUR="/tmp/workflows-export/export.json"

log() { printf '\033[36m[n8n-export]\033[0m %s\n' "$*"; }
err() { printf '\033[31m[n8n-export]\033[0m %s\n' "$*" >&2; }

if ! docker inspect "$CONTENEUR" >/dev/null 2>&1; then
    err "Le conteneur n8n n'existe pas. Lancez d'abord : make up"
    exit 1
fi

ETAT=$(docker inspect -f '{{.State.Status}}' "$CONTENEUR" 2>/dev/null || echo absent)
if [ "$ETAT" != "running" ]; then
    err "n8n n'est pas en marche (etat : $ETAT). Lancez : make up"
    exit 1
fi

mkdir -p "$CIBLE"

log "Export des workflows via la CLI n8n"
docker exec "$CONTENEUR" rm -rf "$DANS_CONTENEUR" >/dev/null 2>&1
docker exec "$CONTENEUR" mkdir -p "$DANS_CONTENEUR" >/dev/null 2>&1

SORTIE=$(docker exec "$CONTENEUR" n8n export:workflow --all --output="$SORTIE_CONTENEUR" 2>&1)
if ! printf '%s' "$SORTIE" | grep -qi "successfully exported"; then
    # 0 workflow exporte : c'est normal au premier lancement.
    if printf '%s' "$SORTIE" | grep -qi "0 workflows"; then
        log "Aucun workflow dans n8n. Construisez-le dans l'interface, puis relancez."
        exit 0
    fi
    err "L'export a echoue :"
    printf '%s\n' "$SORTIE" | tail -5 >&2
    exit 1
fi

# `n8n export:workflow` ecrit un unique tableau JSON contenant tous les
# workflows : on le decompose pour que chacun soit son propre fichier,
# versionnable et lisible en revue de code.
if ! docker exec "$CONTENEUR" cat "$SORTIE_CONTENEUR" 2>/dev/null \
    | python3 "$RACINE/scripts/split_workflows.py" "$CIBLE"; then
    err "Aucun workflow n'a pu etre decompose."
    exit 1
fi

NB_FICHIERS=$(find "$CIBLE" -name '*.json' -type f | wc -l)
log "$NB_FICHIERS workflow(s) dans apps/n8n/workflows/"

# Garde-fou : refuse d'ecrire un fichier contenant un secret. Un webhook
# Slack ou une cle d'API dans un JSON versionne reste dans l'historique Git
# meme apres un `git rm` ulterieur.
if grep -rlE 'hooks\.slack\.com|sk-[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}' "$CIBLE" 2>/dev/null | grep -q .; then
    err "ALERTE : un secret semble avoir ete in-line dans un workflow."
    grep -rlE 'hooks\.slack\.com|sk-[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}' "$CIBLE"
    err "Remplacez la valeur par une credential n8n, puis relancez l'export."
    exit 1
fi

log "Termine. Verifiez le diff puis commitez apps/n8n/workflows/."