"""Liste les mots ASCII restants dans les textes AFFICHES du front.

Compliment de `accents_front.py` : ce script ne modifie rien, il dit ce
qui reste a accentuer, et ou. Il ne regarde QUE le texte affichable :
le texte JSX et les litteraux de chaine qui ne ressemblent pas a une
valeur technique.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"

TEXTE_JSX = re.compile(r">([^<>{}()\[\];=|&?!*`\"'/\\\n]{2,300})<")
CHAINE = re.compile(r"('(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\")")
MOT = re.compile(r"[A-Za-z]{3,}")

#: Mots francais a accentuer : serves de temoin. Un mot de cette liste
#: encore en ASCII dans un texte affichable n'a pas ete traite.
TEMOIN = {
    "a",
    "acces",
    "apres",
    "applique",
    "appliquee",
    "caractere",
    "controle",
    "donnees",
    "etat",
    "etre",
    "modele",
    "operation",
    "piece",
    "precis",
    "qualite",
    "reference",
    "registre",
    "resultat",
    "securite",
    "systeme",
    "tracee",
    "valide",
    "verifie",
}


def textes(chemin: Path):
    texte = chemin.read_text(encoding="utf-8")
    for m in TEXTE_JSX.finditer(texte):
        yield m.group(1)
    for m in CHAINE.finditer(texte):
        interieur = m.group(0)[1:-1]
        if any(c in interieur for c in "_/\\{}$=():;,<>@#"):
            continue
        yield interieur


def main() -> None:
    total: Counter[str] = Counter()
    for chemin in sorted(RACINE.rglob("*.ts*")):
        for bloc in textes(chemin):
            for mot in MOT.findall(bloc):
                if mot.lower() in TEMOIN:
                    total[mot] += 1
    for mot, compte in sorted(total.items(), key=lambda item: (-item[1], item[0])):
        print(f"{compte:4d}  {mot}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
