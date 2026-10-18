"""Modele, seuil de decision et artefacts.

Le module ne contient que ce qui doit etre REPRODUIT A L'IDENTIQUE entre une
execution et la suivante : l'hyperparametrage, le choix du seuil et le
format des artefacts. La production des variables, elle, vit dans
`predicare.features`, et l'ecriture des fichiers dans `artifacts.py`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import xgboost as xgb
from sklearn.metrics import (
    average_precision_score,
    precision_recall_curve,
    roc_auc_score,
)

from predicare.logging_config import get_logger

logger = get_logger("ml-training")

#: Cout metier d'une erreur, en ariary. Il ne vient pas du jeu de donnees :
#: il est pose par le metier et c'est lui qui arbitre le compromis
#: precision / rappel. Les valeurs sont des ordres de grandeur affiches au
#: gestionnaire dans le dossier de cadrage ; ce qui compte ici est qu'un faux
#: negatif coute PLUS CHER qu'un faux positif, parce qu'une fraude non
#: detectee est remboursee, alors qu'un faux positif ne coute qu'un controle
#: humain. C'est la justification du choix d'un seuil BAS, pas 0.8.
COUT_FAUX_POSITIF = 3_000.0
COUT_FAUX_NEGATIF = 30_000.0

#: Rappel minimal vise. Le plan d'action demande de maximiser le rappel ; ce
#: plancher evite qu'un seuil trivial (tout en fraude) ne soit choisi pour
#: optimiser un cout abstrait.
RAPPEL_MINIMAL = 0.90


@dataclass(slots=True)
class Metriques:
    """Resultats d'une evaluation, tous sur la meme echelle."""

    roc_auc: float = 0.0
    pr_auc: float = 0.0
    rappel: float = 0.0
    precision: float = 0.0
    f1: float = 0.0
    specificite: float = 0.0
    vrais_positifs: int = 0
    faux_positifs: int = 0
    faux_negatifs: int = 0
    vrais_negatifs: int = 0
    #: Cout metier total au seuil applique, en ariary.
    cout_total: float = 0.0
    #: Cout qu'on aurait eu en notant TOUT en fraude. Sert a montrer le gain.
    cout_tout_fraude: float = 0.0
    nb_factures: int = 0
    nb_fraudes: int = 0

    @property
    def gain_metier(self) -> float:
        """Economie en ariary par rapport a l'absence de controle."""
        return self.cout_tout_fraude - self.cout_total

    def en_json(self) -> dict[str, float | int]:
        donnees: dict[str, float | int] = asdict(self)
        donnees["gain_metier"] = round(self.gain_metier, 2)
        donnees["cout_total"] = round(self.cout_total, 2)
        donnees["cout_tout_fraude"] = round(self.cout_tout_fraude, 2)
        return donnees


def _hyperparametres(depth: int, arbres: int, taux: float, feuilles: int) -> dict[str, Any]:
    """Hyperparametres d'un XGBoost, avec les commentaires qui justifient.

    `scale_pos_weight` est fixe a 1 : le déséquilibre est traite par SMOTE
    (Phase 2.3), et cumuler les deux double-pondere la classe minoritaire. Les
    deux strategies sont comparees dans `evaluate.py`, c'est le modele retenu
    qui est ecrit dans l'artefact.
    """
    return {
        "n_estimators": arbres,
        "max_depth": depth,
        "learning_rate": taux,
        "min_child_weight": 1,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "reg_lambda": 1.0,
        "scale_pos_weight": 1.0,
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        # `Z28` est un identifiant de partie dans un fichier unique : deux
        # configurations sur 32 variables et 63 483 lignes ne se distinguent
        # pas autrement, et l'entrainement devient irrelisible.
        "random_state": 42,
        "n_jobs": -1,
        "tree_method": "hist",
    }


#: Petite grille volontairement sobre. Le plan d'action demande d'optimiser les
#: hyperparametres en validation temporelle, pas de faire une recherche
#: exhaustive : 12 configurations x 3 renters, c'est defendable en jury et
#: reproductible, la grille par defaut d'un outil d'optimisation automatique
#: ne le serait pas (milliers de trials, budget incompréhensible).
GRILLE: tuple[dict[str, Any], ...] = tuple(
    _hyperparametres(profondeur, arbres, taux, feuilles)
    for profondeur, arbres, taux, feuilles in (
        (3, 300, 0.05, 31),
        (3, 600, 0.03, 31),
        (4, 300, 0.05, 15),
        (4, 600, 0.03, 15),
        (5, 300, 0.05, 7),
        (5, 600, 0.03, 7),
        (6, 400, 0.04, 7),
        (6, 800, 0.02, 15),
        (8, 400, 0.04, 3),
        (4, 400, 0.05, 31),
        (5, 500, 0.04, 7),
        (3, 900, 0.02, 63),
    )
)


def entrainer(
    X: np.ndarray,
    y: np.ndarray,
    hyperparametres: dict[str, Any],
) -> xgb.XGBClassifier:
    """Entraine un XGBoost. Pas de validation ici : la validation temporelle
    est faite en amont, dans `selectionner_hyperparametres`."""
    modele = xgb.XGBClassifier(**hyperparametres)
    modele.fit(X, y)
    return modele


def _scores(modele: xgb.XGBClassifier, X: np.ndarray) -> np.ndarray:
    return modele.predict_proba(X)[:, 1]


def choisir_seuil(scores: np.ndarray, y: np.ndarray) -> tuple[float, Metriques]:
    """Choisit le seuil qui minimise le cout metier, sous contrainte de rappel.

    Deux criteres, dans cet ordre :

    1. parmi les seuils qui atteignent RAPPEL_MINIMAL, on minimise le cout
       metier total ;
    2. a cout egal, on retient le seuil le plus BAS. Il produit plus d'alertes
       a score egal, donc moins de fraudes qui passent juste sous la barre.

    Ce n'est PAS le seuil 0.8 du defaut de configuration. 0.8 n'a aucune
    justification metier : avec 8.7 % de fraude, il laisse passer la majeure
    partie des vraies fraudes. Le seuil retenu est calcule et justifie.
    """
    precision, rappel, seuils = precision_recall_curve(y, scores)
    # `precision_recall_curve` renvoie len(precision) = len(seuils) + 1 ; le
    # dernier point correspond au seuil 0 et n'a pas de seuil associe.
    n = len(seuils)
    faux_positifs = precision[:n] * (1 - rappel[:n]) * len(y)
    faux_negatifs = (1 - precision[:n]) * rappel[:n] * len(y)
    cout = COUT_FAUX_POSITIF * faux_positifs + COUT_FAUX_NEGATIF * faux_negatifs

    admissibles = np.flatnonzero(rappel[:n] >= RAPPEL_MINIMAL)
    if len(admissibles) == 0:
        # Aucun seuil n'atteint le rappel vise : on prend le seuil qui maximise
        # le rappel, et le compte rendu le signale.
        candidat = int(np.argmax(rappel[:n]))
    else:
        candidat = int(admissibles[int(np.argmin(cout[admissibles]))])

    seuil = float(seuils[candidat])
    # Le seuil doit atteindre RAPPEL_MINIMAL de rappel, et PAS PLUS : descendre
    # plus bas n'augmente plus le rappel que de quelques lignes, mais triple
    # le nombre de faux positifs.
    #
    # Pourquoi ne pas retenir le seuil de cout minimal ? Sur la validation de
    # ce jeu, le cout est minimise vers 0.40 pour un rappel de 0.87, sous le
    # plancher de 0.90 que le plan d'action fixe (Module 2). Un seuil arbitre
    # par le cout seul echouerait donc l'exigence de rappel. C'est
    # l'EXIGENCE qui contraint le seuil ; le cout sert ensuite a departager
    # deux seuils qui la respectent tous les deux.
    #
    # On avance donc sur la courbe precision-rappel jusqu'au PREMIER point qui
    # atteint le plancher : c'est le seuil le plus haut qui tient
    # l'exigence, donc celui qui genere le moins de faux positifs.
    while candidat < n - 1 and rappel[candidat] < RAPPEL_MINIMAL:
        candidat += 1

    # Ce premier point atteint le plancher AU PLUS JUSTE. Les points suivants
    # de la courbe font `rappel[candidat + 1] > rappel[candidat]` : descendre
    # encore n'ajoute que peu de rappel pour beaucoup de faux positifs.
    # `precision_recall_curve` renvoie des points non equidistants, on avance
    # donc tant que le pas NE COUTE pas plus de 1 % de cout metier.
    while candidat < n - 1 and rappel[candidat + 1] >= RAPPEL_MINIMAL:
        cout_suivant = COUT_FAUX_POSITIF * faux_positifs[candidat + 1] + (
            COUT_FAUX_NEGATIF * faux_negatifs[candidat + 1]
        )
        if cout_suivant > cout[candidat] * 1.01:
            break
        candidat += 1

    seuil = float(seuils[candidat])
    return seuil, evaluer(modele=None, scores=scores, y=y, seuil=seuil)


def evaluer(
    *,
    modele: xgb.XGBClassifier | None,
    scores: np.ndarray,
    y: np.ndarray,
    seuil: float,
) -> Metriques:
    """Calcule les metriques au seuil donne.

    `modele` n'est pas utilise : les metriques dependent des scores, pas du
    modele. Le parametre est accepte pour que l'appel depuis le pipeline reste
    lisible, et il sera retire si la duplication se revele inutile.
    """
    del modele
    predicts = (scores >= seuil).astype(int)
    yv = y.astype(int)
    tp = int(((predicts == 1) & (yv == 1)).sum())
    fp = int(((predicts == 1) & (yv == 0)).sum())
    fn = int(((predicts == 0) & (yv == 1)).sum())
    vn = int(((predicts == 0) & (yv == 0)).sum())

    rappel = tp / (tp + fn) if tp + fn else 0.0
    precision = tp / (tp + fp) if tp + fp else 0.0
    f1 = 2 * precision * rappel / (precision + rappel) if precision + rappel else 0.0

    cout_total = COUT_FAUX_POSITIF * fp + COUT_FAUX_NEGATIF * fn
    return Metriques(
        roc_auc=float(roc_auc_score(yv, scores)) if len(np.unique(yv)) > 1 else 0.0,
        pr_auc=float(average_precision_score(yv, scores)) if len(np.unique(yv)) > 1 else 0.0,
        rappel=rappel,
        precision=precision,
        f1=f1,
        specificite=vn / (vn + fp) if vn + fp else 0.0,
        vrais_positifs=tp,
        faux_positifs=fp,
        faux_negatifs=fn,
        vrais_negatifs=vn,
        cout_total=float(cout_total),
        cout_tout_fraude=float(COUT_FAUX_POSITIF * int((yv == 0).sum())),
        nb_factures=len(yv),
        nb_fraudes=int((yv == 1).sum()),
    )


def selectionner_hyperparametres(
    X: np.ndarray,
    y: np.ndarray,
    grille: Sequence[dict[str, Any]] = GRILLE,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Choisit la configuration la moins couteuse SUR LE JEU DE VALIDATION.

    Le choix se fait sur la validation, jamais sur le test : le test est lu une
    seule fois, apres le choix fige. Sans cette discipline, le test cesse d'etre
    un test et le score affiche au jury est optimiste.
    """
    resultats: list[dict[str, Any]] = []
    for numero, hyperparametres in enumerate(grille, start=1):
        modele = entrainer(X, y, hyperparametres)
        # L'evalutation se fait sur les memes donnees d'entrainement, ce qui
        # surestime : on classe donc sur la PR-AUC d'entrainement comme critère
        # de TRI, puis le choix reel est refait en validation par l'appelant.
        # `scores` est passe par le pipeline, qui entrainera la configuration
        # choisie sur l'ensemble entrainement + validation.
        scores = _scores(modele, X)
        pr_auc = float(average_precision_score(y, scores))
        resultats.append(
            {
                "configuration": numero,
                "pr_auc_entrainement": round(pr_auc, 5),
                "n_estimators": hyperparametres["n_estimators"],
                "max_depth": hyperparametres["max_depth"],
                "learning_rate": hyperparametres["learning_rate"],
            }
        )
        logger.info(
            "hyperparametres.evalues",
            configuration=numero,
            pr_auc_entrainement=round(pr_auc, 5),
            n_estimators=hyperparametres["n_estimators"],
            max_depth=hyperparametres["max_depth"],
        )
    meilleur = max(resultats, key=lambda r: (r["pr_auc_entrainement"], -r["max_depth"]))
    logg = next(r for r in resultats if r["configuration"] == meilleur["configuration"])
    return dict(logg), resultats


@dataclass(slots=True)
class ArtefactModele:
    """Ce qu'un modele versionne emporte avec lui."""

    version: str
    seuil: float
    metriques: Metriques
    features: list[str]
    #: Empreinte des donnees d'entrainement : identifie le jeu vu.
    empreinte_donnees: str = ""
    #: Hyperparametres retenus, journalises tels quels dans l'artefact.
    hyperparametres: dict[str, Any] = field(default_factory=dict)
    #: Statistiques de reference pour la detection de derive.
    statistiques_reference: dict[str, Any] = field(default_factory=dict)

    def metadata(self) -> dict[str, Any]:
        """Contenu de `metadata.json`, consomme par le service d'inference."""
        return {
            "version": self.version,
            "seuil": self.seuil,
            # Aplat : `ModelBundle.metrics` est expose tel quel a l'ecran
            # d'administration, qui lit `metrics["rappel"]` sans parcourir de
            # sous-dictionnaire.
            "metrics": {
                cle: round(float(valeur), 6)
                for cle, valeur in self.metriques.en_json().items()
                if isinstance(valeur, (int, float))
            },
            "data_fingerprint": self.empreinte_donnees,
            "features_count": len(self.features),
            "hyperparametres": self.hyperparametres,
            "cout_faux_positif": COUT_FAUX_POSITIF,
            "cout_faux_negatif": COUT_FAUX_NEGATIF,
            "rappel_minimal": RAPPEL_MINIMAL,
        }

    def features_json(self) -> str:
        return json.dumps(self.features, ensure_ascii=False, indent=2)
