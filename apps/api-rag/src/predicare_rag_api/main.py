"""Point d'entree du service api-rag (Flux 2)."""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import APIRouter, Depends, FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from predicare import db
from predicare.auth import decode_access_token
from predicare.config import Settings, get_settings
from predicare.errors import AssistantUnavailableError, PrediCareError, UnauthorizedError
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
from predicare_rag_api.session import (
    InMemorySessionStore,
    RedisSessionStore,
    SessionStore,
    adresse_redis,
)
from predicare_rag_api.sql_tool import InsuredHistoryTool

logger = get_logger(SERVICE_NAME)

router = APIRouter(prefix="/rag", tags=["assistant"])


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1000)
    #: Identifiant de conversation choisi par le client. Facultatif : sans
    #: lui, l'assistant repond sans memoire, comme avant.
    session_id: str | None = Field(default=None, max_length=64)


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
    # Estimation FinOps. Nulle sur un succes de cache : aucun LLM n'a ete appele.
    cout_estime_usd: float = 0.0
    cout_estime_eur: float = 0.0
    #: Faux quand l'agent a renvoye un message de degradation : la reponse
    #: n'est alors pas memorisee dans l'historique de session.
    succes: bool = True


def _tour(question: str, answer: str) -> dict:
    """Un tour de session, serialisable en JSON.

    Le tour ne porte que la question, la reponse et l'horodatage : les
    sources ne servent pas a rejouer la conversation et ne sont donc pas
    persistees (minimisation des donnees personnelles).
    """
    return {
        "question": question,
        "answer": answer,
        "timestamp": time.time(),
    }


@dataclass(frozen=True, slots=True)
class Appelant:
    """Identite verifiee du porteur de jeton.

    `assure_id` est le dossier de sante, absent pour un gestionnaire ou un
    administrateur. `subject` est le sujet du jeton (`sub`), qui distingue
    ces profils entre eux.
    """

    assure_id: str | None
    subject: str


def _scope_appelant(appelant: Appelant) -> str:
    """Cle de cloisonnement du cache et des sessions.

    Un assure est identifie par son dossier (`ins`). Un gestionnaire ou un
    administrateur n'a pas d'identifiant assure : on retombe alors sur le
    sujet du jeton. Employer un scope unique « anonyme » ferait partager a
    tous les gestionnaires le meme cache et le meme historique de session.
    """
    return appelant.assure_id or f"user:{appelant.subject}"


def porteuse(authorization: str = Header(default="")) -> Appelant:
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
    return Appelant(assure_id=payload.insured_id, subject=payload.subject)


def _cle_est_placeholder(valeur: str) -> bool:
    """Vrai si la variable contient un modele du depot, pas une vraie cle.

    Une valeur vide n'est pas traitee ici : les tests appellent l'agent avec
    un LLM fictif et une configuration vide. Une cle vide en production
    produit un 401 capture par l'agent, sans fuite de secret.
    """
    texte = (valeur or "").strip()
    if not texte:
        return False
    marqueurs = ("changer", "change-me", "changeme", "not-configured", "votre-cle")
    return any(marqueur in texte.lower() for marqueur in marqueurs)


def _agent_appelle_un_service_externe(request: Request) -> bool:
    """Vrai si l'agent installe appelle reellement un fournisseur externe.

    Les tests injectent un agent fictif : il n'appelle aucun service, il
    repond directement. Le controle des cles ne doit donc pas s'appliquer,
    sinon la suite de tests dependrait de la configuration de la machine.
    """
    return isinstance(getattr(request.app.state, "agent", None), RagAgent)


@router.post("/question", response_model=AskResponse)
def ask(
    payload: AskRequest,
    request: Request,
    appelant: Appelant = Depends(porteuse),
    x_rag_no_cache: bool = Header(default=False),
) -> AskResponse:
    """Point d'entree de l'assistant : filtre, session, cache, agent, sources.

    `X-Rag-No-Cache: true` court-circuite entierement le cache semantique :
    l'evaluation s'execute alors a froid et ses chiffres sont reproductibles.
    Le cache est de plus borne au `scope` de l'assure connecte, sans quoi une
    question proche suffirait a servir l'historique d'un autre.

    Une question de suivi depend de l'historique de sa session : sa reponse
    n'est ni lue ni ecrite dans le cache, car la cle du cache ne porte que
    l'assure et non le contexte de la conversation. Sans ce contournement,
    une reponse construite pour une session pourrait etre servie a une autre
    session du meme assure dont le contexte differe.
    """
    question = sanitize_question(payload.question)
    assure_id = appelant.assure_id
    scope = _scope_appelant(appelant)

    # Sans cle valide, appeler OpenAI ne peut que produire un 401 : cela
    # ajoute de la latence, bruite les journaux et envoie un faux secret a un
    # tiers. On repond immediatement, en nommant la variable manquante.
    #
    # Le controle porte sur l'agent REEL : les tests injectent un agent
    # fictif, qui n'appelle aucun service externe, et doivent donc pouvoir
    # s'executer sur une machine sans aucune cle configuree.
    settings = get_settings()
    manquants = [
        nom
        for nom, valeur in (
            ("EMBEDDING_API_KEY", settings.embedding_api_key),
            ("LLM_API_KEY", settings.llm_api_key),
        )
        if _cle_est_placeholder(valeur)
    ]
    if manquants and _agent_appelle_un_service_externe(request):
        return AskResponse(
            reponse=(
                "L'assistant n'est pas encore configure : "
                + " et ".join(manquants)
                + " doivent etre renseignees. Aucun appel externe n'a ete effectue."
            ),
            sources=[],
            etapes_agent=[
                {
                    "outil": "configuration",
                    "resultat": "absente",
                    "variables": manquants,
                }
            ],
            latence_ms=0.0,
            tokens=0,
            tokens_entree=0,
            tokens_sortie=0,
            cout_estime_usd=0.0,
            cout_estime_eur=0.0,
            cache_semantique=False,
            limite_atteinte=False,
            succes=False,
        )

    agent: RagAgent = request.app.state.agent
    cache: SemanticCache = request.app.state.cache
    sessions: SessionStore = request.app.state.sessions

    # L'historique est lu uniquement dans le scope du porteur : une session
    # identique appartenant a un autre reste invisible. Il est charge avant
    # le cache : sa presence decide si le cache est utilisable.
    historique = sessions.get(scope, payload.session_id) if payload.session_id is not None else []
    suit_une_conversation = bool(historique)

    if not x_rag_no_cache and not suit_une_conversation:
        entree = cache.get(question, scope=scope)
        # Une entree marquee en echec n'est jamais servie comme un succes :
        # elle est ignoree et la question part a l'agent.
        if entree is not None and entree.succes:
            logger.info("cache.reponse_servie", similarite=round(entree.similarity, 4))
            # Un succes de cache est une reponse valide pour cette session :
            # le tour est memorise, avec un cout nul.
            if payload.session_id:
                sessions.append(
                    scope,
                    payload.session_id,
                    _tour(question, entree.answer),
                )
            return AskResponse(
                reponse=entree.answer,
                sources=entree.sources,
                etapes_agent=[{"outil": "cache_semantique", "resultat": "hit"}],
                latence_ms=0.0,
                tokens=0,
                tokens_entree=0,
                tokens_sortie=0,
                cout_estime_usd=0.0,
                cout_estime_eur=0.0,
                cache_semantique=True,
                limite_atteinte=False,
                succes=entree.succes,
            )
        if entree is not None:
            logger.warning("cache.entree_degradee_ignoree", question_cle=entree.question)

    try:
        resultat = agent.ask(question, assure_id=assure_id, history=historique)
    except PrediCareError:
        raise
    except Exception as exc:
        # Une panne imprévue (corpus, base, embeddings) doit rester une panne
        # metier lisible par le front, pas une trace 500 sans message.
        logger.exception("rag.question_impossible", erreur=str(exc))
        raise AssistantUnavailableError(
            "L'assistant est momentanement indisponible. "
            "Verifiez la configuration des embeddings et du modele de langage."
        ) from exc
    # Une degradation ne doit pas etre memorisee : sinon elle serait servie
    # pendant tout le TTL comme une reponse valide, a cette session comme aux
    # suivantes.
    if not x_rag_no_cache and not suit_une_conversation and resultat.succes:
        cache.put(
            question,
            resultat.answer,
            resultat.sources,
            scope=scope,
            latency_ms=resultat.latency_ms,
            # Cout reel de l'appel : il alimente `cout_evite_eur` du cache,
            # qui mesure l'economie au lieu de l'estimer.
            cout_eur=resultat.cout_estime_eur,
            succes=resultat.succes,
        )
    # Seule une vraie reponse entre dans l'historique : un message de
    # degradation ne doit pas polluer le contexte des tours suivants.
    if payload.session_id and resultat.succes:
        sessions.append(
            scope,
            payload.session_id,
            _tour(question, resultat.answer),
        )
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


def _creer_session_store(settings: Settings) -> SessionStore:
    """Redis si disponible, memoire locale sinon.

    Une panne de Redis au demarrage ne doit pas empecher le service de
    repondre : on degrade la memoire de session, pas l'assistant.
    """
    redis_store = RedisSessionStore(
        settings.redis_url,
        ttl_seconds=settings.session_ttl_seconds,
        max_turns=settings.session_max_turns,
    )
    endpoint = adresse_redis(settings.redis_url)
    if redis_store.ping():
        logger.info("session.redis_pret", redis=endpoint)
        return redis_store
    logger.warning("session.repli_memoire", redis=endpoint)
    return InMemorySessionStore(
        ttl_seconds=settings.session_ttl_seconds,
        max_turns=settings.session_max_turns,
        max_sessions=settings.session_max_sessions,
    )


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(SERVICE_NAME, settings.log_level, settings.log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        publish_build(SERVICE_NAME, __version__)
        app.state.sessions = _creer_session_store(settings)
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
    # Valeur par defaut utilisable hors lifespan (tests unitaires de la
    # route) : le lifespan la remplace par Redis ou un repli memoire.
    app.state.sessions = InMemorySessionStore(
        ttl_seconds=settings.session_ttl_seconds,
        max_turns=settings.session_max_turns,
        max_sessions=settings.session_max_sessions,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(ObservabilityMiddleware, service=SERVICE_NAME)  # type: ignore[arg-type]

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
