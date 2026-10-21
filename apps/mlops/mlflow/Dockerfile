# =============================================================================
# MLflow + pilote PostgreSQL
# -----------------------------------------------------------------------------
# L'image officielle `ghcr.io/mlflow/mlflow` n'embarque aucun pilote de base de
# donnees. C'est sans consequence tant que le backend est SQLite ou un fichier,
# mais ici le backend store est PostgreSQL (les experiences doivent survivre a
# une reinitialisation du conteneur).
#
# Sans cette couche, le conteneur demarre, leve `ModuleNotFoundError: No module
# named 'psycopg2'`, sort en erreur et Docker le relance en boucle. Le symptome
# est trompeur : le service apparait dans `docker compose ps` avec un RestartCount
# qui grimpe, et rien n'indique que la cause est un module manquant.
#
# `psycopg2-binary` et non `psycopg2` : la version compilee de psycopg2 exige
# libpq et un compilateur dans l'image, ce qui l'alourdirait pour rien ici.
# =============================================================================
FROM ghcr.io/mlflow/mlflow:v2.19.0

RUN pip install --no-cache-dir "psycopg2-binary>=2.9,<3"
