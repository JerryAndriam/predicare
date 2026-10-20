"""Notification n8n de bascule de modele : contrat « ne leve jamais ».

Une bascule reussie ne doit jamais etre transformee en erreur 500 parce que
n8n est arrete, lent ou mal configure. Ces tests verrouillent ce contrat sans
reseau : `httpx.post` est remplace par une fonction de test.
"""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from predicare.config import Settings, get_settings
from predicare_inference_api import notifications

URL_WEBHOOK = "http://n8n:5678/webhook/bascule-modele"


def _reponse(url: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", url))


@pytest.fixture
def webhook(monkeypatch: pytest.MonkeyPatch) -> str:
    """Active le webhook pour la duree du test (le defaut est vide)."""
    monkeypatch.setattr(get_settings(), "n8n_bascule_webhook_url", URL_WEBHOOK)
    return URL_WEBHOOK


def test_webhook_vide_desactive(monkeypatch: pytest.MonkeyPatch) -> None:
    """URL vide = fonctionnalite desactivee : aucun appel reseau."""
    monkeypatch.setattr(get_settings(), "n8n_bascule_webhook_url", "")

    def _interdit(*args: object, **kwargs: object) -> httpx.Response:
        raise AssertionError("aucun appel reseau ne doit partir quand l'URL est vide")

    monkeypatch.setattr(notifications.httpx, "post", _interdit)
    assert notifications.notifier_bascule(version_avant="1", version_apres="2") is False


def test_payload_bascule(webhook: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Le workflow n8n recoit de quoi nommer la bascule et son auteur."""
    appels: list[tuple[str, dict, float]] = []

    def _post(url: str, *, json: dict, timeout: float) -> httpx.Response:
        appels.append((url, json, timeout))
        return _reponse(url)

    monkeypatch.setattr(notifications.httpx, "post", _post)

    assert (
        notifications.notifier_bascule(
            version_avant="1",
            version_apres="2",
            acteur="admin@predicare.local",
        )
        is True
    )

    assert len(appels) == 1
    url, payload, timeout = appels[0]
    assert url == webhook
    assert timeout == notifications.DELAI_WEBHOOK
    assert payload == {
        "evenement": "modele.bascule",
        "version_avant": "1",
        "version_apres": "2",
        "timestamp": payload["timestamp"],
        "acteur": "admin@predicare.local",
        "service": "api-inference",
    }
    horodatage = datetime.fromisoformat(payload["timestamp"])
    assert horodatage.tzinfo is not None


def test_webhook_injoignable_ne_leve_pas(webhook: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """n8n arrete : la bascule doit rester valide, la notification est perdue."""

    def _post(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("n8n down")

    monkeypatch.setattr(notifications.httpx, "post", _post)
    assert notifications.notifier_bascule(version_avant=None, version_apres="2") is False


def test_webhook_500_ne_leve_pas(webhook: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Un workflow en erreur (500) ne remonte pas dans la bascule."""

    def _post(url: str, *, json: dict, timeout: float) -> httpx.Response:
        return _reponse(url, status=500)

    monkeypatch.setattr(notifications.httpx, "post", _post)
    assert notifications.notifier_bascule(version_avant=None, version_apres="2") is False


def test_setting_vide_par_defaut(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sans configuration, la fonctionnalite est desactivee (pas d'appel)."""
    monkeypatch.delenv("N8N_BASCULE_WEBHOOK_URL", raising=False)
    assert Settings(_env_file=None).n8n_bascule_webhook_url == ""
