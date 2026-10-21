"""Archive l'etat du tableau de bord Superset, et le reapplique.

Deux actions, un seul fichier d'etat :

* `export` : capture l'etat VIVANT du tableau -- les `form_data` des douze
  tuiles, la mise en page, les filtres natifs -- dans un JSON versionne
  (`ops/superset/dashboards/pilotage-mensuel.json`). C'est l'operation a
  lancer apres avoir modifie le tableau dans l'interface : le depot devient
  alors la reference.

* `apply` : rejoue cet etat. Le tableau est reconstruit a partir du depot,
  quel que soit ce qui a ete fait dans l'interface entre-temps.

Le detail des regles est dans `dashboard_etat.py`, module partage avec le
verificateur.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dashboard_etat import Client, appliquer, chemin_archive, exporter


def main(argv: list[str] | None = None) -> int:
    action = (argv or sys.argv[1:] or ["export"])[0]
    slug = os.environ.get("SUPERSET_DASHBOARD", "pilotage-mensuel")
    identifiant = os.environ.get("SUPERSET_ADMIN_USERNAME", "admin")
    mot_de_passe = os.environ.get("SUPERSET_ADMIN_PASSWORD", "")
    if not mot_de_passe:
        print("SUPERSET_ADMIN_PASSWORD absent.", file=sys.stderr)
        return 2

    client = Client(
        os.environ.get("SUPERSET_URL", "http://localhost:8088"), identifiant, mot_de_passe
    )
    chemin = chemin_archive(slug)

    if action == "export":
        etat = exporter(client, chemin, slug)
        print(
            f"Etat exporte : {chemin} "
            f"({len(etat['tuiles'])} tuile(s), {len(etat['position_json'])} noeud(s))."
        )
        return 0
    if action == "apply":
        nombre = appliquer(client, chemin, slug)
        print(f"Etat reapplique : {nombre} tuile(s) depuis {chemin}.")
        return 0
    print(f"Action inconnue : {action} (attendu : export, apply).", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
