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

        shap_values = np.zeros(len(self.bundle.feature_names))
        try:
            shap_values = self._contributions(vecteur)
        except Exception as exc:
            # Meme regle que dans le routeur : une explication indisponible ne
            # prive pas le gestionnaire de son score.
            logger.warning("shap.indisponible", erreur=str(exc))

        contributions = shap_to_contributions(
            self.bundle.feature_names, shap_values, self.bundle.shap_base_value
        )
        return Score(
            score=score,
            is_fraud=score >= self.seuil,
            seuil=self.seuil,
            contributions=contributions,
            inference_ms=(time.perf_counter() - debut) * 1000,
        )
