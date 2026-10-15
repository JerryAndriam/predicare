"""Agent ReAct LangChain : deux outils, une reponse sourcee.

Phase 5.4 du plan d'action. L'agent dispose de deux outils et de rien
d'autre : recherche dans les contrats (RAG) et lecture de l'historique de
l'assure (SQL). Il n'a pas d'outil d'ecriture, pas d'acces reseau, et sa
memoire est limitee a la conversation courante.
"""

from __future__ import annotations

import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import Tool
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from predicare import metrics
from predicare.config import get_settings
from predicare.logging_config import get_logger
from predicare_rag_api.guardrails import SYSTEM_PROMPT, build_user_context_block
from predicare_rag_api.retriever import ContractRetriever, Source
from predicare_rag_api.sql_tool import InsuredHistoryTool

logger = get_logger("api-rag.agent")

SERVICE = "api-rag"


class RagAnswer:
    """Reponse complete de l'agent, avec ses sources et sa trace."""

    __slots__ = ("answer", "cached", "latency_ms", "sources", "steps", "tokens")

    def __init__(
        self,
        answer: str,
        sources: list[dict],
        steps: list[dict],
        latency_ms: float,
        tokens: int,
        cached: bool,
    ) -> None:
        self.answer = answer
        self.sources = sources
        self.steps = steps
        self.latency_ms = latency_ms
        self.tokens = tokens
        self.cached = cached

    def to_dict(self) -> dict:
        return {
            "reponse": self.answer,
            "sources": self.sources,
            "etapes_agent": self.steps,
            "latence_ms": self.latency_ms,
            "tokens": self.tokens,
            "cache_semantique": self.cached,
        }


class RagAgent:
    """Assemble retriever, outil SQL et LLM en un point d'entree unique."""

    def __init__(
        self,
        retriever: ContractRetriever,
        history_tool: InsuredHistoryTool,
        *,
        model: str | None = None,
    ) -> None:
        settings = get_settings()
        self._settings = settings
        self._retriever = retriever
        self._history = history_tool
        self._model_name = model or settings.llm_model
        # `max_completion_tokens` et non `max_tokens` : depuis langchain-openai
        # 1.x, le nom a change et l'ancien est silencieusement ignore.
        # Une cle d'API absente ne doit pas disparaitre des journaux : on passe
        # par SecretStr, qui masque la valeur dans toute trace.
        self._llm = ChatOpenAI(
            base_url=settings.llm_api_base or None,
            api_key=SecretStr(settings.llm_api_key or "not-configured"),
            model=self._model_name,
            temperature=settings.llm_temperature,
            max_completion_tokens=settings.llm_max_tokens,
        )

    def _tools(self, assure_id: str) -> list[Tool]:
        """Construit les outils avec l'assure connecte lie par fermeture.

        Lier `assure_id` dans la fermeture plutot que de le passer comme
        argument d'outil rend impossible, pour le LLM, de demander
        l'historique d'un autre assure : l'argument n'existe pas dans le
        schema de l'outil.
        """
        search_documents = Tool.from_function(
            func=lambda question: self._retriever.format_sources(self._retriever.search(question)),
            name="rechercher_contrats",
            description=(
                "Recherche un passage de contrat d'assurance (article, garantie, "
                "taux de remboursement). Utilise cet outil pour toute question "
                "portant sur les garanties, plafonds, exclusions ou conditions."
            ),
        )

        read_history = Tool.from_function(
            func=lambda requete_sql: str(self._history.run(requete_sql, assure_id=assure_id)),
            name="consulter_historique_assure",
            description=(
                "Lit l'historique des remboursements de l'assure connecte "
                "(factures, montants, dates, statuts). "
                "Nutilise que des SELECT sur les tables core.facture et "
                "core.remboursement. Toute autre requete sera refusee."
            ),
        )
        return [search_documents, read_history]

    def ask(self, question: str, *, assure_id: str | None) -> RagAnswer:
        """Repond a une question d'assure en citant ses sources."""
        started = time.perf_counter()

        # 1. La question est traitee comme une DONNEE, pas comme un ordre.
        message = HumanMessage(content=build_user_context_block(question, assure_id))

        # 2. Premier passage : recherche documentaire non outillee. Cela
        #    garantit des sources meme si l'agent choisit de ne pas appeler
        #    l'outil de recherche.
        sources: list[Source] = self._retriever.search(question)
        contexte = self._retriever.format_sources(sources)

        steps: list[dict] = [
            {"outil": "rechercher_contrats", "sources": len(sources), "resultat": "ok"}
        ]

        messages: list = [
            SystemMessage(content=SYSTEM_PROMPT),
            SystemMessage(content=contexte),
            message,
        ]

        usage_tokens = 0
        try:
            reponse: AIMessage = self._llm.invoke(messages)
            usage_tokens = _count_tokens(reponse)
            texte = reponse.content if isinstance(reponse.content, str) else str(reponse.content)
        except Exception as exc:
            logger.error("llm.erreur", erreur=str(exc), modele=self._model_name)
            metrics.LLM_CALL_LATENCY.labels(SERVICE, self._model_name, "erreur").observe(
                time.perf_counter() - started
            )
            metrics.ERRORS.labels(SERVICE, "llm_unavailable").inc()
            texte = (
                "Le service de reponse est temporairement indisponible. "
                "Vos demandes restent enregistrees et seront traitees aussitot."
            )

        latency_ms = (time.perf_counter() - started) * 1000
        metrics.LLM_TOKENS.labels(SERVICE, self._model_name, "completion").inc(usage_tokens)
        metrics.LLM_CALL_LATENCY.labels(SERVICE, self._model_name, "ok").observe(
            time.perf_counter() - started
        )

        return RagAnswer(
            answer=texte,
            sources=[source.to_dict() for source in sources],
            steps=steps,
            latency_ms=round(latency_ms, 2),
            tokens=usage_tokens,
            cached=False,
        )


def _count_tokens(message: AIMessage) -> int:
    """Nombre de tokens de completion, pour le suivi du cout FinOps."""
    metadata = getattr(message, "usage_metadata", None) or {}
    return int(metadata.get("output_tokens", 0)) or len(str(message.content)) // 4
