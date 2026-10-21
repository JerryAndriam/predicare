"""Point d'entree du service api-core."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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
from predicare_core_api.pilotage.router import router as pilotage_router
from predicare_core_api.rgpd.router import router as rgpd_router


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(SERVICE_NAME, settings.log_level, settings.log_format)
    logger = get_logger(SERVICE_NAME)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        publish_build(SERVICE_NAME, __version__)
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
    # Profil BI optionnel : api-core ne depend pas de Superset au demarrage.
    # L'endpoint de guest token renvoie 503 si le service est absent.
    app.state.superset_url = os.getenv("SUPERSET_URL", "http://superset:8088").rstrip("/")
    app.state.superset_username = os.getenv("SUPERSET_BI_USERNAME", "predicare-bi")
    app.state.superset_password = os.getenv("SUPERSET_BI_PASSWORD", "")
    app.state.superset_dashboard_slug = os.getenv("SUPERSET_DASHBOARD_SLUG", "pilotage-mensuel")

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
        pilotage_router,
    ):
        app.include_router(router, prefix="/api/core")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("predicare_core_api.main:app", host="0.0.0.0", port=8001)
