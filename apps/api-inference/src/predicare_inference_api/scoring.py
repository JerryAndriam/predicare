"""Score et contributions SHAP d'un vecteur de variables.

Ce calcul etait dans `router.py`. Il en sort pour que le job de notation en lot
(`noter.py`) et le service temps reel appliquent EXACTEMENT la meme formule.
Deux appels a `predict_proba` ecrits a deux endroits divergent un jour : un
arrondi, un seuil, un ordre de contributions, et le tableau de bord affiche
deux verites pour la meme facture.

La featurisation reste en amont, dans `predicare.features` : le service part
d'une payload (`build_features`), le job part des lignes stockees. Les deux
produisent le meme vecteur, et c'est ce que verifie `tests/test_features_parite`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from predicare.logging_config import get_logger
from predicare.schemas import ShapContribution
from predicare_inference_api.explainability import shap_to_contributions
from predicare_inference_api.registry import ModelBundle

logger = get_logger("api-inference.scoring")


@dataclass(frozen=True, slots=True)
class Score:
    """Resultat d'une notation, avant persistance."""

    score: float
    is_fraud: bool
    seuil: float
    contributions: list[ShapContribution]
    inference_ms: float
    #: Vrai si SHAP a REELLEMENT calcule les contributions. Faux = echec du
    #: calculateur : `contributions` est alors vide, jamais un vecteur de
    #: zeros. Un zero est une contribution possible ; le confondre avec une
    #: panne ferait croire au gestionnaire que le modele n'a rien vu.
    shap_available: bool = True


class Scorer:
    """Note des vecteurs avec un modele charge.

    Une instance par modele : `TreeExplainer` est construit au premier appel,
    puis reutilise. C'est ce qui rend le lot utilisable sur des milliers de
    factures, sans payer l'initialisation SHAP a chaque ligne.
    """

    def __init__(self, bundle: ModelBundle, *, seuil: float) -> None:
        self.bundle = bundle
        self.seuil = seuil
        self._explainer: Any = None

    def _contributions(self, row: np.ndarray) -> np.ndarray:
        if self._explainer is None:
            import shap

            self._explainer = shap.TreeExplainer(self.bundle.estimator)
        return np.asarray(self._explainer.shap_values(row)).ravel()

    def score(self, row: list[float]) -> Score:
        """Score un vecteur aligne sur `bundle.feature_names`."""
        debut = time.perf_counter()
        vecteur = np.array([row], dtype=float)

        estimateur: Any = self.bundle.estimator
        score = float(estimateur.predict_proba(vecteur)[0, 1])

        # Aucun vecteur de zeros par defaut : un echec de SHAP doit rester
        # VISIBLE. On renvoie une liste vide (le schema `PredictionResponse`
        # autorise `shap=[]`) plutot que des contributions fabriquees, et le
        # drapeau `shap_available` dit pourquoi.
        shap_values: np.ndarray | None = None
        try:
            shap_values = self._contributions(vecteur)
        except Exception as exc:
            # Une explication indisponible ne prive pas le gestionnaire de son
            # score, mais elle ne doit pas se faire passer pour une explication.
            logger.warning("shap.indisponible", erreur=str(exc))

        contributions = (
            shap_to_contributions(
                self.bundle.feature_names, shap_values, self.bundle.shap_base_value
            )
            if shap_values is not None
            else []
        )
        return Score(
            score=score,
            is_fraud=score >= self.seuil,
            seuil=self.seuil,
            contributions=contributions,
            inference_ms=(time.perf_counter() - debut) * 1000,
            shap_available=shap_values is not None,
        )
