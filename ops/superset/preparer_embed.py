"""Prepare l'embedding du tableau de bord Superset.

Trois objets sont crees ou alignes ici, de facon idempotente :

1. le role invite, en lecture seule, qui ne voit que le dashboard et les
   datasets BI (jamais SQL Lab), avec les menus de consultation des tuiles ;
2. la configuration embedded du dashboard, avec la liste blanche des
   domaines qui peuvent afficher l'iframe ;
3. le compte de service utilise par api-core pour demander les guest tokens.

Pourquoi un compte Admin pour le service : Superset classe
``can_grant_guest_token`` dans ``ADMIN_ONLY_PERMISSIONS``. Un role metier,
meme dote de cette permission dans la base, ne peut pas l'exercer. Le compte
de service est donc dedie et garde un mot de passe propre, distinct du compte
administrateur de demonstration.

Le script ne journalise jamais un mot de passe ni un token.
"""

from __future__ import annotations

import os
import sys

from creer_compte_demo import Client, _droits_source_bi

SLUG_DASHBOARD = os.environ.get("SUPERSET_DASHBOARD_SLUG", "pilotage-mensuel")
NOM_ROLE_INVITE = os.environ.get("SUPERSET_GUEST_ROLE", "PrediCare BI (invité)")
NOM_UTILISATEUR_SERVICE = os.environ.get("SUPERSET_BI_SERVICE_USERNAME", "predicare-bi")
LONGUEUR_MINIMALE = 12
ROLES_RESERVES = {"Admin", "Alpha", "Gamma", "Public", "sql_lab"}

#: Droits qui alimentent le menu « ... » d'une tuile. Superset les teste
#: cote navigateur, a partir des roles renvoyes dans le bootstrap : sans eux,
#: le menu ne montre que « Force refresh » et « Enter fullscreen ».
#:
#: * View query / View as table : les deux modales de consultation ;
#: * Download : export CSV/Excel, controle par ``can_csv`` ;
#: * Drill to detail : combine ``can_drill``, ``can_samples`` et
#:   ``can_get_drill_info`` ; ``can_write`` sur ``ExploreFormDataRestApi``
#:   autorise seulement l'etat temporaire de la modale, pas une ecriture BI.
#:
#: On n'accorde volontairement ni ``can_explore`` (Explore exige une vraie
#: session Superset), ni ``can_share_chart``, ni les droits SQL Lab.
DROITS_INTERACTION: tuple[tuple[str, str], ...] = (
    ("can_view_query", "Dashboard"),
    ("can_view_chart_as_table", "Dashboard"),
    ("can_csv", "Superset"),
    ("can_drill", "Dashboard"),
    ("can_write", "ExploreFormDataRestApi"),
    ("can_samples", "Datasource"),
    ("can_get_drill_info", "Dataset"),
)


def _secret(nom: str) -> str:
    valeur = os.environ.get(nom, "").strip()
    if not valeur or valeur.startswith("CHANGER_MOI"):
        print(
            f"{nom} absent ou encore un placeholder : embedding non configure.\n"
            "  Generez-le dans .env (scripts/bootstrap.sh) puis relancez le job.",
            file=sys.stderr,
        )
        return ""
    return valeur


def _domaines_autorises() -> list[str]:
    brut = os.environ.get(
        "SUPERSET_EMBED_ALLOWED_DOMAINS",
        "http://localhost:8080,http://127.0.0.1:8080",
    )
    domaines = [valeur.strip().rstrip("/") for valeur in brut.split(",") if valeur.strip()]
    if not domaines:
        raise RuntimeError("SUPERSET_EMBED_ALLOWED_DOMAINS est vide.")
    return domaines


def _preparer_role_et_dashboard() -> tuple[int, int]:
    """Cree le role invite et le rattache au dashboard.

    Retourne ``(id_role_admin, id_role_invite)``. Le role invite est reparti
    de zero a chaque execution : la liste de droits ci-dessous est sa
    definition, pas un etat a completer.
    """
    from superset.app import create_app

    application = create_app()
    with application.app_context():
        from superset import db as superset_db
        from superset import security_manager as sm
        from superset.connectors.sqla.models import SqlaTable
        from superset.models.core import Database
        from superset.models.dashboard import Dashboard

        sm.sync_role_definitions()

        role_admin = sm.find_role("Admin")
        if role_admin is None:
            raise RuntimeError("Role Admin introuvable dans Superset.")

        if NOM_ROLE_INVITE in ROLES_RESERVES:
            raise RuntimeError(
                f"Le role invite « {NOM_ROLE_INVITE} » est un role reserve de Superset."
            )

        role = sm.find_role(NOM_ROLE_INVITE) or sm.add_role(NOM_ROLE_INVITE)
        role.permissions = []

        droits = set(sm.PUBLIC_ROLE_PERMISSIONS)
        # Le front de Superset demande un jeton CSRF avant ses POST (filtres,
        # etats de dashboard). Sans ces deux droits, le tableau s'affiche mais
        # les interactions echouent en 403.
        droits.update(
            {
                ("can_read", "SecurityApi"),
                ("can_read", "SecurityRestApi"),
            }
        )
        droits.update(DROITS_INTERACTION)
        droits.update(_droits_source_bi(sm, Database, SqlaTable))

        for nom, vue in droits:
            permission = sm.add_permission_view_menu(nom, vue)
            if permission is None:
                raise RuntimeError(f"droit introuvable dans Superset : {nom} sur « {vue} »")
            sm.add_permission_role(role, permission)

        tableau = (
            superset_db.session.query(Dashboard)
            .filter(Dashboard.slug == SLUG_DASHBOARD)
            .one_or_none()
        )
        if tableau is None:
            raise RuntimeError(f"tableau « {SLUG_DASHBOARD} » introuvable dans Superset.")
        if role not in tableau.roles:
            tableau.roles.append(role)

        superset_db.session.commit()
        return int(role_admin.id), int(role.id)


def _utilisateur_service(client: Client, id_role_admin: int, mot_de_passe: str) -> int:
    charge = {
        "username": NOM_UTILISATEUR_SERVICE,
        "first_name": "Service",
        "last_name": "Pilotage",
        "email": f"{NOM_UTILISATEUR_SERVICE}@predicare.local",
        "password": mot_de_passe,
        "active": True,
        "roles": [id_role_admin],
    }
    for utilisateur in (
        client._json("GET", "/api/v1/security/users/?q=(page:0,page_size:100)").get("result") or []
    ):
        if utilisateur.get("username") == NOM_UTILISATEUR_SERVICE:
            client._json("PUT", f"/api/v1/security/users/{utilisateur['id']}", charge)
            return int(utilisateur["id"])
    creee = client._json("POST", "/api/v1/security/users/", charge)
    return int(creee["id"])


def _configurer_embedded(client: Client, domaines: list[str]) -> tuple[str, str]:
    reponse = client._json(
        "POST",
        f"/api/v1/dashboard/{SLUG_DASHBOARD}/embedded",
        {"allowed_domains": domaines},
    )
    resultat = reponse.get("result") or {}
    uuid = str(resultat.get("uuid") or "")
    dashboard_id = str(resultat.get("dashboard_id") or "")
    if not uuid or not dashboard_id:
        raise RuntimeError("Superset n'a pas renvoye l'UUID du dashboard embedded.")
    return uuid, dashboard_id


def main() -> int:
    secret_guest = _secret("SUPERSET_GUEST_TOKEN_SECRET")
    mot_de_passe_service = _secret("SUPERSET_BI_SERVICE_PASSWORD")
    mot_de_passe_admin = _secret("SUPERSET_ADMIN_PASSWORD")
    if not secret_guest or not mot_de_passe_service or not mot_de_passe_admin:
        return 2
    if len(mot_de_passe_service) < LONGUEUR_MINIMALE:
        print(
            f"SUPERSET_BI_SERVICE_PASSWORD doit contenir au moins {LONGUEUR_MINIMALE} caracteres.",
            file=sys.stderr,
        )
        return 2

    identifiant_admin = os.environ.get("SUPERSET_ADMIN_USERNAME", "admin")
    base = os.environ.get("SUPERSET_URL", "http://localhost:8088")
    domaines = _domaines_autorises()

    id_role_admin, id_role_invite = _preparer_role_et_dashboard()
    client = Client(base, identifiant_admin, mot_de_passe_admin)
    id_service = _utilisateur_service(client, id_role_admin, mot_de_passe_service)
    uuid, dashboard_id = _configurer_embedded(client, domaines)

    print(f"Role « {NOM_ROLE_INVITE} » : id {id_role_invite}, en lecture seule.")
    print(f"Dashboard embedded « {SLUG_DASHBOARD} » : uuid {uuid}, id {dashboard_id}.")
    print(f"Compte de service « {NOM_UTILISATEUR_SERVICE} » : id {id_service}, role Admin.")
    print(f"Domaines autorises : {', '.join(domaines)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
