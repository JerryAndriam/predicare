#!/usr/bin/env bash
# =============================================================================
# Attend qu'une URL reponde en succes HTTP
# -----------------------------------------------------------------------------
# Usage : attendre-http.sh <url> <delai-max-secondes> <libelle>
#
# Necessaire pour les services lents dont le compose ne connait pas la sante
# avant le premier demarrage (Superset prepare sa base de metadonnees avant
# d'accepter une connexion). Sans cette attente, `make up-bi` annonce une
# URL que le visiteur decouvre en erreur.
# =============================================================================

set -uo pipefail

URL="${1:-}"
DELAI_MAX="${2:-120}"
LIBELLE="${3:-service}"
INTERVALLE=3
ATTENTE=0

while [ "$ATTENTE" -lt "$DELAI_MAX" ]; do
    if curl -fsS --max-time 5 "$URL" >/dev/null 2>&1; then
        printf '\033[32m  [OK]\033[0m   %s repond\n' "$LIBELLE"
        exit 0
    fi
    sleep "$INTERVALLE"
    ATTENTE=$((ATTENTE + INTERVALLE))
done

printf '\033[31m  [KO]\033[0m   %s ne repond pas sur %s apres %ss\n' "$LIBELLE" "$URL" "$DELAI_MAX" >&2
exit 1
