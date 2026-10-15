#!/usr/bin/env bash
# =============================================================================
# Attente de la disponibilite des services
# -----------------------------------------------------------------------------
# Compose ordonne deja le demarrage via `depends_on: condition`. Ce script
# attend la FIN de la sequence et affiche l'etat final : c'est ce que voit
# le jury juste apres `docker compose up`.
# =============================================================================

set -uo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RACINE"

DELAI_MAX="${DELAI_MAX:-180}"
INTERVALLE=3
ATTENTE=0
CODES_ECHEC=0
ETAPES=(db migrate api-core api-inference api-rag web)

log() { printf '\033[36m[wait]\033[0m %s\n' "$*"; }
ok()  { printf '\033[32m  [OK]\033[0m   %s\n' "$*"; }
ko()  { printf '\033[31m  [KO]\033[0m   %s\n' "$*"; }

# Un conteneur qui boucle en arret/redemarrage affiche `Up 4 seconds` et
# ressemble a un service qui demarre. C'est exactement le symptome du bug
# rencontre sur n8n, ou la base n'existait pas : la boucle masquait la cause
# reelle pendant des minutes. On detecte explicitement ce cas.
en_boucle() {
    local nom="$1" redemarrages
    redemarrages=$(docker inspect -f '{{.RestartCount}}' "predicare-${nom}" 2>/dev/null || echo 0)
    [ "${redemarrages:-0}" -ge 3 ] 2>/dev/null
}

signaler_boucle() {
    local nom="$1"
    ko "$nom est en BOUCLE DE REDEMARRAGE (cause probable : dependance manquante)"
    docker compose logs --tail=40 "$nom" 2>&1 | grep -iE "error|does not exist|fatal|refused" | tail -6
    echo ""
    log "Diagnostic : make logs-service S=${nom}"
}

# Bornes les boucles sans `timeout`, qui n'existe pas sur macOS sauf si
# coreutils y est installe. Une simple boucle `sleep` avec compteur est
# universelle et fait le meme travail.
attendre_condition() {
    local delai_max="$1"
    local condition="$2"
    local attente=0
    while [ "$attente" -lt "$delai_max" ]; do
        if eval "$condition"; then
            return 0
        fi
        sleep 2
        attente=$((attente + 2))
    done
    return 1
}

log "Attente de la sequence de demarrage (max ${DELAI_MAX}s)..."

# --- 1. Base de donnees --------------------------------------------------
log "PostgreSQL en cours de demarrage..."
if attendre_condition "$DELAI_MAX" \
    'docker compose exec -T db pg_isready -U predicare -d predicare >/dev/null 2>&1'; then
    ok "base de donnees prete"
else
    ko "base de donnees indisponible apres ${DELAI_MAX}s"
    docker compose logs --tail=30 db
    exit 1
fi

# --- 2. Jobs one-shot (migrations, chargement) ---------------------------
# `service_completed_successfully` est deja une condition de `depends_on`,
# mais on verifie le resultat : un job en echec laisse la pile en marche
# avec un schema incomplet, ce qui n'apparaitrait sur aucun `/health`.
log "Verification des migrations..."
if attendre_condition "$DELAI_MAX" \
    '[ "$(docker inspect -f "{{.State.Status}}" predicare-migrate 2>/dev/null)" = "exited" ]'; then

    CODE_MIGRATION="$(docker inspect -f '{{.State.ExitCode}}' predicare-migrate 2>/dev/null || echo 1)"
    if [ "$CODE_MIGRATION" = "0" ]; then
        ok "migrations appliquees"
    else
        ko "les migrations ont echoue (code $CODE_MIGRATION)"
        docker compose logs --tail=50 migrate
        exit 1
    fi
else
    ko "les migrations n'ont pas termine apres ${DELAI_MAX}s"
    docker compose logs --tail=50 migrate
    exit 1
fi

# --- 3. API et interface -------------------------------------------------
log "Attente des API..."
for service in "${ETAPES[@]:2}"; do
    ATTENTE=0
    while [ "$ATTENTE" -lt "$DELAI_MAX" ]; do
        ETAT="$(docker inspect -f '{{.State.Status}}' "predicare-${service}" 2>/dev/null || echo absent)"
        if [ "$ETAT" = "running" ] || [ "$ETAT" = "exited" ]; then
            break
        fi
        sleep "$INTERVALLE"
        ATTENTE=$((ATTENTE + INTERVALLE))
    done
    if en_boucle "$service"; then
        signaler_boucle "$service"
        CODES_ECHEC=1
    elif [ "$ETAT" = "running" ]; then
        ok "$service demarre"
    else
        ko "$service non demarre (etat : $ETAT)"
        CODES_ECHEC=1
    fi
done

# n8n demarre lentement : son conteneur passe en `running` avant que le
# serveur HTTP ne reponde, le temps qu'il migre sa base interne. Attendre
# l'etat du conteneur suffit donc a peine : sur un demarrage a froid, n8n
# etait annonce demarre puis declare injoignable une seconde plus tard.
# On attend donc la REPONSE HTTP, tout en surveillant la boucle de
# redemarrage qui, elle, doit interrompre l'attente.
log "Attente de n8n (demarrage lent attendu)..."
DELAI_N8N=150
ATTENTE=0
ETAT_N8N="absent"
SANTE_N8N="ko"
while [ "$ATTENTE" -lt "$DELAI_N8N" ]; do
    ETAT_N8N=$(docker inspect -f '{{.State.Status}}' predicare-n8n 2>/dev/null || echo absent)

    if en_boucle n8n; then
        break
    fi

    if [ "$ETAT_N8N" = "running" ] \
        && curl -fsS --max-time 5 "http://localhost:${N8N_PORT:-5678}/healthz" >/dev/null 2>&1; then
        SANTE_N8N="ok"
        break
    fi

    sleep 3
    ATTENTE=$((ATTENTE + 3))
done

if en_boucle n8n; then
    signaler_boucle n8n
    CODES_ECHEC=1
elif [ "$SANTE_N8N" = "ok" ]; then
    ok "n8n demarre et repond sur /healthz"
elif [ "$ETAT_N8N" = "running" ]; then
    ko "n8n tourne mais ne repond pas sur /healthz apres ${DELAI_N8N}s"
    CODES_ECHEC=1
else
    ko "n8n non demarre (etat : ${ETAT_N8N})"
    CODES_ECHEC=1
fi

echo ""
log "Etat final :"
docker compose ps --format 'table {{.Service}}\t{{.Status}}'
echo ""

# Les services degrade ne bloquent pas : un modele non entraine ou une cle
# LLM absente laisse la plateforme utilisable, et c'est volontaire.
DEGRADES="$(docker compose ps --format '{{.Service}} {{.Status}}' | grep -c 'starting\|unhealthy' || true)"
if [ "$DEGRADES" -gt 0 ]; then
    log "$DEGRADES service(s) en cours de stabilisation ou degrade(s)."
    log "Detail : make health"
fi

log "Plateforme accessible sur http://localhost:${GATEWAY_PORT:-8080}"

if [ "$CODES_ECHEC" -ne 0 ]; then
    ko "La pile n'est pas completement demarree. Corrigez ce qui est ci-dessus avant toute demonstration."
    exit 1
fi