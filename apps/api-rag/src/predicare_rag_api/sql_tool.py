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

import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from predicare.errors import DataAccessError
from predicare.logging_config import get_logger

logger = get_logger("api-rag.sql_tool")

#: Forme attendue, reprise telle quelle dans les erreurs rendues au LLM.
FORME_ATTENDUE = (
    "SELECT <colonnes> FROM core.facture WHERE 1=1 AND assure_id = :assure_id "
    "[AND <predicat>] [ORDER BY ...] [LIMIT n]"
)

#: Exemple minimal, pour que le modele puisse se corriger sans deviner.
EXEMPLE_REQUETE = (
    "SELECT date_facture, montant_total, statut FROM core.facture "
    "WHERE 1=1 AND assure_id = :assure_id ORDER BY date_facture DESC LIMIT 10"
)

#: Predicat supplementaire autorise : `statut = 'PAYEE'`, `date_facture >= ...`.
#: Le nom de colonne et l'operateur sont restreints ; les valeurs sont soit un
#: parametre lie, soit un litteral simple sans point-virgule.
_PREDICAT = (
    r"[a-zA-Z0-9_]+\s*(?:=|<>|!=|>=|<=|>|<)\s*"
    r"(?::[a-zA-Z0-9_]+|'(?:[^']|'')*'|\d+(?:\.\d+)?)"
)

#: Filtre pose par le code pour l'assure connecte.
_FILTRE_ASSURE = r"assure_id\s*=\s*:assure_id"

#: Un seul verbe est autorise. Aucune jointure exotique : moins la surface
#: d'attaque, moins un plan d'execution couteux. Les predicats sont
#: restreints (`colonne operateur valeur`) ; le filtre de l'assure doit etre
#: present des qu'il y a un WHERE (verifie ensuite), sinon le modele
#: obtiendrait toutes les lignes du dossier.
FORME_AUTORISEE = re.compile(
    r"^\s*SELECT\s+(?:DISTINCT\s+)?[a-zA-Z0-9_,\s\*()]+"
    r"\s+FROM\s+core\.(?:remboursement|facture)"
    r"(?:\s+(?:AS\s+)?[a-zA-Z][a-zA-Z0-9_]*)?"
    r"(?:\s+WHERE\s+(?:"
    + _FILTRE_ASSURE
    + r"|"
    + _PREDICAT
    + r")(?:\s+AND\s+(?:"
    + _FILTRE_ASSURE
    + r"|"
    + _PREDICAT
    + r"))*)?"
    r"(?:\s+ORDER\s+BY\s+[a-zA-Z0-9_\s,]+)?"
    r"(?:\s+LIMIT\s+\d+)?\s*;?\s*$",
    re.IGNORECASE,
)

#: Formes strictement refusees, meme si la liste blanche evoluait.
MOTIFS_REFUSES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE)\b", re.I),
    re.compile(r"\b(UNION|INTERSECT|EXCEPT)\b", re.I),
    re.compile(r"--|/\*|\*/", re.I),
    re.compile(r"\bpg_sleep\b|\bpg_read_file\b|\bcopy\b", re.I),
    re.compile(r"\b(information_schema|pg_catalog|sys\.|sqlite_)\b", re.I),
    # L'assure connecte ne doit jamais etre remplace par une valeur en dur :
    # `assure_id = 2` lirait le dossier d'un autre.
    re.compile(r"\bassure_id\s*=\s*(?!:)[^\s,)]+", re.I),
)

#: Trois modeles prets a l'emploi. Ils sont exposes dans la description de
#: l'outil : le modele part d'une forme valide au lieu d'en inventer une.
TEMPLATES_REQUETES: dict[str, str] = {
    "total_rembourse": (
        "SELECT SUM(montant_pris_en_charge) FROM core.facture "
        "WHERE 1=1 AND assure_id = :assure_id AND statut = 'PAYEE'"
    ),
    "dernieres_factures": (
        "SELECT date_facture, montant_total, statut FROM core.facture "
        "WHERE 1=1 AND assure_id = :assure_id ORDER BY date_facture DESC LIMIT 10"
    ),
    "factures_rejetees": (
        "SELECT date_facture, montant_total, motif_rejet FROM core.facture "
        "WHERE 1=1 AND assure_id = :assure_id AND statut = 'REJETEE'"
    ),
}


def _details_erreur(type_erreur: str, **extra: Any) -> dict[str, Any]:
    """Details structures renvoyes au LLM pour qu'il corrige sa requete."""
    details: dict[str, Any] = {
        "type_erreur": type_erreur,
        "forme_attendue": FORME_ATTENDUE,
        "exemple": EXEMPLE_REQUETE,
    }
    details.update(extra)
    return details


def _table_hors_perimetre(requete: str) -> bool:
    """Vrai si la requete cite une table autre que facture/remboursement."""
    tables = re.findall(r"\b(?:FROM|JOIN)\s+([a-zA-Z0-9_.]+)", requete, re.IGNORECASE)
    return any(table.lower() not in {"core.facture", "core.remboursement"} for table in tables)


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
        "Ne retourne aucune donnee d'un autre assure. "
        "Tables autorisees : core.facture (id, assure_id, date_facture, "
        "montant_total, montant_pris_en_charge, statut, motif_rejet, "
        "date_traitement) et core.remboursement (id, assure_id, date_facture, "
        "date_remboursement, montant_total, montant_rembourse, statut, "
        "motif_rejet, reference). "
        "Forme obligatoire : SELECT <colonnes> FROM core.facture "
        "WHERE 1=1 AND assure_id = :assure_id [AND <predicat>] [ORDER BY ...] "
        "[LIMIT n]. Utilise toujours le parametre :assure_id, jamais une "
        "valeur numerique. "
        "Modeles de requetes autorisees : "
        f"1) total rembourse : {TEMPLATES_REQUETES['total_rembourse']} ; "
        f"2) dernieres factures : {TEMPLATES_REQUETES['dernieres_factures']} ; "
        f"3) factures rejetees : {TEMPLATES_REQUETES['factures_rejetees']}. "
        "Adapte les colonnes a la question : date_traitement pour une date "
        "de traitement, COUNT(*) pour un nombre de factures. "
        "N'utilise SUM(...) que pour un total de plusieurs factures ; pour "
        "une facture precise (la derniere, une facture rejetee), selectionne "
        "sa ligne avec ORDER BY date_facture DESC LIMIT 1. "
        "Pour un total, utilise SUM(...) dans la requete : ne calcule jamais "
        "la somme des lignes retournees."
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
                    details=_details_erreur("motif_refuse", motif=motif.pattern),
                )
        if not FORME_AUTORISEE.match(requete):
            type_erreur = "table_refusee" if _table_hors_perimetre(requete) else "forme_refusee"
            logger.warning("sql.forme_non_reconnue", type_erreur=type_erreur)
            raise DataAccessError(
                "Requete refusee : la forme demandee n'est pas autorisee par cet assistant.",
                details=_details_erreur(type_erreur),
            )
        if re.search(r"\bWHERE\b", requete, re.IGNORECASE) and not re.search(
            _FILTRE_ASSURE, requete, re.IGNORECASE
        ):
            logger.warning("sql.filtre_assure_manquant")
            raise DataAccessError(
                "Requete refusee : un WHERE doit toujours filtrer sur assure_id = :assure_id.",
                details=_details_erreur("forme_refusee", motif="filtre_assure_manquant"),
            )
        return requete

    def _injecter_filtre(self, requete: str) -> str:
        """Ajoute le filtre de l'assure si le modele l'a omis.

        La validation accepte encore une requete sans clause WHERE pour ne
        pas casser les usages historiques. Dans ce cas, le code ajoute
        lui-meme `WHERE 1=1 AND assure_id = :assure_id` : la restriction ne
        depend jamais de la bonne volonte du LLM.
        """
        if ":assure_id" in requete:
            return requete
        correspondance = re.search(r"\b(ORDER\s+BY|LIMIT)\b", requete, re.IGNORECASE)
        if correspondance is None:
            return f"{requete.rstrip()} WHERE 1=1 AND assure_id = :assure_id"
        debut = correspondance.start()
        return (
            f"{requete[:debut].rstrip()} WHERE 1=1 AND assure_id = :assure_id "
            f"{requete[debut:].lstrip()}"
        )

    def run(self, requete: str, *, assure_id: str) -> list[dict]:
        """Execute une requete en lecture seule, filtree sur l'assure connecte.

        `assure_id` provient du jeton JWT de l'appelant, jamais d'un argument
        du LLM : l'agent ne peut donc pas demander l'historique d'autrui.
        """
        if not assure_id:
            raise DataAccessError("Aucun dossier assure rattache a votre session.")

        requete_validee = self._injecter_filtre(self._validate(requete))

        try:
            with self._engine.connect() as connection:
                connection.execute(text("SET TRANSACTION READ ONLY"))
                rows = (
                    connection.execute(
                        text(requete_validee),
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

    def run_agent(self, requete: str, *, assure_id: str) -> str:
        """Variante pour l'agent : une erreur devient un JSON exploitable.

        Le LLM doit pouvoir lire `type_erreur`, `forme_attendue` et
        `exemple` pour corriger sa requete, au lieu de recevoir une simple
        chaine d'erreur qu'il risque de répéter a l'identique.
        """
        try:
            lignes = self.run(requete, assure_id=assure_id)
        except DataAccessError as exc:
            details = exc.details
            payload = {
                "ok": False,
                "type_erreur": details.get("type_erreur", "forme_refusee"),
                "erreur": exc.message,
                "forme_attendue": details.get("forme_attendue", FORME_ATTENDUE),
                "exemple": details.get("exemple", EXEMPLE_REQUETE),
                "conseil": (
                    "Ne repete pas la meme requete refusee : corrige-la en "
                    "suivant forme_attendue et exemple."
                ),
            }
            logger.info(
                "sql.agent_refus",
                assure_id=assure_id,
                type_erreur=payload["type_erreur"],
            )
            return json.dumps(payload, ensure_ascii=False)

        return json.dumps({"ok": True, "lignes": lignes}, ensure_ascii=False, default=str)

    def _as_tool(self) -> object:
        """Expose l'outil a LangChain avec un schema de parametres strict."""
        from langchain_core.tools import StructuredTool

        def _call(requete_sql: str, assure_id: str) -> str:
            return self.run_agent(requete_sql, assure_id=assure_id)

        return StructuredTool.from_function(
            func=_call,
            name=self.name,
            description=self.description,
        )

    def close(self) -> None:
        self._engine.dispose()
