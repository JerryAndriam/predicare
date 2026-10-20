"""Ecran d'administration : seuil, canaux, secrets, sante, rollback modele.

Cible : les conditions "Configurable" et "Supervisable" du jury. Aucun de ces
reglages ne doit demander de redemarrer un conteneur ni de modifier le code.
Toute route de ce module exige le role administrateur.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from predicare import db
from predicare.audit import journaliser
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
    #: `configure` dit si le canal a de quoi emettre (URL, adresse). Un canal
    #: `actif` mais non configure ne peut rien envoyer : les confondre etait
    #: exactement le defaut signale a la revue (badge « actif » trompeur).
    configure: bool = False


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
        journaliser(
            session,
            acteur=str(getattr(_admin, "subject", "admin")),
            role=str(getattr(_admin, "role", "")),
            action="seuil_modifie",
            cible="parametre:seuil_alerte",
            details={"seuil": payload.seuil, "motif": payload.motif},
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


def _canaux_par_defaut() -> list[NotificationChannel]:
    """Canaux deduits de la configuration, avant surcharge administrateur."""
    settings = get_settings()
    webhook = settings.slack_webhook_url.strip()
    expeditrice = settings.smtp_from.strip()
    return [
        NotificationChannel(
            nom="slack-gestionnaires",
            type="slack",
            actif=bool(webhook),
            destinataire=webhook or "non-configure",
            configure=bool(webhook),
        ),
        NotificationChannel(
            nom="email-gestionnaires",
            type="email",
            actif=bool(expeditrice),
            destinataire=expeditrice or "non-configure",
            configure=bool(expeditrice),
        ),
    ]


def _lire_surcharge_canaux(session: Session) -> dict[str, dict]:
    """Surcharge persistee par l'ecran d'administration, cle par canal."""
    valeur = session.execute(
        text("SELECT valeur FROM audit.parametre WHERE cle = 'canaux_notification'")
    ).scalar()
    if not valeur:
        return {}
    try:
        charge = json.loads(valeur)
    except (TypeError, ValueError):
        return {}
    return charge if isinstance(charge, dict) else {}


def _canaux_effectifs(session: Session) -> list[NotificationChannel]:
    """Configuration + surcharge, dans cet ordre de priorite."""
    surcharge = _lire_surcharge_canaux(session)
    resultat: list[NotificationChannel] = []
    for canal in _canaux_par_defaut():
        reglage = surcharge.get(canal.nom)
        if isinstance(reglage, dict):
            destinataire = str(reglage.get("destinataire", canal.destinataire))
            resultat.append(
                canal.model_copy(
                    update={
                        "actif": bool(reglage.get("actif", canal.actif)),
                        "destinataire": destinataire,
                        "configure": destinataire.strip().lower() not in {"", "non-configure"},
                    }
                )
            )
        else:
            resultat.append(canal)
    return resultat


class ChannelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actif: bool
    destinataire: str = Field(min_length=1, max_length=254)


@router.get("/canaux", response_model=list[NotificationChannel])
def list_channels(_admin: AdminUser) -> list[NotificationChannel]:
    """Canaux de notification, avec leur surcharge eventuelle."""
    with session_scope() as session:
        return _canaux_effectifs(session)


@router.put("/canaux/{nom}", response_model=NotificationChannel)
def update_channel(nom: str, payload: ChannelUpdate, _admin: AdminUser) -> NotificationChannel:
    """Active/desactive un canal et fixe son destinataire, sans redeploiement."""
    connus = {canal.nom for canal in _canaux_par_defaut()}
    if nom not in connus:
        raise NotFoundError("Canal de notification inconnu.")

    acteur = str(getattr(_admin, "subject", "admin"))
    with session_scope() as session:
        surcharge = _lire_surcharge_canaux(session)
        surcharge[nom] = {
            "actif": payload.actif,
            "destinataire": payload.destinataire.strip(),
        }
        session.execute(
            text(
                """
                INSERT INTO audit.parametre (cle, valeur, modifie_par, modifie_at)
                VALUES ('canaux_notification', :valeur, :user, now())
                ON CONFLICT (cle) DO UPDATE
                    SET valeur = EXCLUDED.valeur,
                        modifie_par = EXCLUDED.modifie_par,
                        modifie_at = EXCLUDED.modifie_at
                """
            ),
            {"valeur": json.dumps(surcharge, ensure_ascii=False), "user": acteur},
        )
        journaliser(
            session,
            acteur=acteur,
            role=str(getattr(_admin, "role", "")),
            action="canal_modifie",
            cible=f"canal:{nom}",
            details={"actif": payload.actif, "destinataire": payload.destinataire.strip()},
        )
        canaux = _canaux_effectifs(session)

    logger.info("admin.canal_modifie", canal=nom, actif=payload.actif, acteur=acteur)
    return next(canal for canal in canaux if canal.nom == nom)


class TestCanal(BaseModel):
    """Resultat d'un envoi d'essai vers un canal de notification."""

    model_config = ConfigDict(extra="forbid")

    nom: str
    type: str
    envoye: bool
    message: str
    destinataire: str


@router.post("/canaux/{nom}/test", response_model=TestCanal)
def tester_canal(nom: str, _admin: AdminUser) -> TestCanal:
    """Envoie un message d'ESSAI sur un canal et dit ce qu'il s'est passe.

    Un canal « actif » dont on ignore s'il fonctionne est un canal qu'on ne
    peut pas demonstrations. Ce test ferme la boucle : l'administrateur
    clique, et voit un message envoye ou la raison de l'echec.

    Slack : POST reel sur le webhook entrant. E-mail : POST reel sur l'API
    HTTP de la boite de reception (Mailpit en developpement) ; sans relais
    configure, l'echec est dit explicitement plutot que masque.
    """
    with session_scope() as session:
        canaux = _canaux_effectifs(session)
    canal = next((item for item in canaux if item.nom == nom), None)
    if canal is None:
        raise NotFoundError("Canal de notification inconnu.")

    if not canal.configure:
        return TestCanal(
            nom=canal.nom,
            type=canal.type,
            envoye=False,
            message=(
                "Ce canal n'a pas de destinataire configure. Renseignez-le "
                "ci-dessus avant de tester."
            ),
            destinataire=canal.destinataire,
        )

    settings = get_settings()
    try:
        if canal.type == "slack":
            reponse = httpx.post(
                canal.destinataire,
                json={
                    "text": (
                        ":white_check_mark: Test PrediCare — la chaine de "
                        "notification fonctionne. Vous pouvez ignorerez ce message."
                    )
                },
                timeout=8.0,
            )
            reponse.raise_for_status()
        else:
            if not settings.smtp_api_url.strip():
                return TestCanal(
                    nom=canal.nom,
                    type=canal.type,
                    envoye=False,
                    message=(
                        "Aucun relais e-mail n'est configure sur cette machine "
                        "(SMTP_API_URL). Renseignez SMTP_HOST, SMTP_PORT et "
                        "SMTP_FROM dans le .env, puis redemarrez la plateforme."
                    ),
                    destinataire=canal.destinataire,
                )
            reponse = httpx.post(
                settings.smtp_api_url,
                json={
                    "From": {"Email": settings.smtp_from, "Name": "PrediCare"},
                    "To": [{"Email": canal.destinataire}],
                    "Subject": "Test PrediCare — canal de notification",
                    "Text": (
                        "Message d'essai envoye depuis l'ecran d'administration. "
                        "Si vous le lisez, la chaine fonctionne."
                    ),
                },
                timeout=8.0,
            )
            reponse.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("admin.canal_test_echoue", canal=nom, erreur=str(exc))
        return TestCanal(
            nom=canal.nom,
            type=canal.type,
            envoye=False,
            message=f"L'envoi a echoue : {exc}",
            destinataire=canal.destinataire,
        )

    with session_scope() as session:
        journaliser(
            session,
            acteur=str(getattr(_admin, "subject", "admin")),
            role=str(getattr(_admin, "role", "")),
            action="canal_teste",
            cible=f"canal:{canal.nom}",
            details={"envoye": True},
        )
    return TestCanal(
        nom=canal.nom,
        type=canal.type,
        envoye=True,
        message="Message d'essai envoye. Verifiez le salon ou la boite de reception.",
        destinataire=canal.destinataire,
    )


class SecretEtat(BaseModel):
    """Etat d'un secret : configure ou non, et quoi faire sinon."""

    model_config = ConfigDict(extra="forbid")

    nom: str
    variable: str
    configure: bool
    effet: str


@router.get("/secrets", response_model=list[SecretEtat])
def etat_secrets(_admin: AdminUser) -> list[SecretEtat]:
    """Inventaire des secrets necessaires, avec la variable a renseigner.

    Un secret vit dans l'ENVIRONNEMENT du conteneur : il ne peut pas etre
    ecrit par l'ecran sans redemarrage. L'ecran doit donc dire exactement
    QUOI renseigner et OU, plutot que se contenter d'afficher « manquant ».
    """
    settings = get_settings()
    return [
        SecretEtat(
            nom="Cle LLM",
            variable="LLM_API_KEY",
            configure=_secret_configure(settings.llm_api_key),
            effet="Sans elle, l'assistant conversationnel ne peut pas repondre.",
        ),
        SecretEtat(
            nom="Cle d'embedding",
            variable="EMBEDDING_API_KEY",
            configure=_secret_configure(settings.embedding_api_key),
            effet="Sans elle, aucun contrat ne peut etre indexe ni recherche.",
        ),
        SecretEtat(
            nom="Webhook Slack",
            variable="SLACK_WEBHOOK_URL",
            configure=_secret_configure(settings.slack_webhook_url),
            effet="Sans lui, aucune alerte n'atteint le canal Slack.",
        ),
        SecretEtat(
            nom="Expediteur e-mail",
            variable="SMTP_FROM",
            configure=_secret_configure(settings.smtp_from),
            effet="Sans lui, l'alerte e-mail n'est pas envoyee.",
        ),
        SecretEtat(
            nom="Webhook d'alerte",
            variable="N8N_ALERTE_WEBHOOK_URL",
            configure=_secret_configure(settings.n8n_alerte_webhook_url),
            effet="Sans lui, le parcours web ne declenche aucune notification.",
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
    resultat = _appeler_inference(request, f"/modele/candidat?version={version}")
    _journaliser_modele(_admin, "modele_candidat_charge", version, resultat)
    return resultat


@router.post("/modele/bascule")
def basculer_modele(request: Request, _admin: AdminUser) -> dict[str, object]:
    """Bascule la candidate en active, puis aligne le registre en base."""
    resultat = _appeler_inference(request, "/modele/bascule", acteur=_admin.subject)
    version = str(resultat.get("active_version", ""))
    if version:
        activer_version(version)
        _journaliser_modele(_admin, "modele_bascule", version, resultat)
    return resultat


@router.post("/modele/retour-arriere")
def retour_arriere(version: str, request: Request, _admin: AdminUser) -> dict[str, object]:
    """Revient a une version deja presente sur le volume `/models`."""
    resultat = _appeler_inference(request, f"/modele/retour-arriere?version={version}")
    activer_version(version)
    _journaliser_modele(_admin, "modele_retour_arriere", version, resultat)
    return resultat


def _journaliser_modele(
    admin: object, action: str, version: str, resultat: dict[str, object]
) -> None:
    """Trace une operation de registre : qui a bascule, et vers quelle version."""
    with session_scope() as session:
        journaliser(
            session,
            acteur=str(getattr(admin, "subject", "admin")),
            role=str(getattr(admin, "role", "")),
            action=action,
            cible=f"modele:{version}",
            details={"active_version": resultat.get("active_version"), "version": version},
        )


def _secret_configure(valeur: str) -> bool:
    """Un secret est utilisable s'il est present et n'est pas un modele."""
    texte = (valeur or "").strip()
    if not texte:
        return False
    marqueurs = ("changer", "change-me", "changeme", "not-configured", "votre-cle")
    return not any(marqueur in texte.lower() for marqueur in marqueurs)


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

    # Un conteneur RAG « healthy » peut n'avoir ni cle d'embedding ni document
    # vectorise : il repond alors a /health tout en etant incapable de citer
    # un contrat. La sonde d'administration doit le dire, sinon le jury
    # decouvre la panne au moment de poser sa premiere question.
    try:
        with session_scope() as session:
            documents = int(
                session.execute(text("SELECT count(*) FROM core.document_vectorise")).scalar_one()
            )
    except Exception:  # base indisponible : la sonde base le signale deja
        documents = 0

    rag = sonder(str(request.app.state.rag_url))
    embedding_ok = _secret_configure(settings.embedding_api_key)
    llm_ok = _secret_configure(settings.llm_api_key)
    if rag["status"] == "ok" and (not embedding_ok or documents == 0):
        rag["status"] = "degraded"
    rag.update(
        {
            "documents": documents,
            "embedding_configure": embedding_ok,
            "llm_configure": llm_ok,
        }
    )

    return {
        "service": request.app.state.service,
        "version": request.app.state.version,
        "seuil": get_threshold(),
        "secrets_manquants": settings.missing_secrets(),
        "timestamp": datetime.now(UTC).isoformat(),
        "dependances": {
            "base": base,
            "inference": sonder(str(request.app.state.inference_url)),
            "rag": rag,
        },
    }


@router.get("/observabilite")
def observabilite(
    request: Request,
    _admin: AdminUser,
    fenetre: str = Query(default="30j", pattern="^(24h|7j|30j|90j)$"),
) -> dict[str, object]:
    """Metriques d'exploitation demandees par le CDC (Supervisable).

    Le front ne joint jamais directement api-inference ni api-rag : api-core
    agrege les indicateurs et reste le seul point d'entree autorise. Chaque
    bloc est tolerant aux pannes pour que l'ecran reste lisible meme si un
    service est arrete.

    `fenetre` selectionne la periode analysee (24 heures, 7, 30 ou 90 jours).
    Sans elle, l'ecran ne montrait que des compteurs depuis toujours : la
    TENDANCE, qui est ce qu'un exploiteur cherche, n'etait pas visible.
    """
    settings = get_settings()
    heures = {"24h": 24, "7j": 24 * 7, "30j": 24 * 30, "90j": 24 * 90}[fenetre]
    resultat: dict[str, object] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "fenetre": fenetre,
        "secrets_manquants": settings.missing_secrets(),
    }

    # Volume et activite metier, lus dans la base (source de verite).
    try:
        with session_scope() as session:
            resultat["base"] = {
                "disponible": True,
                "factures": int(
                    session.execute(text("SELECT count(*) FROM core.facture")).scalar_one()
                ),
                "predictions": int(
                    session.execute(text("SELECT count(*) FROM ml.prediction")).scalar_one()
                ),
                "alertes": int(
                    session.execute(
                        text("SELECT count(*) FROM ml.prediction WHERE is_fraud")
                    ).scalar_one()
                ),
                "decisions": int(
                    session.execute(
                        text("SELECT count(*) FROM audit.decision_gestionnaire")
                    ).scalar_one()
                ),
                "journal": int(
                    session.execute(text("SELECT count(*) FROM audit.journal")).scalar_one()
                ),
            }
            # Serie quotidienne sur la fenetre : c'est elle qui donne la
            # tendance (volume de factures et nombre d'alertes).
            serie = (
                session.execute(
                    text(
                        """
                    SELECT jour::date::text AS jour,
                           count(*) AS factures,
                           count(*) FILTER (WHERE alertes > 0) AS alertes
                    FROM (
                        SELECT date_trunc('day', f.date_facture) AS jour,
                               CASE WHEN p.is_fraud THEN 1 ELSE 0 END AS alertes
                        FROM core.facture f
                        LEFT JOIN ml.prediction p ON p.facture_id = f.id
                        WHERE f.date_facture >= now() - make_interval(hours => :heures)
                    ) AS par_jour
                    GROUP BY jour
                    ORDER BY jour
                    """
                    ),
                    {"heures": heures},
                )
                .mappings()
                .all()
            )
            resultat["serie"] = [
                {
                    "jour": ligne["jour"],
                    "factures": int(ligne["factures"]),
                    "alertes": int(ligne["alertes"]),
                }
                for ligne in serie
            ]
    except Exception as exc:  # la supervision ne doit jamais lever
        logger.warning("admin.observabilite_base_echouee", erreur=str(exc))
        resultat["base"] = {"disponible": False}
        resultat["serie"] = []

    def lire_json(url: str, timeout: float = 3.0) -> dict[str, object] | None:
        try:
            reponse = httpx.get(url, timeout=timeout)
            reponse.raise_for_status()
            corps = reponse.json()
            return corps if isinstance(corps, dict) else {"valeur": corps}
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("admin.observabilite_sonde_echouee", url=url, erreur=str(exc))
            return None

    inference_api = str(request.app.state.inference_api_url).rstrip("/")
    rag = str(request.app.state.rag_url).rstrip("/")
    resultat["inference"] = lire_json(f"{inference_api}/stats") or {"disponible": False}
    resultat["derive"] = lire_json(f"{inference_api}/derive") or {"status": "indisponible"}

    # Le service RAG monte ses routes metier sous `/api` (comme les autres
    # services derriere la passerelle) : `/api/rag/cache/stats`.
    cache = lire_json(f"{rag}/api/rag/cache/stats")
    securite = lire_json(f"{rag}/api/rag/securite")
    resultat["rag"] = {
        "disponible": cache is not None or securite is not None,
        "cache": cache or {},
        "securite": securite or {},
    }
    return resultat


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
    prestataire_code: str | None = None
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
    prestataire_code: str | None = Field(
        default=None,
        max_length=64,
        description="Obligatoire pour un compte professionnel, interdit pour les autres",
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
                       a.pseudonyme AS assured_pseudonyme, p.code AS prestataire_code,
                       u.last_login
                FROM core.utilisateur u
                LEFT JOIN core.assure a ON a.id = u.assured_id
                LEFT JOIN core.prestataire p ON p.id = u.prestataire_id
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
                           a.pseudonyme AS assured_pseudonyme, p.code AS prestataire_code,
                           u.last_login
                    FROM core.utilisateur u
                    LEFT JOIN core.assure a ON a.id = u.assured_id
                    LEFT JOIN core.prestataire p ON p.id = u.prestataire_id
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
        prestataire_id: int | None = None
        if payload.role == Role.ASSURE:
            if not payload.assured_pseudonyme:
                raise InvalidInputError(
                    "Un compte assure doit etre rattache a un dossier.",
                    details={"champ": "assured_pseudonyme"},
                )
            if payload.prestataire_code:
                raise InvalidInputError(
                    "prestataire_code ne s'applique qu'a un compte professionnel.",
                    details={"champ": "prestataire_code"},
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
        elif payload.role == Role.PROFESSIONNEL_SANTE:
            if payload.assured_pseudonyme:
                raise InvalidInputError(
                    "assured_pseudonyme ne s'applique qu'a un compte assure.",
                    details={"champ": "assured_pseudonyme"},
                )
            if not payload.prestataire_code:
                raise InvalidInputError(
                    "Un compte professionnel doit etre rattache a un prestataire.",
                    details={"champ": "prestataire_code"},
                )
            prestataire_id = session.execute(
                text("SELECT id FROM core.prestataire WHERE code = :code"),
                {"code": payload.prestataire_code},
            ).scalar()
            if prestataire_id is None:
                raise InvalidInputError(
                    "prestataire_code : prestataire inconnu.",
                    details={"champ": "prestataire_code"},
                )
        else:
            if payload.assured_pseudonyme:
                raise InvalidInputError(
                    "assured_pseudonyme ne s'applique qu'a un compte assure.",
                    details={"champ": "assured_pseudonyme"},
                )
            if payload.prestataire_code:
                raise InvalidInputError(
                    "prestataire_code ne s'applique qu'a un compte professionnel.",
                    details={"champ": "prestataire_code"},
                )

        try:
            cree = session.execute(
                text(
                    """
                    INSERT INTO core.utilisateur
                        (email, password_hash, role, assured_id, prestataire_id,
                         display_name, is_active)
                    VALUES (:email, :hache, :role, :assure_id, :prestataire_id,
                            :nom, true)
                    RETURNING id
                    """
                ),
                {
                    "email": email,
                    "hache": hash_password(payload.password),
                    "role": str(payload.role),
                    "assure_id": assure_id,
                    "prestataire_id": prestataire_id,
                    "nom": (payload.display_name or "").strip() or None,
                },
            ).scalar_one()
        except IntegrityError as exc:
            raise ConflictError(
                "Un compte existe deja avec cette adresse e-mail.",
                details={"champ": "email"},
            ) from exc

        ligne = _lire_compte(session, int(cree))
        journaliser(
            session,
            acteur=acteur,
            role=str(getattr(_admin, "role", "")),
            action="compte_cree",
            cible=f"compte:{cree}",
            details={
                "email": email,
                "role": str(payload.role),
                "assured_pseudonyme": payload.assured_pseudonyme,
                "prestataire_code": payload.prestataire_code,
            },
        )

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
        journaliser(
            session,
            acteur=acteur,
            role=str(getattr(_admin, "role", "")),
            action="compte_statut",
            cible=f"compte:{user_id}",
            details={"actif": payload.is_active, "email": cible["email"]},
        )
        ligne = _lire_compte(session, user_id)

    logger.info(
        "admin.compte_statut",
        compte=user_id,
        actif=payload.is_active,
        acteur=acteur,
    )
    return UserSummary(**ligne)
