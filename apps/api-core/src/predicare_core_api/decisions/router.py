"""File d'alertes, detail explicable et decisions du gestionnaire.

Le parcours gestionnaire repose sur trois lectures et une ecriture :

- la file des alertes au-dessus du seuil courant ;
- le DETAIL d'une alerte, avec les contributions SHAP qui justifient le
  score : sans elles, le gestionnaire ne peut ni expliquer ni contester la
  decision du modele ;
- l'historique des decisions, pour la tracabilite ;
- l'enregistrement de la decision (valider / rejeter / demander une piece).

Le controle d'acces est applique cote API, avant toute requete base : un
assure ne peut pas lire la file d'alertes, meme en connaissant l'URL.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from predicare.audit import journaliser
from predicare.auth import TokenPayload
from predicare.db import session_scope
from predicare.dependencies import get_threshold, require_permission
from predicare.errors import NotFoundError
from predicare.logging_config import get_logger
from predicare.schemas import ManagerDecision, ShapContribution

router = APIRouter(prefix="/alertes", tags=["alertes"])
logger = get_logger("api-core.decisions")

#: Traduction de la decision du gestionnaire vers le statut metier de la
#: facture. Sans elle, l'assure continuait de voir « recue » apres une fraude
#: confirmee : la decision restait dans le schema ML, invisible pour lui.
STATUT_FACTURE: dict[str, str] = {
    "valider_fraude": "fraude_confirmee",
    "rejeter": "rejetee",
    "demander_piece": "piece_demandee",
}

AlertReader = Annotated[TokenPayload, Depends(require_permission("alerte:lire"))]
AlertDecider = Annotated[TokenPayload, Depends(require_permission("alerte:decider"))]
AuditReader = Annotated[TokenPayload, Depends(require_permission("audit:lire"))]


class AlerteSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prediction_id: str
    facture_id: str
    assure_pseudonyme: str
    score_fraude: float
    montant_total: float
    statut: str
    created_at: datetime


class AlerteDetail(AlerteSummary):
    """Alerte enrichie du rapport SHAP, affiche au gestionnaire."""

    shap: list[ShapContribution] = []


@router.get("/file", response_model=list[AlerteSummary])
def file_alertes(
    user: AlertReader,
    limit: int = Query(default=50, ge=1, le=200),
    statut: str = Query(default="nouvelle"),
) -> list[AlerteSummary]:
    """File d'alertes, triee par score decroissant.

    Le seuil courant est relu a chaque appel : un changement de seuil depuis
    l'ecran d'administration s'applique immediatement, sans redemarrage
    (condition "Configurable" du jury).
    """
    with session_scope() as session:
        rows = (
            session.execute(
                text(
                    """
                SELECT p.id::text AS prediction_id, p.facture_id::text AS facture_id,
                       a.pseudonyme AS assure_pseudonyme, p.score_fraude,
                       f.montant_total, p.statut, p.created_at
                FROM ml.prediction p
                JOIN core.facture f ON f.id = p.facture_id
                JOIN core.assure a ON a.id = f.assure_id
                WHERE p.score_fraude >= :seuil AND p.statut = :statut
                ORDER BY p.score_fraude DESC
                LIMIT :limit
                """
                ),
                {"seuil": get_threshold(), "statut": statut, "limit": limit},
            )
            .mappings()
            .all()
        )
    return [AlerteSummary(**row) for row in rows]


@router.get("/detail/{prediction_id}", response_model=AlerteDetail)
def detail_alerte(prediction_id: str, user: AlertReader) -> AlerteDetail:
    """Detail d'une alerte : le score ET les contributions qui l'expliquent.

    Les contributions sont lues dans `ml.shap_explication`, ecrites par le
    Flux 1 au moment de la notation. L'ecran affiche donc exactement ce que
    le modele a produit, pas une reconstruction approximative.
    """
    if not prediction_id.isdigit():
        raise NotFoundError("Alerte introuvable.")

    with session_scope() as session:
        entete = (
            session.execute(
                text(
                    """
                    SELECT p.id::text AS prediction_id, p.facture_id::text AS facture_id,
                           a.pseudonyme AS assure_pseudonyme, p.score_fraude,
                           f.montant_total, p.statut, p.created_at
                    FROM ml.prediction p
                    JOIN core.facture f ON f.id = p.facture_id
                    JOIN core.assure a ON a.id = f.assure_id
                    WHERE p.id = :prediction_id
                    """
                ),
                {"prediction_id": int(prediction_id)},
            )
            .mappings()
            .first()
        )
        if entete is None:
            raise NotFoundError("Alerte introuvable.")

        contributions = (
            session.execute(
                text(
                    """
                    SELECT feature, valeur AS value, shap_value, base_value,
                           direction, libelle AS human_readable
                    FROM ml.shap_explication
                    WHERE prediction_id = :prediction_id
                    ORDER BY rang
                    """
                ),
                {"prediction_id": int(prediction_id)},
            )
            .mappings()
            .all()
        )

    return AlerteDetail(
        **entete,
        shap=[ShapContribution(**contribution) for contribution in contributions],
    )


@router.post("/decision")
def decider(payload: ManagerDecision, user: AlertDecider) -> dict[str, str]:
    """Enregistre la decision du gestionnaire (valider / rejeter / piece)."""
    if not payload.prediction_id.isdigit():
        raise NotFoundError("Alerte introuvable.")
    prediction_id = int(payload.prediction_id)

    with session_scope() as session:
        facture_id = session.execute(
            text(
                """
                UPDATE ml.prediction SET statut = :decision, decided_by = :user,
                       decided_at = :now
                WHERE id = :prediction_id
                RETURNING facture_id
                """
            ),
            {
                "decision": payload.decision,
                "user": user.subject,
                "now": payload.decided_at,
                "prediction_id": prediction_id,
            },
        ).scalar()
        if facture_id is None:
            raise NotFoundError("Alerte introuvable.")

        statut = STATUT_FACTURE[payload.decision]
        session.execute(
            text("UPDATE core.facture SET statut = :statut WHERE id = :facture_id"),
            {"statut": statut, "facture_id": int(facture_id)},
        )

        session.execute(
            text(
                """
                INSERT INTO audit.decision_gestionnaire
                    (prediction_id, decision, commentaire, decided_by, decided_at)
                VALUES (:prediction_id, :decision, :commentaire, :user, :now)
                """
            ),
            {
                "prediction_id": prediction_id,
                "decision": payload.decision,
                "commentaire": payload.commentaire,
                "user": user.subject,
                "now": payload.decided_at,
            },
        )

        journaliser(
            session,
            acteur=user.subject,
            role=str(user.role),
            action="decision_alerte",
            cible=f"prediction:{prediction_id}",
            details={
                "decision": payload.decision,
                "facture_id": int(facture_id),
                "statut_facture": statut,
                "commentaire": payload.commentaire,
            },
        )

    logger.info(
        "decision.prise",
        prediction_id=prediction_id,
        decision=payload.decision,
        gestionnaire=user.subject,
        role=str(user.role),
    )
    return {"status": "ok", "prediction_id": payload.prediction_id}


@router.get("/historique")
def historique(user: AuditReader, limit: int = Query(default=100, ge=1, le=500)) -> list[dict]:
    """Historique des decisions, exigence du parcours gestionnaire."""
    with session_scope() as session:
        rows = (
            session.execute(
                text(
                    """
                SELECT d.prediction_id::text, d.decision, d.commentaire,
                       d.decided_at, p.score_fraude
                FROM audit.decision_gestionnaire d
                JOIN ml.prediction p ON p.id = d.prediction_id
                ORDER BY d.decided_at DESC
                LIMIT :limit
                """
                ),
                {"limit": limit},
            )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]
