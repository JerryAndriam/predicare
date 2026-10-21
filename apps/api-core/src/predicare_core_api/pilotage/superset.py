"""Client minimal de l'API Superset pour l'embedding.

api-core ne signe pas les guest tokens : Superset les signe avec
`GUEST_TOKEN_JWT_SECRET`. Le client se connecte avec le compte de service
(reserve a cet usage), lit l'UUID du dashboard embedded, puis demande un
token court. Le navigateur ne voit jamais le mot de passe du compte.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from predicare.errors import PilotageUnavailableError
from predicare.logging_config import get_logger

logger = get_logger("api-core.pilotage")


@dataclass(frozen=True)
class GuestToken:
    token: str
    dashboard_uuid: str


class ClientSuperset:
    """Client HTTP synchrone, volontairement limite aux operations d'embedding."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self._jeton = ""
        self._csrf = ""
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
        )

    def __enter__(self) -> ClientSuperset:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _json(
        self, methode: str, chemin: str, charge: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        entetes = {
            "Accept": "application/json",
            "Referer": self.base_url,
        }
        if charge is not None:
            entetes["Content-Type"] = "application/json"
        if self._jeton:
            entetes["Authorization"] = f"Bearer {self._jeton}"
        if self._csrf:
            entetes["X-CSRFToken"] = self._csrf

        reponse = self._client.request(methode, chemin, json=charge, headers=entetes)
        reponse.raise_for_status()
        corps = reponse.json()
        if not isinstance(corps, dict):
            raise ValueError(f"Reponse Superset inattendue sur {chemin}.")
        return corps

    def _connecter(self) -> None:
        reponse = self._json(
            "POST",
            "/api/v1/security/login",
            {
                "username": self.username,
                "password": self.password,
                "provider": "db",
                "refresh": True,
            },
        )
        self._jeton = str(reponse.get("access_token") or "")
        if not self._jeton:
            raise ValueError("Superset n'a pas renvoye de jeton d'acces.")

        csrf = self._json("GET", "/api/v1/security/csrf_token/").get("result")
        self._csrf = str(csrf or "")
        if not self._csrf:
            raise ValueError("Superset n'a pas renvoye de jeton CSRF.")

    def demander_jeton(self, slug: str) -> GuestToken:
        """Demande un guest token pour le dashboard `slug`."""
        try:
            self._connecter()

            embedded = self._json("GET", f"/api/v1/dashboard/{slug}/embedded")
            resultat = embedded.get("result") or {}
            if not isinstance(resultat, dict):
                raise ValueError("Configuration embedded illisible.")
            uuid = str(resultat.get("uuid") or "")
            dashboard_id = str(resultat.get("dashboard_id") or "")
            if not uuid or not dashboard_id:
                raise ValueError("Dashboard non configure pour l'embedding.")

            reponse = self._json(
                "POST",
                "/api/v1/security/guest_token/",
                {
                    "user": {"username": "predicare-guest"},
                    "resources": [{"type": "dashboard", "id": dashboard_id}],
                    "rls": [],
                },
            )
            token = str(reponse.get("token") or "")
            if not token:
                raise ValueError("Superset n'a pas renvoye de guest token.")
            return GuestToken(token=token, dashboard_uuid=uuid)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logger.warning("pilotage.superset_indisponible", erreur=str(exc))
            raise PilotageUnavailableError(
                "Le pilotage decisionnel est indisponible. Verifiez que le profil BI est demarre."
            ) from exc
