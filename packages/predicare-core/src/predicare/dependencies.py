"""Dependances FastAPI partagees : identidade courante et permissions.

Point de controle unique pour les trois services. Le role est verifie avant
toute logique metier, donc avant tout acces base ou tout appel LLM : un
assure qui tente une requete hors perimetre recoit un 403 sans que la
requete n'atteigne la couche de donnees.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from predicare.auth import TokenPayload, decode_access_token
from predicare.config import get_settings
from predicare.errors import UnauthorizedError
from predicare.rbac import Role, ensure_permission, ensure_role

_bearer = HTTPBearer(auto_error=False, description="Jeton d'acces issued par /auth/login")


def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> TokenPayload:
    """Extrait et verifie le jeton. 401 si absent, expire ou invalide."""
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("Authentification requise : jeton Bearer manquant.")

    payload = decode_access_token(credentials.credentials)
    request.state.role = payload.role
    request.state.subject = payload.subject
    request.state.insured_id = payload.insured_id
    return payload


CurrentUser = Annotated[TokenPayload, Depends(get_current_user)]


def require_role(required: Role) -> Callable[[TokenPayload], TokenPayload]:
    """Fabrique une dependance exigeant un role precis.

    Usage : `user: Annotated[TokenPayload, Depends(require_role(Role.GESTIONNAIRE))]`
    """

    def _dependency(user: CurrentUser) -> TokenPayload:
        ensure_role(user.role, required)
        return user

    return _dependency


def require_permission(permission: str) -> Callable[[TokenPayload], TokenPayload]:
    """Fabrique une dependance exigeant une permission fine (voir rbac.PERMISSIONS)."""

    def _dependency(user: CurrentUser) -> TokenPayload:
        ensure_permission(user.role, permission)
        return user

    return _dependency


def get_service_info(request: Request) -> dict[str, str]:
    """Nom et version du service, lus par /health et par la page d'admin."""
    return {
        "service": getattr(request.app.state, "service", "predicare"),
        "version": getattr(request.app.state, "version", "0.1.0"),
    }


def get_threshold() -> float:
    """Seuil d'alerte courant. Modifiable a chaud depuis l'ecran d'admin."""
    return get_settings().fraud_alert_threshold
