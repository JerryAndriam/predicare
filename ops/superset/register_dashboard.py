"""Applique le tableau de bord de reference, archive dans le depot.

Le modele
---------
Les douze tuiles ne sont PLUS decrites ici. Elles sont creees dans
l'interface Superset, puis archivees dans
`ops/superset/dashboards/pilotage-mensuel.json` (`make bi-export`). Ce script
se contente de rejouer cette archive : le tableau est ainsi toujours celui
du depot, quel que soit ce qui a ete fait dans l'interface entre-temps.

Ecrire les tuiles en Python a ete la source d'une longue serie d'erreurs :
la forme du `form_data` attendu par un plugin de Superset 6.1 n'a rien de
comun avec la forme qu'un humain obtient en cliquant, et l'ecart se voit
seulement dans le navigateur (« Empty query », « Duplicate column/metric
labels »). L'interface, elle, produit une forme toujours valide.

Ce que fait ce script
---------------------
1. cree le tableau s'il n'existe pas (titre, slug, publie) ;
2. applique l'archive : chaque tuile est creee ou mise a jour, la mise en
   page est reecrite en remappant les identifiants, les metadonnees sont
   reappliquees ;
3. rattache les douze tuiles au tableau.

Pieges de l'API, tous constates a l'execution
----------------------------------------------
* l'authentification passe par `POST /api/v1/security/login`, qui renvoie un
  jeton ; la session de formulaire du navigateur est refusee par
  `/api/v1/*` avec « Missing Authorization Header » ;
* le jeton CSRF est exige EN PLUS du jeton d'acces, et il se prend sur
  `/api/v1/security/csrf_token/` ;
* le parametre de requete `q` des listes est encode en **Rison**, pas en
  texte libre : un titre brut repond « Not a valid rison/json argument » ;
* l'API des roles n'expose que la LECTURE : un role se cree par le
  gestionnaire de securite de Superset, pas par l'API ;
* l'association d'un graphique a un tableau n'est plus ecrite par l'API
  (`/api/v1/dashboard/<id>/charts` ne repond qu'en GET) : elle passe par la
  table de liaison `dashboard_slices`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dashboard_etat import Client, appliquer, chemin_archive

TITRE_DASHBOARD = "Pilotage mensuel — PrediCare TPA"
SLUG = "pilotage-mensuel"


def _assurer_tableau(client: Client) -> int:
    """Cree le tableau s'il n'existe pas, et rend son identifiant."""
    for tableau in client.lister("/api/v1/dashboard/"):
        if tableau.get("slug") == SLUG:
            return int(tableau["id"])
    cree = client._json(
        "POST",
        "/api/v1/dashboard/",
        {"dashboard_title": TITRE_DASHBOARD, "slug": SLUG, "published": True},
    )
    print(f"  tableau cree : {TITRE_DASHBOARD} (id {cree['id']})")
    return int(cree["id"])


def _rattacher(id_dash: int, identifiants: list[int]) -> None:
    """Rattache les graphiques au dashboard.

    L'API ne le permet plus : dans Superset 6, la route
    `/api/v1/dashboard/<id>/charts` n'expose que `GET` -- `POST` comme `PUT`
    repondent « 405 Method Not Allowed ». L'association se fait donc par la
    table de liaison `dashboard_slices`.

    C'est une table de metadonnees de l'outil, pas une donnee du projet :
    elle n'apparait dans aucun rapport et disparait avec un `down -v`, ce
    qui est le comportement voulu puisque le tableau est reconstruit a
    chaque `make bi-dashboard`.
    """
    import sqlalchemy as sa
    from superset import db as superset_db
    from superset.app import create_app

    application = create_app()
    with application.app_context():
        from superset.models.dashboard import Dashboard, dashboard_slices
        from superset.models.slice import Slice

        tableau = superset_db.session.get(Dashboard, id_dash)
        if tableau is None:
            raise RuntimeError(f"tableau {id_dash} introuvable.")
        existants = {
            slice_id
            for (slice_id,) in superset_db.session.execute(
                sa.select(dashboard_slices.c.slice_id).where(
                    dashboard_slices.c.dashboard_id == id_dash
                )
            )
        }
        for identifiant in identifiants:
            graphique = superset_db.session.get(Slice, identifiant)
            if graphique is None:
                continue
            if identifiant not in existants:
                superset_db.session.execute(
                    sa.insert(dashboard_slices).values(dashboard_id=id_dash, slice_id=identifiant)
                )
        # Les graphiques orphelins sont retires du tableau : le depot n'en
        # veut que douze, et un reste de plus s'afficherait en bas de page.
        for slice_id in list(existants):
            if slice_id not in identifiants:
                superset_db.session.execute(
                    sa.delete(dashboard_slices).where(
                        dashboard_slices.c.dashboard_id == id_dash,
                        dashboard_slices.c.slice_id == slice_id,
                    )
                )
        superset_db.session.commit()
    print(f"  {len(identifiants)} graphique(s) rattache(s) au dashboard {id_dash}.")


def main() -> int:
    identifiant = os.environ.get("SUPERSET_ADMIN_USERNAME", "admin")
    mot_de_passe = os.environ.get("SUPERSET_ADMIN_PASSWORD", "")
    if not mot_de_passe:
        print("SUPERSET_ADMIN_PASSWORD absent : tableau non applique.", file=sys.stderr)
        return 2

    client = Client(
        os.environ.get("SUPERSET_URL", "http://localhost:8088"), identifiant, mot_de_passe
    )
    id_dash = _assurer_tableau(client)
    chemin = chemin_archive(SLUG)
    if not chemin.exists():
        print(
            f"Aucune archive ({chemin}).\n"
            "  Le tableau se cree dans l'interface, puis `make bi-export` l'archive.",
            file=sys.stderr,
        )
        return 2
    identifiants = appliquer(client, chemin, SLUG)
    _rattacher(id_dash, identifiants)
    print(f"Dashboard « {TITRE_DASHBOARD} » : id {id_dash}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
