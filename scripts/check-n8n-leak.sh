#!/usr/bin/env bash
# Garde-fou pre-commit : refuse un workflow n8n contenant un secret inline.
# Un webhook Slack ou une cle LLM dans un JSON versionne est dans l'historique
# Git a jamais, meme apres un `git rm` ulterieur.
set -euo pipefail
if grep -nE 'hooks\.slack\.com|sk-[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}' "$@" >/dev/null 2>&1; then
    echo "Secret detecte dans un workflow n8n : $*" >&2
    echo "Utilisez une credential n8n (Settings > Credentials) au lieu d'une valeur en clair." >&2
    exit 1
fi
exit 0
