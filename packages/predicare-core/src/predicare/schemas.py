"""Schemas metier partages.

Ce sont les CONTRATS D'INTERFACE du projet : le CDC demande de figer tot le
format des predictions et des explications SHAP, car c'est le point de
dependance entre les trois membres de l'equipe. Toute evolution ici doit
etre versionnee.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------
# Sante et supervision
# --------------------------------------------------------------------------
class HealthResponse(BaseModel):
    """Reponse de /health, lue par le jury et par l'ecran d'administration."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded", "down"]
    service: str
    version: str
    checks: dict[str, bool] = Field(default_factory=dict)
    missing_secrets: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Flux 1 - factures et predictions
# --------------------------------------------------------------------------
class InvoiceLine(BaseModel):
    """Une ligne de facture.

    Validation stricte et explicite : le jury soumet 20 factures inedites le
    jour J, dont des factures invalides. Un message d'erreur doit nommer le
    champ fautif, sinon le gestionnaire ne peut rien corriger.
    """

    model_config = ConfigDict(extra="forbid")

    code_acte: str = Field(min_length=2, max_length=20, description="Code de l'acte (referentiel)")
    quantite: int = Field(ge=1, le=999, description="Quantite facturablee")
    montant_unitaire: float = Field(ge=0, le=10_000_000, description="Montant unitaire en ariary")
    date_acte: datetime = Field(description="Date de realisation de l'acte")


class InvoiceSubmission(BaseModel):
    """Facture soumise a l'API d'inference."""

    model_config = ConfigDict(extra="forbid")

    facture_id: str | None = Field(default=None, max_length=64)
    assure_pseudonyme: str = Field(min_length=4, max_length=64)
    prestataire_id: str = Field(min_length=2, max_length=64)
    date_facture: datetime
    montant_total: float = Field(ge=0, le=10_000_000)
    lignes: list[InvoiceLine] = Field(min_length=1, max_length=200)

    @property
    def montant_calcule(self) -> float:
        return round(sum(ligne.quantite * ligne.montant_unitaire for ligne in self.lignes), 2)


class ShapContribution(BaseModel):
    """Une contribution SHAP : une seule feature, son effet sur le score."""

    feature: str = Field(max_length=128)
    value: float
    shap_value: float
    base_value: float | None = None
    direction: Literal["pousse_vers_fraude", "pousse_vers_legitime"]
    human_readable: str = Field(max_length=256, description="Explication en francais")


class PredictionResponse(BaseModel):
    """Contrat de sortie d'inference, consomme par n8n et l'interface."""

    model_config = ConfigDict(extra="forbid")

    facture_id: str
    score_fraude: float = Field(ge=0, le=1)
    is_fraud: bool
    seuil_applique: float
    model_version: str
    shap: list[ShapContribution] = Field(default_factory=list)
    top_features: list[str] = Field(default_factory=list)
    inference_ms: float
    predicted_at: datetime


class ModelVersionInfo(BaseModel):
    """Etat du registre de modeles, pour la bascule et le retour arriere.

    `active_version` est nullable : au premier demarrage, aucun modele n'est
    encore charge, et l'ecran d'administration doit pouvoir l'afficher au lieu
    de recevoir une erreur de validation. `available_versions` fait partie de
    l'etat rendu par le registre : l'omettre ici rendrait la reponse
    inutilisable (le schema est strict).
    """

    model_config = ConfigDict(extra="forbid")

    active_version: str | None = None
    candidate_version: str | None = None
    loaded_at: datetime | None = None
    threshold: float
    metrics: dict[str, Any] = Field(default_factory=dict)
    available_versions: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Flux 3 - pilotage et decisions gestionnaire
# --------------------------------------------------------------------------
class ManagerDecision(BaseModel):
    """Decision du gestionnaire sur une alerte."""

    model_config = ConfigDict(extra="forbid")

    prediction_id: str
    decision: Literal["valider_fraude", "rejeter", "demander_piece"]
    commentaire: str = Field(min_length=3, max_length=2000)
    decided_at: datetime


# --------------------------------------------------------------------------
# FinOps
# --------------------------------------------------------------------------
class CostRecord(BaseModel):
    """Enregistrement de cout unitaire, alimente le dossier FinOps."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    service: str
    operation: Literal["llm_call", "embedding", "cache_hit"]
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_eur: float = 0.0
    latency_ms: float = 0.0
