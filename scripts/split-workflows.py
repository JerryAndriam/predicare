#!/usr/bin/env python3
"""Decoupe l'export n8n en un fichier par workflow.

`n8n export:workflow --all` produit un unique fichier JSON contenant un
tableau de workflows. On le decompose pour que chaque workflow soit son
propre fichier : c'est ce qui rend possible une revue de code lisible et un
historique Git exploitable.

Le format de sortie est volontairement minimal : le nom, les noeuds, les
connexions, les parametres et l'etat actif. Les champs internes de n8n
(`id`, `versionId`, `owner`, `shared`, `triggerCount`...) changent a chaque
execution et produiraient un diff enorme, ou pire, un faux conflit.

Usage : split-workflows.py <repertoire-cible>   (JSON lu sur stdin)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

#: Champs conserves dans le fichier versionne.
CHAMPS_CONSERVES = ("name", "nodes", "connections", "settings", "active", "pinData", "staticData")


def slugifier(nom: str) -> str:
    """Nom de fichier stable et lisible, derive du nom du workflow.

    Les accents sont conserves : un fichier `PK-Alerte-Fraude.json` se lit
    mieux qu'un `PK-alerte-fraude.json`, et la comparaison en revue de code
    n'en souffre pas.
    """
    net = re.sub(r"[^\w\-]+", "-", nom, flags=re.UNICODE).strip("-")
    return (net[:80] or "workflow") + ".json"


def separer(donnees: object, cible: Path) -> list[str]:
    """Ecrit un fichier par workflow et renvoie les noms de fichiers produits."""
    workflows = donnees if isinstance(donnees, list) else [donnees]
    ecrits: list[str] = []

    for workflow in workflows:
        if not isinstance(workflow, dict):
            continue
        nom = str(workflow.get("name", "workflow"))
        export = {champ: workflow[champ] for champ in CHAMPS_CONSERVES if champ in workflow}

        chemin = cible / slugifier(nom)
        chemin.write_text(
            json.dumps(export, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        ecrits.append(chemin.name)

    return ecrits


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage : split-workflows.py <repertoire-cible>", file=sys.stderr)
        return 1

    cible = Path(sys.argv[1])
    cible.mkdir(parents=True, exist_ok=True)

    try:
        donnees = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"Export n8n illisible : {exc}", file=sys.stderr)
        return 1

    ecrits = separer(donnees, cible)
    if not ecrits:
        print("Aucun workflow trouve dans l'export.", file=sys.stderr)
        return 1

    for nom in ecrits:
        print(f"  ecrit : {nom}")
    print(f"{len(ecrits)} workflow(s) exporte(s) dans {cible}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
