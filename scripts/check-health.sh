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
    local reponse lecture statut detail

    reponse="$(curl -fsS --max-time 5 "$url" 2>/dev/null)" || {
        printf '  %-18s %s\n' "$nom" "$(rouge 'injoignable')"
        CODES=1
        return
    }

    # Deux formats de reponse coexistent : les API rendent du JSON
    # ({"status": "ok"|"degraded", "checks": {...}}), l'interface nginx rend
    # du texte plat ("ok") sur /healthz. Un parseur JSON unique faisait passer
    # l'interface pour un service en panne : `make health` sortait en erreur
    # alors que tout repondait, y compris le jour de la demonstration.
    lecture="$(printf '%s' "$reponse" | python3 -c \
        'import json, sys

brut = sys.stdin.read().strip()
statut, detail = "?", "-"
try:
    data = json.loads(brut)
except ValueError:
    if brut.lower() in {"ok", "healthy", "up"}:
        statut, detail = "ok", "texte=plain"
else:
    statut = data.get("status", "?")
    parts = [f"{k}={v}" for k, v in data.get("checks", {}).items()]
    manquants = data.get("missing_secrets", [])
    if manquants:
        parts.append(f"secrets_manquants={len(manquants)}")
    detail = "  ".join(parts)
print(f"{statut}\t{detail}")' 2>/dev/null || printf '?\t-')"

    IFS=$'\t' read -r statut detail <<< "$lecture"

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