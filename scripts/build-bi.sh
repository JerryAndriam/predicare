#!/usr/bin/env bash
# =============================================================================
# Construit l'image BI, et verifie qu'elle porte les scripts du depot.
# -----------------------------------------------------------------------------
# Les scripts Superset sont CUITS dans l'image (`ops/superset/Dockerfile`) :
# modifier `register_dashboard.py` sans reconstruire l'image n'aurait aucun
# effet, et le symptome serait un job qui « marche » avec l'ancien code.
#
# Le build echoue cependant des que le registre est injoignable (le FROM
# `ghcr.io/astral-sh/uv` doit etre resolu a chaque build). Sur une machine
# sans reseau, un build impossible ne doit pas empecher de REJOUER un job dont
# l'image est deja a jour -- mais il ne doit jamais laisser passer une image
# perimee.
#
# D'ou la verification par empreinte : si le build echoue, on compare le
# SHA256 des scripts de l'image a celui des scripts du depot. Identiques :
# l'image est a jour, on continue. Differents : on echoue, en disant
# exactement quel script n'a pas ete reconstruit.
# =============================================================================

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.bi.yml)
IMAGE="predicare-superset:latest"
SCRIPTS=(register_datasets.py register_dashboard.py charger_requetes.py exporter_dashboard.py creer_compte_demo.py preparer_embed.py)

if "${COMPOSE[@]}" build "$@" 2>&1; then
    exit 0
fi

echo "" >&2
echo "  Build impossible (reseau indisponible ?). Verification de l'image existante..." >&2

for script in "${SCRIPTS[@]}"; do
    local_hash=$(sha256sum "ops/superset/${script}" | cut -d' ' -f1)
    image_hash=$(docker run --rm --entrypoint sha256sum "${IMAGE}" "/app/${script}" 2>/dev/null | cut -d' ' -f1)
    if [ -z "${image_hash}" ]; then
        echo "  ECHEC : ${script} absent de l'image ${IMAGE}." >&2
        exit 1
    fi
    if [ "${local_hash}" != "${image_hash}" ]; then
        echo "  ECHEC : ${script} n'a pas ete reconstruit (image perimee)." >&2
        echo "         Reconnectez le reseau, puis relancez la commande." >&2
        exit 1
    fi
done

echo "  Image a jour : les scripts du depot sont bien ceux de l'image." >&2
exit 0
