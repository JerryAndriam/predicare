"""Chargement, notation et bascule d'un modele par le registre.

Ces tests ecrivent un vrai artefact `model.joblib` / `features.json` /
`metadata.json` / `referentiels.json` dans un dossier temporaire, puis le
font charger par `ModelRegistry` exactement comme le fait le demarrage du
service. Ils couvrent donc le contrat d'artefact de bout en bout, sans base ni
conteneur.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import joblib
import numpy as np
import pytest
import xgboost as xgb

from predicare.config import get_settings
from predicare.errors import ModelNotReadyError
from predicare.features import (
    NOMS_FEATURES,
    Acte,
    Contrat,
    GarantieCategorie,
    Ordonnance,
    Prestataire,
    Referentiels,
)
from predicare.schemas import InvoiceSubmission
from predicare_inference_api.context import resolve_context
from predicare_inference_api.explainability import (
    LIBELLES,
    build_shap_report,
    shap_to_contributions,
)
from predicare_inference_api.features import build_features
from predicare_inference_api.registry import ModelRegistry
from predicare_inference_api.validation import validate_invoice

SEUIL_PAR_DEFAUT = 0.5


def entrainer_un_modele(seed: int = 0, seuil: float = SEUIL_PAR_DEFAUT) -> xgb.XGBClassifier:
    """XGBoost minuscule mais REEL, sur le vrai jeu de variables.

    Un modele factice (`predict_proba` bricole) ne prouverait rien : il ne
    serait pas un booster, donc `shap.TreeExplainer` echouerait et le test de
    la note SHAP ne testerait que le repli silencieux sur des zeros.
    """
    generateur = np.random.default_rng(seed)
    n = 400
    X = generateur.normal(size=(n, len(NOMS_FEATURES)))  # noqa: N806 - convention ML
    # Un signal franc sur deux variables : le modele a vraiment de quoi
    # apprendre, et SHAP a vraiment des contributions a calculer.
    y = ((X[:, 0] > 0.5) | (X[:, 3] > 1.0)).astype(int)
    modele = xgb.XGBClassifier(
        n_estimators=20,
        max_depth=3,
        random_state=seed,
        tree_method="hist",
        eval_metric="logloss",
    )
    modele.fit(X, y)
    return modele


def ecrire_artefact(dossier: Path, modele: xgb.XGBClassifier, *, version: str) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    joblib.dump(modele, dossier / "model.joblib")
    (dossier / "features.json").write_text(json.dumps(list(NOMS_FEATURES)), encoding="utf-8")
    (dossier / "metadata.json").write_text(
        json.dumps(
            {
                "version": version,
                "seuil": SEUIL_PAR_DEFAUT,
                "metrics": {"rappel": 0.91, "precision": 0.55, "pr_auc": 0.89},
                "data_fingerprint": "sha256:" + "0" * 64,
            }
        ),
        encoding="utf-8",
    )
    (dossier / "referentiels.json").write_text(
        json.dumps(
            {
                "actes": {
                    "CONS-GEN": {
                        "categorie": "CONSULTATION",
                        "tarif_reference": 20_000.0,
                        "tarif_max": 50_000.0,
                        "ordonnance_requise": True,
                    }
                },
                "prestataires": {"PRE-001": {"jours_ouverture": "123456", "heure_fermeture": 17}},
                "garanties": {"ESSENTIEL|CONSULTATION": {"plafond_annuel_categorie": 600_000.0}},
                "contrats": {"CTR-1": {"date_effet": "2024-01-01", "formule": "ESSENTIEL"}},
            }
        ),
        encoding="utf-8",
    )
    return dossier


@pytest.fixture
def registre(tmp_path: Path) -> tuple[ModelRegistry, Path]:
    modele = entrainer_un_modele()
    racine = tmp_path / "models"
    ecrire_artefact(racine / "1", modele, version="1")
    return ModelRegistry(model_dir=racine, threshold=SEUIL_PAR_DEFAUT), racine


def payload(**champs) -> dict:
    jour = date_du_test()
    base = {
        "facture_id": "FAC-TEST-777",
        "assure_pseudonyme": "assr_test1234",
        "prestataire_id": "PRE-001",
        "date_facture": datetime.combine(jour, datetime.min.time(), tzinfo=UTC),
        "montant_total": 9_000.0,
        "lignes": [
            {
                "code_acte": "CONS-GEN",
                "quantite": 2,
                "montant_unitaire": 4_500.0,
                "date_acte": datetime.combine(
                    jour - timedelta(days=1), datetime.min.time(), tzinfo=UTC
                ),
            }
        ],
    }
    base.update(champs)
    return base


def date_du_test():
    from datetime import date as _date

    return _date.today() - timedelta(days=10)


# ---------------------------------------------------------------------------
# Chargement
# ---------------------------------------------------------------------------
def test_chargement_lit_les_quatre_fichets(registre: tuple[ModelRegistry, Path]) -> None:
    model_registry, _ = registre
    bundle = model_registry.load_version("1")

    assert bundle.version == "1"
    assert bundle.feature_names == list(NOMS_FEATURES)
    assert bundle.metrics["rappel"] == 0.91
    assert bundle.data_fingerprint.startswith("sha256:")
    assert bundle.referentiels is not None
    assert "CONS-GEN" in bundle.referentiels.actes


def test_version_absente_leve_model_not_ready(tmp_path: Path) -> None:
    model_registry = ModelRegistry(model_dir=tmp_path / "vide", threshold=SEUIL_PAR_DEFAUT)
    with pytest.raises(ModelNotReadyError):
        model_registry.load_version("1")


def test_modele_sans_referentiels_charge_quand_meme(tmp_path: Path) -> None:
    """Un artefact ancien, sans `referentiels.json`, doit charger.

    Refuser de demarrer le service parce qu'un fichier optionnel manque
    rendrait la detection de fraude indisponible au pire moment.
    """
    modele = entrainer_un_modele()
    racine = tmp_path / "models"
    dossier = racine / "1"
    dossier.mkdir(parents=True)
    joblib.dump(modele, dossier / "model.joblib")
    (dossier / "features.json").write_text(json.dumps(list(NOMS_FEATURES)), encoding="utf-8")

    model_registry = ModelRegistry(model_dir=racine, threshold=SEUIL_PAR_DEFAUT)
    bundle = model_registry.load_version("1")
    assert bundle.referentiels is None

    # Et la featurisation degrade proprement.
    submission = validate_invoice(payload())
    valeurs = build_features(submission, bundle.referentiels).values
    assert set(valeurs) == set(NOMS_FEATURES)


def test_versions_disponibles_triees(registre: tuple[ModelRegistry, Path]) -> None:
    model_registry, racine = registre
    entrainer_un_modele(seed=1)
    ecrire_artefact(racine / "2", entrainer_un_modele(seed=1), version="2")
    ecrire_artefact(racine / "10", entrainer_un_modele(seed=2), version="10")

    versions = model_registry.available_versions()
    assert versions == sorted(versions, reverse=True)
    assert {"1", "2", "10"} <= set(versions)


# ---------------------------------------------------------------------------
# Notation de bout en bout
# ---------------------------------------------------------------------------
def test_prediction_debout_en_bout(registre: tuple[ModelRegistry, Path]) -> None:
    model_registry, _ = registre
    bundle = model_registry.load_version("1")

    submission = validate_invoice(payload())
    valeurs = build_features(submission, bundle.referentiels)
    # Le passage par `as_row` est ce que fait `router.py`, et c'est lui qui
    # garantit l'alignement sur l'ordre de `features.json`.
    row = valeurs.as_row(bundle.feature_names)

    score = float(bundle.estimator.predict_proba(np.array([row]))[0, 1])
    assert 0.0 <= score <= 1.0
    assert (score >= SEUIL_PAR_DEFAUT) == (score >= bundle.threshold)


def test_alignement_avec_features_json(registre: tuple[ModelRegistry, Path]) -> None:
    """Le vecteur doit avoir la longueur attendue par le modele.

    XGBoost leve une `ValueError` si la longueur ne correspond pas : c'est le
    seul garde-fou, et il se declenche au moment de la notation, pas au
    chargement. Ce test l'attrape avant.
    """
    model_registry, _ = registre
    bundle = model_registry.load_version("1")
    submission = validate_invoice(payload())
    valeurs = build_features(submission, bundle.referentiels)

    row = valeurs.as_row(bundle.feature_names)
    assert len(row) == bundle.estimator.n_features_in_
    # `predict_proba` ne doit pas lever.
    bundle.estimator.predict_proba(np.array([row]))


def test_resolution_de_contexte_absorbee(registre: tuple[ModelRegistry, Path]) -> None:
    """Meme avec une base injoignable, la facture est notee.

    Le jour J, une base indisponible ne doit pas transformer une fraude en
    erreur 500 : la detection se fait sur la facture, le contexte n'est qu'un
    enrichissement.
    """
    model_registry, _ = registre
    bundle = model_registry.load_version("1")
    submission = validate_invoice(payload(assure_pseudonyme="assr_pseudonyme_fantome"))

    contexte = resolve_context(submission, bundle.referentiels)
    valeurs = build_features(submission, bundle.referentiels, **contexte)

    score = float(
        bundle.estimator.predict_proba(np.array([valeurs.as_row(bundle.feature_names)]))[0, 1]
    )
    assert 0.0 <= score <= 1.0


def test_contexte_absent_ne_produit_pas_de_faux_signal() -> None:
    """Le mode degrade doit produire des variables NEUTRES, pas des 0 piegees.

    Le piege : `taux_lignes_non_prescrites` vaut 1.0 quand l'ordonnance est
    introuvable (aucun code ne correspond). Or 1.0 est precisement ce que
    produit une facture qui facture des actes NON prescrits. Sans reference
    disponible, il faut donc rendre 0.0, pas 1.0, sinon une facture sainement
    prescriptive est notee comme une fraude de prescription.
    """
    submission: InvoiceSubmission = validate_invoice(payload())
    sans_contexte = build_features(submission, referentiels_de_test()).values
    avec_contexte = build_features(
        submission,
        referentiels_de_test(),
        ordonnance=Ordonnance(codes_prescrits=frozenset({"CONS-GEN"})),
        contrat=Contrat(date_effet=date(2020, 1, 1), formule="ESSENTIEL"),
    ).values

    # Sans ordonnance, la variable doit valoir 0.0 (neutre), pas 1.0.
    assert sans_contexte["taux_lignes_non_prescrites"] == 0.0
    assert avec_contexte["taux_lignes_non_prescrites"] == 0.0

    # Les variables qui ne dependent que de la facture sont identiques.
    for nom in ("montant_total", "nb_lignes", "ratio_quantite", "quantite_totale"):
        assert sans_contexte[nom] == avec_contexte[nom], nom


def referentiels_de_test() -> Referentiels:
    return Referentiels(
        actes={
            "CONS-GEN": Acte(
                categorie="CONSULTATION",
                tarif_reference=20_000.0,
                ordonnance_requise=True,
            )
        },
        grille={"PRE-001|CONS-GEN": 18_000.0},
        prestataires={"PRE-001": Prestataire()},
        garanties={"ESSENTIEL|CONSULTATION": GarantieCategorie(plafond_annuel_categorie=600_000.0)},
        contrats={"CTR-1": Contrat(formule="ESSENTIEL")},
    )


def test_rapport_shap_est_utilisable(registre: tuple[ModelRegistry, Path]) -> None:
    """Le rapport SHAP doit contenir des valeurs REELLES.

    Si `TreeExplainer` echouait, `router.py` renverrait un vecteur de zeros et
    le rapport dirait « aucune contribution dominante » : l'alerte partirait
    sans explication. Ce test verifie qu'on est dans l'autre cas.
    """
    import shap

    model_registry, _ = registre
    bundle = model_registry.load_version("1")
    submission = validate_invoice(payload())
    valeurs = build_features(submission, bundle.referentiels).values
    row = list(valeurs.values())

    shap_values = np.asarray(
        shap.TreeExplainer(bundle.estimator).shap_values(np.array([row]))
    ).ravel()

    assert len(shap_values) == len(NOMS_FEATURES)
    assert np.abs(shap_values).max() > 0.0, "SHAP plat : le rapport serait vide"

    contributions = shap_to_contributions(bundle.feature_names, shap_values, 0.0)
    assert len(contributions) == 5  # top_n par defaut
    assert all(c.feature in NOMS_FEATURES for c in contributions)

    rapport = build_shap_report(contributions, score=0.87, seuil=0.5)
    assert "87%" in rapport
    assert "50%" in rapport
    # Aucun nom technique de variable ne doit apparaitre dans une alerte.
    for nom in NOMS_FEATURES:
        assert nom not in rapport


# ---------------------------------------------------------------------------
# Seuil et bascule
# ---------------------------------------------------------------------------
def test_seuil_modifiable_a_chaud(registre: tuple[ModelRegistry, Path]) -> None:
    model_registry, _ = registre
    model_registry.load_version("1")
    assert model_registry.threshold == SEUIL_PAR_DEFAUT

    assert model_registry.set_threshold(0.75) == 0.75
    assert model_registry.threshold == 0.75


def test_seuil_hors_bornes_refuse(registre: tuple[ModelRegistry, Path]) -> None:
    model_registry, _ = registre
    for invalide in (-0.1, 1.1, 2.0):
        with pytest.raises(ValueError, match="entre 0 et 1"):
            model_registry.set_threshold(invalide)
    assert model_registry.threshold == SEUIL_PAR_DEFAUT


def test_bascule_et_retour_arriere(registre: tuple[ModelRegistry, Path]) -> None:
    """Exigence « Maintenable » du jury : deployer une version a cote de
    l'ancienne, basculer, revenir en arriere, SANS interruption."""
    model_registry, racine = registre
    model_registry.load_version("1")
    assert model_registry.active.version == "1"

    ecrire_artefact(racine / "2", entrainer_un_modele(seed=9), version="2")
    model_registry.load_version("2", as_candidate=True)
    assert model_registry.active.version == "1", "la candidate ne doit PAS devenir active"
    assert model_registry.candidate is not None
    assert model_registry.candidate.version == "2"

    assert model_registry.promote_candidate() == "2"
    assert model_registry.active.version == "2"
    assert model_registry.candidate is None

    assert model_registry.rollback("1") == "1"
    assert model_registry.active.version == "1"


def test_bascule_notifie_une_seule_fois(
    registre: tuple[ModelRegistry, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le webhook n8n part une fois par bascule, jamais sur une erreur."""
    model_registry, racine = registre
    model_registry.load_version("1")
    ecrire_artefact(racine / "2", entrainer_un_modele(seed=9), version="2")
    model_registry.load_version("2", as_candidate=True)

    appels: list[dict] = []
    monkeypatch.setattr(
        "predicare_inference_api.registry.notifier_bascule",
        lambda **kwargs: appels.append(kwargs) or True,
    )

    assert model_registry.promote_candidate(acteur="admin@predicare.local") == "2"
    assert appels == [
        {
            "version_avant": "1",
            "version_apres": "2",
            "acteur": "admin@predicare.local",
        }
    ]

    with pytest.raises(ModelNotReadyError, match="candidate"):
        model_registry.promote_candidate()
    assert len(appels) == 1, "une promotion refusee ne doit pas notifier"


def test_bascule_reussit_si_notification_echoue(
    registre: tuple[ModelRegistry, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un n8n injoignable ne defait pas une bascule deja appliquee."""
    model_registry, racine = registre
    model_registry.load_version("1")
    ecrire_artefact(racine / "2", entrainer_un_modele(seed=9), version="2")
    model_registry.load_version("2", as_candidate=True)
    monkeypatch.setattr(
        get_settings(),
        "n8n_bascule_webhook_url",
        "http://n8n:5678/webhook/bascule-modele",
    )

    def _post(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("n8n down")

    monkeypatch.setattr("predicare_inference_api.notifications.httpx.post", _post)

    assert model_registry.promote_candidate() == "2"
    assert model_registry.active.version == "2"


def test_etat_serialisable(registre: tuple[ModelRegistry, Path]) -> None:
    model_registry, _ = registre
    model_registry.load_version("1")
    etat = model_registry.state()

    # L'ecran d'administration lit ce dict et le serialise en JSON.
    json.dumps(etat, default=str)
    assert etat["active_version"] == "1"
    assert etat["metrics"]["rappel"] == 0.91
    assert "1" in etat["available_versions"]


def test_promotion_sans_candidate_leve(registre: tuple[ModelRegistry, Path]) -> None:
    model_registry, _ = registre
    model_registry.load_version("1")
    with pytest.raises(ModelNotReadyError, match="candidate"):
        model_registry.promote_candidate()


# ---------------------------------------------------------------------------
# Coherence des libelles d'explicabilite
# ---------------------------------------------------------------------------
def test_toute_variable_a_un_libelle_metier() -> None:
    """Une variable sans libelle s'afficherait avec son nom technique dans
    une alerte : `montant_vs_plafond_garantie` dans un message Slack n'est
    pas une explication, c'est un bug."""
    manquants = [nom for nom in NOMS_FEATURES if nom not in LIBELLES]
    assert not manquants, f"variables sans libelle : {manquants}"


def test_aucun_libelle_ne_contient_de_soulignement() -> None:
    assert all("_" not in libelle for libelle in LIBELLES.values())


def test_libelles_couvrent_exactement_les_variables() -> None:
    """`LIBELLES` ne doit avoir ni trou ni supplement.

    Un trou : une variable s'affiche avec son nom technique dans une alerte.
    Un supplement : un libelle devenu inutile apres un renommage, qui donne
    l'illusion d'une couverture complete.
    """
    assert set(LIBELLES) == set(NOMS_FEATURES)


def test_actif_sans_modele_leve(registre: tuple[ModelRegistry, Path]) -> None:
    """`/health` appelle `registry.state()`, et `/predire` appelle
    `registry.active`. Sans modele, le second doit lever une erreur dediee
    (503), pas une `AttributeError` sur `None`."""
    model_registry, _ = registre
    with pytest.raises(ModelNotReadyError, match="make train"):
        _ = model_registry.active
    assert model_registry.state()["active_version"] is None


def test_referentiels_partiels_toleres(registre: tuple[ModelRegistry, Path]) -> None:
    """Des referentiels incomplets doivent rester exploitables."""
    partiels = Referentiels(
        actes={"CONS-GEN": Acte(categorie="CONSULTATION", tarif_reference=20_000.0)},
        garanties={"ESSENTIEL|CONSULTATION": GarantieCategorie(plafond_annuel_categorie=600_000.0)},
        contrats={"CTR-1": Contrat(date_effet=None, formule="ESSENTIEL")},
    )
    submission = validate_invoice(payload())
    valeurs = build_features(submission, partiels).values
    assert set(valeurs) == set(NOMS_FEATURES)
    assert valeurs["ratio_prix_grille_max"] == 1.0  # pas de grille : neutre
    assert valeurs["montant_vs_plafond_garantie"] > 0.0  # plafond de repli utilise
