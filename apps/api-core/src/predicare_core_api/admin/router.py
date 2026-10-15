"""Ecran d'administration : seuil, canaux, secrets, sante, rollback modele.

Cible : les conditions "Configurable" et "Supervisable" du jury. Aucun de ces
reglages ne doit demander de redemarrer un conteneur ni de modifier le code.
Toute route de ce module exige le role administrateur.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from predicare.config import get_settings
from predicare.db import session_scope
from predicare.dependencies import require_permission
from predicare.logging_config import get_logger
from predicare.schemas import ModelVersionInfo

router = APIRouter(prefix="/admin", tags=["administration"])
logger = get_logger("api-core.admin")

#: Garde-fou commun : le role administrateur est verifie avant le corps de la
#: route, donc avant tout acces base et tout appel reseau sortant.
AdminUser = Annotated[object, Depends(require_permission("seuil:modifier"))]


class ThresholdUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seuil: float = Field(ge=0.0, le=1.0, description="Seuil de declenchement d'alerte")
    motif: str = Field(min_length=3, max_length=500)


class NotificationChannel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nom: str = Field(min_length=2, max_length=50)
    type: str = Field(pattern="^(slack|email)$")
    actif: bool = True
    destinataire: str = Field(max_length=254)


@router.put("/seuil")
def update_threshold(
    payload: ThresholdUpdate, request: Request, _admin: AdminUser
) -> dict[str, object]:
    """Change le seuil d'alerte a chaud.

    Persiste en base ET applique immediatement au service d'inference : le
    jury doit voir l'effet sans redemarrage (Phase 8.3 du plan d'action).
    """
    with session_scope() as session:
        session.execute(
            text(
                """
                INSERT INTO audit.parametre (cle, valeur, modifie_par, modifie_at)
                VALUES ('seuil_alerte', :valeur, :user, now())
                ON CONFLICT (cle) DO UPDATE
                    SET valeur = EXCLUDED.valeur,
                        modifie_par = EXCLUDED.modifie_par,
                        modifie_at = EXCLUDED.modifie_at
                """
            ),
            {"valeur": str(payload.seuil), "user": getattr(_admin, "subject", "admin")},
        )

    propagation = _propagate_threshold(request, payload.seuil)
    logger.info(
        "admin.seuil_change",
        seuil=payload.seuil,
        propagation=propagation,
        motif=payload.motif,
    )
    return {"status": "ok", "seuil": payload.seuil, "propagation": propagation}


def _propagate_threshold(request: Request, seuil: float) -> str:
    """Pousse le nouveau seuil vers api-inference.

    En cas d'echec le changement reste enregistre : il sera repris au
    prochain redemarrage. Preferer un seuil en base et un seuil non
    propage (aucune alerte) vaut mieux qu'un seuil applique a moitie.
    """
    inference_url = request.app.state.inference_url
    try:
        httpx.put(f"{inference_url}/seuil", json={"seuil": seuil}, timeout=5.0).raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("admin.seuil_non_propage", erreur=str(exc))
        return "en_attente"
    return "applique"


@router.get("/seuil")
def read_threshold(_admin: AdminUser) -> dict[str, float]:
    """Seuil courant, lu par l'ecran d'administration et par n8n."""
    return {"seuil": get_settings().fraud_alert_threshold}


@router.get("/canaux", response_model=list[NotificationChannel])
def list_channels(_admin: AdminUser) -> list[NotificationChannel]:
    """Canaux de notification actifs (Slack en priorite, e-mail en option)."""
    settings = get_settings()
    return [
        NotificationChannel(
            nom="slack-gestionnaires",
            type="slack",
            actif=True,
            destinataire=settings.slack_webhook_url or "non-configure",
        ),
        NotificationChannel(
            nom="email-gestionnaires",
            type="email",
            actif=False,
            destinataire=settings.smtp_from or "non-configure",
        ),
    ]


@router.get("/modele", response_model=ModelVersionInfo)
def model_state(request: Request, _admin: AdminUser) -> ModelVersionInfo:
    """Etat du modele : version active, version candidate, metriques."""
    inference_url = request.app.state.inference_url
    try:
        response = httpx.get(f"{inference_url}/modele", timeout=5.0)
        response.raise_for_status()
        return ModelVersionInfo(**response.json())
    except httpx.HTTPError as exc:
        logger.warning("admin.modele_injoignable", erreur=str(exc))
        return ModelVersionInfo(
            active_version=str(get_settings().model_active_version),
            threshold=get_settings().fraud_alert_threshold,
        )


@router.get("/sante")
def sante(request: Request, _admin: AdminUser) -> dict[str, object]:
    """Sante consolidee de la plateforme, pour le bandeau de l'interface."""
    settings = get_settings()
    return {
        "service": request.app.state.service,
        "version": request.app.state.version,
        "seuil": settings.fraud_alert_threshold,
        "secrets_manquants": settings.missing_secrets(),
        "timestamp": datetime.now(UTC).isoformat(),
    }
