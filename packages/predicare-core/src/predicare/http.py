"""Briques HTTP reutilisees par les trois services API.

Factorise ici ce qui doit etre IDENTIQUE entre services : rendu des erreurs
metier en JSON, metriques de latence et de volume, en-tete de correlation.
Duplique, les compteurs et les codes d'erreur divergeraient, et le jury
compare les metriques entre services.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from predicare import metrics
from predicare.config import get_settings
from predicare.errors import PrediCareError
from predicare.logging_config import get_logger

REQUEST_ID_HEADER = "X-Request-Id"

#: Une sonde est un appel sans argument renvoyant un booleen. Elle ne doit
#: JAMAIS lever : une exception dans une sonde transformerait une panne
#: partielle en panne de demarrage du conteneur.
Probe = Callable[[], object]


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Latence, volume et erreurs pour chaque route.

    Le gabarit de route est normalise (`/factures/{id}` et non `/factures/42`)
    : sinon chaque identifiant cree une serie de metriques et le tableau de
    bord devient illisible au bout de quelques centaines de factures.
    """

    def __init__(self, app: FastAPI, *, service: str) -> None:
        super().__init__(app)
        self.service = service
        self.logger = get_logger(service)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        request.state.request_id = request_id

        route = self._route_template(request)
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            elapsed = time.perf_counter() - started
            metrics.HTTP_REQUESTS.labels(self.service, route, request.method, "500").inc()
            metrics.HTTP_LATENCY.labels(self.service, route, request.method).observe(elapsed)
            metrics.ERRORS.labels(self.service, "internal_error").inc()
            self.logger.exception(
                "http.erreur",
                path=request.url.path,
                method=request.method,
                request_id=request_id,
                duree_ms=round(elapsed * 1000, 2),
            )
            return JSONResponse(
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "code": "internal_error",
                    "message": "Erreur interne. Consultez les journaux pour le traceur.",
                    "request_id": request_id,
                },
                headers={REQUEST_ID_HEADER: request_id},
            )

        elapsed = time.perf_counter() - started
        metrics.HTTP_REQUESTS.labels(
            self.service, route, request.method, response.status_code
        ).inc()
        metrics.HTTP_LATENCY.labels(self.service, route, request.method).observe(elapsed)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    @staticmethod
    def _route_template(request: Request) -> str:
        route = request.scope.get("route")
        return getattr(route, "path", request.url.path)


def register_exception_handlers(app: FastAPI) -> None:
    """Rend chaque exception metier au format JSON `{code, message, details}`."""

    @app.exception_handler(PrediCareError)
    async def _handle_predicare_error(request: Request, exc: PrediCareError) -> JSONResponse:
        get_logger().warning(
            "http.erreur_metier",
            code=exc.code,
            path=request.url.path,
            request_id=getattr(request.state, "request_id", None),
            details=exc.details,
        )
        metrics.ERRORS.labels(request.app.state.service, exc.code).inc()
        return JSONResponse(
            status_code=exc.http_status,
            content=exc.to_payload() | {"request_id": getattr(request.state, "request_id", None)},
        )


def register_health_route(
    app: FastAPI,
    service: str,
    version: str,
    probes: dict[str, Probe],
    ready_probes: dict[str, Probe] | None = None,
) -> None:
    """Ajoute /health, /health/ready et /metrics.

    Les deux points d'entree repondent a des questions differentes, et les
    confondre rend l'orchestration inutilisable :

    - `/health` est la SONDE DE VIVACITE. Elle repond 200 des que le
      processus tient debout, et porte le detail (`ok` ou `degraded`) dans
      son corps. C'est ce que lit le jury et l'ecran d'administration.
    - `/health/ready` est la SONDE DE PRET. Elle repond 503 tant qu'une
      dependance critique manque. C'est celle que Docker et la passerelle
      utilisent pour ne pas router vers un service qui echouerait.

    Un service `degraded` mais vivant doit rester joignable : le couper
    parce qu'un modele n'est pas encore entraine rendrait la plateforme
    inutilisable au pire moment.

    `ready_probes` restreint ce qui bloque la Readiness. Par defaut, toute
    sonde le fait. On en retire explicitement ce qui releve de la QUALITE DU
    SERVICE plutot que de sa capacite a repondre : un modele absent rend
    l'inference degradee, elle ne la rend pas injoignable.
    """

    def _evaluer() -> tuple[bool, dict[str, bool]]:
        checks = {name: bool(probe()) for name, probe in probes.items()}
        return all(checks.values()), checks

    @app.get("/health", tags=["supervision"])
    async def health() -> JSONResponse:
        from predicare.schemas import HealthResponse

        healthy, checks = _evaluer()
        payload = HealthResponse(
            status="ok" if healthy else "degraded",
            service=service,
            version=version,
            checks=checks,
            missing_secrets=get_settings().missing_secrets(),
        )
        return JSONResponse(status_code=200, content=payload.model_dump(mode="json"))

    @app.get("/health/ready", tags=["supervision"], include_in_schema=False)
    async def ready() -> Response:
        bloquantes = ready_probes if ready_probes is not None else probes
        verifications = {name: bool(probe()) for name, probe in bloquantes.items()}
        pret = all(verifications.values())
        return JSONResponse(
            status_code=200 if pret else 503,
            content={"ready": pret, "checks": verifications},
        )

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics() -> Response:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
