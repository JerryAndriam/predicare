"""Explicabilite SHAP : transformer un score en justification lisible.

Module 3 du cursus : le rapport SHAP est obligatoire pour chaque alerte
transmise au gestionnaire. Ce test verifie donc deux choses :

1. la selection des contributions les plus fortes est correcte ;
2. le texte produit est en francais et comprehensible par un gestionnaire,
   pas par un statisticien.
"""

from __future__ import annotations

import numpy as np
import pytest

from predicare.schemas import ShapContribution
from predicare_inference_api.explainability import (
    LIBELLES,
    build_shap_report,
    shap_to_contributions,
)
from predicare_inference_api.registry import ModelBundle
from predicare_inference_api.scoring import Scorer

FEATURES = ["montant_total", "actes_du_mois", "doublon_ordonnance", "montant_moyen_ligne"]
BASE_VALUE = 0.12


# --------------------------------------------------------------- selection


def test_valeurs_shap_converties_en_contributions() -> None:
    valeurs = np.array([0.35, -0.12, 0.08, 0.01])

    contributions = shap_to_contributions(FEATURES, valeurs, BASE_VALUE)

    assert len(contributions) == 4
    assert all(isinstance(c, ShapContribution) for c in contributions)


def test_tri_par_importance_decroissante() -> None:
    """Les contributions les plus fortes d'abord.

    Un gestionnaire lit les trois premieres lignes, pas les cinquante.
    """
    valeurs = np.array([0.01, 0.35, 0.08, -0.12])

    contributions = shap_to_contributions(FEATURES, valeurs, BASE_VALUE)
    importances = [abs(c.shap_value) for c in contributions]

    assert importances == sorted(importances, reverse=True)


def test_top_n_respecte() -> None:
    valeurs = np.array([0.35, -0.12, 0.08, 0.01])

    contributions = shap_to_contributions(FEATURES, valeurs, BASE_VALUE, top_n=2)

    assert len(contributions) == 2


def test_vecteur_plus_court_que_les_features_non_crashe() -> None:
    """Un modele et un jeu de donnees desynchronises ne doivent pas
    provoquer une IndexError au milieu d'une requete d'inference."""
    contributions = shap_to_contributions(FEATURES, np.array([0.1, 0.2]), BASE_VALUE)

    assert len(contributions) == 2


def test_vecteur_vide() -> None:
    assert shap_to_contributions(FEATURES, np.array([]), BASE_VALUE) == []


# --------------------------------------------------------------- direction


def test_contribution_positive_pousse_vers_la_fraude() -> None:
    valeurs = np.array([0.35, -0.12, 0.08, 0.01])

    contributions = {c.feature: c for c in shap_to_contributions(FEATURES, valeurs, BASE_VALUE)}

    assert contributions["montant_total"].direction == "pousse_vers_fraude"
    assert contributions["actes_du_mois"].direction == "pousse_vers_legitime"


def test_base_value_reportee() -> None:
    valeurs = np.array([0.35, -0.12, 0.08, 0.01])

    contributions = shap_to_contributions(FEATURES, valeurs, BASE_VALUE)

    assert contributions[0].base_value == pytest.approx(BASE_VALUE)


# --------------------------------------------------------------- lisibilite


@pytest.mark.parametrize("feature", list(LIBELLES))
def test_libelle_metier_present(feature: str) -> None:
    """Chaque variable connue a un libelle en francais.

    Sans libelle, l'interface afficherait le nom technique (`ratio_montant_mois`)
    a un gestionnaire qui ne parle pas SQL.
    """
    libelle = LIBELLES.get(feature, "")

    assert libelle, f"pas de libelle pour {feature}"
    assert "_" not in libelle, f"le libelle de {feature} ressemble a un nom technique"


def test_libelle_par_defaut_si_variable_inconnue() -> None:
    """Une variable inconnue ne doit pas faire echouer la generation :
    SHAP peut introduire une variable qu'on n'a pas encore Cablee."""
    contributions = shap_to_contributions(["mystere_absolue"], np.array([0.5]), BASE_VALUE)

    assert contributions[0].human_readable


def test_explication_positive_mentionne_le_risque() -> None:
    valeurs = np.array([0.35, -0.12, 0.08, 0.01])

    contributions = {c.feature: c for c in shap_to_contributions(FEATURES, valeurs, BASE_VALUE)}
    texte = contributions["montant_total"].human_readable

    assert "fraude" in texte.lower()


def test_explication_negative_dit_qu_elle_reduit_le_risque() -> None:
    valeurs = np.array([0.35, -0.12, 0.08, 0.01])

    contributions = {c.feature: c for c in shap_to_contributions(FEATURES, valeurs, BASE_VALUE)}
    texte = contributions["actes_du_mois"].human_readable

    # « reduire » est accentue : le libelle est destine a un lecteur
    # humain. Le test verifie donc la forme accentuee.
    assert "réduire" in texte.lower()


# --------------------------------------------------------------- rapport


def test_rapport_contient_score_et_seuil() -> None:
    valeurs = np.array([0.35, -0.12, 0.08, 0.01])
    contributions = shap_to_contributions(FEATURES, valeurs, BASE_VALUE)

    rapport = build_shap_report(contributions, score=0.87, seuil=0.8)

    assert "87%" in rapport
    assert "80%" in rapport


def test_rapport_classe_les_facteurs_par_numero() -> None:
    valeurs = np.array([0.35, -0.12, 0.08, 0.01])
    contributions = shap_to_contributions(FEATURES, valeurs, BASE_VALUE)

    rapport = build_shap_report(contributions, score=0.87, seuil=0.8)

    assert "1." in rapport
    assert "2." in rapport


def test_rapport_signe_les_contributions() -> None:
    """Le signe rend lisible si une variable reduit ou accroit le risque."""
    valeurs = np.array([0.35, -0.12, 0.08, 0.01])
    contributions = shap_to_contributions(FEATURES, valeurs, BASE_VALUE)

    rapport = build_shap_report(contributions, score=0.87, seuil=0.8)

    assert "[+0.350]" in rapport
    assert "[-0.120]" in rapport


def test_rapport_sans_contribution_dit_pourquoi() -> None:
    """Sans contribution dominante, l'explication doit le dire plutot que
    d'afficher une liste vide, que le gestionnaire lirait comme une panne."""
    rapport = build_shap_report([], score=0.62, seuil=0.8)

    assert "62%" in rapport
    assert "Aucune contribution" in rapport


def test_rapport_ne_mentionne_les_noms_techniques() -> None:
    """Aucun nom de variable technique ne doit apparaitre dans le texte
    envoye au gestionnaire."""
    valeurs = np.array([0.35, -0.12, 0.08, 0.01])
    contributions = shap_to_contributions(FEATURES, valeurs, BASE_VALUE)

    rapport = build_shap_report(contributions, score=0.87, seuil=0.8)

    for feature in FEATURES:
        assert feature not in rapport, f"{feature} apparait tel quel dans le rapport"


# ------------------------------------------------- indisponibilite de SHAP


class _EstimateurFactice:
    """Le minimum qu'un `Scorer` demande : `predict_proba` sur une ligne."""

    def __init__(self, score: float = 0.8) -> None:
        self._score = score

    def predict_proba(self, _vecteur: np.ndarray) -> np.ndarray:
        return np.array([[1.0 - self._score, self._score]])


class _JournalFactice:
    """Capture les appels de `logger.warning` sans dependre de structlog."""

    def __init__(self) -> None:
        self.evenements: list[tuple[str, dict]] = []

    def warning(self, evenement: str, **champs: object) -> None:
        self.evenements.append((evenement, champs))


def _bundle_factice() -> ModelBundle:
    return ModelBundle(
        version="test",
        estimator=_EstimateurFactice(),
        feature_names=list(FEATURES),
        threshold=0.5,
        metrics={},
    )


def test_shap_indisponible_ne_fabrique_pas_de_contributions(monkeypatch) -> None:
    """Un echec de SHAP ne doit pas produire un vecteur de zeros.

    Un zero est une contribution legitime ; le confondre avec une panne
    reviendrait a presenter au gestionnaire une « explication » vide comme si
    le modele n'avait rien vu. Le score reste servi, la liste est vide, et le
    drapeau dit la verite.
    """
    scorer = Scorer(_bundle_factice(), seuil=0.5)

    def _echec(_row: np.ndarray) -> np.ndarray:
        raise RuntimeError("TreeExplainer indisponible")

    journal = _JournalFactice()
    monkeypatch.setattr(scorer, "_contributions", _echec)
    monkeypatch.setattr("predicare_inference_api.scoring.logger", journal)

    notation = scorer.score([0.0] * len(FEATURES))

    assert notation.score == pytest.approx(0.8)
    assert notation.shap_available is False
    assert notation.contributions == []
    assert journal.evenements, "l'echec SHAP doit etre journalise"
    evenement, champs = journal.evenements[0]
    assert evenement == "shap.indisponible"
    assert "TreeExplainer indisponible" in str(champs.get("erreur", ""))


def test_shap_disponible_marque_les_contributions_comme_reelles(monkeypatch) -> None:
    """Symetrique du test precedent : un succes ne doit pas etre marque en panne."""
    scorer = Scorer(_bundle_factice(), seuil=0.5)
    valeurs = np.array([0.2, -0.1, 0.05, 0.01])
    monkeypatch.setattr(scorer, "_contributions", lambda _row: valeurs)

    notation = scorer.score([0.0] * len(FEATURES))

    assert notation.shap_available is True
    assert len(notation.contributions) == len(FEATURES)
