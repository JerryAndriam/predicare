#!/usr/bin/env bash
# =============================================================================
# Import des workflows n8n depuis Git
# -----------------------------------------------------------------------------
# On utilise la CLI n8n plutot que son API REST, et c'est un choix
# delibere : l'API exige une cle creee a la main dans l'interface, donc
# impossible a automatiser sur une machine vierge. La CLI n'exige aucun
# secret et suffit a installer les workflows du projet.
#
# L'API REST reste utile, et elle est tentee quand elle est configuree : elle
# seule permet de remplacer un workflow existant et de l'activer. Sans elle,
# le script n'ecrase rien et le dit explicitement.
#
# Option --if-missing : mode amorcage, utilise automatiquement par `make up`,
# `make up-light` et `make start`. Il n'installe QUE les workflows absents,
# ne supprime ni ne remplace jamais rien (meme si une cle API est presente)
# et ne publie que les workflows qu'il vient d'installer : il ne peut donc
# pas ecraser une modification faite dans l'interface.
# =============================================================================

set -uo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RACINE"

MODE_IF_MISSING=0
case "${1:-}" in
    --if-missing) MODE_IF_MISSING=1 ;;
    "") ;;
    *) printf 'Option inconnue : %s (options : --if-missing)\n' "$1" >&2; exit 1 ;;
esac

[ -f .env ] && set -a && source .env && set +a

N8N_PORT="${N8N_PORT:-5678}"
N8N_URL="${N8N_URL:-http://localhost:${N8N_PORT}}"
N8N_API_KEY="${N8N_API_KEY:-}"

SOURCE="${RACINE}/apps/n8n/workflows"
CONTENEUR="predicare-n8n"
DANS_CONTENEUR="/tmp/workflows-import"

log() { printf '\033[36m[n8n-import]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[n8n-import]\033[0m %s\n' "$*"; }
err() { printf '\033[31m[n8n-import]\033[0m %s\n' "$*" >&2; }

# La cle API n'est utile que si elle est reellement creee dans l'interface.
# On le verifie sur un point d'ENTREE AUTENTIFIE : `/healthz` est public, le
# tester ne prouverait rien et ferait croire a tort que l'API est disponible.
api_Disponible() {
    [ -n "$N8N_API_KEY" ] || return 1
    [ "$N8N_API_KEY" != "CHANGER_MOI_N8N_API_KEY" ] || return 1
    curl -fsS --max-time 6 \
        -H "X-N8N-API-KEY: ${N8N_API_KEY}" \
        "${N8N_URL}/api/v1/workflows?limit=1" >/dev/null 2>&1
}

# Attente active : l'import via la CLI fait recharger le moteur de workflows
# a n8n. Le conteneur reste `running` mais /healthz repond 503 pendant
# quelques secondes.
attendre_sante() {
    local attente=0
    while [ "$attente" -lt 60 ]; do
        curl -fsS --max-time 5 "${N8N_URL}/healthz" >/dev/null 2>&1 && return 0
        sleep 3
        attente=$((attente + 3))
    done
    return 1
}

# --- Verification de l'environnement ---------------------------------------
NB_FICHIERS=$(find "$SOURCE" -name '*.json' -type f 2>/dev/null | wc -l)
if [ "$NB_FICHIERS" -eq 0 ]; then
    log "Aucun workflow dans apps/n8n/workflows/. Rien a importer."
    exit 0
fi

if ! docker inspect "$CONTENEUR" >/dev/null 2>&1; then
    err "Le conteneur n8n n'existe pas. Lancez d'abord : make up"
    exit 1
fi

ETAT=$(docker inspect -f '{{.State.Status}}' "$CONTENEUR" 2>/dev/null || echo absent)
if [ "$ETAT" != "running" ]; then
    err "n8n n'est pas en marche (etat : $ETAT). Lancez : make up"
    exit 1
fi

API=0
if api_Disponible; then
    API=1
    if [ "$MODE_IF_MISSING" -eq 1 ]; then
        log "Mode --if-missing : seuls les workflows absents seront installes."
    else
        log "API n8n configuree : mise a jour et activation possibles."
    fi
else
    warn "Pas de cle API n8n (Settings > n8n API). Les workflows deja"
    warn "presents seront conserves, pas remplaces. C'est volontaire :"
    warn "la CLI n'n'expose pas de suppression, donc un import forcer"
    warn "dupliquerait les workflows."
fi

# --- Import -----------------------------------------------------------------
docker exec "$CONTENEUR" rm -rf "$DANS_CONTENEUR" >/dev/null 2>&1
docker exec "$CONTENEUR" mkdir -p "$DANS_CONTENEUR" >/dev/null 2>&1

COPIES=0
while IFS= read -r fichier; do
    if docker cp "$fichier" "${CONTENEUR}:${DANS_CONTENEUR}/$(basename "$fichier")" >/dev/null 2>&1; then
        COPIES=$((COPIES + 1))
    else
        err "  copie impossible : $(basename "$fichier")"
    fi
done < <(find "$SOURCE" -name '*.json' -type f | sort)

if [ "$COPIES" -eq 0 ]; then
    err "Aucun fichier n'a pu etre transfere dans le conteneur."
    exit 1
fi

# Noms deja installes : on ne les reimporte pas si l'API n'est pas
# disponible, sinon chaque relance creerait un doublon. En mode
# --if-missing, cette liste sert toujours : le but est justement de
# ne jamais remplacer un workflow existant.
EXISTANTS=""
if [ "$API" -eq 0 ] || [ "$MODE_IF_MISSING" -eq 1 ]; then
    # `n8n list:workflow` sort au format `id|nom`. La premiere ligne est un
    # avertissement PostgreSQL : on ne garde que les lignes contenant un
    # separateur, sinon le nom lu serait en realite l'identifiant.
    EXISTANTS=$(docker exec "$CONTENEUR" n8n list:workflow 2>/dev/null \
        | grep '|' | cut -d'|' -f2 || true)
fi

IMPORTES=0
IGNORES=0
ACTIVES=0
NOMS_IMPORTES=""

# On ne copie que les fichiers reellement a installer : `n8n import:workflow`
# travaille sur un repertoire et n'a pas de suppression, donc re-importer
# un workflow deja present creerait un doublon.
A_IMPORTER=""
while IFS= read -r fichier; do
    nom_fichier="$(basename "$fichier")"
    nom_workflow=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['name'])" "$fichier" 2>/dev/null || basename "$fichier" .json)

    log "Workflow : ${nom_workflow}"

    # --- Cas API disponible : remplacement propre ---
    if [ "$API" -eq 1 ] && [ "$MODE_IF_MISSING" -eq 0 ]; then
        ID_EXISTANT=$(curl -fsS --max-time 6 \
            -H "X-N8N-API-KEY: ${N8N_API_KEY}" \
            --get --data-urlencode "name=${nom_workflow}" \
            "${N8N_URL}/api/v1/workflows" 2>/dev/null \
            | python3 -c "
import json, sys
try:
    donnees = json.load(sys.stdin)['data']
    print(donnees[0]['id'] if donnees else '')
except Exception:
    print('')" 2>/dev/null)

        if [ -n "$ID_EXISTANT" ]; then
            if curl -fsS --max-time 6 -X DELETE \
                -H "X-N8N-API-KEY: ${N8N_API_KEY}" \
                "${N8N_URL}/api/v1/workflows/${ID_EXISTANT}" >/dev/null 2>&1; then
                log "  version precedente supprimee"
            else
                err "  suppression impossible (id ${ID_EXISTANT})"
            fi
        fi
    else
        # --- Cas CLI seule (ou mode --if-missing) : on ne touche a rien ---
        if printf '%s\n' "$EXISTANTS" | grep -Fxq "$nom_workflow"; then
            if [ "$MODE_IF_MISSING" -eq 1 ]; then
                log "  deja installe (mode --if-missing : rien a faire)"
            else
                warn "  deja installe (aucune cle API pour le remplacer)"
            fi
            IGNORES=$((IGNORES + 1))
            continue
        fi
    fi

    A_IMPORTER="${A_IMPORTER} ${DANS_CONTENEUR}/${nom_fichier}"
    NOMS_IMPORTES="${NOMS_IMPORTES}${nom_workflow}
"
    IMPORTES=$((IMPORTES + 1))
done < <(find "$SOURCE" -name '*.json' -type f | sort)

if [ "$IMPORTES" -eq 0 ]; then
    log "Rien a installer."
else
    # `--separate` : chaque fichier est un workflow independant et n8n lui
    # attribue un identifiant. Sans cette option, n8n lit un seul workflow
    # par fichier et echoue sur notre format, volontairement depourvu d'`id`
    # (un identifiant versionne est un champ qui change a chaque import).
    SORTIE=$(docker exec "$CONTENEUR" n8n import:workflow --separate --input="$DANS_CONTENEUR" 2>&1)
    if printf '%s' "$SORTIE" | grep -qi "successfully imported"; then
        log "  ${IMPORTES} workflow(s) installe(s)"
    elif printf '%s' "$SORTIE" | grep -qi "failed to find owner"; then
        # Premier demarrage sur une machine vierge : n8n refuse tout import
        # tant que le compte proprietaire n'existe pas (l'import CLI doit
        # etre rattache a un projet personnel).
        warn "Aucun compte n8n n'existe encore : l'import ne peut pas etre"
        warn "rattache a un proprietaire. C'est normal au tout premier demarrage."
        warn "Ouvrez ${N8N_URL}, creez votre compte, puis relancez :"
        warn "  make n8n-import          (ou simplement make start)"
        exit 0
    else
        err "L'import a echoue :"
        printf '%s\n' "$SORTIE" | tail -4 >&2
        exit 1
    fi
fi

# --- Activation -------------------------------------------------------------
# La CLI importe toujours des workflows INACTIFS. Sans activation, aucune
# alerte ne part : c'est le piege le plus discret de cette brique.
if [ "$IMPORTES" -gt 0 ]; then
    if [ "$MODE_IF_MISSING" -eq 1 ]; then
        # Mode amorcage : publier UNIQUEMENT les workflows tout juste
        # installes. Republier ceux deja presents reviendrait a defaire un
        # choix fait dans l'interface (workflow volontairement en brouillon).
        log "Publication des nouveaux workflows uniquement"
        while IFS='|' read -r id_brut nom_brut; do
            id="$(printf '%s' "$id_brut" | tr -d '[:space:]')"
            nom="$(printf '%s' "$nom_brut" | sed 's/^ *//; s/ *$//')"
            printf '%s' "$id" | grep -Eq '^[A-Za-z0-9]{16}$' || continue
            printf '%s\n' "$NOMS_IMPORTES" | grep -Fxq "$nom" || continue
            if [ "$API" -eq 1 ]; then
                if curl -fsS --max-time 6 -X PATCH \
                    -H "X-N8N-API-KEY: ${N8N_API_KEY}" \
                    -H "Content-Type: application/json" \
                    "${N8N_URL}/api/v1/workflows/${id}" -d '{"active": true}' >/dev/null 2>&1; then
                    ACTIVES=$((ACTIVES + 1))
                else
                    warn "  publication impossible (id ${id})"
                fi
            else
                if docker exec "$CONTENEUR" n8n publish:workflow --id="$id" >/dev/null 2>&1; then
                    ACTIVES=$((ACTIVES + 1))
                else
                    warn "  publication impossible (id ${id})"
                fi
            fi
        done < <(docker exec "$CONTENEUR" n8n list:workflow 2>/dev/null | grep '|' || true)
    elif [ "$API" -eq 1 ]; then
        log "Activation via l'API n8n"
        LISTE=$(curl -fsS --max-time 8 \
            -H "X-N8N-API-KEY: ${N8N_API_KEY}" \
            "${N8N_URL}/api/v1/workflows?active=false&limit=200" 2>/dev/null \
            | python3 -c "import json,sys
try:
    for w in json.load(sys.stdin)['data']:
        print(w['id'])
except Exception:
    pass" 2>/dev/null)
        for id in $LISTE; do
            if curl -fsS --max-time 6 -X PATCH \
                -H "X-N8N-API-KEY: ${N8N_API_KEY}" \
                -H "Content-Type: application/json" \
                "${N8N_URL}/api/v1/workflows/${id}" -d '{"active": true}' >/dev/null 2>&1; then
                ACTIVES=$((ACTIVES + 1))
            fi
        done
    else
        # Depuis n8n 2.x, un workflow n'est plus « active » mais « publie ».
        # `update:workflow --all` est marque deprecie : il faut publier
        # chaque workflow par son identifiant.
        log "Publication via la CLI n8n"
        for id in $(docker exec "$CONTENEUR" n8n list:workflow --onlyId 2>/dev/null | grep -E '^[A-Za-z0-9]{16}$' || true); do
            if docker exec "$CONTENEUR" n8n publish:workflow --id="$id" >/dev/null 2>&1; then
                ACTIVES=$((ACTIVES + 1))
            else
                warn "  publication impossible (id ${id})"
            fi
        done
    fi
fi

# --- Verification -----------------------------------------------------------
log "Attente de la reprise de n8n..."
if ! attendre_sante; then
    err "n8n ne repond pas sur ${N8N_URL}/healthz apres l'import."
    err "Diagnostic : make logs-service S=n8n"
    exit 1
fi

echo ""
log "Termine : ${IMPORTES} installe(s), ${IGNORES} deja present(s), ${ACTIVES} actif(s)."
log "Interface : ${N8N_URL} (menu Workflows)"
log "Credentials Slack / SMTP / LLM : apps/n8n/credentials/README.md"

if [ "$IGNORES" -gt 0 ] && [ "$MODE_IF_MISSING" -eq 0 ]; then
    log ""
    log "Pour remplacer un workflow existant, creez une cle API n8n"
    log "(Settings > n8n API), mettez-la dans N8N_API_KEY du .env,"
    log "puis relancez ce script."
fi