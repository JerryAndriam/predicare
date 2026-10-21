#!/usr/bin/env bash
# Applique les vues de la couche semantique BI depuis l'interieur du reseau
# Docker (service `bi-init`).
#
# Pourquoi ce script en plus de `load.sh`
# ---------------------------------------
# `load.sh` pilote `docker compose exec db psql ...` depuis la machine hote :
# il sert aux rechargements manuels (`make reload-data`, `make bi`). Au
# demarrage, ce meme travail doit se faire sans que l'hote ait a lancer une
# commande apres `docker compose up`. Le service `bi-init` monte donc ce
# script et le dossier `views/` dans un conteneur, et l'execute avant
# `superset-init`.
#
# Sans cette etape, `superset-import` echouait sur la premiere vue absente
# (`ECHEC de l'enregistrement des datasets : bi.v_top5_prestataires`) et
# Superset ne demarrait pas, alors que la base et les migrations etaient
# saines : une vue ajoutee dans le depot n'etait tout simplement jamais
# appliquee par `make up`.
#
# Le script est idempotent : `CREATE OR REPLACE VIEW` remplace la vue, et les
# droits sont rejoues pour que `superset_ro` garde SELECT sur chaque vue.
set -euo pipefail

: "${BI_SCHEMA:=bi}"
: "${BI_ROLE:=superset_ro}"
BI_VIEWS_DIR="${BI_VIEWS_DIR:-/views}"

log() { printf '\033[36m[bi-init]\033[0m %s\n' "$*"; }

shopt -s nullglob
vues=("${BI_VIEWS_DIR}"/*.sql)
if [ "${#vues[@]}" -eq 0 ]; then
    printf '[bi-init] aucune vue trouvee dans %s\n' "$BI_VIEWS_DIR" >&2
    exit 1
fi

for fichier in "${vues[@]}"; do
    psql -X -v ON_ERROR_STOP=1 -q -f "$fichier"
    log "$(basename "$fichier")"
done

# Les droits sont rejoues apres chaque CREATE : une vue remplacee est recreee
# avec les privileges de son createur, pas avec ceux de l'ancienne.
# `\gexec` execute le GRANT produit pour chaque vue, sans avoir a boucler en
# shell sur des noms d'identifiants.
psql -X -v ON_ERROR_STOP=1 -q -v schema="$BI_SCHEMA" -v role="$BI_ROLE" <<'SQL'
-- `\o /dev/null` : `\gexec` affiche le resultat du SELECT (une ligne
-- « GRANT … » par vue). Le journal n'a besoin que des fichiers appliques.
\o /dev/null
SELECT format('GRANT SELECT ON %I.%I TO %I', table_schema, table_name, :'role')
FROM information_schema.views
WHERE table_schema = :'schema'
ORDER BY table_name;
\gexec
\o
SQL

log "droits SELECT accordes a ${BI_ROLE} sur ${BI_SCHEMA}."
