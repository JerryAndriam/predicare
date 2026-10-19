"""Point d'entree du service api-rag (Flux 2)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from predicare import db
from predicare.auth import decode_access_token
from predicare.config import get_settings
from predicare.errors import PrediCareError, UnauthorizedError
from predicare.http import (
    ObservabilityMiddleware,
    register_exception_handlers,
    register_health_route,
)
from predicare.logging_config import configure_logging, get_logger
from predicare.metrics import publish_build
from predicare.rbac import ensure_permission
from predicare_rag_api import SERVICE_NAME, __version__
from predicare_rag_api.agent import RagAgent
from predicare_rag_api.guardrails import sanitize_question
from predicare_rag_api.retriever import ContractRetriever, PgVectorContractStore
from predicare_rag_api.semantic_cache import SemanticCache
from predicare_rag_api.sql_tool import InsuredHistoryTool

logger = get_logger(SERVICE_NAME)

router = APIRouter(prefix="/rag", tags=["assistant"])


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1000)


class AskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reponse: str
    sources: list[dict]
    etapes_agent: list[dict]
    latence_ms: float
    tokens: int
    cache_semantique: bool
    limite_atteinte: bool = False
    # Detail du cout : `tokens` reste le total, ces deux champs permettent de
    # chiffrer separement le prompt et la completion.
    tokens_entree: int = 0
    tokens_sortie: int = 0


def porteuse(authorization: str = Header(default="")) -> str | None:
    """Identite de l'appelant, lue dans le jeton JWT.

    Sans ce controle, l'agent repondrait avec `assure_id = None` : l'outil
    d'historique refuserait de servir des donnees personnelles, mais la route
    resterait ouverte a n'importe qui. Le compte SQL de l'agent reste en
    lecture seule : le jeton ne fait que restreindre la ligne visible.
    """
    if not authorization.startswith("Bearer "):
        raise UnauthorizedError("Jeton d'acces requis pour interroger l'assistant.")
    payload = decode_access_token(authorization.removeprefix("Bearer ").strip())
    # Un profil de sante n'a pas la permission `rag:interroger` : sans ce
    # controle, la route serait ouverte a un role que la matrice exclut.
    ensure_permission(payload.role, "rag:interroger")
    return payload.insured_id


@router.post("/question", response_model=AskResponse)
def ask(
    payload: AskRequest,
    request: Request,
    assure_id: str | None = Depends(porteuse),
    x_rag_no_cache: bool = Header(default=False),
) -> AskResponse:
    """Point d'entree de l'assistant : filtre, cache, agent, sources.

    `X-Rag-No-Cache: true` court-circuite entierement le cache semantique :
    l'evaluation s'execute alors a froid et ses chiffres sont reproductibles.
    Le cache est de plus borne au `scope` de l'assure connecte, sans quoi une
    question proche suffirait a servir l'historique d'un autre.
    """
    question = sanitize_question(payload.question)
    scope = assure_id or "anonyme"

    agent: RagAgent = request.app.state.agent
    cache: SemanticCache = request.app.state.cache
    if not x_rag_no_cache:
        entree = cache.get(question, scope=scope)
        if entree is not None:
            logger.info("cache.reponse_servie", similarite=round(entree.similarity, 4))
            return AskResponse(
                reponse=entree.answer,
                sources=entree.sources,
                etapes_agent=[{"outil": "cache_semantique", "resultat": "hit"}],
                latence_ms=0.0,
                tokens=0,
                cache_semantique=True,
                limite_atteinte=False,
            )

    resultat = agent.ask(question, assure_id=assure_id)
    if not x_rag_no_cache:
        cache.put(question, resultat.answer, resultat.sources, scope=scope)
    return AskResponse(**resultat.to_dict())


@router.get("/cache/stats")
def cache_stats(request: Request) -> dict:
    """Taux de reutilisation : la preuve chiffree du gain FinOps."""
    return request.app.state.cache.stats()


@router.get("/securite")
def security_posture() -> dict:
    """Posture de securite affichee a l'administrateur (critere 15 %)."""
    return {
        "compte_sql": "lecture seule, filtre sur l'assure connecte",
        "filtre_prompt_injection": "actif",
        "separation_instruction_donnee": "actif",
        "citation_sources": "obligatoire",
        "outils_agent": ["rechercher_contrats", "consulter_historique_assure"],
        "outils_ecriture": [],
    }


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(SERVICE_NAME, settings.log_level, settings.log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        publish_build(SERVICE_NAME, __version__)
        try:
            store = PgVectorContractStore(settings.db_url)
            retriever = ContractRetriever(
                store, top_k=settings.rag_top_k, threshold=settings.rag_similarity_threshold
            )
            history_tool = InsuredHistoryTool(settings.db_ro_url)
            app.state.agent = RagAgent(retriever, history_tool)
            app.state.cache = SemanticCache(
                _EmbedderProxy(),
                threshold=settings.semantic_cache_threshold,
                ttl_seconds=settings.semantic_cache_ttl_seconds,
            )
            logger.info("service.pret", version=__version__, modele=settings.llm_model)
        except PrediCareError as exc:
            # Sans compte SQL lecture seule, l'agent n'est pas sur : on
            # demarre quand meme pour que /health explique le blocage.
            logger.error("service.demarrage_partiel", erreur=exc.message)
            app.state.agent = None
            app.state.cache = SemanticCache(_EmbedderProxy())

        yield
        db.dispose_engine()
        logger.info("service.arret")

    app = FastAPI(
        title="PrediCare - API RAG",
        description="Flux 2 : assistant agentique ReAct sur contrats et historique.",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/rag/docs",
        openapi_url="/api/rag/openapi.json",
    )
    app.state.service = SERVICE_NAME
    app.state.version = __version__

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(ObservabilityMiddleware, service=SERVICE_NAME)

    register_exception_handlers(app)
    register_health_route(
        app,
        SERVICE_NAME,
        __version__,
        probes={
            "llm_configure": lambda: bool(settings.llm_api_key),
            "compte_sql_lecture_seule": lambda: bool(settings.db_ro_url),
        },
        # Le compte SQL en lecture seule est non negociable : sans lui,
        # l'agent ne doit pas etre route. La cle LLM, elle, degrade
        # reponses sans supprimer l'acces.
        ready_probes={
            "compte_sql_lecture_seule": lambda: bool(settings.db_ro_url),
            "database": db.check_database,
        },
    )
    app.include_router(router, prefix="/api")
    return app


class _EmbedderProxy:
    """Embeddings via l'API configuree dans `.env`.

    Le cache semantique partage le meme embedder que l'indexation : des
    vecteurs produits par deux modeles differents n'ont aucun sens de
    cosine, le taux de reutilisation serait alors du bruit.
    """

    @property
    def model(self) -> str:
        return get_settings().embedding_model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        from langchain_openai import OpenAIEmbeddings

        settings = get_settings()
        client = OpenAIEmbeddings(
            base_url=settings.embedding_api_base or None,
            api_key=SecretStr(settings.embedding_api_key or "not-configured"),
            model=settings.embedding_model,
        )
        return client.embed_documents(texts)


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("predicare_rag_api.main:app", host="0.0.0.0", port=8003)


#: URL du modele expose au routeur pour le suivi FinOps.
MODEL_NAME = os.getenv("LLM_MODEL", "non-configure")
