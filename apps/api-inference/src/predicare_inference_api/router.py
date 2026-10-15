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
from predicare_inference_api.drift import DriftReport
from predicare_inference_api.explainability import build_shap_report, shap_to_contributions
from predicare_inference_api.features import build_features
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

    features = build_features(invoice)
    row = features.as_row(bundle.feature_names)

    import numpy as np

    estimator = bundle.estimator
    score = float(estimator.predict_proba(np.array([row]))[0, 1])
    base_value = bundle.shap_base_value

    shap_values = np.zeros(len(bundle.feature_names))
    try:
        import shap

        explainer = shap.TreeExplainer(estimator)
        shap_values = np.asarray(explainer.shap_values(np.array([row]))).ravel()
    except Exception as exc:
        logger.warning("shap.indisponible", erreur=str(exc))

    contributions = shap_to_contributions(bundle.feature_names, shap_values, base_value)
    is_fraud = score >= seuil
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
    """Seuil courant, utilise par api-core et par le workflow n8n."""
    return {
        "seuil": get_settings().fraud_alert_threshold,
        "seuil_reel": request.app.state.registry.threshold,
    }


#: Type du rapport de derive conserve en memoire par le worker.
DriftReportType = DriftReport

#: Repertoire des artefacts de modele partage avec le worker d'entrainement.
MODEL_DIR = Path(get_settings().model_dir)
