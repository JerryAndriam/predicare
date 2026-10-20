"""Registre de versions de modele : bascule a chaud et retour arriere.

Repond a la condition "Maintenable" du jury : deployer une nouvelle version
a cote de l'ancienne, basculer, revenir en arriere, SANS interruption de
service. Le modele actif et la version candidate resident dans le meme
processus : la bascule est un remplacement d'objet, donc atomique du point
de vue des appels en cours.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from predicare.errors import ModelNotReadyError
from predicare.logging_config import get_logger
from predicare.persistance_ml import SEUIL_PAR_DEFAUT, activer_version
from predicare_inference_api.notifications import notifier_bascule

logger = get_logger("api-inference.registry")


@dataclass(frozen=True, slots=True)
class ModelBundle:
    """Un modele charge, avec ses metadonnes de version."""

    version: str
    estimator: object
    feature_names: list[str]
    threshold: float
    metrics: dict[str, float]
    data_fingerprint: str = ""
    loaded_at: datetime | None = None
    #: Referentiels statiques, versionnes avec le modele. Sans eux, la
    #: featurisation tournerait a vide et toutes les variables de tarification
    #: retomberaient a leur valeur neutre : le modele noterait des factures
    #: qu'il n'a jamais vues dans cet etat. `features.py` les consomme, et
    #: `router.py` les passe a `build_features`.
    referentiels: object = None

    @property
    def shap_base_value(self) -> float:
        """Valeur de base SHAP : le score avant toute contribution."""
        try:
            return float(
                self.estimator.get_booster().predict(  # type: ignore[attr-defined]
                    [[0.0] * len(self.feature_names)], output_margin=True
                )[0]
            )
        except Exception:
            return 0.0


class ModelRegistry:
    """Etat du modele servi, thread-safe.

    Deux verrous distincts : un verrou de chargement (I/O disque, long) et un
    verrou d'ecriture rapide pour la bascule. Les requetes d'inference ne
    prennent qu'une reference, donc une bascule ne les bloque jamais.
    """

    def __init__(self, model_dir: Path, threshold: float | None = None) -> None:
        self.model_dir = model_dir
        #: Seuil impose par l'exploitation (`FRAUD_ALERT_THRESHOLD`). Il gagne
        #: sur tout le reste : un administrateur qui fixe un seuil le fait
        #: deliberement.
        self._threshold_impose = threshold
        #: Seuil arbitre par le modele (`metadata.json`, Phase 2.5). C'est le
        #: defaut : laisser le modele arriver avec son seuil calcule, sinon
        #: l'arbitrage cout/rappel reste sur l'etagere et le service alerte à
        #: 0.8 alors que le modele a ete cale pour 0.29.
        self._threshold_modele: float | None = None
        #: Seuil pose a chaud via `/seuil` (ecran d'administration).
        self._threshold_manuel: float | None = None
        self._active: ModelBundle | None = None
        self._candidate: ModelBundle | None = None
        self._load_lock = threading.Lock()
        self._swap_lock = threading.Lock()

    # ---------------------------------------------------------------- etat
    @property
    def active(self) -> ModelBundle:
        if self._active is None:
            raise ModelNotReadyError(
                "Aucun modele charge. Lancez `make train` ou verifiez le volume /models."
            )
        return self._active

    @property
    def candidate(self) -> ModelBundle | None:
        return self._candidate

    @property
    def seuil_impose(self) -> float | None:
        """Seuil venu de l'environnement, s'il a ete fixe explicitement."""
        return self._threshold_impose

    @property
    def threshold(self) -> float:
        """Seuil effectif, par ordre de priorite : manuel, impose, modele."""
        if self._threshold_manuel is not None:
            return self._threshold_manuel
        if self._threshold_impose is not None:
            return self._threshold_impose
        if self._threshold_modele is not None:
            return self._threshold_modele
        return SEUIL_PAR_DEFAUT

    def set_threshold(self, seuil: float) -> float:
        """Seuil d'alerte, modifiable a chaud depuis l'ecran d'administration."""
        if not 0.0 <= seuil <= 1.0:
            raise ValueError("Le seuil doit etre compris entre 0 et 1.")
        with self._swap_lock:
            previous = self.threshold
            self._threshold_manuel = seuil
        logger.info("seuil.change", ancien=previous, nouveau=seuil)
        return seuil

    # ---------------------------------------------------------------- chargement
    def load_version(self, version: str, *, as_candidate: bool = False) -> ModelBundle:
        """Charge une version depuis le volume /models et l'installe.

        L'echec de chargement d'une version CANDIDATE ne doit pas versions
        actives : on leve, mais le modele actif reste en place.
        """
        import joblib

        path = self.model_dir / version
        if not (path / "model.joblib").exists():
            raise ModelNotReadyError(
                f"Version {version} introuvable dans {self.model_dir}. "
                " artefacts attendus : model.joblib, metadata.json, features.json"
            )

        with self._load_lock:
            estimator = joblib.load(path / "model.joblib")
            features = json.loads((path / "features.json").read_text(encoding="utf-8"))
            meta_path = path / "metadata.json"
            metadata = (
                json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            )
            # Les referentiels sont optionnels : un modele plus ancien peut ne
            # pas en embarquer. La featurisation degrade alors vers ses valeurs
            # neutres, ce qui est visible dans les journaux, plutot que de
            # refuser de charger le modele.
            ref_path = path / "referentiels.json"
            referentiels = None
            if ref_path.exists():
                from predicare.features import charger_referentiels

                referentiels = charger_referentiels(
                    json.loads(ref_path.read_text(encoding="utf-8"))
                )
            else:
                logger.warning("referentiels.absents", version=version)

            # Seuil arbitre par le modele (Phase 2.5). Lu ici et non a la
            # construction du registre : c'est l'artefact qui le porte, pas la
            # configuration.
            seuil_modele = metadata.get("seuil")
            if isinstance(seuil_modele, (int, float)) and 0.0 < float(seuil_modele) <= 1.0:
                self._threshold_modele = float(seuil_modele)

        bundle = ModelBundle(
            version=version,
            estimator=estimator,
            feature_names=list(features),
            threshold=self.threshold,
            metrics=metadata.get("metrics", {}),
            data_fingerprint=metadata.get("data_fingerprint", ""),
            loaded_at=datetime.now(UTC),
            referentiels=referentiels,
        )

        with self._swap_lock:
            if as_candidate:
                self._candidate = bundle
                logger.info("modele.candidat_charge", version=version)
            else:
                self._active = bundle
                logger.info("modele.actif_charge", version=version)
        return bundle

    # ---------------------------------------------------------------- bascule
    def promote_candidate(self, *, acteur: str | None = None) -> str:
        """Bascule la version candidate en version active.

        Point de passage UNIQUE des deux chemins de bascule (api-core et appel
        direct a api-inference) : la notification n8n est emise ici, une seule
        fois par bascule reussie.
        """
        with self._swap_lock:
            if self._candidate is None:
                raise ModelNotReadyError("Aucune version candidate a promouvoir.")
            precedente = self._active.version if self._active else None
            promotee = self._candidate
            self._active = promotee
            self._candidate = None
        logger.info(
            "modele.bascule",
            version=promotee.version,
            version_avant=precedente,
        )
        # Le registre de la plateforme suit la bascule : sans cet appel,
        # `ml.modele_version` resterait sur « candidat » et l'ecran
        # d'administration annoncerait une version differente de celle qui
        # repond. Best-effort : la bascule en memoire a deja eu lieu.
        activer_version(promotee.version)
        # Meme doctrine pour n8n : la bascule est deja faite, la notification
        # ne peut que manquer (et laisser une trace), jamais la defaire.
        notifier_bascule(
            version_avant=precedente,
            version_apres=promotee.version,
            acteur=acteur,
        )
        return promotee.version

    def rollback(self, version: str) -> str:
        """Retour arriere vers une version precedente, deja presente sur le volume."""
        retour = self.load_version(version, as_candidate=False).version
        activer_version(retour)
        return retour

    def available_versions(self) -> list[str]:
        """Versions presentes sur le volume, de la plus recente a la plus ancienne."""
        if not self.model_dir.exists():
            return []
        versions = [
            d.name for d in self.model_dir.iterdir() if d.is_dir() and (d / "model.joblib").exists()
        ]
        return sorted(versions, reverse=True)

    def state(self) -> dict[str, object]:
        """Etat serialisable, consomme par l'ecran d'administration."""
        return {
            "active_version": self.active.version if self._active else None,
            "candidate_version": self._candidate.version if self._candidate else None,
            "loaded_at": (
                self._active.loaded_at.isoformat()
                if self._active and self._active.loaded_at
                else None
            ),
            "threshold": self.threshold,
            "metrics": self._active.metrics if self._active else {},
            "available_versions": self.available_versions(),
        }
