"""Client Superset utilise pour l'embedding du pilotage."""

from __future__ import annotations

import json

import httpx
import pytest

from predicare.errors import PilotageUnavailableError
from predicare_core_api.pilotage.superset import ClientSuperset


def test_demande_jeton_utilise_le_dashboard_embedded() -> None:
    appels: list[str] = []
    corps_guest: dict = {}

    def repondre(request: httpx.Request) -> httpx.Response:
        appels.append(request.url.path)
        if request.url.path == "/api/v1/security/login":
            return httpx.Response(200, json={"access_token": "jeton-admin"})
        if request.url.path == "/api/v1/security/csrf_token/":
            return httpx.Response(200, json={"result": "csrf"})
        if request.url.path == "/api/v1/dashboard/pilotage-mensuel/embedded":
            assert request.headers["Authorization"] == "Bearer jeton-admin"
            return httpx.Response(
                200,
                json={"result": {"uuid": "uuid-1", "dashboard_id": "42"}},
            )
        if request.url.path == "/api/v1/security/guest_token/":
            assert request.headers["X-CSRFToken"] == "csrf"
            corps_guest.update(json.loads(request.content))
            return httpx.Response(200, json={"token": "guest-token"})
        return httpx.Response(404)

    with ClientSuperset(
        "http://superset:8088",
        "predicare-bi",
        "mot-de-passe",
        transport=httpx.MockTransport(repondre),
    ) as client:
        jeton = client.demander_jeton("pilotage-mensuel")

    assert jeton.token == "guest-token"
    assert jeton.dashboard_uuid == "uuid-1"
    assert corps_guest["resources"] == [{"type": "dashboard", "id": "42"}]
    assert corps_guest["rls"] == []
    assert appels == [
        "/api/v1/security/login",
        "/api/v1/security/csrf_token/",
        "/api/v1/dashboard/pilotage-mensuel/embedded",
        "/api/v1/security/guest_token/",
    ]


def test_login_refuse_leve_pilotage_indisponible() -> None:
    def repondre(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "identifiants refuses"})

    with (
        ClientSuperset(
            "http://superset:8088",
            "predicare-bi",
            "mauvais",
            transport=httpx.MockTransport(repondre),
        ) as client,
        pytest.raises(PilotageUnavailableError) as erreur,
    ):
        client.demander_jeton("pilotage-mensuel")

    assert erreur.value.code == "pilotage_indisponible"
    assert erreur.value.http_status == 503
