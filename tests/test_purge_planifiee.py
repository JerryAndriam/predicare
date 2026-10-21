"""La purge RGPD doit tourner seule, sans jamais peser sur le demarrage.

Ces tests ne touchent pas PostgreSQL : ils verrouillent le cablage de la
tache de fond et la trace d'audit produite par la purge. Le comportement SQL
reel est verifie sur la pile, par la ligne `audit.journal` d'action
`purge_planifiee`.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

import pytest

from predicare_core_api import main as api_main
from predicare_core_api.rgpd import purge


class _LoggerFactice:
    def info(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def warning(self, *_args: Any, **_kwargs: Any) -> None:
        pass


def test_la_boucle_planifiee_appelle_la_purge(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le premier passage part apres le delai, puis la tache attend l'intervalle."""
    appels: list[str] = []
    monkeypatch.setenv("PURGE_PLANIFIEE", "1")
    monkeypatch.setenv("PURGE_DELAI_INITIAL_SECONDS", "0")
    monkeypatch.setenv("PURGE_INTERVALLE_SECONDS", "3600")

    def purge_factice() -> dict[str, int]:
        appels.append("purge")
        return {"predictions": 0, "factures": 0, "journal": 0}

    monkeypatch.setattr(purge, "executer_purge_planifiee", purge_factice)

    async def scenario() -> list[str]:
        tache = api_main.demarrer_purge_planifiee(_LoggerFactice())
        assert tache is not None
        for _ in range(200):
            if appels:
                break
            await asyncio.sleep(0.01)
        tache.cancel()
        with suppress(asyncio.CancelledError):
            await tache
        return appels

    assert asyncio.run(scenario()) == ["purge"]


def test_purge_planifiee_desactivee_ne_demarre_pas(monkeypatch: pytest.MonkeyPatch) -> None:
    """`PURGE_PLANIFIEE=0` ne cree aucune tache et n'appelle jamais la purge."""
    monkeypatch.setenv("PURGE_PLANIFIEE", "0")

    def purge_interdite() -> dict[str, int]:
        pytest.fail("la purge ne doit pas etre appelee quand PURGE_PLANIFIEE=0")

    monkeypatch.setattr(purge, "executer_purge_planifiee", purge_interdite)

    async def scenario() -> asyncio.Task[None] | None:
        return api_main.demarrer_purge_planifiee(_LoggerFactice())

    assert asyncio.run(scenario()) is None


def test_la_purge_journalise_son_compte_par_table(monkeypatch: pytest.MonkeyPatch) -> None:
    """La trace porte `purge_planifiee` et le nombre de lignes par famille."""
    resume = {"predictions": 2, "factures": 1, "journal": 3}
    captures: dict[str, Any] = {}
    monkeypatch.setattr(
        purge,
        "_cibles",
        lambda _session, _maintenant=None: (
            resume,
            {},
            {"predictions": [1, 2], "factures": [3], "journal": [4, 5, 6]},
        ),
    )
    monkeypatch.setattr(purge, "_supprimer", lambda _session, _ids: None)
    monkeypatch.setattr(
        purge,
        "journaliser",
        lambda _session, **champs: captures.update(champs),
    )

    resultat = purge.purger(object(), appliquer=True)

    assert resultat == resume
    assert captures["action"] == "purge_planifiee"
    assert captures["details"] == resume
    assert captures["role"] == "systeme"


def test_l_apercu_ne_journalise_rien(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sans application, aucune suppression et aucune ligne d'audit."""
    monkeypatch.setattr(
        purge,
        "_cibles",
        lambda _session, _maintenant=None: (
            {"predictions": 1, "factures": 0, "journal": 0},
            {},
            {"predictions": [9], "factures": [], "journal": []},
        ),
    )
    monkeypatch.setattr(
        purge,
        "_supprimer",
        lambda *_args: pytest.fail("un apercu ne supprime rien"),
    )
    monkeypatch.setattr(
        purge,
        "journaliser",
        lambda *_args, **_kwargs: pytest.fail("un apercu n'ecrit pas d'audit"),
    )

    resultat = purge.purger(object(), appliquer=False)

    assert resultat["predictions"] == 1
