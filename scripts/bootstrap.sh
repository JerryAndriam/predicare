#!/usr/bin/env bash
# =============================================================================
# Preparation de l'environnement PrediCare
# -----------------------------------------------------------------------------
# Idempotent : peut etre relance sans effet de bord. C'est la premiere chose
# executee par `make up`, donc elle doit reussir sur une machine vierge ou le
# projet vient d'etre clone.
#
# Usage : scripts/bootstrap.sh [--secrets-only]
# =============================================================================

set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RACINE"

ENV_FILE="${RACINE}/.env"
ENV_EXAMPLE="${RACINE}/.env.example"
SECRETS_ONLY="${1:-}"

log()  { printf '\033[36m[bootstrap]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[bootstrap]\033[0m %s\n' "$*"; }
err()  { printf '\033[31m[bootstrap]\033[0m %s\n' "$*" >&2; }

# --- Verification des outils de la machine hote ---------------------------
# `make up` est la commande que le jury execute sur une machine vierge. Si un
# outil manque, il faut le dire en deux secondes, avec la commande
# d'installation, et non trois minutes plus tard au milieu d'un build.
#
# Volontairement peu d'exigences : le strict necessaire du chemin critique
# (bootstrap + build + attente). `uv`, `python3` et `node` ne sont pas dans
# cette liste : ils ne servent qu'au developpement ou a l'interieur des
# images.
OUTILS_REQUIS="make bash curl docker head base64 tr cut grep sed awk wc sleep touch mkdir"

command_installation() {
    case "$1" in
        make)
            printf '  Debian / Ubuntu : sudo apt install make\n'
            printf '  Fedora          : sudo dnf install make\n'
            printf '  macOS           : xcode-select --install\n'
            ;;
        curl)
            printf '  Debian / Ubuntu : sudo apt install curl\n'
            printf '  Fedora          : sudo dnf install curl\n'
            printf '  macOS           : brew install curl\n'
            ;;
        bash)
            printf '  Debian / Ubuntu : sudo apt install bash\n'
            printf '  Alpine          : apk add bash\n'
            printf '  macOS           : brew install bash\n'
            ;;
        docker)
            printf '  Linux           : https://docs.docker.com/engine/install/\n'
            printf '  macOS / Windows : https://docs.docker.com/desktop/install/\n'
            ;;
        *)
            printf '  Voir la documentation de %s\n' "$1"
            ;;
    esac
}

verifier_outils() {
    local manquants=()

    for outil in $OUTILS_REQUIS; do
        command -v "$outil" >/dev/null 2>&1 || manquants+=("$outil")
    done

    if [ "${#manquants[@]}" -eq 0 ]; then
        return 0
    fi

    err "Outils manquants sur cette machine : ${manquants[*]}"
    echo ""
    printf '  Installation :\n' >&2
    for outil in "${manquants[@]}"; do
        command_installation "$outil" >&2
    done
    echo ""
    err "Sur une machine vierge, il suffit de Docker, make et curl."
    exit 1
}

# --- Verification de Docker ----------------------------------------------
verifier_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        err "Docker n'est pas installe."
        err ""
        printf '  Linux   : https://docs.docker.com/engine/install/\n' >&2
        printf '  macOS   : https://docs.docker.com/desktop/install/mac-install/\n' >&2
        printf '  Windows : https://docs.docker.com/desktop/install/windows-install/\n' >&2
        exit 1
    fi
    if ! docker info >/dev/null 2>&1; then
        err "Le demon Docker ne repond pas. Demarrez Docker puis relancez."
        exit 1
    fi
    docker compose version >/dev/null 2>&1 || {
        err "Le plugin Docker Compose v2 est requis (docker compose)."
        err "Debian / Ubuntu : sudo apt install docker-compose-plugin"
        exit 1
    }
}

# --- Generation des secrets ----------------------------------------------
# Tout est genere par /dev/urandom et les coreutils, sans openssl ni python3.
# C'est un choix de portabilite, pas un detail : `make up` est la commande que
# le jury execute sur une machine vierge qu'on ne maitrise pas. Moins il y a
# de paquets a pre-installer, moins la demonstration commence par un echec.
generer_secret() {
    # 48 octets aleatoires, encodes en base64 : entropie largement suffisante
    # pour une cle de signature, et aucun caractere special a echapper dans
    # le .env (on retire '=' et l'on passe en base64 URL-safe).
    head -c 48 /dev/urandom | base64 | tr -d '\n=' | tr '+/' '-_'
}

# Cle de chiffrement de la table d'identites, au format attendu par Fernet :
# 32 octets en base64 URL-safe, soit 44 caracteres terminant par '='.
generer_cle_fernet() {
    head -c 32 /dev/urandom | base64 | tr -d '\n' | tr '+/' '-_'
}

maj_secret() {
    local cle="$1" valeur="$2"
    if grep -qE "^${cle}=" "$ENV_FILE"; then
        # sed avec | comme separateur : la valeur peut contenir / et +
        sed -i "s|^${cle}=.*|${cle}=${valeur}|" "$ENV_FILE"
    else
        printf '%s=%s\n' "$cle" "$valeur" >> "$ENV_FILE"
    fi
}

# Un secret est regenere si, et seulement si, la ligne existe ET contient
# encore le marqueur. Utilise `if` et non `grep &&` : sous `set -e`, un grep
# sans correspondance retourne 1 et tuerait le script.
maj_si_placeholder() {
    local cle="$1" valeur="$2"
    if grep -qE "^${cle}=CHANGER_MOI" "$ENV_FILE"; then
        maj_secret "$cle" "$valeur"
        log "  ${cle} genere"
    fi
}

generer_secrets() {
    [ -f "$ENV_FILE" ] || return 0
    log "Generation des secrets manquants dans .env"

    local cle_fernet
    cle_fernet="$(generer_cle_fernet)"

    maj_si_placeholder "APP_SECRET_KEY"           "$(generer_secret)"
    maj_si_placeholder "JWT_SECRET_KEY"            "$(generer_secret)"
    maj_si_placeholder "POSTGRES_PASSWORD"         "$(generer_secret)"
    maj_si_placeholder "PREDICARE_DB_RO_PASSWORD"  "$(generer_secret)"
    maj_si_placeholder "IDENTITY_ENCRYPTION_KEY"   "$cle_fernet"
    maj_si_placeholder "N8N_ENCRYPTION_KEY"        "$(generer_secret)"
    maj_si_placeholder "N8N_BASIC_AUTH_PASSWORD"   "$(generer_secret)"
    maj_si_placeholder "N8N_API_KEY"               "$(generer_secret)"
    maj_si_placeholder "SUPERSET_SECRET_KEY"       "$(generer_secret)"
    maj_si_placeholder "SUPERSET_ADMIN_PASSWORD"   "$(generer_secret)"
    maj_si_placeholder "SUPERSET_FERNET_KEY"       "$(generer_secret)"
    maj_si_placeholder "SUPERSET_DB_RO_PASSWORD"   "$(generer_secret)"
    maj_si_placeholder "GRAFANA_ADMIN_PASSWORD"    "$(generer_secret)"

    # L'URL de connexion porte le mot de passe base : si elle n'est pas
    # synchronisee, la migration echoue sur une base deja initialisee.
    local pgpass ropass
    pgpass="$(grep -E '^POSTGRES_PASSWORD=' "$ENV_FILE" | cut -d= -f2- || true)"
    ropass="$(grep -E '^PREDICARE_DB_RO_PASSWORD=' "$ENV_FILE" | cut -d= -f2- || true)"
    sed -i "s|^PREDICARE_DB_URL=.*|PREDICARE_DB_URL=postgresql+psycopg://predicare:${pgpass}@db:5432/predicare|" "$ENV_FILE"
    sed -i "s|^PREDICARE_DB_RO_URL=.*|PREDICARE_DB_RO_URL=postgresql+psycopg://predicare_ro:${ropass}@db:5432/predicare|" "$ENV_FILE"

    chmod 600 "$ENV_FILE"
}

# --- Piège du volume PostgreSQL persistant -------------------------------
# POSTGRES_PASSWORD n'est appliqué par l'image officielle qu'à la PREMIÈRE
# initialisation du volume. Régénérer un .env sur une base déjà existante
# produit donc « FATAL: password authentication failed » sans cause lisible.
verifier_coherence_volume() {
    local conteneur="predicare-db"
    command -v docker >/dev/null 2>&1 || return 0

    # La base n'existe pas encore : rien à vérifier.
    docker volume inspect predicare_pgdata >/dev/null 2>&1 || return 0
    grep -qE "^POSTGRES_PASSWORD=CHANGER_MOI" "$ENV_FILE" && return 0

    warn "Le volume PostgreSQL existe deja, mais le .env porte de nouveaux secrets."
    warn "Si POSTGRES_PASSWORD a change, la base sera INACCESSIBLE :"
    warn "  - pour repartir de zero   : make clean && make up"
    warn "  - pour garder l'ancien .env : restaurez votre sauvegarde de .env"
}

# --- Fichiers et repertoires necessaires ---------------------------------
creer_repertoires() {
    log "Creation des repertoires de travail"
    mkdir -p data/raw backups models artifacts
    # Un .gitkeep dans les dossiers ignores par .gitignore : Git peut ainsi
    # suivre le dossier, et sa presence evite un checkout vide.
    for dossier in data/raw backups models artifacts; do
        [ -f "$dossier/.gitkeep" ] || touch "$dossier/.gitkeep"
    done
}

verifier_ports() {
    local conflits=()
    local ports_a_verifier="GATEWAY_PORT WEB_PORT API_CORE_PORT API_INFERENCE_PORT API_RAG_PORT POSTGRES_PORT N8N_PORT MAILPIT_UI_PORT"

    command -v ss >/dev/null 2>&1 || return 0

    for cle in $ports_a_verifier; do
        valeur="$(grep -E "^${cle}=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- || true)"
        [ -n "$valeur" ] || continue
        if ss -ltn "sport = :${valeur}" >/dev/null 2>&1 && ss -ltn | awk '{print $4}' | grep -qE "[:.]${valeur}\$"; then
            conflits+=("${cle}=${valeur}")
        fi
    done

    if [ ${#conflits[@]} -gt 0 ]; then
        warn "Ports deja occupes : ${conflits[*]}"
        warn "Modifiez les valeurs correspondantes dans .env avant de demarrer."
    fi
}

# --- Point d'entree ------------------------------------------------------
main() {
    verifier_outils
    verifier_docker

    if [ ! -f "$ENV_FILE" ]; then
        [ -f "$ENV_EXAMPLE" ] || { err ".env.example introuvable."; exit 1; }
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        log ".env cree a partir de .env.example"
    else
        log ".env deja present"
    fi

    generer_secrets
    [ "$SECRETS_ONLY" = "--secrets-only" ] && { log "Secrets a jour."; exit 0; }

    creer_repertoires
    verifier_ports
    verifier_coherence_volume

    if ! command -v uv >/dev/null 2>&1; then
        # Apostrophes simples obligatoires : entre guillemets doubles, les
        # accents graves sont des substitutions de commande, et ce message
        # executerait reellement `make sync`.
        warn 'uv est introuvable : les commandes de developpement Python'
        warn '(make sync, lint, typecheck, test) ne fonctionneront pas.'
        warn 'Installation : https://docs.astral.sh/uv/getting-started/installation/'
    fi

    # Le verrou est commité : un ecart signifie que pyproject.toml a ete
    # modifie sans regenerer uv.lock, et la CI echouerait.
    if command -v uv >/dev/null 2>&1; then
        if ! uv lock --check >/dev/null 2>&1; then
            warn "uv.lock n'est pas a jour. Lancez : uv lock"
        fi
    fi

    log "Environnement pret."
}

main "$@"