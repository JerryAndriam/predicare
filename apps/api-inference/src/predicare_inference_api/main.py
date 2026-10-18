"""Point d'entree du service api-inference (Flux 1)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

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
from predicare.persistance_ml import amorcer_seuil_effectif, lire_seuil_effectif
from predicare_inference_api import SERVICE_NAME, __version__
from predicare_inference_api.registry import ModelRegistry
from predicare_inference_api.router import router as inference_router


def create_app(*, worker: bool = False) -> FastAPI:
    """Construit l'application.

    Le parametre `worker` sert au job d'ingestion et de suivi de derive :
    meme image, meme code, mais aucune API exposee et une boucle de fond a
    la place. Un seul Dockerfile, deux usages.
    """
    settings = get_settings()
    configure_logging(SERVICE_NAME, settings.log_level, settings.log_format)
    logger = get_logger(SERVICE_NAME)

    def _restaurer_seuil(registre: ModelRegistry) -> None:
        """Le seuil en vigueur survit au redemarrage du service.

        Deux sens : un seuil deja choisi par un administrateur est reapplique
        (sans quoi un redemarrage annulerait silencieusement son reglage),
        sinon le seuil du modele est inscrit en base pour que la file du
        gestionnaire et l'ecran d'administration affichent le meme chiffre que
        le service d'inference.
        """
        if registre.seuil_impose is not None:
            # L'exploitation a fixe le seuil : il prime sur ce qui est
            # enregistre, et devient la valeur de reference de la plateforme.
            amorcer_seuil_effectif(registre.threshold)
            return
        enregistre = lire_seuil_effectif()
        if enregistre is not None:
            registre.set_threshold(enregistre)
        else:
            amorcer_seuil_effectif(registre.threshold)

    registry = ModelRegistry(
        model_dir=Path(os.getenv("MODEL_DIR", settings.model_dir)),
        threshold=settings.fraud_alert_threshold,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        publish_build(SERVICE_NAME, __version__)
        try:
            registry.load_version(os.getenv("MODEL_ACTIVE_VERSION", "1"))
        except Exception as exc:
            # Le service demarre quand meme et /health signale "degraded" :
            # c'est preferable a un conteneur qui refuse de demarrer pendant
            # qu'un modele est entrainement.
            logger.warning("modele.non_charge", erreur=str(exc))
        else:
            _restaurer_seuil(registry)

        if worker:
            logger.info("worker.demarrage", mode="ingestion_et_derive")
        else:
            logger.info("service.pret", version=__version__, modele=registry.state())
        yield
        db.dispose_engine()
        logger.info("service.arret")

    app = FastAPI(
        title="PrediCare - API inference",
        description="Flux 1 : validation, scoring XGBoost, explicabilite SHAP, derive.",
        version=__version__,
        lifespan=lifespan,
        # Le worker n'expose aucune route : inutile de monter la documentation.
        docs_url=None if worker else "/api/inference/docs",
        openapi_url=None if worker else "/api/inference/openapi.json",
    )
    app.state.service = SERVICE_NAME
    app.state.version = __version__
    app.state.registry = registry
    app.state.drift_report = None

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # `service` est un mot-cle : l'annot de `add_middleware` suppose une
    # factory positionnelle, ce que le type ne peut pas voir.
    app.add_middleware(ObservabilityMiddleware, service=SERVICE_NAME)  # type: ignore[arg-type]

    register_exception_handlers(app)
    register_health_route(
        app,
        SERVICE_NAME,
        __version__,
        probes={
            # `registry.active` leve une exception quand rien n'est charge :
            # une sonde ne doit pas lever, elle doit repondre faux.
            # Un modele absent rend le service DEGRADE, pas mort : le service
            # doit rester joignable pour que l'ecran d'administration explique
            # pourquoi aucune facture n'est notee.
            "modele_charge": lambda: registry.state().get("active_version") is not None,
            "database": db.check_database,
        },
        # Seule la base conditionne la Readiness : sans modele, le service
        # est degraded et `/health` l'annonce, mais il reste routable.
        ready_probes={"database": db.check_database},
    )
    app.include_router(inference_router, prefix="/api/inference")
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("predicare_inference_api.main:app", host="0.0.0.0", port=8002)
