"""Authentification : hachage des mots de passe et jetons JWT.

L'agent RAG et les API partagent ce module : un seul endroit ou la regle de
validite d'un jeton est decidee, donc aucune divergence entre services.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from predicare.config import get_settings
from predicare.errors import UnauthorizedError
from predicare.rbac import Role

_hasher = PasswordHasher()


# --------------------------------------------------------------------------
# Mots de passe
# --------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """Hache un mot de passe (Argon2id). Jamais de MD5/SHA dans ce projet."""
    if len(password) < 12:
        raise ValueError("Le mot de passe doit contenir au moins 12 caracteres.")
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verifie sans lever : un login invalide n'est pas une erreur technique."""
    try:
        _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return True


# --------------------------------------------------------------------------
# Jetons
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TokenPayload:
    """Contenu verifie d'un jeton d'acces."""

    subject: str
    role: Role
    insured_id: str | None
    expires_at: datetime
    token_use: str = "access"


def create_access_token(
    *,
    subject: str,
    role: Role,
    insured_id: str | None = None,
    expires_minutes: int | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Emet un jeton HS256 pour un utilisateur authentifie."""
    settings = get_settings()
    minutes = expires_minutes or settings.jwt_expire_minutes
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": str(role),
        "ins": insured_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
        "jti": uuid.uuid4().hex,
        "token_use": "access",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> TokenPayload:
    """Verifie la signature, l'expiration et l'usage du jeton.

    On refuse explicitement un jeton de type autre que `access` : un jeton
    emis pour un autre usage ne doit jamais ouvrir une session API.
    """
    settings = get_settings()
    try:
        claims = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Jeton expire.") from exc
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Jeton invalide.") from exc

    if claims.get("token_use") != "access":
        raise UnauthorizedError("Type de jeton refuse.")

    role_value = claims.get("role")
    try:
        role = Role(str(role_value))
    except ValueError as exc:
        raise UnauthorizedError("Role inconnu dans le jeton.") from exc

    return TokenPayload(
        subject=str(claims.get("sub", "")),
        role=role,
        insured_id=claims.get("ins"),
        expires_at=datetime.fromtimestamp(claims["exp"], tz=UTC),
    )
