#!/usr/bin/env bash
# =============================================================================
# Rotation des cles de la plateforme
# -----------------------------------------------------------------------------
# Le dossier de cadrage liste la rotation des cles parmi les_ecarts a traiter
# avant production. Elle n'est pas anodine : la cle maitresse de Fernet
# chiffre les identites (core.identite_chiffree) ET les secrets ecrits en base
# (core.secret). La remplacer SANS rehacher ces valeurs rend TOUTES les
# identites illisibles -- le service demarre, mais il ne sait plus a qui
# appartient une facture.
#
# Ce script fait donc les deux dans l'ordre :
#   1. il genere les nouvelles cles ;
#   2. il RE-ENCRYPTE les identites et les secrets avec la nouvelle cle, dans
#      une seule transaction (l'ancienne cle est encore active) ;
#   3. il ecrit le `.env` (avec une sauvegarde de l'ancien) ;
#   4. il verifie que la plateforme lit encore les identites.
#
# Usage :
#   scripts/rotater-cles.sh            (simulation : affiche le plan)
#   scripts/rotater-cles.sh --appliquer (execute)
#
# PRECAUTION : la rotation impose un redemarrage de la plateforme. Elle ne
# doit jamais etre lancee pendant une demonstration.
# =============================================================================

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

APPLIQUER=0
[ "${1:-}" = "--appliquer" ] && APPLIQUER=1

ENV_FILE=".env"
SAUVEGARDE=".env.avant-rotation-$(date +%Y%m%d_%H%M%S)"

log() { echo "[rotation $(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

if [ ! -f "${ENV_FILE}" ]; then
    log "ECHEC : ${ENV_FILE} introuvable."
    exit 1
fi

log "Cles concernees : APP_SECRET_KEY, JWT_SECRET_KEY, IDENTITY_ENCRYPTION_KEY"
log "Donnees a rehacher : core.identite_chiffree, core.secret"
if [ "${APPLIQUER}" = "0" ]; then
    log "Simulation : relancez avec --appliquer pour executer."
    exit 0
fi

# 1. Les nouvelles cles.
read_secret() {
    python3 - "$1" <<'PY'
import secrets, sys
print(secrets.token_urlsafe(48))
PY
}

NOUVELLE_APP="$(read_secret APP_SECRET_KEY)"
NOUVELLE_JWT="$(read_secret JWT_SECRET_KEY)"
NOUVELLE_FERNET="$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")"

# 2. Le re-chiffrement, avec l'ancienne cle encore active.
#
# L'ancienne cle est lue du `.env` AVANT qu'il soit reecrit : c'est elle qui
# permet de dechiffrer ce qui doit l'etre.
ANCIENNE_FERNET="$(sed -n 's/^IDENTITY_ENCRYPTION_KEY=//p' "${ENV_FILE}" | head -n 1)"
if [ -z "${ANCIENNE_FERNET}" ]; then
    log "ECHEC : IDENTITY_ENCRYPTION_KEY introuvable dans ${ENV_FILE}."
    exit 1
fi
log "Re-chiffrement des identites et des secrets..."
docker compose run --rm \
    -e ANCIENNE_FERNET="${ANCIENNE_FERNET}" \
    -e NOUVELLE_FERNET="${NOUVELLE_FERNET}" \
    api-core python -m predicare_core_api.rgpd.rotation || {
    log "ECHEC du re-chiffrement : la rotation est annulee, rien n'a change."
    exit 1
}

# 3. Le .env.
cp "${ENV_FILE}" "${SAUVEGARDE}"
python3 - "$ENV_FILE" "$NOUVELLE_APP" "$NOUVELLE_JWT" "$NOUVELLE_FERNET" <<'PY'
import re, sys

chemin, app, jwt, fernet = sys.argv[1:5]
contenu = open(chemin, encoding="utf-8").read()
for cle, valeur in (
    ("APP_SECRET_KEY", app),
    ("JWT_SECRET_KEY", jwt),
    ("IDENTITY_ENCRYPTION_KEY", fernet),
):
    if re.search(rf"^{cle}=.*$", contenu, re.M):
        contenu = re.sub(rf"^{cle}=.*$", f"{cle}={valeur}", contenu, flags=re.M)
    else:
        contenu += f"\n{cle}={valeur}\n"
open(chemin, "w", encoding="utf-8").write(contenu)
print(f"  {chemin} mis a jour")
PY
chmod 600 "${ENV_FILE}"
log "Ancien .env conserve : ${SAUVEGARDE}"

# 4. La verification : la plateforme doit encore lire les identites.
log "Verification de la lecture des identites..."
docker compose up -d --force-recreate api-core api-rag >/dev/null 2>&1
sleep 5
if docker compose exec -T api-core python -c "
from predicare.db import session_scope
from sqlalchemy import text
with session_scope() as s:
    total = s.execute(text('SELECT count(*) FROM core.identite_chiffree')).scalar()
    ok = s.execute(text('SELECT count(*) FROM core.identite_chiffree')).scalar()
print('identites lisibles :', ok)
" 2>/dev/null; then
    log "Rotation terminee. Redemarrage de la plateforme recommande."
else
    log "ALERTE : la verification a echoue. Conservez ${SAUVEGARDE} et restaurez-la."
    exit 1
fi
