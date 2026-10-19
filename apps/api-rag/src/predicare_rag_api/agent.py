"""Agent ReAct LangChain : deux outils, une reponse sourcee.

Phase 5.4 du plan d'action. L'agent dispose de deux outils et de rien
d'autre : recherche dans les contrats (RAG) et lecture de l'historique de
l'assure (SQL). Il n'a pas d'outil d'ecriture, pas d'acces reseau, et sa
memoire est limitee a la conversation courante.
"""

from __future__ import annotations

import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool, Tool
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

    __slots__ = ("answer", "cached", "latency_ms", "limite_atteinte", "sources", "steps", "tokens")

    def __init__(
        self,
        answer: str,
        sources: list[dict],
        steps: list[dict],
        latency_ms: float,
        tokens: int,
        cached: bool,
        limite_atteinte: bool = False,
    ) -> None:
        self.answer = answer
        self.sources = sources
        self.steps = steps
        self.latency_ms = latency_ms
        self.tokens = tokens
        self.cached = cached
        self.limite_atteinte = limite_atteinte

    def to_dict(self) -> dict:
        return {
            "reponse": self.answer,
            "sources": self.sources,
            "etapes_agent": self.steps,
            "latence_ms": self.latency_ms,
            "tokens": self.tokens,
            "cache_semantique": self.cached,
            "limite_atteinte": self.limite_atteinte,
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
        self._max_steps = settings.rag_max_agent_steps
        self._llm = ChatOpenAI(
            base_url=settings.llm_api_base or None,
            api_key=SecretStr(settings.llm_api_key or "not-configured"),
            model=self._model_name,
            temperature=settings.llm_temperature,
            max_completion_tokens=settings.llm_max_tokens,
        )

    def _tools(self, assure_id: str) -> list[Tool]:
        def _rechercher(question: str) -> str:
            return self._retriever.format_sources(self._retriever.search(question))

        def _consulter(requete_sql: str) -> str:
            return str(self._history.run(requete_sql, assure_id=assure_id))

        search_documents = StructuredTool.from_function(
            func=_rechercher,
            name="rechercher_contrats",
            description=(
                "Recherche un passage de contrat d'assurance (article, garantie, "
                "taux de remboursement). Utilise cet outil pour toute question "
                "portant sur les garanties, plafonds, exclusions ou conditions."
            ),
        )

        read_history = StructuredTool.from_function(
            func=_consulter,
            name="consulter_historique_assure",
            description=(
                "Lit l'historique des remboursements de l'assure connecte "
                "(factures, montants, dates, statuts). "
                "Nutilise que des SELECT sur les tables core.facture et "
                "core.remboursement. Colonnes disponibles : id, assure_id, "
                "date_facture, montant_total, montant_pris_en_charge (ou "
                "montant_rembourse), statut (PAYEE/REJETEE/EN_ATTENTE), "
                "motif_rejet, date_traitement. "
                "Forme obligatoire : SELECT <colonnes> FROM core.facture "
                "WHERE 1=1 AND assure_id = :assure_id [ORDER BY ...] "
                "[LIMIT n]. Toute autre requete sera refusee. "
                "Utilise TOUJOURS le parametre :assure_id, jamais de valeur "
                "numerique. "
                "Exemple : SELECT montant_total, statut FROM core.facture "
                "WHERE 1=1 AND assure_id = :assure_id LIMIT 10."
            ),
        )
        return [search_documents, read_history]

    def ask(self, question: str, *, assure_id: str | None) -> RagAnswer:
        """Repond a une question d'assure en citant ses sources."""
        started = time.perf_counter()

        message = HumanMessage(content=build_user_context_block(question, assure_id))

        sources: list[Source] = self._retriever.search(question)
        contexte = self._retriever.format_sources(sources)

        steps: list[dict] = [
            {"outil": "rechercher_contrats", "sources": len(sources), "resultat": "ok"}
        ]

        tools = self._tools(assure_id or "")
        tool_map = {tool.name: tool for tool in tools}
        llm_avec_outils = self._llm.bind_tools(tools)

        messages: list = [
            SystemMessage(content=SYSTEM_PROMPT),
            SystemMessage(content=contexte),
            message,
        ]

        usage_tokens = 0
        texte = ""
        limite_atteinte = False
        try:
            for _ in range(self._max_steps):
                reponse: AIMessage = llm_avec_outils.invoke(messages)
                usage_tokens += _count_tokens(reponse)
                messages.append(reponse)

                if not getattr(reponse, "tool_calls", None):
                    texte = reponse.content if isinstance(reponse.content, str) else str(reponse.content)
                    break

                for appel in reponse.tool_calls:
                    nom = appel.get("name")
                    args = appel.get("args", {}) or {}
                    outil = tool_map.get(nom)
                    debut = time.perf_counter()
                    try:
                        if outil is None:
                            resultat = f"Outil inconnu : {nom}"
                            statut = "inconnu"
                        else:
                            resultat = outil.invoke(args)
                            statut = "ok"
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("agent.outil_erreur", outil=nom, erreur=str(exc))
                        resultat = f"Erreur outil : {exc}"
                        statut = "erreur"
                    duree = (time.perf_counter() - debut) * 1000
                    steps.append(
                        {
                            "outil": nom,
                            "args": args,
                            "resultat": statut,
                            "duree_ms": round(duree, 2),
                        }
                    )
                    messages.append(
                        ToolMessage(content=str(resultat), tool_call_id=appel.get("id", ""))
                    )
            else:
                limite_atteinte = True
                # Derniere tentative sans outils pour forcer une reponse.
                try:
                    reponse_finale = self._llm.invoke(messages)
                    usage_tokens += _count_tokens(reponse_finale)
                    texte = (
                        reponse_finale.content
                        if isinstance(reponse_finale.content, str)
                        else str(reponse_finale.content)
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.error("llm.erreur", erreur=str(exc), modele=self._model_name)
                    texte = (
                        "Le service de reponse est temporairement indisponible. "
                        "Vos demandes restent enregistrees et seront traitees aussitot."
                    )
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

        if not texte:
            texte = (
                "Je n'ai pas pu formuler de reponse. "
                "Reformulez votre question ou contactez votre gestionnaire."
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
            limite_atteinte=limite_atteinte,
        )


def _count_tokens(message: AIMessage) -> int:
    """Nombre de tokens de completion, pour le suivi du cout FinOps."""
    metadata = getattr(message, "usage_metadata", None) or {}
    return int(metadata.get("output_tokens", 0)) or len(str(message.content)) // 4