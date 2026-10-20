"""Parcours complet du lot de 20 factures inedites (CDC F17).

Ces tests ne tournent que si `PREDICARE_E2E=1` et `DEMO_PASSWORD` sont
definis : ils exigent api-core, api-inference et PostgreSQL demarres. Ils
soumettent le lot versionne `data/seed/lot_20_factures.json` par la porte du
front (`POST /api/core/factures/soumettre`), puis verifient :

- les 15 valides sont notees et les 7 alertes attendues apparaissent dans la
  file du gestionnaire ;
- les 5 invalides sont rejetees en nommant le champ fautif ;
- une alerte parcourt le cycle complet : detail SHAP -> decision -> historique.

Attention : ce parcours ecrit dans la base de demonstration. C'est le but
(le jury doit voir les alertes), mais il ne doit pas tourner sur une base de
production.

Usage :
    DEMO_PASSWORD='...' PREDICARE_E2E=1 \\
        uv run --all-packages pytest tests/e2e/test_lot_jury_e2e.py -q
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from predicare_seed.lot_jury import CasLot, Resultat, charger_lot, executer

pytestmark = pytest.mark.e2e

API_CORE_URL = os.getenv("API_CORE_URL", "http://localhost:8001").rstrip("/")
LOT = Path("data/seed/lot_20_factures.json")
#: Le lot couvre plusieurs prestataires : un professionnel ne peut deposer
#: que pour le sien, il refuse donc le lot. C'est l'administrateur qui passe :
#: c'est le role qui n'a pas de perimetre impose.
ADMIN_EMAIL = os.getenv("DEMO_EMAIL_ADMIN", "admin@predicare.local")
GESTIONNAIRE_EMAIL = os.getenv("DEMO_EMAIL_GESTIONNAIRE", "gestionnaire@predicare.local")
TIMEOUT = float(os.getenv("E2E_TIMEOUT", "60"))

MESSAGE_MOT_DE_PASSE = (
    "DEMO_PASSWORD non defini. Lancez : DEMO_PASSWORD='<mot-de-passe>' "
    "make comptes (le mot de passe est affiche une seule fois)"
)


def _login(http: httpx.Client, email: str, mot_de_passe: str) -> httpx.Client:
    reponse = http.post(
        f"{API_CORE_URL}/api/core/auth/login",
        json={"email": email, "password": mot_de_passe},
    )
    assert reponse.status_code == 200, reponse.text
    http.headers["Authorization"] = f"Bearer {reponse.json()['access_token']}"
    return http


@pytest.fixture(scope="module")
def mot_de_passe() -> str:
    if os.getenv("PREDICARE_E2E") != "1":
        pytest.skip("PREDICARE_E2E=1 requis pour interroger la pile reelle.")
    valeur = os.getenv("DEMO_PASSWORD", "").strip()
    if not valeur:
        pytest.skip(MESSAGE_MOT_DE_PASSE)
    return valeur


@pytest.fixture(scope="module")
def lot() -> list[CasLot]:
    return charger_lot(LOT)


@pytest.fixture(scope="module")
def resultats(mot_de_passe: str, lot: list[CasLot]) -> list[Resultat]:
    """Soumet le lot une seule fois pour tous les tests du module.

    `deja_notees=set()` est volontaire : ce parcours tourne depuis l'hote, ou
    la base (reseau Docker interne) n'est pas joignable. Une facture deja
    notee est donc renvoyee a l'API ; `stocker_prediction` met a jour la
    prediction en attente au lieu de la dupliquer.
    """
    with httpx.Client(base_url=API_CORE_URL, timeout=TIMEOUT) as http:
        _login(http, ADMIN_EMAIL, mot_de_passe)
        return executer(http, lot, deja_notees=set())


@pytest.fixture(scope="module")
def gestionnaire(mot_de_passe: str) -> httpx.Client:
    with httpx.Client(timeout=TIMEOUT) as http:
        yield _login(http, GESTIONNAIRE_EMAIL, mot_de_passe)


def _file_alertes(client: httpx.Client) -> list[dict]:
    """La file d'alertes du gestionnaire.

    La reponse est PAGEE : `{"items": [...], "total": N}`. Iterer sur la
    reponse brute iterait sur les CLES du dictionnaire -- et le test
    echouait sur un `TypeError` qui n'avait rien a voir avec la fraude.
    """
    reponse = client.get(f"{API_CORE_URL}/api/core/alertes/file", params={"limit": 200})
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    if isinstance(corps, dict):
        return list(corps.get("items") or [])
    return list(corps)


def test_les_15_valides_sont_notees(resultats: list[Resultat]) -> None:
    notees = [r for r in resultats if r.statut == "notee"]

    assert len(notees) == 15, [(r.facture_id, r.statut, r.message) for r in resultats]
    assert all(r.score is not None and 0.0 <= r.score <= 1.0 for r in notees)
    assert sum(1 for r in notees if r.alerte) == 7
    assert all(r.conforme for r in resultats), [
        (r.facture_id, r.message) for r in resultats if not r.conforme
    ]


def test_les_5_invalides_sont_rejetees_en_nommant_le_champ(
    lot: list[CasLot], resultats: list[Resultat]
) -> None:
    par_id = {r.facture_id: r for r in resultats}
    invalides = [cas for cas in lot if not cas.valide]

    assert len(invalides) == 5
    for cas in invalides:
        resultat = par_id[cas.facture_id]
        assert resultat.statut == "rejetee", (cas.facture_id, resultat.message)
        assert cas.champ_attendu in resultat.message, (cas.facture_id, resultat.message)


def test_les_alertes_attendues_sont_dans_la_file(
    resultats: list[Resultat], gestionnaire: httpx.Client
) -> None:
    file = _file_alertes(gestionnaire)
    scores = [float(alerte["score_fraude"]) for alerte in file]

    alertes_attendues = [r for r in resultats if r.alerte]
    assert len(alertes_attendues) == 7
    for resultat in alertes_attendues:
        assert any(abs(score - resultat.score) < 1e-4 for score in scores), (
            f"{resultat.facture_id} (score {resultat.score}) absente de la file"
        )


def _vient_du_lot(alerte: dict, resultats: list[Resultat]) -> bool:
    score = float(alerte["score_fraude"])
    return any(
        resultat.alerte and resultat.score is not None and abs(score - resultat.score) < 1e-4
        for resultat in resultats
    )


def test_une_alerte_parcourt_le_cycle_complet(
    resultats: list[Resultat], gestionnaire: httpx.Client
) -> None:
    """Detail SHAP -> decision -> historique, sur une alerte du lot."""
    file = _file_alertes(gestionnaire)
    candidates = [alerte for alerte in file if _vient_du_lot(alerte, resultats)]
    assert candidates, "aucune alerte du lot dans la file"
    alerte = max(candidates, key=lambda item: float(item["score_fraude"]))
    prediction_id = str(alerte["prediction_id"])

    detail = gestionnaire.get(f"{API_CORE_URL}/api/core/alertes/detail/{prediction_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["shap"], "le detail doit porter les contributions SHAP"

    decision = gestionnaire.post(
        f"{API_CORE_URL}/api/core/alertes/decision",
        json={
            "prediction_id": prediction_id,
            "decision": "rejeter",
            "commentaire": "Cycle e2e du lot F17 : facture conforme apres verification.",
            "decided_at": datetime.now(UTC).isoformat(),
        },
    )
    assert decision.status_code == 200, decision.text

    restantes = {str(item["prediction_id"]) for item in _file_alertes(gestionnaire)}
    assert prediction_id not in restantes, "une alerte decidee ne doit plus etre dans la file"

    historique = gestionnaire.get(
        f"{API_CORE_URL}/api/core/alertes/historique", params={"limit": 200}
    )
    assert historique.status_code == 200, historique.text
    corps = historique.json()
    elements = corps.get("items") if isinstance(corps, dict) else corps
    lignes = [item for item in (elements or []) if item["prediction_id"] == prediction_id]
    assert lignes, "la decision doit etre tracee dans audit.decision_gestionnaire"
    assert lignes[0]["decision"] == "rejeter"
