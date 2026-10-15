#!/usr/bin/env bash
# =============================================================================
# Controle de sante de la plateforme
# -----------------------------------------------------------------------------
# Interroge /health et /metrics de chaque service et affiche un tableau.
# Utilisable avant la soutenance pour verifier la pile sans la modifier.
# =============================================================================

set -uo pipefail

CODES=0
vert()  { printf '\033[32m%s\033[0m' "$1"; }
rouge() { printf '\033[31m%s\033[0m' "$1"; }
jaune() { printf '\033[33m%s\033[0m' "$1"; }

verifier_service() {
    local nom="$1" url="$2"
    local reponse statut detail

    reponse="$(curl -fsS --max-time 5 "$url" 2>/dev/null)" || {
        printf '  %-18s %s\n' "$nom" "$(rouge 'injoignable')"
        CODES=1
        return
    }

    statut="$(printf '%s' "$reponse" | python3 -c \
        'import json,sys; print(json.load(sys.stdin).get("status","?"))' 2>/dev/null || echo '?')"

    detail="$(printf '%s' "$reponse" | python3 -c \
        'import json,sys
data = json.load(sys.stdin)
checks = data.get("checks", {})
manquants = data.get("missing_secrets", [])
parts = [f"{k}={v}" for k, v in checks.items()]
if manquants:
    parts.append(f"secrets_manquants={len(manquants)}")
print("  ".join(parts))' 2>/dev/null || echo '-')"

    case "$statut" in
        ok)       printf '  %-18s %-12s %s\n' "$nom" "$(vert 'ok')" "$detail" ;;
        degraded) printf '  %-18s %-12s %s\n' "$nom" "$(jaune 'degrade')" "$detail" ;;
        *)        printf '  %-18s %-12s %s\n' "$nom" "$(rouge "$statut")" "$detail"; CODES=1 ;;
    esac
}

verifier_metriques() {
    local nom="$1" url="$2"
    local octets
    octets="$(curl -fsS --max-time 5 "$url" 2>/dev/null | wc -c)" || octets=0
    if [ "$octets" -gt 100 ]; then
        printf '  %-18s %s\n' "$nom" "$(vert "${octets} octets exposes")"
    else
        printf '  %-18s %s\n' "$nom" "$(rouge 'aucune metrique')"
    fi
}

echo ""
echo "Sante des services PrediCare"
echo "-------------------------------------------"
verifier_service "api-core"      "http://localhost:${API_CORE_PORT:-8001}/health"
verifier_service "api-inference" "http://localhost:${API_INFERENCE_PORT:-8002}/health"
verifier_service "api-rag"       "http://localhost:${API_RAG_PORT:-8003}/health"
verifier_service "web"           "http://localhost:${WEB_PORT:-8081}/healthz"
echo ""
echo "Metriques Prometheus"
echo "-------------------------------------------"
verifier_metriques "api-core"      "http://localhost:${API_CORE_PORT:-8001}/metrics"
verifier_metriques "api-inference" "http://localhost:${API_INFERENCE_PORT:-8002}/metrics"
verifier_metriques "api-rag"       "http://localhost:${API_RAG_PORT:-8003}/metrics"
echo ""

if [ "$CODES" -ne 0 ]; then
    echo "$(rouge 'Un ou plusieurs services sont injoignables.')  Diagnostic : make logs-service S=<service>"
else
    echo "$(vert 'Tous les services repondent.')"
fi
exit "$CODES"