# =============================================================================
# Superset - image de pilotage decisionnel
# -----------------------------------------------------------------------------
# On part de l'image officielle Apache Superset, version PIN'GEE.
#
# Pourquoi pas un build depuis python:3.12-slim :
# - l'image officielle est deja optimisee et reproductible ;
# - installer Superset par pip prend plus de dix minutes et produit une image
#   deux fois plus lourde ;
# - surtout, la version 4.1.x exige Python 3.9 et ne peut pas tourner sur
#   une image 3.12 : le build echoue sur une contrainte de version, pas sur
#   une erreur de configuration, ce qui est tres long a diagnostiquer.
#
# Cette image n'ajoute que ce que l'image officielle n'a pas : le pilote
# PostgreSQL psycopg2 et notre configuration. Le reste est heredite.
# =============================================================================

FROM apache/superset:6.1.0

USER root

# psycopg2-binary : l'image officielle ne contient AUCUN pilote PostgreSQL.
# On l'installe donc nous-memes.
#
# L'image travaille dans un environnement virtuel (/app/.venv) qui n'a pas
# `pip`, d'ou l'usage de `uv` comme installeur : c'est le meme gestionnaire que
# le reste du projet, il n'a pas besoin de `pip` dans la cible, et il est
# nettement plus rapide. Un `pip install` ici reussirait en apparence sans rien
# installer dans le bon environnement : le symptome n'apparait qu'a la
# premiere connexion a PostgreSQL.
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv

RUN uv pip install --python /app/.venv/bin/python --no-cache "psycopg2-binary==2.9.10" \
    && /app/.venv/bin/python -c "import psycopg2; print('psycopg2', psycopg2.__version__)"

# La configuration doit etre explicitement designee : sans
# SUPERSET_CONFIG_PATH, Superset cherche `superset_config.py` dans des
# repertoires par defaut et demarre avec une configuration neutre, donc SANS
# la connexion BI et SANS le mode lecture seule.
# `FLASK_APP` doit etre l'usine d'application complete
# (`superset.app:create_app()`), pas le simple module `superset` : le script
# de demarrage officiel passe cette valeur a gunicorn, qui cherche un
# attribut `application` dans le module designe.
ENV SUPERSET_CONFIG_PATH=/app/pythonpath/superset_config.py \
    SUPERSET_HOME=/app/superset_home \
    FLASK_APP=superset.app:create_app() \
    SUPERSET_BIND_ADDRESS=0.0.0.0 \
    SUPERSET_PORT=8088 \
    SERVER_WORKER_AMOUNT=2 \
    GUNICORN_TIMEOUT=120 \
    PYTHONUNBUFFERED=1

COPY ops/superset/superset_config.py /app/pythonpath/superset_config.py
COPY ops/superset/register_datasets.py /app/register_datasets.py
COPY ops/superset/register_dashboard.py /app/register_dashboard.py
COPY ops/superset/init.sh /app/init.sh

# Les vues de la couche semantique voyagent dans l'image : le job BI doit
# pouvoir les reappliquer sur une base fraichement creee, sans avoir le depot
# sous la main. Elles restent versionnees dans `db/bi/views/`, image n'est
# qu'un moyen de les rendre accessibles au conteneur.
COPY db/bi/views /app/bi/views

# Le r\xe9pertoire de travail doit appartenir \xe0 l'utilisateur non root avec
# lequel Superset s'execute, sinon l'ecriture des metadonnees echoue.
RUN mkdir -p /app/superset_home /app/pythonpath \
    && chown -R superset:root /app/superset_home /app/pythonpath \
    && chmod +x /app/init.sh

USER superset
WORKDIR /app

EXPOSE 8088

HEALTHCHECK --interval=20s --timeout=5s --start-period=90s --retries=5 \
    CMD curl -f http://localhost:8088/health || exit 1

# On demarre par le script de l'image officielle, donc par gunicorn, et non
# par `superset run` qui lance le serveur de developpement de Flask.
# `superset run` n'accepte plus aucune option de bind depuis la version 6 :
# l'adresse se reglait par `-b`, puis `-H`, et aucune des deux n'existe
# encore. Le bind passe par la variable `SUPERSET_BIND_ADDRESS`.
CMD ["/app/docker/entrypoints/run-server.sh"]