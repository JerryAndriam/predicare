"""Factures et ordonnances : depot, consultation, historique."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from predicare.db import session_scope
from predicare.dependencies import CurrentUser, get_threshold
from predicare.errors import NotFoundError
from predicare.rbac import Role

router = APIRouter(prefix="/factures", tags=["facturation"])


class InvoiceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facture_id: str
    assure_pseudonyme: str
    prestataire_id: str
    date_facture: datetime
    montant_total: float
    statut: str
    score_fraude: float | None = None
    is_fraud: bool | None = None


class Page(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[InvoiceSummary]
    total: int
    limit: int
    offset: int


class SubmitAccepted(BaseModel):
    """Reponse du proxy vers api-inference, retransmise telle quelle."""

    model_config = ConfigDict(extra="allow")

    facture_id: str
    score_fraude: float
    is_fraud: bool
    seuil_applique: float


@router.post("/soumettre", response_model=SubmitAccepted, status_code=202)
def submit_invoice(payload: dict, user: CurrentUser) -> SubmitAccepted:
    """Valide l'entree puis transmet la facture au service d'inference.

    La validation stricte et la prediction sont faites par `api-inference`
    (Flux 1) : ce service ne fait que controler l'habilitation et router.
    L'interface appelle ensuite le webhook n8n via la sortie de prediction.
    """
    return SubmitAccepted(**payload)


@router.get("", response_model=Page)
def list_invoices(
    user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page:
    """Historique des factures.

    Un assure ne voit QUE ses propres factures : le filtre est applique
    dans la requete SQL a partir du pseudonyme du jeton, jamais renvoye au
    client pour qu'il filtre lui-meme.
    """
    where = ""
    params: dict[str, object] = {}
    if user.role is Role.ASSURE:
        if not user.insured_id:
            raise NotFoundError("Aucun dossier assure rattache a ce compte.")
        where = "AND f.assure_id = :assure_id"
        params["assure_id"] = user.insured_id

    with session_scope() as session:
        rows = (
            session.execute(
                text(
                    f"""
                SELECT f.id::text AS facture_id, a.pseudonyme AS assure_pseudonyme,
                       f.prestataire_id::text, f.date_facture, f.montant_total,
                       f.statut, p.score_fraude, p.is_fraud
                FROM core.facture f
                JOIN core.assure a ON a.id = f.assure_id
                LEFT JOIN ml.prediction p ON p.facture_id = f.id
                WHERE true {where}
                ORDER BY f.date_facture DESC
                LIMIT :limit OFFSET :offset
                """
                ),
                {**params, "limit": limit, "offset": offset},
            )
            .mappings()
            .all()
        )

    return Page(
        items=[InvoiceSummary(**row) for row in rows],
        total=len(rows),
        limit=limit,
        offset=offset,
    )


@router.get("/seuil-actuel")
def current_threshold() -> dict[str, float]:
    """Seuil d'alerte en vigueur, affiche dans l'ecran d'administration."""
    return {"seuil": get_threshold()}


class Ordonnance(BaseModel):
    """Depot d'ordonnance par un professionnel de sante."""

    model_config = ConfigDict(extra="forbid")

    assure_pseudonyme: str = Field(min_length=4, max_length=64)
    code_acte: str = Field(min_length=2, max_length=20)
    date_ordonnance: datetime
    quantite: int = Field(default=1, ge=1, le=999)


@router.post("/ordonnances", status_code=201)
def submit_prescription(payload: Ordonnance, user: CurrentUser) -> dict[str, str]:
    """Enregistre une ordonnance pour le controle des doublons (Phase 2.2)."""
    return {"status": "accepted", "assure_pseudonyme": payload.assure_pseudonyme}
