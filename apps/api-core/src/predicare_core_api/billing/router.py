"""Factures et ordonnances : depot, consultation, historique.

Le depot d'une facture est un enchainement, pas un simple proxy :

1. valider la charge utile avec le MEME schema que le service d'inference
   (`InvoiceSubmission`) : le front et le back refusent donc les memes
   documents, avec le meme vocabulaire ;
2. verifier que l'assure, le prestataire et les actes existent ;
3. faire noter la facture par le Flux 1 (XGBoost + SHAP) ;
4. seulement alors, ecrire la facture en base.

L'ordre est delibere. Noter avant d'ecrire garantit qu'une facture invalide
ne laisse AUCUNE trace, et que la base ne contient jamais un document que le
modele n'a pas vu. La prediction est ensuite persistee depuis api-core, parce
que la facture n'existait pas encore au moment de l'appel d'inference.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from predicare.auth import TokenPayload
from predicare.db import session_scope
from predicare.dependencies import get_threshold, require_permission
from predicare.errors import InvalidInvoiceError, ModelNotReadyError, PrediCareError
from predicare.logging_config import get_logger
from predicare.persistance_ml import persister_prediction
from predicare.rbac import Role
from predicare.schemas import InvoiceSubmission, ShapContribution

router = APIRouter(prefix="/factures", tags=["facturation"])
logger = get_logger("api-core.billing")

#: Le controle d'acces est applique AVANT le corps de la route, donc avant
#: toute lecture ou ecriture en base. Le front ne fait que refleter la regle ;
#: la verite est ici (CDC, Phase 6.1).
SubmitUser = Annotated[TokenPayload, Depends(require_permission("facture:soumettre"))]
ReadUser = Annotated[TokenPayload, Depends(require_permission("facture:lire"))]


class InvoiceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facture_id: str
    assure_pseudonyme: str
    prestataire_id: str
    date_facture: datetime
    montant_total: float
    montant_eligible: float | None = None
    montant_pris_en_charge: float | None = None
    reste_a_charge: float | None = None
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
    """Reponse du service d'inference, retransmise telle quelle.

    `extra="allow"` est volontaire : le score, les contributions SHAP et le
    rapport lisible sont ajoutes par le Flux 1. Les figer ici obligerait a
    modifier api-core a chaque evolution de l'explicabilite.
    """

    model_config = ConfigDict(extra="allow")

    facture_id: str
    score_fraude: float
    is_fraud: bool
    seuil_applique: float
    model_version: str | None = None


@router.post("/soumettre", response_model=SubmitAccepted, status_code=202)
def submit_invoice(payload: dict, request: Request, user: SubmitUser) -> SubmitAccepted:
    """Valide, note via le Flux 1, puis enregistre la facture."""
    try:
        invoice = InvoiceSubmission.model_validate(payload)
    except ValidationError as exc:
        raise InvalidInvoiceError(f"Facture invalide - {_field_error(exc)}") from exc

    # L'identifiant metier est la `reference` en base : c'est lui que le
    # service d'inference renvoie, et lui qui rattache la prediction.
    reference = invoice.facture_id or f"FAC-{uuid4().hex[:12].upper()}"

    _verifier_references(invoice)
    resultat = _appeler_inference(request, {**payload, "facture_id": reference})
    _enregistrer_facture(invoice, reference)

    contributions = [ShapContribution(**contribution) for contribution in resultat.get("shap", [])]
    persister_prediction(
        reference=reference,
        model_version=str(resultat.get("model_version", "inconnu")),
        score=float(resultat["score_fraude"]),
        seuil=float(resultat["seuil_applique"]),
        is_fraud=bool(resultat["is_fraud"]),
        contributions=contributions,
    )

    logger.info(
        "facture.soumise",
        reference=reference,
        score=resultat["score_fraude"],
        acteur=user.subject,
    )
    return SubmitAccepted(**resultat)


def _field_error(exc: ValidationError) -> str:
    """Message nommant le champ fautif, comme dans le service d'inference."""
    return " ; ".join(
        f"{'.'.join(str(partie) for partie in erreur['loc']) or 'racine'} : {erreur['msg']}"
        for erreur in exc.errors()
    )


def _exiger(session: Session, table: str, colonne: str, valeur: str, champ: str) -> int:
    """Resout un identifiant technique, ou rejette la facture en nommant le champ.

    `table` et `colonne` sont des litteraux du code, jamais des valeurs
    utilisateur : l'interpolation est donc sans risque d'injection.
    """
    identifiant = session.execute(
        text(f"SELECT id FROM {table} WHERE {colonne} = :valeur"),
        {"valeur": valeur},
    ).scalar()
    if identifiant is None:
        raise InvalidInvoiceError(
            f"Facture invalide - {champ} : valeur inconnue ({valeur})",
            details={"champ": champ, "valeur": valeur},
        )
    return int(identifiant)


def _verifier_references(invoice: InvoiceSubmission) -> None:
    """Verifie les references AVANT de noter : rien n'est ecrit si elles manquent."""
    with session_scope() as session:
        _exiger(
            session, "core.assure", "pseudonyme", invoice.assure_pseudonyme, "assure_pseudonyme"
        )
        _exiger(session, "core.prestataire", "code", invoice.prestataire_id, "prestataire_id")
        for index, ligne in enumerate(invoice.lignes):
            _exiger(session, "core.acte", "code", ligne.code_acte, f"lignes.{index}.code_acte")


def _appeler_inference(request: Request, payload: dict) -> dict:
    """Appelle le Flux 1 et traduit ses erreurs en erreurs metier d'api-core.

    Sans cette traduction, un modele absent remonterait en 500 : le
    gestionnaire verrait une panne technique la ou il faut lui dire
    exactement ce qui manque.
    """
    url = str(request.app.state.inference_api_url).rstrip("/")
    try:
        response = httpx.post(f"{url}/predire", json=payload, timeout=15.0)
    except httpx.HTTPError as exc:
        raise ModelNotReadyError(
            "Service d'inference injoignable : verifiez le conteneur api-inference."
        ) from exc

    if response.status_code == 422:
        corps = _corps_json(response)
        raise InvalidInvoiceError(
            str(corps.get("message", "Facture invalide.")),
            details=corps.get("details") or {},
        )
    if response.status_code == 503:
        raise ModelNotReadyError(
            "Aucun modele actif : lancez `make train`, puis `make model-promote`."
        )
    if response.status_code >= 400:
        raise PrediCareError(
            "Le service d'inference a refuse la facture.",
            details={"status": response.status_code, **_corps_json(response)},
        )
    return response.json()


def _corps_json(response: httpx.Response) -> dict:
    """Corps JSON tolerant : une passerelle peut renvoyer du HTML."""
    try:
        corps = response.json()
    except ValueError:
        return {"message": response.text[:500]}
    return corps if isinstance(corps, dict) else {"message": str(corps)[:500]}


def _enregistrer_facture(invoice: InvoiceSubmission, reference: str) -> None:
    """Ecrit la facture et ses lignes. Idempotent sur `reference`."""
    with session_scope() as session:
        existante = session.execute(
            text("SELECT id FROM core.facture WHERE reference = :reference"),
            {"reference": reference},
        ).scalar()
        if existante is not None:
            return

        assure_id = _exiger(
            session, "core.assure", "pseudonyme", invoice.assure_pseudonyme, "assure_pseudonyme"
        )
        prestataire_id = _exiger(
            session, "core.prestataire", "code", invoice.prestataire_id, "prestataire_id"
        )
        facture_id = session.execute(
            text(
                """
                INSERT INTO core.facture
                    (reference, assure_id, prestataire_id, date_facture,
                     montant_total, statut)
                VALUES (:reference, :assure_id, :prestataire_id, :date_facture,
                        :montant_total, 'recue')
                RETURNING id
                """
            ),
            {
                "reference": reference,
                "assure_id": assure_id,
                "prestataire_id": prestataire_id,
                "date_facture": invoice.date_facture,
                "montant_total": invoice.montant_total,
            },
        ).scalar()

        for index, ligne in enumerate(invoice.lignes):
            acte_id = _exiger(
                session, "core.acte", "code", ligne.code_acte, f"lignes.{index}.code_acte"
            )
            session.execute(
                text(
                    """
                    INSERT INTO core.ligne_facture
                        (facture_id, acte_id, quantite, montant_unitaire, date_acte)
                    VALUES (:facture_id, :acte_id, :quantite, :montant_unitaire, :date_acte)
                    """
                ),
                {
                    "facture_id": facture_id,
                    "acte_id": acte_id,
                    "quantite": ligne.quantite,
                    "montant_unitaire": ligne.montant_unitaire,
                    "date_acte": ligne.date_acte,
                },
            )


@router.get("", response_model=Page)
def list_invoices(
    user: ReadUser,
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
            raise InvalidInvoiceError(
                "Aucun dossier assure rattache a ce compte.",
                details={"champ": "assured_id"},
            )
        where = "AND f.assure_id = :assure_id"
        params["assure_id"] = user.insured_id

    with session_scope() as session:
        rows = (
            session.execute(
                text(
                    f"""
                SELECT f.id::text AS facture_id, a.pseudonyme AS assure_pseudonyme,
                       pr.code AS prestataire_id, f.date_facture, f.montant_total,
                       f.montant_eligible, f.montant_pris_en_charge, f.reste_a_charge,
                       f.statut, p.score_fraude, p.is_fraud
                FROM core.facture f
                JOIN core.assure a ON a.id = f.assure_id
                JOIN core.prestataire pr ON pr.id = f.prestataire_id
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


class ReferenceAssure(BaseModel):
    pseudonyme: str


class ReferencePrestataire(BaseModel):
    code: str
    nom: str
    specialite: str


class ReferenceActe(BaseModel):
    code: str
    libelle: str
    prix_unitaire: float


class References(BaseModel):
    """Referentiels necessaires au formulaire de depot.

    Sans eux, un professionnel devrait connaitre par coeur les codes d'acte
    et les pseudonymes : l'interface serait inutilisable en demonstration.
    Seules des valeurs de reference sont exposees, jamais une identite.
    """

    model_config = ConfigDict(extra="forbid")

    assures: list[ReferenceAssure]
    prestataires: list[ReferencePrestataire]
    actes: list[ReferenceActe]


@router.get("/references", response_model=References)
def references(user: SubmitUser) -> References:
    """Valeurs de reference pour pre-remplir le formulaire de depot."""
    with session_scope() as session:
        assures = (
            session.execute(text("SELECT pseudonyme FROM core.assure ORDER BY id LIMIT 50"))
            .mappings()
            .all()
        )
        prestataires = (
            session.execute(
                text("SELECT code, nom, specialite FROM core.prestataire ORDER BY code LIMIT 100")
            )
            .mappings()
            .all()
        )
        actes = (
            session.execute(
                text(
                    "SELECT code, libelle, prix_unitaire FROM core.acte "
                    "WHERE actif ORDER BY code LIMIT 200"
                )
            )
            .mappings()
            .all()
        )
    return References(
        assures=[ReferenceAssure(**row) for row in assures],
        prestataires=[ReferencePrestataire(**row) for row in prestataires],
        actes=[ReferenceActe(**row) for row in actes],
    )


class Ordonnance(BaseModel):
    """Depot d'ordonnance par un professionnel de sante."""

    model_config = ConfigDict(extra="forbid")

    assure_pseudonyme: str = Field(min_length=4, max_length=64)
    prestataire_id: str = Field(min_length=2, max_length=64)
    code_acte: str = Field(min_length=2, max_length=20)
    date_ordonnance: datetime
    quantite: int = Field(default=1, ge=1, le=999)


@router.post("/ordonnances", status_code=201)
def submit_prescription(payload: Ordonnance, user: SubmitUser) -> dict[str, str]:
    """Enregistre une ordonnance pour le controle des doublons (Phase 2.2)."""
    with session_scope() as session:
        assure_id = _exiger(
            session, "core.assure", "pseudonyme", payload.assure_pseudonyme, "assure_pseudonyme"
        )
        prestataire_id = _exiger(
            session, "core.prestataire", "code", payload.prestataire_id, "prestataire_id"
        )
        acte_id = _exiger(session, "core.acte", "code", payload.code_acte, "code_acte")
        session.execute(
            text(
                """
                INSERT INTO core.ordonnance
                    (assure_id, prestataire_id, acte_id, date_ordonnance, quantite)
                VALUES (:assure_id, :prestataire_id, :acte_id, :date_ordonnance, :quantite)
                """
            ),
            {
                "assure_id": assure_id,
                "prestataire_id": prestataire_id,
                "acte_id": acte_id,
                "date_ordonnance": payload.date_ordonnance,
                "quantite": payload.quantite,
            },
        )

    logger.info("ordonnance.deposee", acteur=user.subject, acte=payload.code_acte)
    return {"status": "accepted", "assure_pseudonyme": payload.assure_pseudonyme}
