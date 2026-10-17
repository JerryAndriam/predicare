#!/usr/bin/env bash
# =============================================================================
# Etat du compte n8n de cette machine
# -----------------------------------------------------------------------------
#   make n8n-compte
#
# n8n a supprime l'authentification basique en version 1.x : les variables
# N8N_BASIC_AUTH_* ne sont plus lues du tout. Le compte proprietaire se cree
# au premier lancement de l'interface, avec l'email saisi par le visiteur.
#
# Consequence pour l'equipe : chaque machine a son PROPRE compte n8n, et le
# partage des workflows se fait par Git, pas a l'interieur de n8n. Ce script
# dit ou en est chaque poste, sans avoir a ouvrir le navigateur.
# =============================================================================

set -uo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RACINE"

[ -f .env ] && set -a && source .env && set +a

N8N_PORT="${N8N_PORT:-5678}"
N8N_URL="http://localhost:${N8N_PORT}"
CONTENEUR="predicare-n8n"

vert()  { printf '\033[32m%s\033[0m\n' "$*"; }
jaune() { printf '\033[33m%s\033[0m\n' "$*"; }
gris()  { printf '\033[90m%s\033[0m\n' "$*"; }
err()   { printf '\033[31m%s\033[0m\n' "$*" >&2; }

echo ""

if ! docker inspect "$CONTENEUR" >/dev/null 2>&1; then
    err "Le conteneur n8n n'existe pas. Lancez d'abord : make up"
    exit 1
fi

if [ "$(docker inspect -f '{{.State.Status}}' "$CONTENEUR" 2>/dev/null)" != "running" ]; then
    err "n8n n'est pas en marche. Lancez : make up"
    exit 1
fi

# --- Le conteneur repond-il ? ---------------------------------------------
if ! curl -fsS --max-time 5 "${N8N_URL}/healthz" >/dev/null 2>&1; then
    err "n8n ne repond pas sur ${N8N_URL}/healthz"
    exit 1
fi

# --- Le compte existe-t-il ? ----------------------------------------------
# On interroge la base plutot que l'API : n8n ne rend pas la liste des
# comptes sans session, et l'API publique exige une cle qu'on n'a pas ici.
COMPTES=$(docker compose exec -T db psql -U "${POSTGRES_USER:-predicare}" -d n8n \
    -tAc 'SELECT email FROM "user" ORDER BY email' 2>/dev/null | tr -d ' \r' | grep -v '^$')

if [ -z "$COMPTES" ]; then
    INCOMPLET=$(docker compose exec -T db psql -U "${POSTGRES_USER:-predicare}" -d n8n \
        -tAc 'SELECT count(*) FROM "user"' 2>/dev/null | tr -d '\r\n' || echo 0)

    if [ "${INCOMPLET:-0}" -gt 0 ]; then
        jaune "Un compte existe mais le formulaire de proprietaire n'a jamais ete termine."
        echo ""
        echo "  Ouvrez ${N8N_URL} : n8n va afficher le formulaire de creation."
        echo "  Saisissez l'email de l'equipe, puis choisissez un mot de passe."
        echo "  Ce mot de passe n'est stocke dans aucun fichier : notez-le."
        echo ""
        gris "Le compte vide qui existe en base n'est PAS utilisable."
        exit 0
    fi

    jaune "Aucun compte n8n n'existe encore sur cette machine."
    echo ""
    echo "  1. Ouvrez ${N8N_URL} dans un navigateur"
    echo "  2. n8n affiche un ecran de creation de compte : saisissez"
    echo "     l'adresse email de l'equipe"
    echo "  3. Choisissez un mot de passe et notez-le : il n'est pas"
    echo "     stocke dans le .env, il ne peut pas etre retrouve"
    echo ""
    gris "Chaque machine possede son propre compte. Pour partager les"
    gris "workflows : make n8n-export puis git, puis make n8n-import."
    exit 0
fi

NB=$(printf '%s\n' "$COMPTES" | grep -c .)
vert "${NB} compte(s) n8n sur cette machine :"
printf '%s\n' "$COMPTES" | sed 's/^/  - /'
echo ""
gris "Mot de passe : defini par vous a la creation, non stocke dans le .env."
echo ""
jaune "Mot de passe oublie ? Reinitialisation de l'instance :"
gris "  docker compose exec n8n n8n user-management:reset"
gris "  puis rouvrir ${N8N_URL} et recreer le compte"
gris "  ATTENTION : cette operation reinitialise l'instance entiere."
echo ""
gris "Partage des workflows entre machines : make n8n-export, git, puis make n8n-import."