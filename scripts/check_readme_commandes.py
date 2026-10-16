#!/usr/bin/env python3
"""Verifie que le README documente exactement les commandes de `make help`.

Aucune commande non documentee, aucune commande fantome.

Pourquoi un script plutot qu'un coup d'oeil : le Makefile compte 44 cibles et
le README doit rester aligne au fil des ajouts. Une commande oubliee n'echoit
rien -- elle est simplement absente, et l'echec n'apparait qu'au moment ou
quelqu'un la tape. Ce controle transforme cette absence silencieuse en echec
visible.

`grep -E` n'est pas utilise ici : sur cette machine, une classe de caracteres
comme `[a-z]` ne concorde pas de facon fiable sur une ligne commencant par
plusieurs espaces. Python n'a pas cette ambiguite.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
ANSI = re.compile(r"\x1b\[[0-9;]*m")
#: `make help` indente de DEUX espaces, pas quatre, et insere un code couleur
#: entre l'indentation et le nom de la cible. Les codes sont retires avant
#: comparaison : la largeur d'une tabulation rendue dans une sortie capturee
#: n'a rien de fiable.
# MULTILINE est indispensable : sans lui, `^` ne concorde qu'au tout debut de la
# sortie, et aucune commande n'est trouvee puisque l'aide commence par un titre.
LIGNE_COMMANDE = re.compile(r"^ {2}([a-z][a-z0-9-]*) ", re.MULTILINE)
REFERENCE = re.compile(r"make ([a-z][a-z0-9-]*)")


def commandes_reelles() -> set[str]:
    aide = subprocess.run(
        ["make", "help"], capture_output=True, text=True, cwd=RACINE
    )
    return set(LIGNE_COMMANDE.findall(ANSI.sub("", aide.stdout)))


def main() -> int:
    reelles = commandes_reelles()
    if not reelles:
        print("  ERREUR : aucune commande extraite de `make help`.")
        return 2

    readme = (RACINE / "README.md").read_text()
    documentees = set(REFERENCE.findall(readme))

    non_doct = sorted(reelles - documentees)
    fantomes = sorted(documentees - reelles)

    print(f"  commandes reelles (make help) : {len(reelles)}")
    print(f"  citees dans le README         : {len(documentees & reelles)}")
    if non_doct:
        print(f"  NON DOCUMENTEES               : {' '.join(non_doct)}")
    else:
        print("  non documentees               : aucune")
    if fantomes:
        print(f"  FANTOMES (inexistantes)       : {' '.join(fantomes)}")
    else:
        print("  commandes fantomes            : aucune")

    return 1 if (non_doct or fantomes) else 0


if __name__ == "__main__":
    sys.exit(main())
