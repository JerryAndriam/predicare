"""Suivi de derive : comparer les donnees servies a celles de l'entrainement.

Phase 3.4 du plan d'action. Un modele de fraude degrade silencieusement
quand la population change (nouveaux actes, nouveau comportement de
prescription). Sans surveillance, la seule mesure de sa qualite est la
qualite passe, obtenue des mois plus tot.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass(slots=True)
class DriftReport:
    """Resultat d'une analyse de derive, par variable et global."""

    window_days: int
    psi_global: float
    drifted_features: list[str] = field(default_factory=list)
    feature_scores: dict[str, float] = field(default_factory=dict)
    score_mean_reference: float = 0.0
    score_mean_current: float = 0.0
    alert: bool = False

    def summary(self) -> str:
        etat = "ALERTE" if self.alert else "nominal"
        return (
            f"Derive {etat} sur {self.window_days} jours - PSI global {self.psi_global:.4f}, "
            f"{len(self.drifted_features)} variable(s) concernee(s). "
            f"Score moyen : reference {self.score_mean_reference:.3f} "
            f"-> courant {self.score_mean_current:.3f}"
        )


def population_stability_index(
    reference: np.ndarray, current: np.ndarray, *, bins: int = 10
) -> float:
    """PSI entre deux distributions d'une meme variable.

    PSI < 0,10 : stable. 0,10 a 0,25 : derive moderee. > 0,25 : derive forte
    qui doit déclencher une revision du modele. Ce sont les seuils
    conventionnels du secteur, a citer dans le dossier de cadrage.
    """
    reference = np.asarray(reference, dtype=float)
    current = np.asarray(current, dtype=float)
    reference = reference[~np.isnan(reference)]
    current = current[~np.isnan(current)]
    if reference.size == 0 or current.size == 0:
        return 0.0

    quantiles = np.unique(np.quantile(reference, np.linspace(0, 1, bins + 1)))
    if quantiles.size < 3:
        return 0.0

    ref_counts, _ = np.histogram(reference, bins=quantiles)
    cur_counts, _ = np.histogram(current, bins=quantiles)
    # Lissage : une proportion nulle produit un PSI infini, ce qui est
    # statistiquement juste mais operationnellement inutile.
    epsilon = 1e-6
    ref_pct = (ref_counts / max(ref_counts.sum(), 1)) + epsilon
    cur_pct = (cur_counts / max(cur_counts.sum(), 1)) + epsilon

    return float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))


def detect_drift(
    reference_frame: pd.DataFrame,
    current_frame: pd.DataFrame,
    *,
    window_days: int = 30,
    psi_threshold: float = 0.10,
    score_threshold: float = 0.10,
) -> DriftReport:
    """Compare les distributions/features de la fenetre courante a l'entrainement."""
    common = [c for c in reference_frame.columns if c in current_frame.columns]

    scores: dict[str, float] = {}
    for column in common:
        scores[column] = population_stability_index(
            reference_frame[column].to_numpy(), current_frame[column].to_numpy()
        )

    drifted = [column for column, psi in scores.items() if psi >= psi_threshold]
    global_psi = max(scores.values(), default=0.0)

    ref_mean = (
        float(reference_frame["score_fraude"].mean()) if "score_fraude" in reference_frame else 0.0
    )
    cur_mean = (
        float(current_frame["score_fraude"].mean()) if "score_fraude" in current_frame else 0.0
    )

    return DriftReport(
        window_days=window_days,
        psi_global=global_psi,
        drifted_features=sorted(drifted, key=lambda c: scores[c], reverse=True),
        feature_scores=scores,
        score_mean_reference=ref_mean,
        score_mean_current=cur_mean,
        alert=global_psi >= psi_threshold or abs(cur_mean - ref_mean) >= score_threshold,
    )
