"""Le point d'entree de la purge : `python -m predicare_core_api.rgpd.purge`.

Ce que le dossier de cadrage demande : « ecrire une politique de
conservation, ajouter des jobs de purge et un test qui verifie qu'une donnee
expiree n'est plus servie ».

La politique est dans `audit.parametre` (les durees y sont lisibles et
modifiables), la selection dans `purge.py` (testee sans base), et l'ecriture
ici. Le job supprime, dans une seule transaction, ce qui est anterieur a la
limite de chaque famille de donnees -- et il COMPTE ce qu'il supprime, pour
que la purge soit prouvee et pas supposee.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from predicare.db import dispose_engine, session_scope
from predicare.logging_config import configure_logging, get_logger
from predicare_core_api.rgpd.conservation import (
    DUREES_PAR_DEFAUT,
    date_de_purge,
    durees,
)

configure_logging("api-core", "INFO", "text")
logger = get_logger("api-core.purge")

#: La purge est une operation de masse : elle est irreversible, donc le
#: defaut est l'APERCU. Le `--appliquer` est explicite.
APPLIQUER = "--appliquer" in sys.argv


def _durees_de_base(session: Any) -> dict[str, int]:
    lignes = session.execute(
        text(
            """
            SELECT cle, valeur FROM audit.parametre
            WHERE cle LIKE 'duree_conservation_%'
            """
        )
    ).fetchall()
    return durees({str(ligne[0]): str(ligne[1]) for ligne in lignes})


def main() -> int:
    resume: dict[str, int] = {}
    with session_scope() as session:
        durees_effectives = _durees_de_base(session)
        maintenant = datetime.now(UTC)

        predictions = [
            dict(ligne)
            for ligne in session.execute(
                text("SELECT id, created_at FROM ml.prediction")
            ).mappings()
        ]
        limite_predictions = date_de_purge(
            durees_effectives.get("predictions_ans", DUREES_PAR_DEFAUT["predictions_ans"]),
            maintenant=maintenant,
        )
        a_purger_predictions = [
            ligne["id"] for ligne in predictions if ligne["created_at"] < limite_predictions
        ]

        factures = [
            dict(ligne)
            for ligne in session.execute(
                text("SELECT id, date_facture FROM core.facture")
            ).mappings()
        ]
        limite_factures = date_de_purge(
            durees_effectives.get("factures_ans", DUREES_PAR_DEFAUT["factures_ans"]),
            maintenant=maintenant,
        )
        a_purger_factures = [
            ligne["id"] for ligne in factures if ligne["date_facture"] < limite_factures
        ]

        journal = [
            dict(ligne)
            for ligne in session.execute(
                text("SELECT id, created_at FROM audit.journal")
            ).mappings()
        ]
        limite_journal = date_de_purge(
            durees_effectives.get("audit_ans", DUREES_PAR_DEFAUT["audit_ans"]),
            maintenant=maintenant,
        )
        a_purger_journal = [
            ligne["id"] for ligne in journal if ligne["created_at"] < limite_journal
        ]

        resume = {
            "predictions": len(a_purger_predictions),
            "factures": len(a_purger_factures),
            "journal": len(a_purger_journal),
        }

        if not APPLIQUER:
            print("Apercu de la purge (rien n'est ecrit) :")
            print(f"  predictions avant {limite_predictions.date()} : {resume['predictions']}")
            print(f"  factures avant {limite_factures.date()} : {resume['factures']}")
            print(f"  journal avant {limite_journal.date()} : {resume['journal']}")
            print("  Relancez avec --appliquer pour supprimer.")
            return 0

        if a_purger_factures:
            session.execute(
                text(
                    """
                    DELETE FROM ml.shap_explication WHERE prediction_id IN (
                        SELECT p.id FROM ml.prediction p
                        JOIN core.facture f ON f.id = p.facture_id
                        WHERE f.id = ANY(:ids)
                    )
                    """
                ),
                {"ids": a_purger_factures},
            )
            session.execute(
                text(
                    """
                    DELETE FROM ml.prediction WHERE facture_id = ANY(:ids)
                    """
                ),
                {"ids": a_purger_factures},
            )
            session.execute(
                text("DELETE FROM core.ligne_facture WHERE facture_id = ANY(:ids)"),
                {"ids": a_purger_factures},
            )
            session.execute(
                text("DELETE FROM core.facture WHERE id = ANY(:ids)"),
                {"ids": a_purger_factures},
            )
        if a_purger_predictions:
            session.execute(
                text(
                    """
                    DELETE FROM ml.shap_explication
                    WHERE prediction_id IN (SELECT id FROM ml.prediction WHERE id = ANY(:ids))
                    """
                ),
                {"ids": a_purger_predictions},
            )
            session.execute(
                text("DELETE FROM ml.prediction WHERE id = ANY(:ids)"),
                {"ids": a_purger_predictions},
            )
        if a_purger_journal:
            session.execute(
                text("DELETE FROM audit.journal WHERE id = ANY(:ids)"),
                {"ids": a_purger_journal},
            )

    logger.info("purge.appliquee", **resume)
    print(json.dumps(resume, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        dispose_engine()
