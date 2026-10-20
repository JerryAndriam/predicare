"""Router d'inference : validation -> scoring -> SHAP -> persistance -> n8n."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from predicare import metrics
from predicare.config import get_settings
from predicare.logging_config import get_logger
from predicare.persistance_ml import persister_prediction
from predicare_inference_api.context import resolve_context
from predicare_inference_api.drift import DriftReport
from predicare_inference_api.explainability import build_shap_report
from predicare_inference_api.features import build_features
from predicare_inference_api.scoring import Scorer
from predicare_inference_api.validation import validate_invoice

router = APIRouter(tags=["inference"])
logger = get_logger("api-inference")

SERVICE = "api-inference"


class ThresholdPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seuil: float = Field(ge=0.0, le=1.0)


@router.post("/predire")
def predict(payload: dict, request: Request) -> dict:
    """Valide une facture, la score, et renvoie l'alerte avec son rapport SHAP.

    Le seuil est lu AU MOMENT de l'appel : un changement depuis l'ecran
    d'administration s'applique a la facture suivante, sans redemarrage.
    """
    started = time.perf_counter()

    invoice = validate_invoice(payload)

    registry = request.app.state.registry
    bundle = registry.active
    seuil = registry.threshold

    features = build_features(
        invoice,
        bundle.referentiels,
        **resolve_context(invoice, bundle.referentiels),
    )
    row = features.as_row(bundle.feature_names)

    if features.references_manquantes:
        # Signale, pas bloque : une facture dont une reference est absente doit
        # etre NOTEE. Mais l'echec de resolution doit rester visible, sinon on
        # ne verrait jamais que le referentiel est incomplet.
        logger.info(
            "references.manquantes",
            facture_id=invoice.facture_id,
            references=features.references_manquantes[:10],
        )

    notation = Scorer(bundle, seuil=seuil).score(row)
    score = notation.score
    contributions = notation.contributions
    is_fraud = notation.is_fraud
    inference_ms = (time.perf_counter() - started) * 1000

    metrics.MODEL_INFERENCE.labels(SERVICE, bundle.version).observe(inference_ms / 1000)
    metrics.PREDICTIONS.labels(SERVICE, _score_bucket(score)).inc()

    result = {
        "facture_id": invoice.facture_id or invoice.assure_pseudonyme,
        "score_fraude": round(score, 6),
        "is_fraud": is_fraud,
        "seuil_applique": seuil,
        "model_version": bundle.version,
        "shap": [c.model_dump(mode="json") for c in contributions],
        "top_features": [c.feature for c in contributions],
        "inference_ms": round(inference_ms, 2),
        "predicted_at": datetime.now(UTC),
        "rapport_shap": build_shap_report(contributions, score, seuil),
    }

    # Stockage de la transaction (Flux 1), AVANT la notification n8n : une
    # alerte notifiee mais absente de la base serait introuvable dans la file
    # du gestionnaire. Best-effort : une base indisponible ne doit pas priver
    # le demandeur de son score.
    if invoice.facture_id:
        persister_prediction(
            reference=invoice.facture_id,
            model_version=bundle.version,
            score=score,
            seuil=seuil,
            is_fraud=is_fraud,
            contributions=contributions,
        )

    if is_fraud:
        logger.info(
            "alerte.emise",
            facture_id=result["facture_id"],
            score=score,
            modele=bundle.version,
            inference_ms=round(inference_ms, 2),
        )
    return result


def _score_bucket(score: float) -> str:
    """Decoupe la distribution des scores : l'histogramme doit rester lisible."""
    tranche = min(int(score * 10), 9)
    return f"{tranche / 10:.1f}-{(tranche + 1) / 10:.1f}"


@router.put("/seuil")
def update_threshold(payload: ThresholdPayload, request: Request) -> dict:
    """Applique un nouveau seuil sans redemarrage."""
    applied = request.app.state.registry.set_threshold(payload.seuil)
    return {"status": "ok", "seuil": applied}


@router.get("/modele")
def model_state(request: Request) -> dict:
    """Etat du registre : version active, candidate, versions disponibles."""
    return request.app.state.registry.state()


@router.post("/modele/candidat")
def load_candidate(version: str, request: Request) -> dict:
    """Charge une version a cote de l'active, SANS l'activer.

    C'est ce qui rend le deploiement sans interruption possible : l'active
    continue de repondre pendant que la candidate se prepare.
    """
    bundle = request.app.state.registry.load_version(version, as_candidate=True)
    return {"status": "ok", "candidate_version": bundle.version, "active_version": bundle.version}


@router.post("/modele/bascule")
def promote(request: Request) -> dict:
    """Bascule la candidate en version active."""
    version = request.app.state.registry.promote_candidate()
    return {"status": "ok", "active_version": version}


@router.post("/modele/retour-arriere")
def rollback(version: str, request: Request) -> dict:
    """Retour arriere vers une version precedente."""
    applied = request.app.state.registry.rollback(version)
    return {"status": "ok", "active_version": applied}


@router.get("/derive", response_model=dict)
def drift(request: Request) -> dict:
    """Dernier rapport de derive calcule par le worker."""
    report = request.app.state.drift_report
    if report is None:
        return {
            "status": "non_calcule",
            "message": "Le worker de derive n'a pas encore produit de rapport.",
        }
    return {"status": "ok", **report}


@router.get("/seuil")
def read_threshold(request: Request) -> dict:
    """Seuil courant, utilise par api-core et par le workflow n8n.

    `seuil` est le seuil EFFECTIF : celui qui decide de l'alerte. Un appelant
    n'a pas a savoir s'il vient du modele, de l'administration ou de
    l'environnement ; `seuil_impose` expose la valeur d'exploitation pour
    l'ecran d'administration.
    """
    return {
        "seuil": request.app.state.registry.threshold,
        "seuil_impose": get_settings().fraud_alert_threshold,
    }


#: Type du rapport de derive conserve en memoire par le worker.
DriftReportType = DriftReport

#: Repertoire des artefacts de modele partage avec le worker d'entrainement.
MODEL_DIR = Path(get_settings().model_dir)
