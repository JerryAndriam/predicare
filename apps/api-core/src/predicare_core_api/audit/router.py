"""Journal d'audit : trace de qui a fait quoi, et quand.

Exigence RGPD (Phase 9.3) et AI Act (traçabilite). Le journal est ecrit par
les services, jamais lu par l'agent RAG en ecriture : le compte SQL de l'agent
est en lecture seule et filtre sur l'assure connecte.
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from predicare.db import session_scope
from predicare.dependencies import CurrentUser
from predicare.logging_config import get_logger
from predicare.rbac import Role, ensure_permission

router = APIRouter(prefix="/audit", tags=["audit"])
logger = get_logger("api-core.audit")


class AuditEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    acteur: str
    role: str
    action: str
    cible: str | None = None
    details: dict | None = None
    created_at: datetime


@router.get("/journal", response_model=list[AuditEntry])
def journal(
    user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=1000),
    action: str | None = Query(default=None, max_length=64),
) -> list[AuditEntry]:
    """Journal d'audit, reserve au gestionnaire et a l'administrateur."""
    ensure_permission(user.role, "audit:lire")

    where = ""
    params: dict[str, object] = {"limit": limit}
    if action:
        where = "AND action = :action"
        params["action"] = action

    with session_scope() as session:
        rows = (
            session.execute(
                text(
                    f"""
                SELECT id, acteur, role, action, cible, details, created_at
                FROM audit.journal
                WHERE true {where}
                ORDER BY created_at DESC
                LIMIT :limit
                """
                ),
                params,
            )
            .mappings()
            .all()
        )

    return [AuditEntry(**row) for row in rows]


@router.post("/evenement")
def log_event(payload: dict, user: CurrentUser) -> dict[str, str]:
    """Ecrit un evenement dans le journal.

    Volontairement ouvert a tout utilisateur authentifie : chaque parcours de
    role doit pouvoir tracer son activité. Le contenu est tronque par la base
    (colonnes texte) et ne doit jamais contenir de PII en clair.
    """
    with session_scope() as session:
        session.execute(
            text(
                """
                INSERT INTO audit.journal (acteur, role, action, cible, details)
                VALUES (:acteur, :role, :action, :cible, CAST(:details AS jsonb))
                """
            ),
            {
                "acteur": user.subject,
                "role": str(user.role),
                "action": str(payload.get("action", "inconnu"))[:64],
                "cible": str(payload.get("cible"))[:128] if payload.get("cible") else None,
                # psycopg n'adapte pas un dict Python a une colonne jsonb :
                # on serialise explicitement, sinon l'insertion leve un 500.
                "details": json.dumps(payload.get("details") or {}, ensure_ascii=False),
            },
        )
    return {"status": "ok"}


#: Seuls ces roles Accèdent au journal complet.
AUDIT_ROLES = (Role.GESTIONNAIRE, Role.ADMINISTRATEUR)
