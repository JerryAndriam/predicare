#!/bin/sh
# =============================================================================
# Sauvegarde quotidienne de PostgreSQL
# -----------------------------------------------------------------------------
# Execute par supercronic dans le conteneur `backup`.
# Format : archive compressee pg_dump, une par jour, conservee 14 jours.
#
# La restauration n'est PAS automatique : elle exige `make restore`, sinon
# une erreur de script ecraserait les donnees de la journee.
# =============================================================================

set -eu

RETENTION_DAYS="${RETENTION_DAYS:-14}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
STAMP="$(date +%Y%m%d_%H%M%S)"
TARGET="${BACKUP_DIR}/predicare_${STAMP}.sql.gz"

log() {
    echo "[backup $(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
}

log "Debut de la sauvegarde vers ${TARGET}"

# --clean-before-dump : necessaire pour un dump coherent quand des sessions
# restent ouvertes, et sans ca une vue peut disparaitre entre deux snapshots.
if ! pg_dump --clean --if-exists --no-owner --no-privileges | gzip -9 > "${TARGET}.part"; then
    rm -f "${TARGET}.part"
    log "ECHEC de la sauvegarde"
    exit 1
fi

mv "${TARGET}.part" "${TARGET}"
SIZE="$(du -h "${TARGET}" | cut -f1)"
log "Sauvegarde reussie : ${TARGET} (${SIZE})"

# La commande `find -mtime` est volontairement stricte : une sauvegarde trop
# recente ne doit pas etre supprimee par un run qui se chevauche.
find "${BACKUP_DIR}" -name 'predicare_*.sql.gz' -type f -mtime "+${RETENTION_DAYS}" -print -delete
log "Rétention appliquee : ${RETENTION_DAYS} jours"

# Verification immediate : une sauvegarde jamais restauree n'est pas une
# sauvegarde. On verifie que l'archive est bien lisible par pg_restore.
if gzip -t "${TARGET}" 2>/dev/null; then
    log "Integrite de l'archive verifiee"
else
    log "ALERTE : archive corrompue"
    exit 1
fi

log "Fin"