"""Point d'entree du service api-core."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from predicare import db
from predicare.config import get_settings
from predicare.http import (
    ObservabilityMiddleware,
    register_exception_handlers,
    register_health_route,
)
from predicare.logging_config import configure_logging, get_logger
from predicare.metrics import publish_build
from predicare_core_api import SERVICE_NAME, __version__
from predicare_core_api.admin.router import router as admin_router
from predicare_core_api.audit.router import router as audit_router
from predicare_core_api.billing.router import router as billing_router
from predicare_core_api.decisions.router import router as decisions_router
from predicare_core_api.identity.router import router as identity_router


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(SERVICE_NAME, settings.log_level, settings.log_format)
    logger = get_logger(SERVICE_NAME)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        publish_build(SERVICE_NAME, __version__)
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
    app.state.inference_url = os.getenv("INFERENCE_API_URL", "http://api-inference:8002")
    app.state.rag_url = os.getenv("RAG_API_URL", "http://api-rag:8003")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id"],
    )
    app.add_middleware(ObservabilityMiddleware, service=SERVICE_NAME)

    register_exception_handlers(app)
    register_health_route(
        app,
        SERVICE_NAME,
        __version__,
        probes={"database": db.check_database},
    )

    for router in (identity_router, billing_router, decisions_router, admin_router, audit_router):
        app.include_router(router, prefix="/api/core")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("predicare_core_api.main:app", host="0.0.0.0", port=8001)
