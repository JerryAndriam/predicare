#!/usr/bin/env bash
# =============================================================================
# Diagnostic de l'environnement PrediCare
# -----------------------------------------------------------------------------
# A executer avant une demonstration. Le script ne modifie rien : il se limite
# a dire ce qui manque et ce qui ne va pas, avant que le jury ne le decouvre.
#
#   make doctor
#
# Sortie 0 si tout est pret pour `make up`, 1 sinon.
#
# Note d'ecriture : aucun message n'est construit dans un `$( )`. Les
# parentheses d'un texte (« fichier(s) ») y ferment la substitution, et le
# resultat est une erreur de syntaxe dont le message ne designe pas la vraie
# cause. Les textes sont donc construits a part.
# =============================================================================

set -uo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RACINE"

PROBLEMES=0

V_OK='\033[32m'
V_WARN='\033[33m'
V_KO='\033[31m'
V_DOUX='\033[90m'
V_RESET='\033[0m'
V_GRAS='\033[1m'

titre() { printf "\n${V_GRAS}%s${V_RESET}\n" "$1"; }

# ligne <libelle> <etat> <couleur_etat> <detail>
ligne() {
    local etat_couleur="$3"
    printf "  %-24s ${etat_couleur}%-10s${V_RESET} ${V_DOUX}%s${V_RESET}\n" "$1" "$2" "$4"
}

# Les quatre aides recoivent <libelle> <detail>. C'est le seul moyen de
# garder une seule definition de l'affichage : c'etait ici que le detail
# disparaitait, les aides passant trois arguments a une fonction qui en
# attend quatre.
ok()     { ligne "$1" "OK"        "$V_OK"   "${2:-}"; }
manque() { ligne "$1" "MANQUE"    "$V_KO"   "${2:-}"; }
alerte() { ligne "$1" "a voir"    "$V_WARN" "${2:-}"; }
doux()   { ligne "$1" "optionnel" "$V_DOUX" "${2:-}"; }

premiere_version() {
    "$@" --version 2>/dev/null | head -1 | cut -c1-46
}

# =============================================================================
titre "1. Outils requis par « make up »"
# =============================================================================
# Liste volontairement courte. Tout le reste tourne dans des conteneurs :
# sur une machine vierge, Docker, make et curl suffisent.
for outil in bash make curl; do
    if command -v "$outil" >/dev/null 2>&1; then
        version="$(premiere_version "$outil")"
        ok "$outil" "${version:-present}"
    else
        manque "$outil" "a installer"
        PROBLEMES=$((PROBLEMES + 1))
    fi
done

COREUTILS_MANQUANTS=""
for outil in head base64 tr cut grep sed awk wc sleep touch mkdir ls; do
    command -v "$outil" >/dev/null 2>&1 || COREUTILS_MANQUANTS="${COREUTILS_MANQUANTS}${outil} "
done
if [ -z "${COREUTILS_MANQUANTS}" ]; then
    ok "coreutils" "head base64 tr cut grep sed"
else
    manque "coreutils" "${COREUTILS_MANQUANTS}"
    PROBLEMES=$((PROBLEMES + 1))
fi

if command -v docker >/dev/null 2>&1; then
    version="$(docker --version 2>/dev/null | cut -c1-46)"
    if docker info >/dev/null 2>&1; then
        ok "demon Docker" "$version"
    else
        alerte "demon Docker" "arret - demarrez Docker Desktop"
        PROBLEMES=$((PROBLEMES + 1))
    fi
    if docker compose version >/dev/null 2>&1; then
        version="$(docker compose version --short 2>/dev/null | cut -c1-46)"
        ok "Compose v2" "$version"
    else
        manque "Compose v2" "sudo apt install docker-compose-plugin"
        PROBLEMES=$((PROBLEMES + 1))
    fi
else
    manque "Docker" "docs.docker.com/engine/install"
    PROBLEMES=$((PROBLEMES + 1))
fi

# =============================================================================
titre "2. Outils de developpement, optionnels"
# =============================================================================
for outil in uv python3 git; do
    if command -v "$outil" >/dev/null 2>&1; then
        chemin="$(command -v "$outil")"
        ok "$outil" "$chemin"
    else
        doux "$outil" "non requis pour utiliser la plateforme"
    fi
done
printf "  ${V_DOUX}node et npm ne sont jamais necessaires : le build de\n"
printf "  ${V_DOUX}l'interface se fait dans Docker.${V_RESET}\n"

# =============================================================================
titre "3. Configuration"
# =============================================================================
if [ -f .env ]; then
    nb_lignes="$(wc -l < .env | tr -d ' ')"
    ok "fichier .env" "${nb_lignes} lignes"
    restants="$(grep -c "CHANGER_MOI" .env 2>/dev/null || echo 0)"
    if [ "${restants}" -gt 0 ]; then
        detail="${restants} variable(s) encore a remplir"
        alerte "secrets generes" "$detail"
        printf "  ${V_DOUX}LLM_API_KEY et SLACK_WEBHOOK_URL se remplissent a la main${V_RESET}\n"
    else
        ok "secrets generes" "aucun marqueur restant"
    fi
else
    alerte "fichier .env" "sera cree par make up"
fi

ACCES_PAR_DEFAUT="/home/jerry/Documents/predicare/ACCES_PREDICARE.md"
FICHE_ACCES="${ACCES_FILE:-$ACCES_PAR_DEFAUT}"
if [ -f "$FICHE_ACCES" ]; then
    ok "fiche d'acces" "$FICHE_ACCES"
else
    alerte "fiche d'acces" "generez-la avec make acces"
fi

# =============================================================================
titre "4. Depot"
# =============================================================================
if command -v git >/dev/null 2>&1 && [ -d .git ]; then
    branche="$(git branch --show-current 2>/dev/null || echo '?')"
    modifies="$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
    detail="${branche} - ${modifies} fichier(s) non commite(s)"
    ok "branche" "$detail"

    if git ls-files --error-unmatch .env >/dev/null 2>&1; then
        manque ".env versionne" "des secrets sont dans l'historique Git"
        PROBLEMES=$((PROBLEMES + 1))
    else
        ok ".env versionne" "correctement ignore"
    fi
else
    doux "git" "pas necessaire pour utiliser la plateforme"
fi

# =============================================================================
titre "5. Plateforme"
# =============================================================================
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    actifs="$(docker ps --filter label=com.docker.compose.project=predicare --format '{{.Names}}' 2>/dev/null | wc -l | tr -d ' ')"
    if [ "${actifs}" -gt 0 ]; then
        detail="${actifs} conteneur(s) en marche"
        ok "conteneurs" "$detail"
        for service in api-core api-inference api-rag web n8n; do
            conteneur="predicare-${service}"
            if ! docker inspect "$conteneur" >/dev/null 2>&1; then
                continue
            fi
            etat="$(docker inspect -f '{{.State.Status}}' "$conteneur" 2>/dev/null)"
            boucle="$(docker inspect -f '{{.RestartCount}}' "$conteneur" 2>/dev/null || echo 0)"
            if [ "${boucle:-0}" -ge 3 ]; then
                manque "  ${service}" "BOUCLE - dependance manquante"
                PROBLEMES=$((PROBLEMES + 1))
            elif [ "$etat" = "running" ]; then
                ok "  ${service}" ""
            else
                alerte "  ${service}" "$etat"
            fi
        done
    else
        alerte "conteneurs" "aucun - lancez make up"
    fi
fi

# =============================================================================
printf "\n%s\n" "-------------------------------------------"
if [ "$PROBLEMES" -eq 0 ]; then
    printf "${V_OK}Environnement pret. Lancez : make up${V_RESET}\n"
    exit 0
fi
printf "${V_WARN}${PROBLEMES} point(s) a regler avant la demonstration.${V_RESET}\n"
exit 1