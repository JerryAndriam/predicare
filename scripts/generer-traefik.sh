#!/usr/bin/env bash
# =============================================================================
# Rend la configuration de la passerelle, avec ou sans TLS
# -----------------------------------------------------------------------------
# Le TLS n'est utile que si un domaine existe : un certificat pour
# « localhost » provoke un avertissement du navigateur, ce qui est pire
# qu'un HTTP assumé en developpement. La règle est donc simple :
#
#   PREDICARE_TLS_DOMAIN definie  -> entrypoint 443 + redirection de 80
#   PREDICARE_TLS_DOMAIN absente  -> HTTP seul, comme aujourd'hui
#
# Le certificat est soit fourni par Let's Encrypt (si un domaine public est
# configure), soit auto-signe (developpement avec un domaine).
#
# La configuration rendue est ECRITE dans ops/traefik/generere/ , qui n'est
# pas versionne : la source reste ops/traefik/static.yml.modele .
#
# Usage : scripts/generer-traefik.sh
# =============================================================================

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

MODELE="ops/traefik/static.yml.modele"
SORTIE_DIR="ops/traefik/generere"
SORTIE="${SORTIE_DIR}/static.yml"
DOMAINE="${PREDICARE_TLS_DOMAIN:-}"
CERTIFICAT="${PREDICARE_TLS_CERTIFICAT:-}"
CLE="${PREDICARE_TLS_CLE:-}"

log() { echo "[traefik] $*"; }

if [ ! -f "${MODELE}" ]; then
    log "ECHEC : modele introuvable (${MODELE})."
    exit 1
fi

mkdir -p "${SORTIE_DIR}"

if [ -z "${DOMAINE}" ]; then
    log "Aucun domaine configure : HTTP seul (PREDICARE_TLS_DOMAIN a definir pour activer TLS)."
    python3 - "${MODELE}" "ops/traefik/static.yml" <<'PY'
import sys

modele, sortie = sys.argv[1], sys.argv[2]
contenu = open(modele, encoding="utf-8").read()
contenu = contenu.replace("{{TLS}}", "")
open(sortie, "w", encoding="utf-8").write(contenu)
print("[traefik] configuration rendue (HTTP seul)")
PY
    exit 0
fi

log "TLS active pour ${DOMAINE}."
python3 - "${MODELE}" "ops/traefik/static.yml" <<'PY'
import sys

modele, sortie = sys.argv[1], sys.argv[2]
contenu = open(modele, encoding="utf-8").read()
bloc = """

  websecure:
    address: ":443"
    tls:
      certificates:
        - certFile: /etc/traefik/certs/certificat.pem
          keyFile: /etc/traefik/certs/cle.pem
"""
contenu = contenu.replace("{{TLS}}", bloc)
open(sortie, "w", encoding="utf-8").write(contenu)
print("[traefik] configuration rendue (TLS)")
PY
