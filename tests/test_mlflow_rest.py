"""Journalisation MLflow : le job parle l'API REST, pas le SDK.

Un transport httpx simule verifie la SEQUENCE exacte des appels et la forme des
corps envoyes. C'est le contrat avec le serveur : une faute de frappe dans un
chemin d'API ne se verrait qu'au premier entrainement reel, c'est-a-dire au
pire moment.

Le deuxieme bloc verifie le contrat inverse : un serveur de suivi absent ne
doit JAMAIS faire echouer un entrainement qui, lui, est complet.
"""

from __future__ import annotations

import json
from typing import ClassVar

import httpx
import pytest

from predicare_ml_training import train as module_train
from predicare_ml_training.mlflow_rest import (
    JournalisationImpossibleError,
    journaliser,
)


def _client_simule(
    appels: list[tuple[str, dict]],
    *,
    statut: int = 200,
    experience_existe: bool = True,
    experience_supprimee: bool = False,
) -> httpx.Client:
    def repondre(requete: httpx.Request) -> httpx.Response:
        chemin = requete.url.path
        corps = json.loads(requete.content) if requete.content else dict(requete.url.params)
        appels.append((chemin, corps))
        if statut != 200:
            return httpx.Response(statut, text="serveur en vrac")
        if chemin.endswith("experiments/get-by-name"):
            if not experience_existe:
                return httpx.Response(
                    404, json={"error_code": "RESOURCE_DOES_NOT_EXIST", "message": "inconnue"}
                )
            etat = "deleted" if experience_supprimee else "active"
            return httpx.Response(
                200,
                json={
                    "experiment": {
                        "experiment_id": "7",
                        "name": "predicare-detection-fraude",
                        "lifecycle_stage": etat,
                    }
                },
            )
        if chemin.endswith("experiments/create"):
            return httpx.Response(200, json={"experiment_id": "8"})
        if chemin.endswith("experiments/restore"):
            return httpx.Response(200, json={})
        if chemin.endswith("runs/create"):
            return httpx.Response(200, json={"run": {"info": {"run_id": "run-abc"}}})
        return httpx.Response(200, json={})

    return httpx.Client(transport=httpx.MockTransport(repondre), base_url="http://mlflow:5000")


def test_journalisation_suit_les_quatre_etapes() -> None:
    appels: list[tuple[str, dict]] = []
    run_id = journaliser(
        "http://mlflow:5000",
        "modele-v2",
        {"version": "2", "seuil": 0.2766, "hp.max_depth": 8},
        {"rappel": 0.8747, "vrais_positifs": 768.0},
        client=_client_simule(appels),
    )

    assert run_id == "run-abc"
    assert [chemin for chemin, _ in appels] == [
        "/api/2.0/mlflow/experiments/get-by-name",
        "/api/2.0/mlflow/runs/create",
        "/api/2.0/mlflow/runs/log-batch",
        "/api/2.0/mlflow/runs/update",
    ]

    corps_run = appels[1][1]
    assert corps_run["experiment_id"] == "7"
    assert corps_run["run_name"] == "modele-v2"

    corps_lot = appels[2][1]
    assert corps_lot["run_id"] == "run-abc"
    # L'API MLflow n'accepte que des chaines en parametre : un nombre envoye
    # tel quel fait echouer la requete en 400.
    assert corps_lot["params"] == [
        {"key": "version", "value": "2"},
        {"key": "seuil", "value": "0.2766"},
        {"key": "hp.max_depth", "value": "8"},
    ]
    assert {metrique["key"] for metrique in corps_lot["metrics"]} == {
        "rappel",
        "vrais_positifs",
    }
    assert all(metrique["step"] == 0 for metrique in corps_lot["metrics"])

    assert appels[3][1]["status"] == "FINISHED"


def test_experience_creee_a_la_premiere_execution() -> None:
    """Le point d'entree « get-or-create » n'existe plus : creation en deux temps."""
    appels: list[tuple[str, dict]] = []
    journaliser(
        "http://mlflow:5000",
        "modele-v2",
        {},
        {},
        client=_client_simule(appels, experience_existe=False),
    )

    assert [chemin for chemin, _ in appels][:2] == [
        "/api/2.0/mlflow/experiments/get-by-name",
        "/api/2.0/mlflow/experiments/create",
    ]
    assert appels[1][1] == {"name": "predicare-detection-fraude"}
    assert appels[2][1]["experiment_id"] == "8"


def test_experience_supprimee_est_restauree() -> None:
    """Supprimer l'experience depuis l'interface ne doit pas perdre le suivi.

    MLflow refuse un run dans une experience `deleted` (400). La suppression
    est reversible : on la restaure, et le run part dans l'experience
    d'origine -- pas dans une deuxieme experience au nom voisin.
    """
    appels: list[tuple[str, dict]] = []
    journaliser(
        "http://mlflow:5000",
        "modele-v2",
        {},
        {},
        client=_client_simule(appels, experience_supprimee=True),
    )

    assert [chemin for chemin, _ in appels][:2] == [
        "/api/2.0/mlflow/experiments/get-by-name",
        "/api/2.0/mlflow/experiments/restore",
    ]
    assert appels[1][1] == {"experiment_id": "7"}
    assert appels[2][1]["experiment_id"] == "7"


def test_erreur_serveur_est_une_exception_explicite() -> None:
    appels: list[tuple[str, dict]] = []
    with pytest.raises(JournalisationImpossibleError, match="500"):
        journaliser(
            "http://mlflow:5000",
            "modele-v2",
            {},
            {},
            client=_client_simule(appels, statut=500),
        )


def test_reponse_non_json_est_une_exception_explicite() -> None:
    def repondre(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>portail captif</html>")

    client = httpx.Client(transport=httpx.MockTransport(repondre), base_url="http://mlflow:5000")
    with pytest.raises(JournalisationImpossibleError, match="illisible"):
        journaliser("http://mlflow:5000", "modele-v2", {}, {}, client=client)


class ArtefactFactice:
    """Ce que `_journaliser_mlflow` lit d'un artefact, et rien de plus."""

    seuil = 0.2766
    empreinte_donnees = "sha256:test"
    hyperparametres: ClassVar[dict[str, int]] = {"max_depth": 8}

    def metadata(self) -> dict:
        return {"metrics": {"rappel": 0.8747, "vrais_positifs": 768}}


def test_entrainement_aboutit_sans_serveur_de_suivi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    assert module_train._journaliser_mlflow("2", ArtefactFactice()) is False


def test_serveur_en_panne_ne_fait_pas_echouer_l_entrainement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")

    def explose(*args: object, **kwargs: object) -> str:
        raise httpx.ConnectError("DNS introuvable")

    monkeypatch.setattr(module_train, "journaliser", explose)
    assert module_train._journaliser_mlflow("2", ArtefactFactice()) is False


def test_artefact_transmis_sous_la_forme_attendue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
    recu: dict[str, object] = {}

    def capture(uri: str, run_name: str, params: dict, metrics: dict) -> str:
        recu.update(uri=uri, run_name=run_name, params=params, metrics=metrics)
        return "run-abc"

    monkeypatch.setattr(module_train, "journaliser", capture)
    assert module_train._journaliser_mlflow("2", ArtefactFactice()) is True
    assert recu["uri"] == "http://mlflow:5000"
    assert recu["run_name"] == "modele-v2"
    assert recu["params"] == {
        "version": "2",
        "seuil": 0.2766,
        "empreinte_donnees": "sha256:test",
        "hp.max_depth": 8,
    }
    assert recu["metrics"] == {"rappel": 0.8747, "vrais_positifs": 768.0}
