"""Authentification : connexion, profil, changement de mot de passe."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from predicare.audit import journaliser
from predicare.auth import create_access_token, hash_password, verify_password
from predicare.config import get_settings
from predicare.db import session_scope
from predicare.dependencies import CurrentUser
from predicare.errors import InvalidInputError, UnauthorizedError
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
                "auth.echec",
                email=payload.email,
                request_id=getattr(request.state, "request_id", None),
            )
            raise UnauthorizedError("Identifiants invalides.")

        # `last_login` est ecrit dans la meme transaction que la validation :
        # l'ecran d'administration affiche ainsi une date reelle, pas la date
        # de creation du compte.
        session.execute(
            text("UPDATE core.utilisateur SET last_login = now() WHERE id = :user_id"),
            {"user_id": row["id"]},
        )
        # La connexion est un evenement sensible au sens RGPD/AI Act : elle
        # est tracee dans la meme transaction que la mise a jour de
        # `last_login`, donc jamais perdue si l'ecriture reussit.
        journaliser(
            session,
            acteur=str(row["id"]),
            role=str(row["role"]),
            action="connexion",
            cible=f"compte:{row['id']}",
        )

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
    profil = None
    try:
        identifiant = int(user.subject)
    except (TypeError, ValueError):
        identifiant = None

    if identifiant is not None:
        with session_scope() as session:
            profil = (
                session.execute(
                    text(
                        """
                        SELECT u.display_name, u.last_login,
                               a.pseudonyme AS assured_pseudonym
                        FROM core.utilisateur u
                        LEFT JOIN core.assure a ON a.id = u.assured_id
                        WHERE u.id = :identifiant
                        """
                    ),
                    {"identifiant": identifiant},
                )
                .mappings()
                .first()
            )

    # Le pseudonyme vient du dossier assure quand le compte en a un ; sinon on
    # retombe sur l'entier du jeton. Afficher un identifiant technique a la
    # place d'un pseudonyme serait une fuite de la cle interne.
    pseudonyme = profil["assured_pseudonym"] if profil else None
    if pseudonyme is None and user.insured_id is not None:
        pseudonyme = str(user.insured_id)

    return ProfileResponse(
        subject=user.subject,
        role=user.role,
        assured_pseudonym=pseudonyme,
        display_name=profil["display_name"] if profil else None,
        last_login=profil["last_login"] if profil else None,
    )


class PasswordChange(BaseModel):
    """Changement de mot de passe : contrat explicite, bornes incluses."""

    model_config = ConfigDict(extra="forbid")

    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


@router.post("/password")
def change_password(payload: PasswordChange, user: CurrentUser) -> dict[str, str]:
    """Change le mot de passe de l'utilisateur connecte.

    L'ancien mot de passe est verifie, le nouveau est hache, et le journal
    enregistre l'operation. Le compte est cible par l'identifiant du jeton,
    jamais par un parametre client : on ne peut pas changer le mot de passe
    d'un autre.
    """
    if payload.old_password == payload.new_password:
        raise InvalidInputError("Le nouveau mot de passe doit differer de l'ancien.")

    if not str(user.subject).isdigit():
        raise UnauthorizedError("Compte sans identifiant exploitable.")

    with session_scope() as session:
        hache = session.execute(
            text("SELECT password_hash FROM core.utilisateur WHERE id = :user_id"),
            {"user_id": int(user.subject)},
        ).scalar()
        if hache is None or not verify_password(payload.old_password, str(hache)):
            raise UnauthorizedError("Ancien mot de passe incorrect.")

        session.execute(
            text("UPDATE core.utilisateur SET password_hash = :hache WHERE id = :user_id"),
            {"hache": hash_password(payload.new_password), "user_id": int(user.subject)},
        )
        journaliser(
            session,
            acteur=user.subject,
            role=str(user.role),
            action="mot_de_passe_change",
            cible=f"compte:{user.subject}",
        )

    logger.info("auth.mot_de_passe_change", user_id=user.subject)
    return {"status": "ok", "message": "Mot de passe modifie."}
