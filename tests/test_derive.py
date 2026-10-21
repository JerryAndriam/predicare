"""Suivi de derive : PSI, detection et persistance tolerante.

Les tests de calcul sont purs (numpy/pandas). Les deux tests de persistance
verifient le contrat « une panne de base ne tue pas le worker » : ils ne
touchent pas PostgreSQL.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from predicare.persistance_ml import (
    lire_dernier_rapport_derive,
    persister_rapport_derive,
)
from predicare_inference_api.drift import detect_drift, population_stability_index


def _frame(scores: np.ndarray, montants: np.ndarray | None = None) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "score_fraude": scores,
            "montant_total": montants if montants is not None else np.full(scores.size, 100.0),
        }
    )


def test_psi_nul_sur_deux_distributions_identiques() -> None:
    rng = np.random.default_rng(42)
    valeurs = rng.normal(0.3, 0.1, 1_000)
    assert population_stability_index(valeurs, valeurs) == pytest.approx(0.0, abs=1e-9)


def test_psi_detecte_un_decalage_fort() -> None:
    reference = np.linspace(0.0, 0.3, 1_000)
    courante = np.linspace(0.7, 1.0, 1_000)
    assert population_stability_index(reference, courante) > 0.25


def test_detect_drift_nominal() -> None:
    rng = np.random.default_rng(7)
    reference = _frame(rng.normal(0.2, 0.05, 2_000))
    courante = _frame(rng.normal(0.2, 0.05, 2_000))

    rapport = detect_drift(reference, courante, window_days=30)

    assert rapport.alert is False
    assert rapport.drifted_features == []
    assert rapport.psi_global < 0.10
    assert rapport.score_mean_reference == pytest.approx(0.2, abs=0.01)
    assert rapport.score_mean_current == pytest.approx(0.2, abs=0.01)


def test_detect_drift_alerte_et_nomme_la_variable() -> None:
    rng = np.random.default_rng(11)
    montants = rng.normal(100.0, 5.0, 2_000)
    reference = _frame(rng.normal(0.15, 0.05, 2_000), montants)
    courante = _frame(rng.normal(0.75, 0.05, 2_000), montants)

    rapport = detect_drift(reference, courante, window_days=30)

    assert rapport.alert is True
    assert "score_fraude" in rapport.drifted_features
    assert rapport.feature_scores["score_fraude"] > 0.25
    assert rapport.score_mean_current > rapport.score_mean_reference
    assert "ALERTE" in rapport.summary()


def test_detect_drift_ignore_les_colonnes_absentes() -> None:
    reference = _frame(np.linspace(0.0, 1.0, 100))
    courante = _frame(np.linspace(0.0, 1.0, 100)).drop(columns=["montant_total"])

    rapport = detect_drift(reference, courante)

    assert set(rapport.feature_scores) == {"score_fraude"}


def test_rapport_non_persiste_ne_leve_pas(monkeypatch: pytest.MonkeyPatch) -> None:
    import predicare.persistance_ml as module

    def _explose() -> None:
        raise RuntimeError("base injoignable")

    monkeypatch.setattr(module, "session_scope", _explose)

    resultat = persister_rapport_derive(
        fenetre_jours=30,
        psi_global=0.4,
        variables_concernees={"concernees": ["score_fraude"]},
        score_moyen_reference=0.1,
        score_moyen_courant=0.5,
        alerte=True,
    )

    assert resultat is None


def test_lecture_derive_base_injoignable_ne_leve_pas(monkeypatch: pytest.MonkeyPatch) -> None:
    import predicare.persistance_ml as module

    def _explose() -> None:
        raise RuntimeError("base injoignable")

    monkeypatch.setattr(module, "session_scope", _explose)

    assert lire_dernier_rapport_derive() is None
