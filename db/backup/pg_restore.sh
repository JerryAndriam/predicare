#!/bin/sh
# =============================================================================
# Restauration d'une sauvegarde PostgreSQL
# -----------------------------------------------------------------------------
# Usage : make restore            (derniere sauvegarde)
#         make restore FILE=...   (sauvegarde precise)
#
# L'action est IRREVERSIBLE : la base courante est remplacee. Le script
# demande une confirmation explicite, sauf en mode automate
# (RESTORE_FORCE=1), utilise par les tests d'exploitation.
# =============================================================================

set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
FILE="${FILE:-}"
FORCE="${RESTORE_FORCE:-0}"
TARGET_DB="${TARGET_DB:-predicare}"

log() {
    echo "[restore $(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
}

CLE="${BACKUP_CLE_FILE:-/run/secrets/backup_key}"

if [ -z "${FILE}" ]; then
    FILE="$(ls -1t "${BACKUP_DIR}"/predicare_*.sql.gz.enc 2>/dev/null | head -n 1 || true)"
    if [ -z "${FILE}" ]; then
        FILE="$(ls -1t "${BACKUP_DIR}"/predicare_*.sql.gz 2>/dev/null | head -n 1 || true)"
    fi
fi

if [ -z "${FILE}" ] || [ ! -f "${FILE}" ]; then
    log "ECHEC : aucune sauvegarde trouvee dans ${BACKUP_DIR}"
    log "Sauvegardes disponibles :"
    ls -lh "${BACKUP_DIR}" 2>/dev/null || log "  (dossier vide ou inaccessible)"
    exit 1
fi

log "Fichier retenu : ${FILE}"

if [ "${FORCE}" != "1" ]; then
    printf "Cette operation REMPLACE la base '%s'. Confirmer ? [oui/N] " "${TARGET_DB}"
    read -r reponse
    case "${reponse}" in
        oui|OUI|Oui|yes|Y|y) ;;
        *)
            log "Annule."
            exit 1
            ;;
    esac
fi

# Sauvegarde de securite avant ecrasement : une restauration est reversible
# tant que l'etat anterieur est conserve.
SECURITE="${BACKUP_DIR}/avant_restore_$(date +%Y%m%d_%H%M%S).sql.gz"
log "Sauvegarde de securite avant restauration : ${SECURITE}"
pg_dump --clean --if-exists --no-owner --no-privileges | gzip -9 > "${SECURITE}"

log "Restauration en cours..."
case "${FILE}" in
    *.enc)
        if [ ! -f "${CLE}" ]; then
            log "ECHEC : sauvegarde chiffree, mais aucune cle (${CLE})"
            exit 1
        fi
        DECHIFFRE="openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass file:${CLE}"
        ;;
    *)
        DECHIFFRE="cat"
        ;;
esac

if ${DECHIFFRE} "${FILE}" 2>/dev/null | gzip -dc | psql -d "${TARGET_DB}" -v ON_ERROR_STOP=1 -q; then
    log "Restauration reussie"
else
    log "ECHEC de la restauration. La sauvegarde de securite est dans ${SECURITE}"
    exit 1
fi

# Verification : on recompte les tables metier. Restaurer une base vide sans
# s'en apercevoir est le piege classique.
TABLES="$(psql -d "${TARGET_DB}" -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema IN ('core','ml','audit')")"
log "Tables presentes apres restauration : ${TABLES}"

if [ "${TABLES}" -lt 10 ]; then
    log "ALERTE : moins de 10 tables, la restauration est probablement incomplete"
    exit 1
fi

log "Fin"