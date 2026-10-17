#!/usr/bin/env bash
# Applique les vues de la couche semantique BI.
#
# `CREATE OR REPLACE VIEW` rend l'operation idempotente : le script peut
# etre rejoue a chaque `make reload-data` sans migration, ce qui est le
# principe retenu pour la semantique (les vues changent plus souvent que le
# schema).
set -euo pipefail

#: Schéma cible et role lecteur. Exportés pour que le Makefile puisse les
#: surcharger, et reprennent les memes noms que `make up`.
BI_SCHEMA="${BI_SCHEMA:-bi}"
BI_ROLE="${BI_ROLE:-superset_ro}"

# Le script vit dans db/bi/ : la racine du depot est deux niveaux au-dessus.
# Un seul `..` menait a db/, ou aucun fichier .SQL n existe -- et le glob
# echouait silencieusement sur un dossier vide.
RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$RACINE"

echo "[bi] Schema $BI_SCHEMA : application des vues..."
for f in db/bi/views/*.sql; do
  nom=$(basename "$f" .sql)
  nb=$(grep -c "CREATE OR REPLACE VIEW" "$f")
  docker compose exec -T db psql -v ON_ERROR_STOP=1 -q \
      -U "${POSTGRES_USER:-predicare}" -d "${POSTGRES_DB:-predicare}" < "$f"
  echo "[bi]   $nom ($nb vue(s))"
done

# Les droits sont rejoues apres chaque CREATE : une vue remplacee est
# recreee avec les privileges de son createur, pas avec ceux de l'ancienne.
for vue in $(docker compose exec -T db psql -U "${POSTGRES_USER:-predicare}" \
      -d "${POSTGRES_DB:-predicare}" -X -tAc \
      "SELECT table_name FROM information_schema.tables
       WHERE table_schema='${BI_SCHEMA}' AND table_type='VIEW'"); do
  docker compose exec -T db psql -q -U "${POSTGRES_USER:-predicare}" \
      -d "${POSTGRES_DB:-predicare}" \
      -c "GRANT SELECT ON ${BI_SCHEMA}.${vue} TO ${BI_ROLE}"
done
echo "[bi] Droits SELECT accordes a ${BI_ROLE} sur ${BI_SCHEMA}."
