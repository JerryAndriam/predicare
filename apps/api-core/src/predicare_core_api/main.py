"""Point d'entree du service api-core."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from predicare import db
from predicare.config import get_settings
from predicare.db import session_scope
from predicare.http import (
    ObservabilityMiddleware,
    register_exception_handlers,
    register_health_route,
)
from predicare.logging_config import configure_logging, get_logger
from predicare.metrics import publish_build
from predicare.secrets import appliquer_secrets
from predicare_core_api import SERVICE_NAME, __version__
from predicare_core_api.admin.router import router as admin_router
from predicare_core_api.audit.router import router as audit_router
from predicare_core_api.billing.router import router as billing_router
from predicare_core_api.decisions.router import router as decisions_router
from predicare_core_api.identity.router import router as identity_router
from predicare_core_api.rgpd import purge as purge_rgpd
from predicare_core_api.rgpd.router import router as rgpd_router

#: Delai avant le premier passage de la purge planifiee. Assez long pour ne
#: jamais peser sur un demarrage ni sur une demonstration ; le job tourne
#: ensuite toutes les 24 h. Reglable pour les tests et l'exploitation.
PURGE_DELAI_INITIAL_DEFAUT_S = 60.0
PURGE_INTERVALLE_DEFAUT_S = 24 * 60 * 60.0


def _secondes(nom: str, defaut: float) -> float:
    """Lit une duree en secondes, en ignorant une valeur illisible."""
    valeur = os.getenv(nom)
    if valeur is None:
        return defaut
    try:
        return max(0.0, float(valeur))
    except ValueError:
        return defaut


def purge_planifiee_activee() -> bool:
    """`PURGE_PLANIFIEE=0` desactive la boucle ; tout le reste l'active."""
    valeur = os.getenv("PURGE_PLANIFIEE", "1").strip().lower()
    return valeur not in {"0", "false", "non", "no", "off"}


async def boucle_purge(logger) -> None:
    """Tache de fond : un premier passage differe, puis un toutes les 24 h.

    La purge est synchrone (SQLAlchemy) : elle part dans un thread pour ne
    pas bloquer la boucle d'evenements. Une erreur n'arrete pas le service :
    on la journalise et on reessaie au tour suivant.
    """
    await asyncio.sleep(_secondes("PURGE_DELAI_INITIAL_SECONDS", PURGE_DELAI_INITIAL_DEFAUT_S))
    while True:
        try:
            resume = await asyncio.to_thread(purge_rgpd.executer_purge_planifiee)
            logger.info("purge.planifiee.execution", **resume)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - base indisponible
            logger.warning("purge.planifiee.erreur", erreur=str(exc))
        await asyncio.sleep(_secondes("PURGE_INTERVALLE_SECONDS", PURGE_INTERVALLE_DEFAUT_S))


def demarrer_purge_planifiee(logger) -> asyncio.Task[None] | None:
    """Demarre la tache si elle est active, sinon rend `None`.

    Rend la tache pour que le `lifespan` puisse l'annuler proprement a
    l'arret ; c'est aussi le point d'entree teste sans lancer l'application.
    """
    if not purge_planifiee_activee():
        logger.info("purge.planifiee.desactivee")
        return None
    return asyncio.create_task(boucle_purge(logger), name="purge-planifiee")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(SERVICE_NAME, settings.log_level, settings.log_format)
    logger = get_logger(SERVICE_NAME)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        publish_build(SERVICE_NAME, __version__)
        tache_purge = demarrer_purge_planifiee(logger)
        # Les secrets ecrits en base PRIMENT sur l'environnement : c'est ce
        # qui permet de corriger un canal depuis l'ecran d'administration
        # sans redemarrer la plateforme entiere. Le secret de la cle
        # maitresse (Fernet) reste, lui, dans l'environnement : la base ne
        # contient que des valeurs chiffrees.
        try:
            with session_scope() as session:
                surcharge = appliquer_secrets(settings, session)
            if surcharge:
                logger.info("service.secrets_de_base", secrets=",".join(surcharge))
        except Exception as exc:  # pragma: no cover - base indisponible
            logger.warning("service.secrets_illisible", erreur=str(exc))
        logger.info(
            "service.pret",
            version=__version__,
            seuil=settings.fraud_alert_threshold,
            secrets_manquants=settings.missing_secrets(),
        )
        yield
        if tache_purge is not None:
            tache_purge.cancel()
            with suppress(asyncio.CancelledError):
                await tache_purge
        db.dispose_engine()
        logger.info("service.arret")

    app = FastAPI(
        title="PrediCare - API coeur",
        description="Socle d'exploitation : identites, factures, decisions, administration.",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/core/docs",
        openapi_url="/api/core/openapi.json",
    )
    app.state.service = SERVICE_NAME
    app.state.version = __version__
    # URL interne du Flux 1 : utilisee par l'ecran d'administration pour
    # pousser le seuil et lire l'etat du modele sans passer par n8n.
    # `inference_url` reste la racine (sonde /health) ; les routes metier
    # vivent sous /api/inference, comme derriere la passerelle.
    inference_base = os.getenv("INFERENCE_API_URL", "http://api-inference:8002").rstrip("/")
    app.state.inference_url = inference_base
    app.state.inference_api_url = f"{inference_base}/api/inference"
    app.state.rag_url = os.getenv("RAG_API_URL", "http://api-rag:8003")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id"],
    )
    app.add_middleware(ObservabilityMiddleware, service=SERVICE_NAME)  # type: ignore[arg-type]

    register_exception_handlers(app)
    register_health_route(
        app,
        SERVICE_NAME,
        __version__,
        probes={"database": db.check_database},
    )

    for router in (
        identity_router,
        billing_router,
        decisions_router,
        admin_router,
        audit_router,
        rgpd_router,
    ):
        app.include_router(router, prefix="/api/core")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("predicare_core_api.main:app", host="0.0.0.0", port=8001)
