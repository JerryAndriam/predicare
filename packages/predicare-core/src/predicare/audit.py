"""Ecriture du journal d'audit.

Le journal est la piece commune au RGPD (tracabilite des acces) et a l'AI Act
(tracabilite des decisions). Il est ecrit dans la MEME transaction que l'action
qu'il trace : si l'action est annulee, la trace l'est aussi, et inversement.
Aucune action sensible ne doit pouvoir reussir sans laisser de ligne.

Le module est volontairement minuscule : une seule fonction, appelee par les
services qui modifient une donnee (decision, seuil, compte, canal, modele).
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def journaliser(
    session: Session,
    *,
    acteur: str,
    role: str,
    action: str,
    cible: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Ajoute une ligne au journal d'audit dans la transaction courante.

    `acteur` est l'identifiant du porteur du jeton (jamais son mot de passe),
    `cible` une reference stable et lisible (`prediction:12`, `compte:3`).
    """
    session.execute(
        text(
            """
            INSERT INTO audit.journal (acteur, role, action, cible, details)
            VALUES (:acteur, :role, :action, :cible, CAST(:details AS jsonb))
            """
        ),
        {
            "acteur": acteur,
            "role": role,
            "action": action,
            "cible": cible,
            "details": json.dumps(details or {}, ensure_ascii=False, default=str),
        },
    )
