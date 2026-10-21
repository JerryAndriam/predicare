"""Configuration Superset pour le pilotage decisionnel PrediCare.

Point d'attention : la connexion BI est en LECTURE SEULE. Deux defenses
cumulatives :

1. `options=-c default_transaction_read_only=on` : PostgreSQL refuse toute
   ecriture sur cette session, meme si une requete BI contient un INSERT.
2. Le compte `superset_ro` n'a aucun droit d'ecriture dans les schemas.

Un tableau de bord qui affiche une valeur erronee est gene ; un tableau de
bord qui modifie la base est un incident de securite.
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# DEUX connexions, et elles ne se confondent pas.
#
# 1. Les METADONNEES de Superset (utilisateurs, dashboards, valeurs par
#    defaut) : c'est la base `superset`, en LECTURE ECRITURE. Superset doit
#    pouvoir creer ses tables au premier demarrage. La pointer sur la connexion
#    BI rend `superset db upgrade` impossible.
# 2. La SOURCE BI : les donnees metier PrediCare, en LECTURE SEULE stricte.
#    C'est celle que le tableau de bord interroge.
#
# Confondre les deux est le piege classique : soit Superset ne demarre pas,
# soit il demarre avec des droits d'ecriture sur les donnees de l'assureur.
# ---------------------------------------------------------------------------
_utilisateur = os.environ.get("POSTGRES_USER", "predicare")
_mot_de_passe = os.environ.get("POSTGRES_PASSWORD", "")
_hote = os.environ.get("DB_HOST", "db")
_port = os.environ.get("DB_PORT", "5432")
_base_superset = os.environ.get("SUPERSET_DB_NAME", "superset")

# (1) Metadonnees de l'outil : lecture ecriture, base dediee.
SQLALCHEMY_DATABASE_URI = (
    f"postgresql+psycopg2://{_utilisateur}:{_mot_de_passe}@{_hote}:{_port}/{_base_superset}"
)

# (2) Source BI : lecture seule, sur les schemas metier de la base applicative.
PREDICARE_BI_DATABASE_URI = os.environ.get("DB_CONNECTION_STRING", "")

SQLALCHEMY_TRACK_MODIFICATIONS = False

SECRET_KEY = os.environ.get("SUPERSET_SECRET_KEY", "change-me")

# Cle de chiffrement des MOTS DE PASSE des connexions stockees par Superset.
# Elle est distincte de SECRET_KEY, volontairement : deriver l'une de
# l'autre relierait la session d'administration au stockage des secrets, et
# une fuite de la premiere livrerait la seconde.
FERNET_KEYS = [os.environ.get("SUPERSET_FERNET_KEY", SECRET_KEY)]

# Pas de donnees d'exemple : elles alourdissent le demarrage et n'ont aucun
# rapport avec le metier du projet.
LOAD_EXAMPLES = os.environ.get("SUPERSET_LOAD_EXAMPLES", "no") == "yes"

SQLLAB_CTAS_NO_LIMIT = True
SQLLAB_TIMEOUT = 30

# `SQLALCHEMY_ENGINE_OPTIONS` s'applique a TOUTES les connexions que Superset
# gere, metadonnees comprises. Y mettre `default_transaction_read_only`
# empechait Superset de creer ses propres tables au premier demarrage
# ("cannot execute CREATE SEQUENCE in a read-only transaction").
# Le mode lecture seule de la source BI est donc porte PAR L'URI de cette
# seule connexion (voir PREDICARE_BI_DATABASE_URI dans docker-compose.bi.yml),
# et la base reste protegee par les droits du role `superset_ro`.
SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

FEATURE_FLAGS = {
    # Explicitement requis par le CDC pour le pilotage des operations.
    "DASHBOARD_RBAC": True,
    "ENABLE_TEMPLATE_PROCESSING": False,
    # Evite de charger des extensions navigateur pour un usage interne.
    "ALERT_REPORTS": True,
    # Le tableau est affiche dans l'application via un guest token. Sans ce
    # drapeau, Superset refuse `/embedded/...` et le SDK ne peut pas monter
    # l'iframe.
    "EMBEDDED_SUPERSET": True,
    # Le menu d'une tuile expose « Drill to detail ». Le drapeau est actif par
    # defaut en 6.1, mais on le fixe ici pour qu'une montee de version ne le
    # transforme pas silencieusement en fonction absente.
    "DRILL_TO_DETAIL": True,
}

ROW_LIMIT = 10_000
SAMPLES_ROW_LIMIT = 1000

# ---------------------------------------------------------------------------
# Prefixe `/bi` : Superset est servi DERRIERE la passerelle, pas a la racine.
#
# Deux mecanismes, qui repondent a deux problemes distincts.
#
# 1. COTE SERVEUR — `ProxyFix` lit `X-Forwarded-Prefix` (que Traefik pose
#    automatiquement a cote du middleware `stripPrefix`) et le place dans
#    `SCRIPT_NAME`. Sans lui, `GET /bi/superset/dashboard/...` repondait
#    `Location: /login/?next=...`, SANS le prefixe : le navigateur sortait de
#    l'espace `/bi` et l'iframe echouait sur l'application React.
#
# 2. COTE NAVIGATEUR — `FLASK_APP_MUTATOR` publie `application_root = "/bi"`
#    dans les donnees d'amorcage de l'interface. Sans cela, le routeur React
#    de Superset compare `window.location.pathname` (`/bi/login/`) a ses
#    propres routes (`/login/`) : aucune ne correspond, et il affiche la page
#    d'accueil anonyme au lieu du formulaire de connexion.
#
# On passe par le mutateur plutot que par `APPLICATION_ROOT` directement :
# renseigner `APPLICATION_ROOT` en configuration aurait active le middleware
# `AppRootMiddleware` de Superset, qui exige que le chemin recu commence par
# `/bi` — alors que Traefik le retire deja. Les deux se seraient annules.
#
# `APPLICATION_ROOT` est donc pose APRES la creation de l'application, quand
# la decision d'installer ce middleware est deja prise.
# ---------------------------------------------------------------------------
ENABLE_PROXY_FIX = True
PROXY_FIX_CONFIG = {
    "x_for": 1,
    "x_proto": 1,
    "x_host": 1,
    "x_port": 1,
    "x_prefix": 1,
}


def _declarer_prefixe_bi(app: Flask) -> None:  # noqa: F821
    """Annonce le prefixe `/bi` a l'interface, sans middleware WSGI."""
    app.config["APPLICATION_ROOT"] = "/bi"


FLASK_APP_MUTATOR = _declarer_prefixe_bi

# Le cookie de session doit rester valable quelle que soit l'URL d'acces :
# Flask deduit son `Path` de `SESSION_COOKIE_PATH`, et a defaut de
# `APPLICATION_ROOT`. Sans ces deux lignes il serait ecrit `Path=/bi`, donc
# absent des appels directs au conteneur (`SUPERSET_URL=http://superset:8088`,
# utilise par `make bi-dashboard`) : l'API repondait alors
# « The CSRF session token is missing » et l'archive ne pouvait plus etre
# rejouee. Le prefixe reste gere par `ProxyFix`, pas par le cookie.
SESSION_COOKIE_PATH = "/"
REMEMBER_COOKIE_PATH = "/"

LOG_LEVEL = os.environ.get("SUPERSET_LOG_LEVEL", "INFO")

# Repertoire de travail persistant : sans cela, les dashboards crees dans
# l'interface disparaissent au redemarrage du conteneur.
DATA_DIR = os.environ.get("SUPERSET_DATA_DIR", "/app/superset_home")

# ---------------------------------------------------------------------------
# Embedding : le tableau est affiche dans l'application sans seconde session.
#
# Le navigateur ne recoit jamais le mot de passe Superset : api-core demande
# un guest token court (5 min) avec un compte de service, et le SDK le
# renouvelle. Le role invite est distinct du role de demonstration : il ne
# voit que le dashboard et les datasets necessaires, jamais SQL Lab.
# ---------------------------------------------------------------------------
GUEST_ROLE_NAME = os.environ.get("SUPERSET_GUEST_ROLE", "PrediCare BI (invité)")
# Pas de valeur par defaut exploitable : le job `preparer_embed.py` refuse un
# secret vide, et le deploiement doit le generer dans `.env`.
GUEST_TOKEN_JWT_SECRET = os.environ.get("SUPERSET_GUEST_TOKEN_SECRET", "")
GUEST_TOKEN_JWT_AUDIENCE = os.environ.get("SUPERSET_PUBLIC_URL", "http://localhost:8080")
GUEST_TOKEN_JWT_EXP_SECONDS = int(os.environ.get("SUPERSET_GUEST_TOKEN_EXP_SECONDS", "300"))
