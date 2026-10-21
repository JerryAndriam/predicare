"""Router d'inference : validation -> scoring -> SHAP -> persistance -> n8n."""

from __future__ import annotations

import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from predicare import metrics
from predicare.config import get_settings
from predicare.db import session_scope
from predicare.logging_config import get_logger
from predicare.persistance_ml import lire_dernier_rapport_derive, persister_prediction
from predicare_inference_api.context import resolve_context
from predicare_inference_api.explainability import build_shap_report
from predicare_inference_api.features import build_features
from predicare_inference_api.scoring import Scorer
from predicare_inference_api.validation import validate_invoice

router = APIRouter(tags=["inference"])
logger = get_logger("api-inference")

SERVICE = "api-inference"

#: Fenetre glissante des latences observees dans ce processus. Elle alimente
#: l'onglet Observabilite sans dependre de Prometheus : le jury voit une
#: latence reelle meme si la pile de supervision n'est pas demarree.
_LATENCES_MS: deque[float] = deque(maxlen=5000)


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
    _LATENCES_MS.append(inference_ms)

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


class NoterPayload(BaseModel):
    """La demande de re-controle d'un stock de factures."""

    model_config = ConfigDict(extra="forbid")

    portee: str = Field(default="historique", pattern="^(historique|nouvelles)$")
    force: bool = False
    remplacer: bool = False


@router.post("/noter")
async def noter(payload: NoterPayload, request: Request) -> dict:
    """Lance le scoring en lot, dans un SOUS-PROCES.

    Le re-controle de l'historique porte sur 84 592 factures : il dure deux
    minutes. Le lancer dans le processus du service le bloquerait, et le
    proxy HTTP expirerait avant la fin. Un sous-processus rend le service
    repondant, et l'etat est relu par l'ecran d'administration
    (`GET /noter`).
    """
    import asyncio
    import sys

    from predicare_inference_api.batch import _ecrire_etat

    arguments = [sys.executable, "-m", "predicare_inference_api.batch", payload.portee]
    if payload.force:
        arguments.append("--force")
    if payload.remplacer:
        arguments.append("--remplacer")
    _ecrire_etat("en_cours")
    process = await asyncio.create_subprocess_exec(
        *arguments,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    logger.info("recontrole.lance", portee=payload.portee, pid=process.pid)
    return {"lance": True, "pid": process.pid, "portee": payload.portee}


@router.get("/noter")
def etat_noter() -> dict:
    """L'etat du dernier re-controle : en cours, termine, ou le resume."""
    from predicare_inference_api.batch import lire_resume

    return lire_resume()


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
    """Bascule la candidate en version active.

    `X-Acteur` est pose par api-core (sujet du jeton administrateur) et recopie
    tel quel dans la notification n8n. Un appel direct (Makefile) n'en pose
    pas : l'acteur vaut alors null.
    """
    version = request.app.state.registry.promote_candidate(acteur=request.headers.get("X-Acteur"))
    return {"status": "ok", "active_version": version}


@router.post("/modele/retour-arriere")
def rollback(version: str, request: Request) -> dict:
    """Retour arriere vers une version precedente."""
    applied = request.app.state.registry.rollback(version)
    return {"status": "ok", "active_version": applied}


@router.get("/derive", response_model=dict)
def drift() -> dict:
    """Dernier rapport de derive persiste par le worker.

    Le rapport vit dans `ml.rapport_derive` : l'API et le worker sont deux
    processus, un etat en memoire du worker ne serait jamais visible ici. La
    lecture est tolerante (base absente = `non_calcule`), pour qu'un ecran de
    supervision ne tombe pas en 500.
    """
    rapport = lire_dernier_rapport_derive()
    if rapport is None:
        return {
            "status": "non_calcule",
            "message": "Aucun rapport de derive persiste pour le moment.",
        }
    return {"status": "ok", **rapport}


def _somme_prometheus(nom_echantillon: str) -> int:
    """Somme un compteur Prometheus du processus courant.

    Les compteurs sont deja alimentes par le middleware commun. On les relit
    ici pour que l'ecran d'administration affiche le volume et les erreurs
    sans avoir a interroger Prometheus, qui n'est pas toujours demarre.
    """
    from prometheus_client import REGISTRY

    total = 0.0
    for famille in REGISTRY.collect():
        for echantillon in famille.samples:
            if echantillon.name == nom_echantillon:
                total += echantillon.value
    return int(total)


def _percentile(valeurs: list[float], quantile: float) -> float | None:
    if not valeurs:
        return None
    index = min(len(valeurs) - 1, max(0, round(quantile * (len(valeurs) - 1))))
    return round(valeurs[index], 2)


@router.get("/stats")
def stats(request: Request) -> dict:
    """Photo d'exploitation : volume, alertes, latence, erreurs.

    Cette route est volontairement tolerante aux pannes : la supervision ne
    doit pas tomber parce que la base ou un compteur est indisponible. Chaque
    bloc est donc rendu separement, avec `disponible: false` en cas d'echec.
    """
    latences = sorted(_LATENCES_MS)
    try:
        version = request.app.state.registry.active.version
    except Exception:
        version = None
    resultat: dict = {
        "service": SERVICE,
        "version": version,
        "seuil": request.app.state.registry.threshold,
        "latence_ms": {
            "disponible": bool(latences),
            "echantillons": len(latences),
            "moyenne": round(sum(latences) / len(latences), 2) if latences else None,
            "p50": _percentile(latences, 0.50),
            "p95": _percentile(latences, 0.95),
            "p99": _percentile(latences, 0.99),
        },
        "erreurs_total": _somme_prometheus("predicare_errors_total"),
        "requetes_total": _somme_prometheus("predicare_http_requests_total"),
    }
    try:
        with session_scope() as session:
            resultat["volume"] = {
                "disponible": True,
                "predictions_total": int(
                    session.execute(text("SELECT count(*) FROM ml.prediction")).scalar_one()
                ),
                "alertes_total": int(
                    session.execute(
                        text("SELECT count(*) FROM ml.prediction WHERE is_fraud")
                    ).scalar_one()
                ),
                "derniere_prediction": session.execute(
                    text("SELECT max(created_at) FROM ml.prediction")
                ).scalar(),
            }
    except Exception as exc:  # pragma: no cover - depend de la disponibilite de la base
        logger.warning("stats.base_indisponible", erreur=str(exc))
        resultat["volume"] = {"disponible": False}
    return resultat


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


#: Repertoire des artefacts de modele partage avec le worker d'entrainement.
MODEL_DIR = Path(get_settings().model_dir)
