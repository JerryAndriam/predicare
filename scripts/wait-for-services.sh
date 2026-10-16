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

# Charge le .env. Compose le fait pour lui, pas ce script : sans cela, une
# valeur de port personnalisee dans le .env fait tourner le conteneur sur
# 3007 alors que la sonde interroge 3001, et le service est declare degrade
# alors qu'il fonctionne. `set -a` exporte chaque variable pour les sous-
# commandes (curl, docker).
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

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

  # --- 6. Services de demonstration ---------------------------------------
  # Superset, Grafana, Prometheus et MLflow ont ete integres a `make up` et
  # `make start`. Aucun ne declare de `healthcheck`, donc Compose considere
  # demarre un conteneur qui n'ecoute pas encore : sans cette phase, `make up`
  # annoncerait « pret » pendant que Superset initialise encore ses bases, et
  # le premier clic du jury tomberait sur une page blanche.
  #
  # Mode degrade VOLONTAIRE : un echec ici n'annule pas le code de sortie.
  # Le noyau est deja verifie et fonctionnel ; un Superset qui ne demarre pas
  # doit priver le jury de la demonstration complete, pas l'annuler. Le detail
  # de l'echec est quand meme affiche.
  log "Services de demonstration (mode degrade : un echec n'annule pas 'make up')..."
  attendre_optional() {
      local nom="$1" url="$2" delai="$3"

      if ! docker inspect "predicare-${nom}" >/dev/null 2>&1; then
          printf '\033[90m  [--]\033[0m   %s non lance (attendu en mode `make up-light`)\n' "$nom"
          return 0
      fi

      if en_boucle "$nom"; then
          printf '\033[33m  [!!]\033[0m   %s en boucle de redemarrage\n' "$nom"
          signaler_boucle "$nom"
          return 0
      fi

      # Un seul `curl` ne suffit pas : Superset met jusqu'a plusieurs minutes
      # a initialiser ses bases apres un demarrage a froid, et le declarer
      # degrade parce qu'il n'etait pas pret a l'instant T produirait un faux
      # signal sur la service le plus lent de la pile. On interroge donc en
      # boucle jusqu'a epuisement du delai, comme le fait attendre-http.sh.
      local attente=0
      while [ "$attente" -lt "$delai" ]; do
          if curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then
              ok "$nom repond sur $url"
              return 0
          fi
          [ $((attente % 15)) -eq 0 ] && \
              printf '\033[90m  [..]\033[0m   %s demarre (%ss)\n' "$nom" "$attente"
          sleep 3
          attente=$((attente + 3))
      done

      local etat
      etat=$(docker inspect -f '{{.State.Status}}' "predicare-${nom}" 2>/dev/null || echo absent)
      printf '\033[33m  [!!]\033[0m   %s ne repond pas sur %s apres %ss (etat : %s) -- service degrade, la suite reste utilisable\n' \
          "$nom" "$url" "$delai" "$etat"
  }

  attendre_optional superset   "http://localhost:${SUPERSET_PORT:-8088}/health"    "${DELAI_SUPERSET:-240}"
  attendre_optional grafana    "http://localhost:${GRAFANA_PORT:-3001}/api/health"  "${DELAI_OPTIONAL:-120}"
  attendre_optional prometheus "http://localhost:${PROMETHEUS_PORT:-9090}/-/healthy" "${DELAI_OPTIONAL:-120}"
  attendre_optional mlflow     "http://localhost:${MLFLOW_PORT:-5000}/health"       "${DELAI_OPTIONAL:-120}"

  # Les workers n'ont pas de port : on verifie seulement qu'ils ne bouclent
  # pas, ce que fait deja `en_boucle`.
  for worker in worker-ingest worker-ai; do
      if docker inspect "predicare-${worker}" >/dev/null 2>&1 && ! en_boucle "$worker"; then
          ok "$worker stable"
      fi
  done

  echo ""

# Les services degrade ne bloquent pas : un modele non entraine ou une cle
# LLM absente laisse la plateforme utilisable, et c'est volontaire.
DEGRADES="$(docker compose ps --format '{{.Service}} {{.Status}}' | grep -c 'starting\|unhealthy' || true)"
if [ "$DEGRADES" -gt 0 ]; then
    log "$DEGRADES service(s) en cours de stabilisation ou degrade(s)."
    log "Detail : make health"
fi

  # --- 7. Derive du schema --------------------------------------------------
  # `migrate` est un one-shot : Compose le reutilise s'il est sorti avec le meme
  # config-hash. Ajouter une migration ne change pas ce hash (les fichiers sont
  # montes en lecture seule), donc la base peut rester perimee sans que rien ne
  # le signale. C'est exactement ce qui est arrive ici : `make up` annoncait
  # une plateforme prete sur un schema 0002 alors que le code attendait 0003.
  #
  # Ce controle est BLOQUANT : le reste de la pile peut tourner, mais si le
  # schema ne correspond pas au code, la demonstration porte sur autre chose que
  # ce que le projet contient.
  if scripts/db-status.sh >/dev/null 2>&1; then
      ok "schema a jour avec le code"
  else
      ko "schema derrive : la base n'est pas au niveau attendu par le code"
      scripts/db-status.sh 2>/dev/null | sed 's/^/      /'
      log "Les migrations ne sont pas appliquees automatiquement par 'make up'."
      log "  Lance 'make migrate', puis 'make start'."
      CODES_ECHEC=1
  fi

  echo ""
  log "Plateforme accessible sur http://localhost:${GATEWAY_PORT:-8080}"

if [ "$CODES_ECHEC" -ne 0 ]; then
    ko "La pile n'est pas completement demarree. Corrigez ce qui est ci-dessus avant toute demonstration."
    exit 1
fi