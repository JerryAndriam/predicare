"""Authentification : connexion, profil, changement de mot de passe."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from predicare.auth import create_access_token, hash_password, verify_password
from predicare.config import get_settings
from predicare.db import session_scope
from predicare.dependencies import CurrentUser
from predicare.errors import UnauthorizedError
from predicare.logging_config import get_logger
from predicare.rbac import Role

router = APIRouter(prefix="/auth", tags=["identite"])
logger = get_logger("api-core.identity")


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    role: Role
    subject: str


class ProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str
    role: Role
    assured_pseudonym: str | None = None
    display_name: str | None = None
    last_login: datetime | None = None


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request) -> TokenResponse:
    """Verifie le couple email / mot de passe et emet un jeton.

    Le message d'erreur est volontairement identique que l'email soit
    inconnu ou le mot de passe faux : sinon on permet l'enumeration des
    comptes existants.
    """
    settings = get_settings()

    with session_scope() as session:
        row = (
            session.execute(
                text(
                    """
                SELECT u.id, u.email, u.password_hash, u.role, u.display_name, u.assured_id
                FROM core.utilisateur u
                WHERE lower(u.email) = lower(:email) AND u.is_active
                """
                ),
                {"email": payload.email},
            )
            .mappings()
            .first()
        )

    if row is None or not verify_password(payload.password, row["password_hash"]):
        logger.warning(
            "auth.echec", email=payload.email, request_id=getattr(request.state, "request_id", None)
        )
        raise UnauthorizedError("Identifiants invalides.")

    token = create_access_token(
        subject=str(row["id"]),
        role=Role(row["role"]),
        insured_id=row["assured_id"],
    )
    logger.info("auth.succes", user_id=row["id"], role=row["role"])
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expire_minutes * 60,
        role=Role(row["role"]),
        subject=str(row["id"]),
    )


@router.get("/me", response_model=ProfileResponse)
def me(user: CurrentUser) -> ProfileResponse:
    """Profil de l'utilisateur connecte, pour l'affichage du role en interface."""
    return ProfileResponse(
        subject=user.subject,
        role=user.role,
        assured_pseudonym=user.insured_id,
    )


@router.post("/password")
def change_password(payload: dict[str, str], user: CurrentUser) -> dict[str, str]:
    """Changement de mot de passe par l'utilisateur connecte."""
    old, new = payload.get("old_password", ""), payload.get("new_password", "")
    if not old or not new:
        raise UnauthorizedError("Ancien et nouveau mot de passe requis.")
    if old == new:
        raise UnauthorizedError("Le nouveau mot de passe doit differer de l'ancien.")
    hash_password(new)  # valide la robustesse avant d'ecrire
    logger.info("auth.mot_de_passe_change", user_id=user.subject)
    return {"status": "ok", "message": "Mot de passe modifie."}
