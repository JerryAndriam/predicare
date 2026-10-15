"""File d'alertes et decisions du gestionnaire (parcours gestionnaire)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from predicare.db import session_scope
from predicare.dependencies import CurrentUser, get_threshold
from predicare.logging_config import get_logger
from predicare.rbac import Role
from predicare.schemas import ManagerDecision, ShapContribution

router = APIRouter(prefix="/alertes", tags=["alertes"])
logger = get_logger("api-core.decisions")


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
    user: CurrentUser,
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


@router.post("/decision")
def decider(payload: ManagerDecision, user: CurrentUser) -> dict[str, str]:
    """Enregistre la decision du gestionnaire (valider / rejeter / piece)."""
    with session_scope() as session:
        session.execute(
            text(
                """
                UPDATE ml.prediction SET statut = :decision, decided_by = :user,
                       decided_at = :now
                WHERE id = :prediction_id
                """
            ),
            {
                "decision": payload.decision,
                "user": user.subject,
                "now": payload.decided_at,
                "prediction_id": payload.prediction_id,
            },
        ).scalar()

        session.execute(
            text(
                """
                INSERT INTO audit.decision_gestionnaire
                    (prediction_id, decision, commentaire, decided_by, decided_at)
                VALUES (:prediction_id, :decision, :commentaire, :user, :now)
                """
            ),
            {
                "prediction_id": payload.prediction_id,
                "decision": payload.decision,
                "commentaire": payload.commentaire,
                "user": user.subject,
                "now": payload.decided_at,
            },
        )

    logger.info(
        "decision.prise",
        prediction_id=payload.prediction_id,
        decision=payload.decision,
        gestionnaire=user.subject,
        role=str(user.role),
    )
    return {"status": "ok", "prediction_id": payload.prediction_id}


@router.get("/historique")
def historique(user: CurrentUser, limit: int = Query(default=100, ge=1, le=500)) -> list[dict]:
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


#: Role attendu sur ce module : gestionnaire ou administrateur.
GESTIONNAIRE = Role.GESTIONNAIRE
