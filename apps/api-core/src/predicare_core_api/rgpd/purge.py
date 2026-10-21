"""Le point d'entree de la purge : `python -m predicare_core_api.rgpd.purge`.

Ce que le dossier de cadrage demande : « ecrire une politique de
conservation, ajouter des jobs de purge et un test qui verifie qu'une donnee
expiree n'est plus servie ».

La politique est dans `audit.parametre` (les durees y sont lisibles et
modifiables), la selection dans `purge.py` (testee sans base), et l'ecriture
ici. Le job supprime, dans une seule transaction, ce qui est anterieur a la
limite de chaque famille de donnees -- et il COMPTE ce qu'il supprime, pour
que la purge soit prouvee et pas supposee.

Deux facons de le declencher :

* a la main, `make purge` ou `python -m ... --appliquer` (apercu par defaut) ;
* automatiquement, par la boucle de fond d'`api-core` (voir `main.py`) qui
  appelle `executer_purge_planifiee` toutes les 24 h. Chaque execution reelle
  laisse une ligne `audit.journal` d'action `purge_planifiee`, avec le nombre
  de lignes supprimees par table : la purge est idempotente et tracee.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from predicare.audit import journaliser
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

#: Acteur et role portes par la trace d'une purge automatique : aucun
#: utilisateur n'est connecte, mais l'action doit rester attribuable.
ACTEUR_PURGE = "systeme:purge-planifiee"
ROLE_PURGE = "systeme"


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


def _cibles(
    session: Any, maintenant: datetime | None = None
) -> tuple[dict[str, int], dict[str, datetime], dict[str, list[int]]]:
    """Selectionne ce qui est expire, sans rien supprimer.

    Rend trois vues coherentes : le compte par table (le resume journalise),
    les dates de coupure (l'apercu lisible par l'exploitant) et les
    identifiants a supprimer.
    """
    durees_effectives = _durees_de_base(session)
    reference = maintenant or datetime.now(UTC)

    predictions = [
        dict(ligne)
        for ligne in session.execute(text("SELECT id, created_at FROM ml.prediction")).mappings()
    ]
    limite_predictions = date_de_purge(
        durees_effectives.get("predictions_ans", DUREES_PAR_DEFAUT["predictions_ans"]),
        maintenant=reference,
    )
    a_purger_predictions = [
        ligne["id"] for ligne in predictions if ligne["created_at"] < limite_predictions
    ]

    factures = [
        dict(ligne)
        for ligne in session.execute(text("SELECT id, date_facture FROM core.facture")).mappings()
    ]
    limite_factures = date_de_purge(
        durees_effectives.get("factures_ans", DUREES_PAR_DEFAUT["factures_ans"]),
        maintenant=reference,
    )
    a_purger_factures = [
        ligne["id"] for ligne in factures if ligne["date_facture"] < limite_factures
    ]

    journal = [
        dict(ligne)
        for ligne in session.execute(text("SELECT id, created_at FROM audit.journal")).mappings()
    ]
    limite_journal = date_de_purge(
        durees_effectives.get("audit_ans", DUREES_PAR_DEFAUT["audit_ans"]),
        maintenant=reference,
    )
    a_purger_journal = [ligne["id"] for ligne in journal if ligne["created_at"] < limite_journal]

    resume = {
        "predictions": len(a_purger_predictions),
        "factures": len(a_purger_factures),
        "journal": len(a_purger_journal),
    }
    limites = {
        "predictions": limite_predictions,
        "factures": limite_factures,
        "journal": limite_journal,
    }
    identifiants = {
        "predictions": a_purger_predictions,
        "factures": a_purger_factures,
        "journal": a_purger_journal,
    }
    return resume, limites, identifiants


def _supprimer(session: Any, identifiants: dict[str, list[int]]) -> None:
    """Supprime les lignes expirees, des dependances vers les racines."""
    a_purger_factures = identifiants["factures"]
    a_purger_predictions = identifiants["predictions"]
    a_purger_journal = identifiants["journal"]

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


def purger(
    session: Any, *, appliquer: bool = True, maintenant: datetime | None = None
) -> dict[str, int]:
    """Purge (ou compte seulement) dans la transaction fournie.

    L'ecriture de la trace est dans la MEME transaction que les suppressions :
    ou bien la purge et sa preuve existent, ou bien aucune des deux. Le
    compteur est journalise meme quand il vaut zero : une purge planifiee qui
    n'a rien trouve est une information d'exploitation, pas un silence.
    """
    resume, _, identifiants = _cibles(session, maintenant)
    if appliquer:
        _supprimer(session, identifiants)
        journaliser(
            session,
            acteur=ACTEUR_PURGE,
            role=ROLE_PURGE,
            action="purge_planifiee",
            cible="conservation",
            details=resume,
        )
    return resume


def executer_purge_planifiee() -> dict[str, int]:
    """Le passage appele par la boucle de fond d'`api-core`.

    Ouvre sa propre session : la tache de fond ne partage pas la transaction
    d'une requete HTTP. Rend le compteur pour que l'appelant le journalise.
    """
    with session_scope() as session:
        resume = purger(session, appliquer=True)
    logger.info("purge.planifiee", **resume)
    return resume


def main() -> int:
    with session_scope() as session:
        if not APPLIQUER:
            resume, limites, _ = _cibles(session, datetime.now(UTC))
            print("Apercu de la purge (rien n'est ecrit) :")
            print(f"  predictions avant {limites['predictions'].date()} : {resume['predictions']}")
            print(f"  factures avant {limites['factures'].date()} : {resume['factures']}")
            print(f"  journal avant {limites['journal'].date()} : {resume['journal']}")
            print("  Relancez avec --appliquer pour supprimer.")
            return 0
        resume = purger(session, appliquer=True)

    logger.info("purge.appliquee", **resume)
    print(json.dumps(resume, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        dispose_engine()
