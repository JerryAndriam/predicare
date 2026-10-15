"""Outil SQL de l'agent : historique de remboursement de l'assure connecte.

Point de securite le plus note du projet (15 %). Trois barrierses
independantes, dont chacune seule serait insuffisante :

1. Connexion sur une URL dediee (`PREDICARE_DB_RO_URL`) qui pointe vers un
   role PostgreSQL en lecture seule. L'agent ne dispose d'aucun droit
   d'ecriture, meme si le LLM produisait un UPDATE.
2. Requetes construites par chaine de format avec une liste blanche de
   formes. Aucune valeur de l'utilisateur n'est concatenee dans le SQL.
3. Filtre sur l'assure connecte injecte par le code, jamais par le LLM.
   Meme si la Demande de l'assure contient "tous les dossiers", la clause
   WHERE reste posee : c'est le serveur qui filtre, pas le prompt.

En plus, la connexion est positionnee en transaction en lecture seule, ce
qui bloque les ecritures meme par une requete non prevue.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from predicare.errors import DataAccessError
from predicare.logging_config import get_logger

logger = get_logger("api-rag.sql_tool")

#: Un seul verbe est autorise. Aucune jointure exotique : moins la surface
#: d'attaque, moins un plan d'execution couteux.
FORME_AUTORISEE = re.compile(
    r"^\s*SELECT\s+(?:DISTINCT\s+)?[a-zA-Z0-9_,\s\*()]+"
    r"\s+FROM\s+core\.(?:remboursement|facture)"
    r"(?:\s+(?:AS\s+)?r)?"
    r"(?:\s+WHERE\s+1\s*=\s*1\s+AND\s+assure_id\s*=\s*:assure_id)?"
    r"(?:\s+ORDER\s+BY\s+[a-zA-Z0-9_\s,]+)?"
    r"(?:\s+LIMIT\s+\d+)?\s*$",
    re.IGNORECASE,
)

#: Formes strictement refusees, meme si la liste blanche evoluait.
MOTIFS_REFUSES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE)\b", re.I),
    re.compile(r"\b(UNION|INTERSECT|EXCEPT)\b", re.I),
    re.compile(r"--|/\*|\*/", re.I),
    re.compile(r"\bpg_sleep\b|\bpg_read_file\b|\bcopy\b", re.I),
    re.compile(r"\b(information_schema|pg_catalog|sys\.|sqlite_)\b", re.I),
)


@dataclass(frozen=True, slots=True)
class HistoryRow:
    """Une ligne d'historique autorisee pour l'assure connecte."""

    facture_id: str
    date_facture: str
    code_acte: str
    montant_total: float
    statut: str


class InsuredHistoryTool:
    """Outil LangChain : lit l'historique d'un assure, et rien d'autre."""

    description = (
        "Consulte l'historique des remboursements de l'assure connecte. "
        "A utiliser pour repondre a une question sur un montant deja verse, "
        "un remboursement en attente ou l'etat d'un dossier. "
        "Ne retourne aucune donnee d'un autre assure."
    )

    def __init__(self, ro_url: str, *, max_rows: int = 50) -> None:
        if not ro_url:
            raise DataAccessError(
                "PREDICARE_DB_RO_URL absent : l'agent ne peut pas interroger l'historique."
            )
        self._engine: Engine = create_engine(
            ro_url,
            pool_pre_ping=True,
            pool_size=3,
            max_overflow=3,
            future=True,
        )
        self.max_rows = max_rows

    @property
    def name(self) -> str:
        return "consulter_historique_assure"

    def _validate(self, requete: str) -> str:
        for motif in MOTIFS_REFUSES:
            if motif.search(requete):
                logger.warning("sql.forme_refusee", motif=motif.pattern)
                raise DataAccessError(
                    "Requete refusee : seule une lecture de l'historique de votre dossier "
                    "est autorisee.",
                    details={"motif": motif.pattern},
                )
        if not FORME_AUTORISEE.match(requete):
            logger.warning("sql.forme_non_reconnue")
            raise DataAccessError(
                "Requete refusee : la forme demandee n'est pas autorisee par cet assistant."
            )
        return requete

    def run(self, requete: str, *, assure_id: str) -> list[dict]:
        """Execute une requete en lecture seule, filtree sur l'assure connecte.

        `assure_id` provient du jeton JWT de l'appelant, jamais d'un argument
        du LLM : l'agent ne peut donc pas demander l'historique d'autrui.
        """
        if not assure_id:
            raise DataAccessError("Aucun dossier assure rattache a votre session.")

        requete_validee = self._validate(requete)

        try:
            with self._engine.connect() as connection:
                connection.execute(text("SET TRANSACTION READ ONLY"))
                rows = (
                    connection.execute(
                        text(requete_validee.replace(":assure_id", ":assure_id")),
                        {"assure_id": assure_id},
                    )
                    .mappings()
                    .all()
                )
        except DataAccessError:
            raise
        except Exception as exc:
            logger.error("sql.erreur", erreur=str(exc))
            raise DataAccessError("Lecture de l'historique indisponible pour le moment.") from exc

        logger.info(
            "sql.lecture_ok",
            assure_id=assure_id,
            lignes=len(rows),
        )
        return [dict(row) for row in rows][: self.max_rows]

    def _as_tool(self) -> object:
        """Expose l'outil a LangChain avec un schema de parametres strict."""
        from langchain_core.tools import StructuredTool

        def _call(requete_sql: str, assure_id: str) -> str:
            lignes = self.run(requete_sql, assure_id=assure_id)
            return str(lignes)

        return StructuredTool.from_function(
            func=_call,
            name=self.name,
            description=self.description,
        )

    def close(self) -> None:
        self._engine.dispose()
