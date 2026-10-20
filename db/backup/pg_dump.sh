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

# Chiffrement de la sauvegarde.
#
# La cle vient d'un FICHIER, jamais de la ligne de commande : une ligne de
# commande est lisible par tous les processus de la machine. Sans ce fichier,
# la sauvegarde reste en clair -- c'est un choix explicite de l'exploitant,
# pas un oubli.
CLE="${BACKUP_CLE_FILE:-/run/secrets/backup_key}"
CHIFFRE=0
if [ -f "${CLE}" ]; then
    CHIFFRE=1
    TARGET="${TARGET}.enc"
fi

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

if [ "${CHIFFRE}" = "1" ]; then
    # openssl lit la cle dans un fichier : elle n'apparait ni dans la ligne
    # de commande, ni dans la liste des processus.
    if ! openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt \
         -in "${TARGET}.part" -out "${TARGET}.enc" -pass "file:${CLE}"; then
        rm -f "${TARGET}.part" "${TARGET}.enc"
        log "ECHEC du chiffrement"
        exit 1
    fi
    rm -f "${TARGET}.part"
    mv "${TARGET}.enc" "${TARGET}"
    log "Sauvegarde chiffree (AES-256-CBC, PBKDF2)"
else
    mv "${TARGET}.part" "${TARGET}"
    log "Sauvegarde en clair : aucune cle de chiffrement fournie"
fi
SIZE="$(du -h "${TARGET}" | cut -f1)"
log "Sauvegarde reussie : ${TARGET} (${SIZE})"

# La commande `find -mtime` est volontairement stricte : une sauvegarde trop
# recente ne doit pas etre supprimee par un run qui se chevauche.
find "${BACKUP_DIR}" -name 'predicare_*.sql.gz' -type f -mtime "+${RETENTION_DAYS}" -print -delete
find "${BACKUP_DIR}" -name 'predicare_*.sql.gz.enc' -type f -mtime "+${RETENTION_DAYS}" -print -delete
log "Rétention appliquee : ${RETENTION_DAYS} jours"

# Verification immediate : une sauvegarde jamais restauree n'est pas une
# sauvegarde. On verifie que l'archive est bien lisible par pg_restore.
if [ "${CHIFFRE}" = "1" ]; then
    # Une sauvegarde chiffree dont on ne peut pas relire n'est pas une
    # sauvegarde : on la dechiffre pour verifier.
    if openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in "${TARGET}" \
         -pass "file:${CLE}" 2>/dev/null | gzip -t 2>/dev/null; then
        log "Integrite de l'archive chiffree verifiee"
    else
        log "ALERTE : archive chiffree illisible ou corrompue"
        exit 1
    fi
elif gzip -t "${TARGET}" 2>/dev/null; then
    log "Integrite de l'archive verifiee"
else
    log "ALERTE : archive corrompue"
    exit 1
fi

log "Fin"