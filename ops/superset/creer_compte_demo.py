"""Cree le compte de demonstration Superset, en LECTURE SEULE.

Pourquoi
--------
Le tableau de bord est pilotable depuis l'interface, et une sauvegarde depuis
« Explore » ecrase la definition du depot : le symptome est un « ! » sur la
tuile, sans que rien ne dise d'ou il vient. Le remede est un controle de
derive (`make bi-graphiques`), mais le mieux est de ne pas pouvoir ecrire.

Les roles standards de Superset ne conviennent pas :

* `Admin` peut tout ecrire ;
* `Gamma` a `can_write` sur les graphiques et sur les tableaux ;
* `Public` n'a rien.

D'ou un role metier, cree ici, avec la liste EXACTE des droits de lecture :
voir le tableau, consulter le SQL d'un graphique, l'exporter, et lire
l'historique SQL Lab. Pas d'ecriture, pas de suppression, pas de creation.

Le mot de passe n'est jamais code en dur : il vient de l'environnement
(`SUPERSET_DEMO_PASSWORD`), comme les comptes de la plateforme.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

BASE = os.environ.get("SUPERSET_URL", "http://localhost:8088")
NOM_ROLE = "PrediCare BI (lecture seule)"
NOM_UTILISATEUR = "demo"
SLUG_DASHBOARD = "pilotage-mensuel"
LONGUEUR_MINIMALE = 12

#: Les droits accordes, et RIEN d'autre. La liste est explicite : un droit
#: absent est un droit refuse. C'est l'inverse de la logique « tout sauf ».
#:
#: Les libelles de vue ne sont pas interchangeables : l'API SQL Lab verifie
#: « can_read sur SQLLab », l'API des requetes enregistrees « can_read sur
#: SavedQuery », et le MENU de l'interface « menu_access sur SQL Lab ». Un
#: seul de ces droits lisible ne suffit pas : l'onglet est visible, mais
#: l'API repond 403.
PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("can_dashboard", "Superset"),
    ("can_read", "Dashboard"),
    ("can_read", "Chart"),
    ("can_export", "Chart"),
    ("can_view_query", "Dashboard"),
    ("can_view_chart_as_table", "Dashboard"),
    ("can_read", "Explore"),
    ("menu_access", "SQL Lab"),
    ("can_read", "SQLLab"),
    ("menu_access", "Saved Queries"),
    ("can_read", "SavedQuery"),
    ("can_read", "Query"),
    ("can_query", "Api"),
    # Le jeton CSRF se prend sur `/api/v1/security/csrf_token/`, qui est
    # protege par `can_read` sur « SecurityApi ». Sans lui, l'interface
    # renvoie 403 des la premiere requete -- un compte de demonstration qui
    # ne peut pas ouvrir le tableau ne sert a rien.
    ("can_read", "SecurityApi"),
    ("can_read", "SecurityRestApi"),
)


class Client:
    def __init__(self, base: str, username: str, password: str) -> None:
        self.base = base.rstrip("/")
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.jeton = ""
        self.csrf = ""
        self._connecter(username, password)

    def _json(self, methode: str, chemin: str, charge: dict | None = None) -> dict:
        data = json.dumps(charge).encode() if charge is not None else None
        entetes = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Referer": self.base,
        }
        if self.jeton:
            entetes["Authorization"] = f"Bearer {self.jeton}"
        if self.csrf:
            entetes["X-CSRFToken"] = self.csrf
        req = urllib.request.Request(
            f"{self.base}{chemin}", data=data, method=methode, headers=entetes
        )
        try:
            with self.opener.open(req, timeout=120) as r:
                brut = r.read()
                return json.loads(brut) if brut else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            raise RuntimeError(f"{methode} {chemin} -> HTTP {exc.code} : {detail}") from exc

    def _connecter(self, username: str, password: str) -> None:
        reponse = self._json(
            "POST",
            "/api/v1/security/login",
            {"username": username, "password": password, "provider": "db", "refresh": True},
        )
        self.jeton = reponse.get("access_token", "")
        if not self.jeton:
            raise RuntimeError("Superset n'a pas renvoye de jeton d'acces.")
        self.csrf = self._json("GET", "/api/v1/security/csrf_token/").get("result", "")
        if not self.csrf:
            raise RuntimeError("Superset n'a pas renvoye de jeton CSRF.")


def _droits_sql_lab(sm: object) -> list[tuple[str, str]]:
    """Les droits SQL Lab de Superset, repris tels quels.

    Superset livre un role `sql_lab` : executer une requete, lire l'historique,
    enregistrer une requete, ouvrir un onglet. Aucun de ces droits ne porte
    sur les graphiques ni sur les tableaux -- c'est ce qui rend le role
    utilisable par un compte de demonstration.

    On le reprend integralement plutot que d'enumerer ses droits : sa liste
    evolue avec les versions de Superset, et une liste recopiee a la main
    finit toujours par manquer un droit. Ce qu'on refuse explicitement, c'est
    l'ECRITURE sur les graphiques et les tableaux, qui n'y figure pas.
    """
    role = sm.find_role("sql_lab")
    if role is None:
        return []
    return [
        (permission.permission.name, permission.view_menu.name) for permission in role.permissions
    ]


def _droits_source_bi(sm: object, database: object, table: object) -> list[tuple[str, str]]:
    """Les droits d'acces a la source BI : base, schema, datasets.

    Superset cree un menu de vue par source de donnees -- la base, son
    schema, chaque dataset -- et n'accorde l'acces QUE par ces droits. Sans
    eux, le compte de demonstration voit le tableau mais aucune tuile : la
    liste des graphiques est filtree par les datasets accessibles.

    Les noms de ces menus sont imposes par Superset
    (`[nom_base].(id:N)`, `[nom_base].[schema]`, `[nom_base].[table](id:N)`) :
    on les reconstruit a l'identique, et `add_permission_view_menu` les
    retrouve -- ou les cree, ce qui reviendrait au meme.
    """
    from superset import db as superset_db

    droits: list[tuple[str, str]] = []
    for base in superset_db.session.query(database).all():
        prefixe = f"[{base.database_name}]"
        droits.append(("database_access", f"{prefixe}.(id:{base.id})"))
    for vue in superset_db.session.query(table).all():
        base = superset_db.session.query(database).filter_by(id=vue.database_id).one_or_none()
        if base is None:
            continue
        prefixe = f"[{base.database_name}]"
        if vue.schema:
            droits.append(("schema_access", f"{prefixe}.[{vue.schema}]"))
        droits.append(("datasource_access", f"{prefixe}.[{vue.table_name}](id:{vue.id})"))
    return droits


def _role() -> int:
    """Cree le role metier, ou aligne ses droits sur la liste blanche.

    L'API REST de Superset 6 n'expose QUE la lecture des roles : creer un
    role par API y est impossible (« Unknown field » sur `permissions` comme
    sur `permission_ids`). La creation passe donc par le gestionnaire de
    securite de Superset, qui est la voie normale.

    Le role est REPARTI DE ZERO a chaque execution : la liste blanche est la
    definition, pas un etat a completer. Un droit ajoute a la main dans
    l'interface disparait donc au prochain lancement -- c'est voulu, dans un
    role dont la seule raison d'etre est d'etre en lecture seule.
    """
    from superset.app import create_app

    # L'application d'abord, les modeles ensuite : importer un modele avant
    # que l'application soit initialisee echoue sur « App not initialized
    # yet » (la fabrique de champs chiffres a besoin de l'application).
    application = create_app()
    with application.app_context():
        from superset import db as superset_db
        from superset import security_manager as sm
        from superset.connectors.sqla.models import SqlaTable
        from superset.models.core import Database
        from superset.models.dashboard import Dashboard

        sm.sync_role_definitions()
        role = sm.find_role(NOM_ROLE) or sm.add_role(NOM_ROLE)
        role.permissions = []

        droits = list(PERMISSIONS)
        droits += _droits_sql_lab(sm)
        droits += _droits_source_bi(sm, Database, SqlaTable)
        for nom, vue in droits:
            permission = sm.add_permission_view_menu(nom, vue)
            if permission is None:
                raise RuntimeError(f"droit introuvable dans Superset : {nom} sur « {vue} »")
            sm.add_permission_role(role, permission)

        # Le tableau doit etre visible PAR CE ROLE. `DASHBOARD_RBAC` est
        # actif dans la configuration du projet : un tableau sans role
        # rattache n'est visible que par les administrateurs. Sans cette
        # ligne, le compte de demonstration se connecte et ne voit rien.
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
        return int(role.id)


def _utilisateur(client: Client, mot_de_passe: str, id_role: int) -> int:
    charge = {
        "username": NOM_UTILISATEUR,
        "first_name": "Demonstration",
        "last_name": "PrediCare",
        "email": f"{NOM_UTILISATEUR}@predicare.local",
        "password": mot_de_passe,
        "active": True,
        "roles": [id_role],
    }
    for utilisateur in (
        client._json("GET", "/api/v1/security/users/?q=(page:0,page_size:100)").get("result") or []
    ):
        if utilisateur.get("username") == NOM_UTILISATEUR:
            client._json("PUT", f"/api/v1/security/users/{utilisateur['id']}", charge)
            return int(utilisateur["id"])
    creee = client._json("POST", "/api/v1/security/users/", charge)
    return int(creee["id"])


def main() -> int:
    mot_de_passe = os.environ.get("SUPERSET_DEMO_PASSWORD", "").strip()
    if not mot_de_passe:
        print(
            "SUPERSET_DEMO_PASSWORD absent : compte de demonstration non cree.\n"
            "  Ajoutez SUPERSET_DEMO_PASSWORD=... dans .env (12 caracteres minimum).",
            file=sys.stderr,
        )
        return 2
    if len(mot_de_passe) < LONGUEUR_MINIMALE:
        print(
            f"SUPERSET_DEMO_PASSWORD doit contenir au moins {LONGUEUR_MINIMALE} caracteres.",
            file=sys.stderr,
        )
        return 2

    identifiant = os.environ.get("SUPERSET_ADMIN_USERNAME", "admin")
    mot_de_passe_admin = os.environ.get("SUPERSET_ADMIN_PASSWORD", "")
    if not mot_de_passe_admin:
        print("SUPERSET_ADMIN_PASSWORD absent.", file=sys.stderr)
        return 2

    client = Client(BASE, identifiant, mot_de_passe_admin)
    id_role = _role()
    id_user = _utilisateur(client, mot_de_passe, id_role)
    print(f"Role « {NOM_ROLE} » : {len(PERMISSIONS)} droit(s) de lecture, id {id_role}.")
    print(
        f"Compte « {NOM_UTILISATEUR} » : id {id_user}, mot de passe pris dans SUPERSET_DEMO_PASSWORD."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
