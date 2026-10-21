"""Notification n8n des bascules de modele.

La bascule est un evenement d'exploitation : le jury doit voir qu'un nouveau
modele est en service, et sur quelle version il est revenu en cas de retour
arriere. Le webhook n8n est donc appele APRES la bascule en memoire.

Contrat : ne leve jamais. Une notification perdue ne doit pas transformer une
bascule reussie en erreur 500, ni empecher l'ecriture dans `ml.modele_version`.
C'est la meme doctrine que `predicare.persistance_ml.activer_version`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from predicare.config import get_settings
from predicare.logging_config import get_logger

logger = get_logger("api-inference.notifications")

#: Court volontairement : api-core proxifie la bascule avec un timeout de 10 s.
DELAI_WEBHOOK = 2.0


def notifier_bascule(
    *,
    version_avant: str | None,
    version_apres: str,
    acteur: str | None = None,
) -> bool:
    """POST le webhook n8n de bascule. Retourne True si la notification est partie.

    URL vide = fonctionnalite desactivee (cas par defaut, et cas des tests
    unitaires) : aucun appel reseau n'est tente.
    """
    url = get_settings().n8n_bascule_webhook_url.strip()
    if not url:
        return False

    payload = {
        "evenement": "modele.bascule",
        "version_avant": version_avant,
        "version_apres": version_apres,
        "timestamp": datetime.now(UTC).isoformat(),
        "acteur": acteur,
        "service": "api-inference",
    }
    # Volontairement large : une notification ne fait jamais echouer la bascule.
    try:
        httpx.post(url, json=payload, timeout=DELAI_WEBHOOK).raise_for_status()
    except Exception as exc:
        logger.warning(
            "modele.bascule_non_notifiee",
            version_avant=version_avant,
            version_apres=version_apres,
            erreur=str(exc),
        )
        return False

    logger.info(
        "modele.bascule_notifiee",
        version_avant=version_avant,
        version_apres=version_apres,
        acteur=acteur,
    )
    return True
