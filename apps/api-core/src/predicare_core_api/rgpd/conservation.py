"""La politique de conservation : les durees et le calcul des coupures.

Les durees ne sont pas une opinion : elles sont un engagement pris devant la
personne concernee et devant le regulateur. Le dossier de cadrage les fixe
(3 ans pour les predictions, 10 ans pour les factures, 5 ans pour le journal
d'audit) et exige « un test qui verifie qu'une donnee expiree n'est plus
servie ».

Ce module porte la PART pure de la regle -- le calcul des coupures et la
selection des lignes -- pour qu'elle soit testable sans base. La partie SQL
est dans `purge.py`, qui appelle ces fonctions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

#: Les durees de conservation, en annees. Elles viennent du dossier de
#: cadrage (section 2.5) et sont surchargeables par `audit.parametre`.
DUREES_PAR_DEFAUT: dict[str, int] = {
    "predictions_ans": 3,
    "factures_ans": 10,
    "audit_ans": 5,
}


def date_de_purge(annees: int, *, maintenant: datetime | None = None) -> datetime:
    """La date de coupure : ce qui est anterieur est purge.

    Une annee vaut 365 jours : la purge est un acte d'exploitation, elle ne
    doit pas dependre du calendrier bissextile.
    """
    reference = maintenant or datetime.now(UTC)
    return reference - timedelta(days=annees * 365)


def lignes_a_purger(
    lignes: list[dict[str, Any]], limite: datetime, *, champ: str = "cree_le"
) -> list[dict[str, Any]]:
    """Les lignes anterieures a la limite, les plus anciennes d'abord.

    Le tri rend la purge deterministe : deux executions successives
    suppriment le meme lot, et le journal des suppressions se lit dans
    l'ordre chronologique.
    """
    eligible = [
        ligne
        for ligne in lignes
        if isinstance(ligne.get(champ), datetime) and ligne[champ] < limite
    ]
    return sorted(eligible, key=lambda ligne: ligne[champ])


def durees(durees_personnalisees: dict[str, str] | None = None) -> dict[str, int]:
    """Les durees effectives, surchargeables par `audit.parametre`."""
    resultat = dict(DUREES_PAR_DEFAUT)
    for cle, valeur in (durees_personnalisees or {}).items():
        if cle in resultat:
            try:
                resultat[cle] = int(valeur)
            except (TypeError, ValueError):
                continue
    return resultat
