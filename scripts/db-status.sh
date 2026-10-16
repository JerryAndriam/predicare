#!/usr/bin/env bash
# =============================================================================
# Etat du schema de base : version appliquee contre version du code
# -----------------------------------------------------------------------------
# Pourquoi cette commande existe
#
# `migrate` est un job one-shot. Compose ne le relance que si le `config-hash`
# du service change, et ce hash couvre la definition du service (YAML, image,
# environnement) -- PAS le contenu de ./db/migrations, monte en lecture seule.
#
# Consequence observee : une migration ajoutee apres le premier demarrage n'est
# jamais appliquee. La base reste en 0002, `migrate` sort en 0, `make wait`
# verifie le code de sortie et conclude que tout va bien. La plateforme tourne
# sur un schema perime, sans le moindre signal.
#
# Cette commande rend l'ecart visible.
# =============================================================================

set -uo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RACINE"

BLEU='\033[36m'
VERT='\033[32m'
JAUNE='\033[33m'
ROUGE='\033[31m'
GRIS='\033[90m'
FIN='\033[0m'

log()  { printf "${BLEU}[db]${FIN} %s\n" "$*"; }
ok()   { printf "${VERT}  [OK]${FIN}   %s\n" "$*"; }
warn() { printf "${JAUNE}  [!!]${FIN}   %s\n" "$*"; }
ko()   { printf "${ROUGE}  [KO]${FIN}   %s\n" "$*"; }
gris() { printf "${GRIS}  [--]${FIN}   %s\n" "$*"; }

# --- 1. La base repond-elle ? ----------------------------------------------
if ! docker compose exec -T db pg_isready -U predicare -d predicare >/dev/null 2>&1; then
    ko "PostgreSQL ne repond pas. Lance 'make start' d'abord."
    exit 1
fi

# --- 2. Version reellement appliquee ---------------------------------------
# La table de version est dans le schema `audit`, pas dans `public` : c'est un
# choix de env.py (`version_table_schema`). L'interroger dans `public` echoue
# avec « relation does not exist » et donne l'impression que les migrations n'ont
# jamais tourne.
APPLIQUEE=$(docker compose exec -T db psql -U predicare -d predicare -X -tAc \
    "SELECT version_num FROM audit.alembic_version" 2>/dev/null | tr -d '\r\n')

if [ -z "$APPLIQUEE" ]; then
    ko "Aucune version enregistree : les migrations n'ont jamais ete appliquees."
    gris "  Lance 'make migrate'."
    exit 1
fi

# --- 3. Version attendue par le code ----------------------------------------
# Interroge Alembic lui-meme plutot que de parser les fichiers Python : c'est
# l'autorite, et ca evite de reinventer la lecture de la chaine de revisions.
ATTENDUE=$(docker compose run --rm -T migrate alembic heads 2>/dev/null \
    | tr -d '\r' | awk '/^[[:space:]]*[0-9a-zA-Z_]+[[:space:]]*\(/ {print $1; exit}')

if [ -z "$ATTENDUE" ]; then
    warn "Version attendue illisible (Alembic n'a pas reponde)."
    gris "  Appliquee : $APPLIQUEE"
    exit 0
fi

# --- 4. Verdict --------------------------------------------------------------
if [ "$APPLIQUEE" = "$ATTENDUE" ]; then
    ok "schema a jour : $APPLIQUEE"
    exit 0
fi

warn "schema perime"
printf "      applique en base : %s\n" "$APPLIQUEE"
printf "      attendu par le code : %s\n" "$ATTENDUE"
echo ""
log "Les migrations en attente ne seront PAS appliquees par 'make up' :"
log "  le job 'migrate' est un one-shot que Compose considere deja fait."
gris "  Lance 'make migrate' pour appliquer."
exit 1
