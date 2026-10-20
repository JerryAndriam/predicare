"""Ecran d'administration : seuil, canaux, secrets, sante, rollback modele.

Cible : les conditions "Configurable" et "Supervisable" du jury. Aucun de ces
reglages ne doit demander de redemarrer un conteneur ni de modifier le code.
Toute route de ce module exige le role administrateur.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from predicare import db
from predicare.auth import TokenPayload, hash_password
from predicare.config import get_settings
from predicare.db import session_scope
from predicare.dependencies import get_threshold, require_permission
from predicare.errors import (
    ConflictError,
    InvalidInputError,
    ModelNotReadyError,
    NotFoundError,
)
from predicare.logging_config import get_logger
from predicare.persistance_ml import activer_version
from predicare.rbac import Role
from predicare.schemas import ModelVersionInfo

router = APIRouter(prefix="/admin", tags=["administration"])
logger = get_logger("api-core.admin")

#: Garde-fou commun : le role administrateur est verifie avant le corps de la
#: route, donc avant tout acces base et tout appel reseau sortant.
AdminUser = Annotated[TokenPayload, Depends(require_permission("seuil:modifier"))]


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
    inference_url = str(request.app.state.inference_api_url).rstrip("/")
    try:
        httpx.put(f"{inference_url}/seuil", json={"seuil": seuil}, timeout=5.0).raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("admin.seuil_non_propage", erreur=str(exc))
        return "en_attente"
    return "applique"


@router.get("/seuil")
def read_threshold(_admin: AdminUser) -> dict[str, float]:
    """Seuil courant, lu par l'ecran d'administration et par n8n."""
    return {"seuil": get_threshold()}


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
    inference_url = request.app.state.inference_api_url
    try:
        response = httpx.get(f"{inference_url}/modele", timeout=5.0)
        response.raise_for_status()
        return ModelVersionInfo(**response.json())
    except httpx.HTTPError as exc:
        logger.warning("admin.modele_injoignable", erreur=str(exc))
        return ModelVersionInfo(
            active_version=str(get_settings().model_active_version),
            threshold=get_threshold(),
        )


def _appeler_inference(request: Request, chemin: str, *, acteur: str | None = None) -> dict:
    """Appelle le registre du Flux 1, en traduisant une panne en 503 metier.

    `acteur` est le sujet du jeton administrateur. Il traverse api-core ->
    api-inference -> n8n pour que la notification de bascule nomme son auteur.
    """
    inference_url = str(request.app.state.inference_api_url).rstrip("/")
    headers = {"X-Acteur": acteur} if acteur else None
    try:
        response = httpx.post(f"{inference_url}{chemin}", headers=headers, timeout=10.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("admin.modele_action_impossible", chemin=chemin, erreur=str(exc))
        raise ModelNotReadyError(
            "Le service d'inference n'a pas pu appliquer l'operation sur le modele."
        ) from exc
    return response.json()


@router.post("/modele/candidat")
def charger_candidat(version: str, request: Request, _admin: AdminUser) -> dict[str, object]:
    """Charge une version a cote de l'active, SANS l'activer.

    C'est l'etape qui rend le deploiement sans interruption possible : le
    modele en service continue de repondre pendant que la candidate charge.
    """
    return _appeler_inference(request, f"/modele/candidat?version={version}")


@router.post("/modele/bascule")
def basculer_modele(request: Request, _admin: AdminUser) -> dict[str, object]:
    """Bascule la candidate en active, puis aligne le registre en base."""
    resultat = _appeler_inference(request, "/modele/bascule", acteur=_admin.subject)
    version = str(resultat.get("active_version", ""))
    if version:
        activer_version(version)
    return resultat


@router.post("/modele/retour-arriere")
def retour_arriere(version: str, request: Request, _admin: AdminUser) -> dict[str, object]:
    """Revient a une version deja presente sur le volume `/models`."""
    resultat = _appeler_inference(request, f"/modele/retour-arriere?version={version}")
    activer_version(version)
    return resultat


@router.get("/sante")
def sante(request: Request, _admin: AdminUser) -> dict[str, object]:
    """Sante consolidee de la plateforme, pour l'ecran de supervision.

    api-core interroge les deux autres services sur le reseau interne : le
    navigateur n'a donc pas besoin de connaitre leurs adresses, et la sonde
    reste possible meme si la passerelle est en panne.
    """
    settings = get_settings()

    def sonder(url: str) -> dict[str, object]:
        try:
            reponse = httpx.get(f"{url.rstrip('/')}/health", timeout=2.0)
            reponse.raise_for_status()
            corps = reponse.json()
            return {
                "status": str(corps.get("status", "inconnu")),
                "version": corps.get("version"),
            }
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("admin.sonde_echouee", url=url, erreur=str(exc))
            return {"status": "down", "version": None}

    try:
        base: bool = bool(db.check_database())
    except Exception:  # une sonde de sante ne doit jamais lever
        base = False

    return {
        "service": request.app.state.service,
        "version": request.app.state.version,
        "seuil": get_threshold(),
        "secrets_manquants": settings.missing_secrets(),
        "timestamp": datetime.now(UTC).isoformat(),
        "dependances": {
            "base": base,
            "inference": sonder(str(request.app.state.inference_url)),
            "rag": sonder(str(request.app.state.rag_url)),
        },
    }


# ---------------------------------------------------------------------------
# GESTION DES COMPTES
# ---------------------------------------------------------------------------
# Reservee a l'administrateur par la dependance `AdminUser`. Le mot de passe
# n'est JAMAIS renvoye : il est hache (Argon2id) a l'ecriture, et le contrat de
# sortie ne contient que des champs d'affichage.


class UserSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    email: str
    role: str
    display_name: str | None = None
    is_active: bool
    assured_pseudonyme: str | None = None
    last_login: datetime | None = None


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(
        min_length=3,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="Adresse e-mail de connexion",
    )
    password: str = Field(min_length=12, max_length=256)
    role: Role
    display_name: str | None = Field(default=None, max_length=128)
    assured_pseudonyme: str | None = Field(
        default=None,
        max_length=64,
        description="Obligatoire pour un compte assure, interdit pour les autres",
    )


class UserStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: bool


def _lire_compte(session: Session, user_id: int) -> dict:
    """Lit un compte avec le pseudonyme de son dossier, ou leve un 404."""
    ligne = (
        session.execute(
            text(
                """
                SELECT u.id, u.email, u.role, u.display_name, u.is_active,
                       a.pseudonyme AS assured_pseudonyme, u.last_login
                FROM core.utilisateur u
                LEFT JOIN core.assure a ON a.id = u.assured_id
                WHERE u.id = :user_id
                """
            ),
            {"user_id": user_id},
        )
        .mappings()
        .first()
    )
    if ligne is None:
        raise NotFoundError("Compte introuvable.")
    return dict(ligne)


@router.get("/utilisateurs", response_model=list[UserSummary])
def lister_utilisateurs(
    _admin: AdminUser,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[UserSummary]:
    """Liste des comptes, sans jamais exposer le moindre secret."""
    with session_scope() as session:
        lignes = (
            session.execute(
                text(
                    """
                    SELECT u.id, u.email, u.role, u.display_name, u.is_active,
                           a.pseudonyme AS assured_pseudonyme, u.last_login
                    FROM core.utilisateur u
                    LEFT JOIN core.assure a ON a.id = u.assured_id
                    ORDER BY u.role, u.email
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            )
            .mappings()
            .all()
        )
    return [UserSummary(**ligne) for ligne in lignes]


@router.post("/utilisateurs", response_model=UserSummary, status_code=201)
def creer_utilisateur(payload: UserCreate, _admin: AdminUser) -> UserSummary:
    """Cree un compte. Le mot de passe est hache avant d'atteindre la base."""
    email = payload.email.strip().lower()
    acteur = str(getattr(_admin, "subject", "admin"))

    with session_scope() as session:
        assure_id: int | None = None
        if payload.role == Role.ASSURE:
            if not payload.assured_pseudonyme:
                raise InvalidInputError(
                    "Un compte assure doit etre rattache a un dossier.",
                    details={"champ": "assured_pseudonyme"},
                )
            assure_id = session.execute(
                text("SELECT id FROM core.assure WHERE pseudonyme = :pseudonyme"),
                {"pseudonyme": payload.assured_pseudonyme},
            ).scalar()
            if assure_id is None:
                raise InvalidInputError(
                    "assured_pseudonyme : dossier inconnu.",
                    details={"champ": "assured_pseudonyme"},
                )
        elif payload.assured_pseudonyme:
            raise InvalidInputError(
                "assured_pseudonyme ne s'applique qu'a un compte assure.",
                details={"champ": "assured_pseudonyme"},
            )

        try:
            cree = session.execute(
                text(
                    """
                    INSERT INTO core.utilisateur
                        (email, password_hash, role, assured_id, display_name, is_active)
                    VALUES (:email, :hache, :role, :assure_id, :nom, true)
                    RETURNING id
                    """
                ),
                {
                    "email": email,
                    "hache": hash_password(payload.password),
                    "role": str(payload.role),
                    "assure_id": assure_id,
                    "nom": (payload.display_name or "").strip() or None,
                },
            ).scalar_one()
        except IntegrityError as exc:
            raise ConflictError(
                "Un compte existe deja avec cette adresse e-mail.",
                details={"champ": "email"},
            ) from exc

        ligne = _lire_compte(session, int(cree))

    logger.info("admin.compte_cree", email=email, role=str(payload.role), acteur=acteur)
    return UserSummary(**ligne)


@router.patch("/utilisateurs/{user_id}", response_model=UserSummary)
def changer_statut_compte(
    user_id: int,
    payload: UserStatusUpdate,
    _admin: AdminUser,
) -> UserSummary:
    """Active ou desactive un compte.

    Deux garde-fous : on ne se desactive pas soi-meme, et on ne retire pas le
    dernier administrateur actif. Sans eux, un mauvais clic rendrait la
    plateforme inadministrable.
    """
    acteur = str(getattr(_admin, "subject", "admin"))

    with session_scope() as session:
        cible = _lire_compte(session, user_id)

        if not payload.is_active and str(user_id) == acteur:
            raise InvalidInputError(
                "Vous ne pouvez pas desactiver votre propre compte.",
                details={"champ": "is_active"},
            )

        if (
            not payload.is_active
            and cible["role"] == str(Role.ADMINISTRATEUR)
            and cible["is_active"]
        ):
            autres = session.execute(
                text(
                    """
                    SELECT count(*) FROM core.utilisateur
                    WHERE role = :role AND is_active AND id <> :user_id
                    """
                ),
                {"role": str(Role.ADMINISTRATEUR), "user_id": user_id},
            ).scalar()
            if not autres:
                raise InvalidInputError(
                    "Impossible de desactiver le dernier administrateur actif.",
                    details={"champ": "is_active"},
                )

        session.execute(
            text("UPDATE core.utilisateur SET is_active = :actif WHERE id = :user_id"),
            {"actif": payload.is_active, "user_id": user_id},
        )
        ligne = _lire_compte(session, user_id)

    logger.info(
        "admin.compte_statut",
        compte=user_id,
        actif=payload.is_active,
        acteur=acteur,
    )
    return UserSummary(**ligne)
