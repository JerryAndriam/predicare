"""Recherche dans les contrats PDF indexes dans pgvector.

Phase 5.2 et 5.3 du plan d'action. La regle la plus importante ici est
l'obligation de citation : aucune reponse ne peut reposer sur un document
qui n'est pas retourne par cette recherche, avec sa reference.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from predicare import metrics
from predicare.config import get_settings
from predicare.logging_config import get_logger
from pydantic import SecretStr

logger = get_logger("api-rag.retriever")

SERVICE = "api-rag"


class VectorStore(Protocol):
    """Interface de recherche vectorielle, isolee du reste du service."""

    def similarity_search(
        self, query: str, *, k: int, score_threshold: float
    ) -> list[tuple[dict, float]]: ...


@dataclass(frozen=True, slots=True)
class Source:
    """Un document cite dans la reponse. Doit etre affichable tel quel."""

    contrat: str
    article: str
    garantie: str
    extrait: str
    score: float

    def to_dict(self) -> dict:
        return {
            "contrat": self.contrat,
            "article": self.article,
            "garantie": self.garantie,
            "extrait": self.extrait,
            "score": round(self.score, 4),
        }


class ContractRetriever:
    """Recherche hybride : vecteurs + mots-cles, avec citation obligatoire."""

    def __init__(self, store: VectorStore, *, top_k: int = 6, threshold: float = 0.72) -> None:
        self._store = store
        self._top_k = top_k
        self._threshold = threshold

    def search(self, question: str) -> list[Source]:
        """Retourne les extraits de contrat pertinents, tries par similarite."""
        try:
            resultats = self._store.similarity_search(
                question, k=self._top_k, score_threshold=self._threshold
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("rag.recherche_indisponible", erreur=str(exc))
            return []

        sources: list[Source] = []
        for metadata, score in resultats:
            sources.append(
                Source(
                    contrat=str(metadata.get("contrat", "contrat inconnu")),
                    article=str(metadata.get("article", "-")),
                    garantie=str(metadata.get("garantie", "-")),
                    extrait=str(metadata.get("texte", "")).strip()[:600],
                    score=float(score),
                )
            )

        sources.sort(key=lambda s: s.score, reverse=True)
        metrics.CACHE_EVENTS.labels(SERVICE, "rag_sources").inc(len(sources))
        logger.info("rag.recherche", question_len=len(question), sources=len(sources))
        return sources

    def format_sources(self, sources: list[Source]) -> str:
        """Bloc de contexte donne au LLM, avec references explicites."""
        if not sources:
            return "<sources>Aucun passage de contrat pertinent.</sources>"
        blocs = "\n\n".join(
            f"[Source {index}] Contrat : {s.contrat} - Article {s.article} "
            f"(garantie : {s.garantie})\n{s.extrait}"
            for index, s in enumerate(sources, start=1)
        )
        return f"<sources>\n{blocs}\n</sources>"


class PgVectorContractStore:
    """Store pgvector : une seule instance PostgreSQL pour tout le projet."""

    def __init__(
        self,
        connection_url: str,
        *,
        table: str = "core.document_vectorise",
        embedder: object | None = None,
    ) -> None:
        self._connection_url = connection_url
        self._table = table
        self._embedder = embedder

    def _obtenir_embedder(self) -> object:
        if self._embedder is not None:
            return self._embedder
        from langchain_openai import OpenAIEmbeddings

        settings = get_settings()
        self._embedder = OpenAIEmbeddings(
            base_url=settings.embedding_api_base or None,
            api_key=SecretStr(settings.embedding_api_key or "not-configured"),
            model=settings.embedding_model,
        )
        return self._embedder

    def similarity_search(
        self, query: str, *, k: int, score_threshold: float
    ) -> list[tuple[dict, float]]:
        from sqlalchemy import create_engine, text

        embedder = self._obtenir_embedder()
        if hasattr(embedder, "embed_query"):
            vecteur = embedder.embed_query(query)
        else:
            vecteur = embedder.embed_documents([query])[0]
        vecteur_texte = str(list(vecteur))

        engine = create_engine(self._connection_url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                rows = (
                    connection.execute(
                        text(
                            f"""
                        SELECT contrat, article, garantie, texte,
                               1 - (embedding <=> CAST(:query AS vector)) AS score
                        FROM {self._table}
                        WHERE 1 - (embedding <=> CAST(:query AS vector)) >= :seuil
                        ORDER BY embedding <=> CAST(:query AS vector)
                        LIMIT :k
                        """
                        ),
                        {"query": vecteur_texte, "seuil": score_threshold, "k": k},
                    )
                    .mappings()
                    .all()
                )
            return [(dict(row), float(row["score"])) for row in rows]
        finally:
            engine.dispose()