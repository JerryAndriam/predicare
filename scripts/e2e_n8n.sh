#!/usr/bin/env bash
# =============================================================================
# Preuve de bout en bout de la chaine n8n
# -----------------------------------------------------------------------------
# Verifie, sur une pile reellement demarree :
#   1. que le workflow PK-Alerte-Fraude est actif et son webhook enregistre ;
#   2. qu'une facture du lot F17 au-dessus du seuil de notification produit
#      une reponse 200 avec score + rapport SHAP ;
#   3. que l'e-mail reel arrive dans Mailpit avec le rapport SHAP ;
#   4. que l'execution n8n est `success` (donc Slack a repondu 2xx : le noeud
#      final transforme tout echec Slack/e-mail en execution `error`) ;
#   5. qu'une facture invalide (422 de l'API) repond 502, ne produit AUCUN
#      e-mail et laisse l'execution en `error` : pas de notification fantome.
#
# Prerequis d'exploitation : SLACK_WEBHOOK_URL renseigne (sinon la preuve
# Slack est impossible) et Mailpit demarre (`make up-email`).
#
# Usage :
#   scripts/e2e_n8n.sh
#   N8N_URL=http://localhost:5678 MAILPIT_URL=http://localhost:8025 scripts/e2e_n8n.sh
# =============================================================================

set -uo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RACINE"

[ -f .env ] && set -a && source .env && set +a

N8N_URL="${N8N_URL:-http://localhost:${N8N_PORT:-5678}}"
MAILPIT_URL="${MAILPIT_URL:-http://localhost:${MAILPIT_UI_PORT:-8025}}"
TIMEOUT="${TIMEOUT:-30}"
WORKFLOW="PK-Alerte-Fraude"
SEUIL_NOTIFICATION="${SEUIL_NOTIFICATION_SLACK:-0.8}"
LOT="${RACINE}/data/seed/lot_20_factures.json"

for dependance in curl jq python3 docker; do
  if ! command -v "$dependance" >/dev/null 2>&1; then
    echo "Dependance manquante : $dependance" >&2
    exit 2
  fi
done

if [ -z "${SLACK_WEBHOOK_URL:-}" ]; then
  echo "SLACK_WEBHOOK_URL non defini : la preuve Slack est impossible." >&2
  echo "Renseignez-le dans .env (Slack > Apps > Incoming Webhooks), puis :" >&2
  echo "  docker compose up -d --force-recreate n8n" >&2
  exit 2
fi

if ! curl -fsS --max-time 5 "${N8N_URL}/healthz" >/dev/null 2>&1; then
  echo "n8n ne repond pas sur ${N8N_URL}. Lancez : make up" >&2
  exit 2
fi

if ! curl -fsS --max-time 5 "${MAILPIT_URL}/api/v1/messages?limit=1" >/dev/null 2>&1; then
  echo "Mailpit ne repond pas sur ${MAILPIT_URL}. Lancez : make up-email" >&2
  exit 2
fi

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

REUSSITES=0
ECHECS=0

passer() {
  REUSSITES=$((REUSSITES + 1))
  printf '  [OK]    %s\n' "$1"
}

echouer() {
  ECHECS=$((ECHECS + 1))
  printf '  [ECHEC] %s\n' "$1"
}

psql_n8n() {
  docker compose exec -T db psql -U predicare -d n8n -tAc "$1" 2>/dev/null | tr -d '[:space:]'
}

mail_ids() {
  curl -fsS --max-time 10 "${MAILPIT_URL}/api/v1/messages?limit=100" \
    | jq -r '.messages[].ID'
}

mail_total() {
  curl -fsS --max-time 10 "${MAILPIT_URL}/api/v1/messages?limit=1" | jq -r '.total'
}

# Ecrit la premiere facture du lot correspondant au filtre python, sans les
# cles de scenario (`cas_attendu`, `attendu`) que l'API refuse (`extra: forbid`).
extraire_facture() {
  local filtre="$1" destination="$2"
  python3 - "$LOT" "$destination" "$filtre" <<'PY'
import json
import sys

lot, destination, filtre = sys.argv[1], sys.argv[2], sys.argv[3]
with open(lot, encoding="utf-8") as flux:
    factures = json.load(flux)["factures"]

if filtre == "alerte":
    candidats = [
        f for f in factures
        if f.get("cas_attendu") == "valide" and f.get("attendu", {}).get("alerte") is True
    ]
else:
    candidats = [
        f for f in factures if str(f.get("cas_attendu", "")).startswith("invalide")
    ]

if not candidats:
    raise SystemExit(f"aucune facture '{filtre}' dans {lot}")

facture = {k: v for k, v in candidats[0].items() if k not in {"cas_attendu", "attendu"}}
with open(destination, "w", encoding="utf-8") as flux:
    json.dump(facture, flux, ensure_ascii=False)
PY
}

# ---------------------------------------------------------------------------
# 1. Etat du workflow
# ---------------------------------------------------------------------------
echo "Workflow n8n : ${WORKFLOW} sur ${N8N_URL}"

WORKFLOW_ID="$(psql_n8n "SELECT id FROM workflow_entity WHERE name='${WORKFLOW}' LIMIT 1;")"
if [ -z "$WORKFLOW_ID" ]; then
  echouer "workflow ${WORKFLOW} absent. Lancez : make n8n-import"
else
  passer "workflow present (id ${WORKFLOW_ID})"
fi

ACTIF="$(psql_n8n "SELECT active FROM workflow_entity WHERE id='${WORKFLOW_ID}';")"
if [ "$ACTIF" = "t" ]; then
  passer "workflow actif"
else
  echouer "workflow inactif. Lancez : make n8n-import"
fi

CHEMIN="$(psql_n8n "SELECT \"webhookPath\" FROM webhook_entity WHERE \"workflowId\"='${WORKFLOW_ID}' AND method='POST' LIMIT 1;")"
if [ "$CHEMIN" = "alerte-fraude" ]; then
  passer "webhook POST /webhook/alerte-fraude enregistre"
else
  echouer "webhook absent (chemin lu : '${CHEMIN}'). Redemarrez n8n apres l'import."
fi

# ---------------------------------------------------------------------------
# 2. Facture au-dessus du seuil : score + SHAP + e-mail + execution
# ---------------------------------------------------------------------------
echo ""
echo "Facture du lot F17 au-dessus du seuil de notification"

MAIL_IDS_AVANT="$(mail_ids || true)"
EXECUTIONS_AVANT="$(psql_n8n "SELECT COALESCE(MAX(id), 0) FROM execution_entity;")"

extraire_facture alerte "$TMPDIR/alerte.json"
FACTURE_ID="$(jq -r '.facture_id' "$TMPDIR/alerte.json")"

STATUT_HTTP="$(curl -sS --max-time "$TIMEOUT" -o "$TMPDIR/reponse.json" -w '%{http_code}' \
  -X POST "${N8N_URL}/webhook/alerte-fraude" \
  -H 'Content-Type: application/json' \
  --data-binary @"$TMPDIR/alerte.json")"

if [ "$STATUT_HTTP" = "200" ]; then
  passer "webhook HTTP 200 pour ${FACTURE_ID}"
else
  echouer "webhook HTTP ${STATUT_HTTP} pour ${FACTURE_ID} : $(cat "$TMPDIR/reponse.json")"
fi

SCORE="$(jq -r '.score_fraude // empty' "$TMPDIR/reponse.json")"
if awk -v score="$SCORE" -v seuil="$SEUIL_NOTIFICATION" 'BEGIN { exit !(score + 0 >= seuil + 0) }'; then
  passer "score ${SCORE} >= seuil de notification ${SEUIL_NOTIFICATION}"
else
  echouer "score '${SCORE}' sous le seuil de notification ${SEUIL_NOTIFICATION}"
fi

if jq -e '.rapport_shap | type == "string" and length > 20' "$TMPDIR/reponse.json" >/dev/null; then
  passer "reponse contient le rapport SHAP"
else
  echouer "rapport_shap absent ou vide dans la reponse"
fi

# L'e-mail part apres la reponse : on laisse au SMTP le temps d'arriver.
MAIL_ID=""
for _ in $(seq 1 20); do
  for identifiant in $(curl -fsS --max-time 10 "${MAILPIT_URL}/api/v1/messages?limit=100" \
      | jq -r --arg facture "$FACTURE_ID" '.messages[] | select(.Subject | contains($facture)) | .ID'); do
    if ! grep -qx "$identifiant" <<<"$MAIL_IDS_AVANT"; then
      MAIL_ID="$identifiant"
      break 2
    fi
  done
  sleep 1
done

if [ -n "$MAIL_ID" ]; then
  passer "e-mail recu dans Mailpit (${MAIL_ID})"
  TEXTE_MAIL="$(curl -fsS --max-time 10 "${MAILPIT_URL}/api/v1/message/${MAIL_ID}" | jq -r '.Text // ""')"
  if grep -q "Facture notee" <<<"$TEXTE_MAIL" && grep -q "Principaux facteurs" <<<"$TEXTE_MAIL"; then
    passer "corps de l'e-mail contient le rapport SHAP lisible"
  else
    echouer "corps de l'e-mail sans rapport SHAP lisible"
  fi
else
  echouer "aucun e-mail pour ${FACTURE_ID} dans Mailpit"
fi

EXECUTION_ID="$(psql_n8n "SELECT COALESCE(MAX(id), 0) FROM execution_entity;")"
if [ -n "$EXECUTION_ID" ] && [ "$EXECUTION_ID" -gt "$EXECUTIONS_AVANT" ]; then
  STATUT_EXEC="$(psql_n8n "SELECT status FROM execution_entity WHERE id=${EXECUTION_ID};")"
  if [ "$STATUT_EXEC" = "success" ]; then
    passer "execution ${EXECUTION_ID} success (Slack a repondu 2xx)"
    echo "          detail : ${N8N_URL}/workflow/${WORKFLOW_ID}/executions/${EXECUTION_ID}"
  else
    echouer "execution ${EXECUTION_ID} en '${STATUT_EXEC}' (voir ${N8N_URL}/workflow/${WORKFLOW_ID}/executions/${EXECUTION_ID})"
  fi
else
  echouer "aucune nouvelle execution n8n apres le webhook"
fi

# ---------------------------------------------------------------------------
# 3. Facture invalide : 502, aucune notification, execution en erreur
# ---------------------------------------------------------------------------
echo ""
echo "Facture invalide : l'echec doit etre journalise sans notification fantome"

# Reference prise APRES l'e-mail de l'alerte precedente : sinon on compterait
# cette alerte legitime comme une notification fantome.
MAIL_TOTAL_AVANT="$(mail_total || echo 0)"
EXECUTIONS_AVANT="$(psql_n8n "SELECT COALESCE(MAX(id), 0) FROM execution_entity;")"

extraire_facture invalide "$TMPDIR/invalide.json"
FACTURE_INVALIDE="$(jq -r '.facture_id' "$TMPDIR/invalide.json")"

STATUT_HTTP="$(curl -sS --max-time "$TIMEOUT" -o "$TMPDIR/reponse_invalide.json" -w '%{http_code}' \
  -X POST "${N8N_URL}/webhook/alerte-fraude" \
  -H 'Content-Type: application/json' \
  --data-binary @"$TMPDIR/invalide.json")"

if [ "$STATUT_HTTP" = "502" ]; then
  passer "facture invalide refusee en HTTP 502"
else
  echouer "facture invalide : HTTP ${STATUT_HTTP} au lieu de 502"
fi

if grep -q "aucune notification" "$TMPDIR/reponse_invalide.json"; then
  passer "reponse annonce explicitement l'absence de notification"
else
  echouer "reponse d'erreur sans mention de l'absence de notification"
fi

MAIL_TOTAL_APRES="$(mail_total || echo 0)"
if [ "$MAIL_TOTAL_APRES" = "$MAIL_TOTAL_AVANT" ]; then
  passer "aucun e-mail supplementaire (${MAIL_TOTAL_AVANT} avant, ${MAIL_TOTAL_APRES} apres)"
else
  echouer "notification fantome : ${MAIL_TOTAL_AVANT} e-mail(s) avant, ${MAIL_TOTAL_APRES} apres"
fi

EXECUTION_ID="$(psql_n8n "SELECT COALESCE(MAX(id), 0) FROM execution_entity;")"
STATUT_EXEC="$(psql_n8n "SELECT status FROM execution_entity WHERE id=${EXECUTION_ID};")"
if [ "$STATUT_EXEC" = "error" ]; then
  passer "echec journalise dans execution_entity (id ${EXECUTION_ID}, status error)"
else
  echouer "execution ${EXECUTION_ID} en '${STATUT_EXEC}' au lieu de 'error'"
fi

# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------
echo ""
echo "Resume : ${REUSSITES} reussite(s), ${ECHECS} echec(s)"
if [ "$ECHECS" -gt 0 ]; then
  echo "Parcours n8n : ECHEC"
  exit 1
fi
echo "Parcours n8n : SUCCES"
