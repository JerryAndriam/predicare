"""Route d'emission du guest token pour le tableau de bord integre."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from predicare.auth import TokenPayload
from predicare.dependencies import require_permission
from predicare.logging_config import get_logger
from predicare_core_api.pilotage.superset import ClientSuperset

router = APIRouter(prefix="/pilotage", tags=["pilotage"])
logger = get_logger("api-core.pilotage")

PilotageUser = Annotated[TokenPayload, Depends(require_permission("pilotage:consulter"))]


class GuestTokenResponse(BaseModel):
    token: str
    dashboard_uuid: str


@router.post("/guest-token")
def guest_token(request: Request, response: Response, _user: PilotageUser) -> GuestTokenResponse:
    """Retourne un token court pour afficher le dashboard dans l'iframe.

    Le token est signe par Superset et ne contient que l'acces au dashboard.
    Il n'est jamais journalise : seuls le sujet et l'UUID le sont.
    """
    response.headers["Cache-Control"] = "no-store"
    with ClientSuperset(
        str(request.app.state.superset_url),
        str(request.app.state.superset_username),
        str(request.app.state.superset_password),
    ) as client:
        jeton = client.demander_jeton(str(request.app.state.superset_dashboard_slug))

    logger.info(
        "pilotage.jeton_emis",
        sujet=str(getattr(_user, "subject", "")),
        dashboard_uuid=jeton.dashboard_uuid,
    )
    return GuestTokenResponse(token=jeton.token, dashboard_uuid=jeton.dashboard_uuid)
