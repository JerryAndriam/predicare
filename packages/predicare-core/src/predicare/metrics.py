"""Metriques Prometheus : latence, volume, erreurs, derive.

Correspond directement a la condition "Supervisable" du CDC
(metriques de latence, de volume et d'erreurs).
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram, Info

# Volume : nombre d'appels par route et statut
HTTP_REQUESTS = Counter(
    "predicare_http_requests_total",
    "Nombre total de requetes HTTP",
    ["service", "route", "method", "status"],
)

# Latence : le jury doit voir un P95, pas une moyenne
HTTP_LATENCY = Histogram(
    "predicare_http_request_duration_seconds",
    "Latence des requetes HTTP en secondes",
    ["service", "route", "method"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# Erreurs applicatives explicites
ERRORS = Counter(
    "predicare_errors_total",
    "Erreurs applicatives par type",
    ["service", "error_code"],
)

# Predictions : distribution des scores pour le suivi de derive
PREDICTIONS = Counter(
    "predicare_predictions_total",
    "Predictions de fraude emises",
    ["service", "bucket"],
)

# Inference de modele
MODEL_INFERENCE = Histogram(
    "predicare_model_inference_seconds",
    "Duree d'inference du modele de fraude",
    ["service", "model_version"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0),
)

# Coût LLM : colonne vertébrale du dossier FinOps (20 % de la note)
LLM_TOKENS = Counter(
    "predicare_llm_tokens_total",
    "Tokens consommes par le LLM",
    ["service", "model", "kind"],
)
LLM_CALL_LATENCY = Histogram(
    "predicare_llm_call_duration_seconds",
    "Latence des appels LLM",
    ["service", "model", "outcome"],
    buckets=(0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0),
)

# Semantic caching : gain demontre devant le jury
CACHE_EVENTS = Counter(
    "predicare_semantic_cache_total",
    "Evenements du cache semantique",
    ["service", "result"],
)


#: Singleton cree a l'import. Prometheus refuse deux metriques de meme nom
#: dans un meme process : le construire dans chaque lifespan ferait echouer
#: le demarrage au second appel.
BUILD_INFO = Info("predicare_build", "Version du service deploye", ["service", "version"])


def publish_build(service: str, version: str) -> None:
    """Publie la version du service sur /metrics."""
    BUILD_INFO.labels(service=service, version=version)
