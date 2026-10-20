"""File d'alertes, detail explicable et decisions du gestionnaire.

Le parcours gestionnaire repose sur trois lectures et une ecriture :

- la file des alertes au-dessus du seuil courant ;
- le DETAIL d'une alerte, avec les contributions SHAP qui justifient le
  score : sans elles, le gestionnaire ne peut ni expliquer ni contester la
  decision du modele ;
- l'historique des decisions, pour la tracabilite ;
- l'enregistrement de la decision (valider / rejeter / demander une piece).

Le controle d'acces est applique cote API, avant toute requete base : un
assure ne peut pas lire la file d'alertes, meme en connaissant l'URL.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from predicare.audit import journaliser
from predicare.auth import TokenPayload
from predicare.db import session_scope
from predicare.dependencies import get_threshold, require_permission
from predicare.errors import NotFoundError
from predicare.logging_config import get_logger
from predicare.schemas import ManagerDecision, ShapContribution

router = APIRouter(prefix="/alertes", tags=["alertes"])
logger = get_logger("api-core.decisions")

#: Traduction de la decision du gestionnaire vers le statut metier de la
#: facture. Sans elle, l'assure continuait de voir « recue » apres une fraude
#: confirmee : la decision restait dans le schema ML, invisible pour lui.
STATUT_FACTURE: dict[str, str] = {
    "valider_fraude": "fraude_confirmee",
    "rejeter": "rejetee",
    "demander_piece": "piece_demandee",
}

AlertReader = Annotated[TokenPayload, Depends(require_permission("alerte:lire"))]
AlertDecider = Annotated[TokenPayload, Depends(require_permission("alerte:decider"))]
AuditReader = Annotated[TokenPayload, Depends(require_permission("audit:lire"))]


class AlerteSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prediction_id: str
    facture_id: str
    assure_pseudonyme: str
    score_fraude: float
    montant_total: float
    statut: str
    created_at: datetime
    #: Age de l'alerte en minutes : le temps de traitement est un indicateur
    #: de charge du gestionnaire, et un dossier laisse trop longtemps en file
    #: signale un defaut de dispositif, pas une urgence de fond.
    age_minutes: int = 0


class AlerteLigne(BaseModel):
    """Une ligne de la facture suspecte, avec l'acte qui la porte."""

    model_config = ConfigDict(extra="forbid")

    code_acte: str
    libelle: str
    quantite: int
    montant_unitaire: float
    montant_total: float
    prescrite: bool = False


class AlerteDetail(AlerteSummary):
    """Alerte enrichie du rapport SHAP, affiche au gestionnaire."""

    shap: list[ShapContribution] = []
    #: Les lignes de la facture source. Sans elles, le gestionnaire ne peut
    #: pas verifier l'alerte : il ne voit que le score et les facteurs, pas
    #: ce qui a ete facture.
    lignes: list[AlerteLigne] = []


class AlertePage(BaseModel):
    """File d'alertes paginee : au-dela de la page, les alertes existent."""

    model_config = ConfigDict(extra="forbid")

    items: list[AlerteSummary]
    total: int
    limit: int
    offset: int


@router.get("/file", response_model=AlertePage)
def file_alertes(
    user: AlertReader,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    statut: str = Query(default="nouvelle"),
    score_min: float | None = Query(default=None, ge=0.0, le=1.0),
    montant_min: float | None = Query(default=None, ge=0.0),
    montant_max: float | None = Query(default=None, ge=0.0),
    assure: str | None = Query(default=None, max_length=64),
    depuis: datetime | None = Query(default=None),
    jusque: datetime | None = Query(default=None),
) -> AlertePage:
    """File d'alertes, paginee et filtrable.

    Le seuil courant est relu a chaque appel : un changement de seuil depuis
    l'ecran d'administration s'applique immediatement, sans redemarrage
    (condition "Configurable" du jury).

    La file est PAGINEE : plafonner a 100 alertes faisait disparaitre les
    suivantes de l'ecran, alors qu'elles existaient bel et bien en base.
    Les filtres portent sur ce que le gestionnaire cherche reellement : le
    montant (les grosses factures), l'assure, la periode, le score.
    """
    conditions = ["p.score_fraude >= :seuil", "p.statut = :statut"]
    params: dict[str, object] = {"seuil": get_threshold(), "statut": statut}

    if score_min is not None:
        conditions.append("p.score_fraude >= :score_min")
        params["score_min"] = score_min
    if montant_min is not None:
        conditions.append("f.montant_total >= :montant_min")
        params["montant_min"] = montant_min
    if montant_max is not None:
        conditions.append("f.montant_total <= :montant_max")
        params["montant_max"] = montant_max
    if assure:
        conditions.append("a.pseudonyme ILIKE :assure")
        params["assure"] = f"%{assure.strip()}%"
    if depuis is not None:
        conditions.append("p.created_at >= :depuis")
        params["depuis"] = depuis
    if jusque is not None:
        conditions.append("p.created_at <= :jusque")
        params["jusque"] = jusque

    where = " AND ".join(conditions)

    with session_scope() as session:
        total = int(
            session.execute(
                text(
                    f"""
                SELECT count(*)
                FROM ml.prediction p
                JOIN core.facture f ON f.id = p.facture_id
                JOIN core.assure a ON a.id = f.assure_id
                WHERE {where}
                """
                ),
                params,
            ).scalar_one()
        )
        rows = (
            session.execute(
                text(
                    f"""
                SELECT p.id::text AS prediction_id, p.facture_id::text AS facture_id,
                       a.pseudonyme AS assure_pseudonyme, p.score_fraude,
                       f.montant_total, p.statut, p.created_at,
                       EXTRACT(EPOCH FROM (now() - p.created_at)) / 60 AS age_minutes
                FROM ml.prediction p
                JOIN core.facture f ON f.id = p.facture_id
                JOIN core.assure a ON a.id = f.assure_id
                WHERE {where}
                ORDER BY p.score_fraude DESC, p.created_at ASC
                LIMIT :limit OFFSET :offset
                """
                ),
                {**params, "limit": limit, "offset": offset},
            )
            .mappings()
            .all()
        )

    return AlertePage(
        items=[AlerteSummary(**{**row, "age_minutes": int(row["age_minutes"] or 0)}) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/detail/{prediction_id}", response_model=AlerteDetail)
def detail_alerte(prediction_id: str, user: AlertReader) -> AlerteDetail:
    """Detail d'une alerte : le score ET les contributions qui l'expliquent.

    Les contributions sont lues dans `ml.shap_explication`, ecrites par le
    Flux 1 au moment de la notation. L'ecran affiche donc exactement ce que
    le modele a produit, pas une reconstruction approximative.
    """
    if not prediction_id.isdigit():
        raise NotFoundError("Alerte introuvable.")

    with session_scope() as session:
        entete = (
            session.execute(
                text(
                    """
                    SELECT p.id::text AS prediction_id, p.facture_id::text AS facture_id,
                           a.pseudonyme AS assure_pseudonyme, p.score_fraude,
                           f.montant_total, p.statut, p.created_at
                    FROM ml.prediction p
                    JOIN core.facture f ON f.id = p.facture_id
                    JOIN core.assure a ON a.id = f.assure_id
                    WHERE p.id = :prediction_id
                    """
                ),
                {"prediction_id": int(prediction_id)},
            )
            .mappings()
            .first()
        )
        if entete is None:
            raise NotFoundError("Alerte introuvable.")

        contributions = (
            session.execute(
                text(
                    """
                    SELECT feature, valeur AS value, shap_value, base_value,
                           direction, libelle AS human_readable
                    FROM ml.shap_explication
                    WHERE prediction_id = :prediction_id
                    ORDER BY rang
                    """
                ),
                {"prediction_id": int(prediction_id)},
            )
            .mappings()
            .all()
        )

        # Les LIGNES de la facture source. Sans elles, le gestionnaire ne
        # peut pas verifier l'alerte : il ne voit que le score et les
        # facteurs, pas ce qui a ete facture. `prescrite` indique si l'acte
        # figure dans l'ordonnance liee a la facture : c'est le doublon de
        # prescription que le gestionnaire doit pouvoir constater.
        lignes = (
            session.execute(
                text(
                    """
                    SELECT a.code AS code_acte, a.libelle, l.quantite,
                           l.montant_unitaire,
                           (l.quantite * l.montant_unitaire) AS montant_total,
                           (EXISTS (
                               SELECT 1
                               FROM core.ordonnance o
                               JOIN core.ordonnance_ligne ol ON ol.ordonnance_id = o.id
                               WHERE f.ordonnance_id = o.id AND ol.acte_id = a.id
                           )) AS prescrite
                    FROM core.ligne_facture l
                    JOIN core.acte a ON a.id = l.acte_id
                    JOIN core.facture f ON f.id = l.facture_id
                    WHERE f.id = CAST(:facture_id AS integer)
                    ORDER BY l.id
                    """
                ),
                {"facture_id": entete["facture_id"]},
            )
            .mappings()
            .all()
        )

    return AlerteDetail(
        **entete,
        shap=[ShapContribution(**contribution) for contribution in contributions],
        lignes=[AlerteLigne(**ligne) for ligne in lignes],
    )


@router.post("/decision")
def decider(payload: ManagerDecision, user: AlertDecider) -> dict[str, str]:
    """Enregistre la decision du gestionnaire (valider / rejeter / piece)."""
    if not payload.prediction_id.isdigit():
        raise NotFoundError("Alerte introuvable.")
    prediction_id = int(payload.prediction_id)

    with session_scope() as session:
        facture_id = session.execute(
            text(
                """
                UPDATE ml.prediction SET statut = :decision, decided_by = :user,
                       decided_at = :now
                WHERE id = :prediction_id
                RETURNING facture_id
                """
            ),
            {
                "decision": payload.decision,
                "user": user.subject,
                "now": payload.decided_at,
                "prediction_id": prediction_id,
            },
        ).scalar()
        if facture_id is None:
            raise NotFoundError("Alerte introuvable.")

        statut = STATUT_FACTURE[payload.decision]
        session.execute(
            text("UPDATE core.facture SET statut = :statut WHERE id = :facture_id"),
            {"statut": statut, "facture_id": int(facture_id)},
        )

        session.execute(
            text(
                """
                INSERT INTO audit.decision_gestionnaire
                    (prediction_id, decision, commentaire, decided_by, decided_at)
                VALUES (:prediction_id, :decision, :commentaire, :user, :now)
                """
            ),
            {
                "prediction_id": prediction_id,
                "decision": payload.decision,
                "commentaire": payload.commentaire,
                "user": user.subject,
                "now": payload.decided_at,
            },
        )

        journaliser(
            session,
            acteur=user.subject,
            role=str(user.role),
            action="decision_alerte",
            cible=f"prediction:{prediction_id}",
            details={
                "decision": payload.decision,
                "facture_id": int(facture_id),
                "statut_facture": statut,
                "commentaire": payload.commentaire,
            },
        )

    logger.info(
        "decision.prise",
        prediction_id=prediction_id,
        decision=payload.decision,
        gestionnaire=user.subject,
        role=str(user.role),
    )
    return {"status": "ok", "prediction_id": payload.prediction_id}


@router.get("/historique")
def historique(
    user: AuditReader,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    decision: str | None = Query(default=None, max_length=32),
    depuis: datetime | None = Query(default=None),
    jusque: datetime | None = Query(default=None),
) -> dict[str, object]:
    """Historique des decisions, exigeance du parcours gestionnaire.

    Comme la file, l'historique est PAGINE et filtrable : plafonner a 200
    decisions sans pagination ni filtre rendait l'historique inexploitable
    des la premiere semaine d'exploitation.
    """
    conditions = ["true"]
    params: dict[str, object] = {}
    if decision:
        conditions.append("d.decision = :decision")
        params["decision"] = decision
    if depuis is not None:
        conditions.append("d.decided_at >= :depuis")
        params["depuis"] = depuis
    if jusque is not None:
        conditions.append("d.decided_at <= :jusque")
        params["jusque"] = jusque
    where = " AND ".join(conditions)

    with session_scope() as session:
        total = int(
            session.execute(
                text(
                    f"""
                SELECT count(*)
                FROM audit.decision_gestionnaire d
                JOIN ml.prediction p ON p.id = d.prediction_id
                WHERE {where}
                """
                ),
                params,
            ).scalar_one()
        )
        rows = (
            session.execute(
                text(
                    f"""
                SELECT d.prediction_id::text, d.decision, d.commentaire,
                       d.decided_at, d.decided_by, p.score_fraude,
                       p.facture_id::text AS facture_id
                FROM audit.decision_gestionnaire d
                JOIN ml.prediction p ON p.id = d.prediction_id
                WHERE {where}
                ORDER BY d.decided_at DESC
                LIMIT :limit OFFSET :offset
                """
                ),
                {**params, "limit": limit, "offset": offset},
            )
            .mappings()
            .all()
        )
    return {"items": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}
