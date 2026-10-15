#!/usr/bin/env bash
# Connexion du depot (module 8 du cursus) : titres de commits normalises,
# pour que l'historique se lise comme un journal de projet.
set -euo pipefail

TYPES="feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert"
PATTERN="^(${TYPES})(\(.+\))?: .{1,72}$"

TITRE="$(head -n 1 "$1")"

if ! printf '%s' "$TITRE" | grep -qE "$PATTERN"; then
    cat >&2 <<MSG
Titre de commit invalide : "${TITRE}"

Format attendu : <type>(<portee>) : <description en francais>
Types : ${TYPES}

Exemples :
  feat(rag) : ajoute le cache semantique et ses metriques
  fix(validation) : rejette les factures au-dela du plafond quotidien
  chore(compose) : isole MLflow dans un profil optionnel
MSG
    exit 1
fi
