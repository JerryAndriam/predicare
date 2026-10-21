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
from predicare_core_api import notifications as core_notifications
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


# ---------------------------------------------------------------------------
# Flux 1 cote api-core : seuil de notification et charge envoyee a n8n
# ---------------------------------------------------------------------------
def test_seuil_notification_base_prime_sur_environnement(monkeypatch: pytest.MonkeyPatch) -> None:
    """`audit.parametre.seuil_notification` est la source prioritaire."""
    monkeypatch.setattr(core_notifications, "_lire_seuil_notification_base", lambda: 0.9)
    monkeypatch.setattr(core_notifications, "get_threshold", lambda: 0.2876)
    assert core_notifications.seuil_notification_effectif() == 0.9


def test_seuil_notification_repli_sur_environnement(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sans reglage en base, `N8N_SEUIL_NOTIFICATION` s'applique (defaut 0,8)."""
    monkeypatch.setattr(core_notifications, "_lire_seuil_notification_base", lambda: None)
    monkeypatch.setattr(core_notifications, "get_threshold", lambda: 0.2876)
    monkeypatch.setattr(get_settings(), "n8n_seuil_notification", 0.8)
    assert core_notifications.seuil_notification_effectif() == 0.8


def test_seuil_notification_ne_descend_pas_sous_la_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On ne notifie pas une facture que le modele n'a pas retenue."""
    monkeypatch.setattr(core_notifications, "_lire_seuil_notification_base", lambda: 0.2)
    monkeypatch.setattr(core_notifications, "get_threshold", lambda: 0.5)
    assert core_notifications.seuil_notification_effectif() == 0.5


def test_charge_alerte_porte_le_seuil_effectif(monkeypatch: pytest.MonkeyPatch) -> None:
    """n8n recoit le seuil : il n'a plus a relire une variable d'environnement."""
    monkeypatch.setattr(get_settings(), "n8n_alerte_webhook_url", URL_WEBHOOK)
    monkeypatch.setattr(core_notifications, "seuil_notification_effectif", lambda: 0.8)

    appels: list[tuple[str, dict, float]] = []

    def _post(url: str, *, json: dict, timeout: float) -> httpx.Response:
        appels.append((url, json, timeout))
        return _reponse(url)

    monkeypatch.setattr(core_notifications.httpx, "post", _post)

    resultat = core_notifications.notifier_alerte(
        facture_id="FAC-DEMO",
        score=0.985813,
        seuil=0.2876,
        rapport_shap="SHAP — montant_total (+0.42)",
        model_version="2",
        assure_pseudonyme="assr_demo",
        montant_total=12345.0,
    )

    assert resultat.envoye is True
    assert len(appels) == 1
    url, payload, timeout = appels[0]
    assert url == URL_WEBHOOK
    assert timeout == core_notifications.DELAI_SECONDES
    assert payload["seuil_notification"] == 0.8
    assert payload["seuil_applique"] == 0.2876
    assert payload["rapport_shap"].startswith("SHAP")
    assert payload["montant_total"] == 12345.0


def test_sous_le_seuil_aucun_appel_reseau(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le seuil de notification filtre AVANT l'appel : rien ne part."""
    monkeypatch.setattr(get_settings(), "n8n_alerte_webhook_url", URL_WEBHOOK)
    monkeypatch.setattr(core_notifications, "seuil_notification_effectif", lambda: 0.8)

    def _interdit(*args: object, **kwargs: object) -> httpx.Response:
        raise AssertionError("aucun appel reseau sous le seuil de notification")

    monkeypatch.setattr(core_notifications.httpx, "post", _interdit)

    resultat = core_notifications.notifier_alerte(
        facture_id="FAC-SOUS-SEUIL",
        score=0.45,
        seuil=0.2876,
        rapport_shap="SHAP",
    )
    assert resultat.envoye is False
    assert "sous le seuil de notification" in resultat.motif
