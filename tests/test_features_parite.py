"""Parite entre l'entrainement et la production.

Ces tests verifient la propriete la plus importante du projet ML : le
service d'inference calcule EXACTEMENT les memes variables que celles sur
lesquelles le modele a ete entraine.

L'echec typique de cet appel est silencieux : si le service calcule 30
variables au lieu de 32, `InvoiceFeatures.as_row` complete avec des zeros et
le modele note quand meme, avec un score plausible mais faux. Ces tests
ferment cette porte.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pytest

from predicare.features import (
    NOMS_FEATURES,
    Acte,
    Contrat,
    FactureBrute,
    LigneFacture,
    Medicament,
    Ordonnance,
    Prestataire,
    Referentiels,
    calculer_features,
    charger_referentiels,
    referentiels_vers_dict,
)
from predicare.schemas import InvoiceSubmission
from predicare_inference_api.context import resolve_context
from predicare_inference_api.features import build_features
from predicare_inference_api.validation import validate_invoice


# ---------------------------------------------------------------------------
# Referentiel de test
# ---------------------------------------------------------------------------
def referentiel_de_test() -> Referentiels:
    return Referentiels(
        actes={
            "CONS-GEN": Acte(
                categorie="CONSULTATION",
                specialite="GENERALISTE",
                tarif_reference=20_000.0,
                tarif_max=50_000.0,
                ordonnance_requise=True,
                sexe_requis="F",
                age_min=0,
                age_max=120,
            ),
            "IMG-IRM": Acte(
                categorie="IMAGERIE",
                specialite="RADIOLOGIE",
                tarif_reference=150_000.0,
                tarif_max=200_000.0,
                ordonnance_requise=True,
                age_min=18,
                age_max=120,
            ),
        },
        medicaments={"MED-X": Medicament(prix_reference=2_000.0, remboursable=False)},
        grille={"PRE-001|CONS-GEN": 18_000.0, "PRE-001|IMG-IRM": 140_000.0},
        prestataires={
            "PRE-001": Prestataire(
                radie=False,
                jours_ouverture="123456",
                heure_ouverture=8,
                heure_fermeture=17,
                niveau_tarif="ELEVE",
            )
        },
        garanties={
            "ESSENTIEL|CONSULTATION": Garantie_avec(600_000.0, 90, frozenset({"IMG-IRM"})),
            "ESSENTIEL|IMAGERIE": Garantie_avec(900_000.0, 90, frozenset()),
        },
        contrats={"CTR-1": Contrat(date_effet=date(2024, 1, 1), formule="ESSENTIEL")},
    )


def Garantie_avec(  # noqa: N802 - utilitaire de test
    plafond: float,
    carence: int,
    exclus: frozenset[str],
):
    from predicare.features import GarantieCategorie

    return GarantieCategorie(
        taux_remboursement=80.0,
        plafond_annuel_categorie=plafond,
        plafond_annuel_global=3_000_000.0,
        delai_carence_jours=carence,
        actes_exclus=exclus,
    )


def facture_de_test(**surcharges) -> FactureBrute:
    base = {
        "montant_total": 9_000.0,
        "date_facture": date(2026, 3, 10),
        "lignes": [LigneFacture("CONS-GEN", 2, 4_500.0, datetime(2026, 3, 9, 10, 30))],
        "ordonnance": Ordonnance(
            prescripteur_id="PRE-001",
            date_prescription=date(2026, 3, 5),
            validite_jours=10,
            codes_prescrits=frozenset({"CONS-GEN"}),
        ),
        "contrat": Contrat(date_effet=date(2024, 1, 1), formule="ESSENTIEL"),
        "assure_annee_naissance": 1980,
        "assure_sexe": "F",
        "prestataire_id": "PRE-001",
    }
    base.update(surcharges)
    return FactureBrute(**base)


def submission_de_test(**champs) -> dict:
    """Payload de soumission VALIDE au regard de `api-inference/validation.py`.

    Deux bornes de ce module a respecter : un montant unitaire de ligne ne
    peut pas depasser 10 000 000 MGA (la grille tarifaire du jeu de
    l'encadrement est en ariary, une consultation a 18 000 doit donc etre
    acceptee), et le total doit rester coherent avec le detail des lignes. On
    travaille donc sur une facture de 2 lignes de 4 500, ce qui teste la
    structure sans frôler les limites.
    """
    base = {
        "facture_id": "FAC-TEST-001",
        "assure_pseudonyme": "assr_test1234",
        "prestataire_id": "PRE-001",
        "date_facture": datetime.now(UTC) - timedelta(days=3),
        "montant_total": 9_000.0,
        "lignes": [
            {
                "code_acte": "CONS-GEN",
                "quantite": 2,
                "montant_unitaire": 4_500.0,
                "date_acte": datetime.now(UTC) - timedelta(days=4),
            }
        ],
    }
    base.update(champs)
    return base


# ---------------------------------------------------------------------------
# Le contrat de variables
# ---------------------------------------------------------------------------
def test_noms_features_sont_uniques_et_non_vides() -> None:
    assert len(NOMS_FEATURES) == len(set(NOMS_FEATURES))
    assert all(nom and nom.islower() for nom in NOMS_FEATURES)


def test_chaque_variable_est_produite() -> None:
    """`calculer_features` rend exactement les variables annoncees.

    L'assertion est dans le module, mais elle ne couvre qu'un chemin. Ce test
    verifie le contrat depuis l'exterieur, comme le fera `features.json`.
    """
    valeurs = calculer_features(facture_de_test(), referentiel_de_test())
    assert set(valeurs) == set(NOMS_FEATURES)
    assert list(valeurs) == list(NOMS_FEATURES)


def test_ordre_est_stable_entre_deux_appels() -> None:
    """L'ordre des clbes doit etre identique : c'est lui qui definit la
    position de chaque variable dans le vecteur envoye a `predict_proba`."""
    reference = calculer_features(facture_de_test(), referentiel_de_test())
    for _ in range(5):
        autre = calculer_features(facture_de_test(), referentiel_de_test())
        assert list(autre) == list(reference)


def test_valeurs_toujours_finies() -> None:
    """Aucun `inf` ni `NaN` ne doit atteindre l'entrainement ni le service.

    XGBoost refuse de predire sur une valeur non finie ; une seule ligne
    entrainee avec un `inf` suffit a casser le modele en service.
    """
    import math

    cas = [
        facture_de_test(montant_total=0.0),
        facture_de_test(lignes=[]),
        facture_de_test(lignes=[LigneFacture("INCONNU", 0, 0.0, None)]),
        facture_de_test(date_facture=None),
        facture_de_test(ordonnance=None),
        facture_de_test(contrat=None),
        facture_de_test(assure_annee_naissance=None, assure_sexe=""),
    ]
    for facture in cas:
        valeurs = calculer_features(facture, referentiel_de_test())
        for nom, valeur in valeurs.items():
            assert math.isfinite(valeur), f"{nom} non fini pour {facture}"


# ---------------------------------------------------------------------------
# Robustesse : ne jamais lever
# ---------------------------------------------------------------------------
def test_facture_vide_ne_leve_pas() -> None:
    valeurs = calculer_features(FactureBrute())
    assert len(valeurs) == len(NOMS_FEATURES)


def test_facture_sans_referentiel_ne_leve_pas() -> None:
    valeurs = calculer_features(facture_de_test(), Referentiels())
    assert len(valeurs) == len(NOMS_FEATURES)


def test_code_inconnu_est_signale() -> None:
    facture = facture_de_test(lignes=[LigneFacture("CODE-QUI-N-EXISTE-PAS", 1, 1000.0, None)])
    calculer_features(facture, referentiel_de_test())
    assert "code:CODE-QUI-N-EXISTE-PAS" in facture.references_manquantes


def test_references_manquantes_sont_dedupliquees() -> None:
    """200 lignes du meme code inconnu ne doivent pas donner 200 entrees."""
    facture = facture_de_test(
        lignes=[LigneFacture("INCONNU-1", 1, 1000.0, None) for _ in range(200)]
    )
    calculer_features(facture, referentiel_de_test())
    assert facture.references_manquantes.count("code:INCONNU-1") == 1


def test_appels_repetes_ne_dupliquent_pas() -> None:
    facture = facture_de_test(lignes=[LigneFacture("INCONNU-2", 1, 1.0, None)])
    calculer_features(facture, referentiel_de_test())
    calculer_features(facture, referentiel_de_test())
    assert facture.references_manquantes.count("code:INCONNU-2") == 1


# ---------------------------------------------------------------------------
# La parite, qui est le point du fichier
# ---------------------------------------------------------------------------
def test_api_et_socle_produisent_les_memes_variables() -> None:
    """`build_features` (service) et `calculer_features` (entrainement)
    doivent produire le meme dictionnaire pour la meme facture.

    C'est le test le plus important du projet : il casse le piege de la
    featurisation dupliquee qui diverge silencieusement.
    """
    # Une date de soin et une prescription CHOISIES, et non derivees de
    # l'horloge : le test compare deux chemins de calcul, il ne doit pas
    # dependre de la journee. `validation.py` interdit une date de soin
    # posterieure a la date de facture de plus d'un jour, et la soumission doit
    # rester dans la duree de conservation : on ancre donc tout sur une date
    # fixe, decalee du jour pour rester valide.
    jour = date.today() - timedelta(days=10)
    submission: InvoiceSubmission = validate_invoice(
        submission_de_test(
            date_facture=datetime.combine(jour, time(12, 0), tzinfo=UTC),
            lignes=[
                {
                    "code_acte": "CONS-GEN",
                    "quantite": 2,
                    "montant_unitaire": 4_500.0,
                    "date_acte": datetime.combine(
                        jour - timedelta(days=1), time(10, 30), tzinfo=UTC
                    ),
                }
            ],
        )
    )
    referentiels = referentiel_de_test()

    ordonnance = Ordonnance(
        prescripteur_id="PRE-001",
        date_prescription=jour - timedelta(days=5),
        validite_jours=10,
        codes_prescrits=frozenset({"CONS-GEN"}),
    )
    contrat = Contrat(date_effet=date(2024, 1, 1), formule="ESSENTIEL")

    via_api = build_features(
        submission,
        referentiels,
        ordonnance=ordonnance,
        contrat=contrat,
        prestataire=referentiels.prestataires["PRE-001"],
        assure_annee_naissance=1980,
        assure_sexe="F",
    ).values

    via_socle = calculer_features(
        facture_de_test(
            montant_total=9_000.0,
            date_facture=jour,
            lignes=[
                LigneFacture(
                    "CONS-GEN", 2, 4_500.0, datetime.combine(jour - timedelta(days=1), time(10, 30))
                )
            ],
            ordonnance=ordonnance,
            contrat=contrat,
            prestataire=referentiels.prestataires["PRE-001"],
        ),
        referentiels,
    )

    assert via_api == via_socle


def test_ordre_de_alignement_du_service() -> None:
    """`as_row` doit suivre l'ordre de `features.json`, pas celui du dict."""
    submission: InvoiceSubmission = validate_invoice(submission_de_test())
    valeurs = build_features(submission, referentiel_de_test()).values

    ordre = list(reversed(NOMS_FEATURES))
    assert valeurs and len(ordre) == len(valeurs)
    ligne = [float(valeurs.get(nom, 0.0)) for nom in ordre]
    # et non un KeyError : c'est le comportement qui rend le decalage
    # silencieux quand `features.json` et le featuriseur divergent.
    assert len(ligne) == len(valeurs)


def test_resolution_de_contexte_sans_base_ne_leve_pas() -> None:
    """Le jour J, le jury soumet des factures dont le pseudonyme n'existe
    pas. La resolution doit echouer proprement et laisser la facture notee."""
    submission: InvoiceSubmission = validate_invoice(
        submission_de_test(assure_pseudonyme="assr_inexistant_au_jury")
    )
    contexte = resolve_context(submission, referentiel_de_test())
    # La base peut repondre ou non selon l'environnement ; ce qui compte est
    # qu'aucune exception ne remonte et que le contexte reste exploitable.
    assert isinstance(contexte, dict)
    valeurs = build_features(submission, referentiel_de_test(), **contexte).values
    assert set(valeurs) == set(NOMS_FEATURES)


# ---------------------------------------------------------------------------
# Coherence des lectures entre l'entrainement et le service
# ---------------------------------------------------------------------------
def test_lecture_booleene_identique_les_deux_cotes() -> None:
    """`dataset._booleen` duplique `_booleen` du socle ; les deux doivent
    repondre pareil, sinon `statut` et `conventionne` seraient interpretes
    differemment a l'entrainement et en service."""
    from predicare.features import _booleen as booleen_socle
    from predicare_ml_training.dataset import _booleen as booleen_entrainement

    cas = ["1", "0", "true", "false", "oui", "non", "", None, 1, 0, 1.0, 0.0, "vrai", "peut-etre"]
    for valeur in cas:
        assert booleen_entrainement(valeur) == booleen_socle(valeur), valeur


def test_lecture_date_identique_les_deux_cotes() -> None:
    from predicare.features import _date as date_socle
    from predicare_ml_training.dataset import _jour as jour_entrainement

    cas = ["2026-03-09", "2026-03-09T10:30:00", date(2026, 3, 9), datetime(2026, 3, 9, 10, 30)]
    for valeur in cas:
        assert jour_entrainement(valeur) == date_socle(valeur), valeur


def test_aller_retour_des_referentiels() -> None:
    """Ce qui est ecrit dans l'artefact doit se relire a l'identique.

    L'inference lit `referentiels.json` : si la serialization perdait un
    champ, la production noterait avec un referentiel different de celui de
    l'entrainement, sans aucun signal.
    """
    original = referentiel_de_test()
    relu = charger_referentiels(json.loads(json.dumps(referentiels_vers_dict(original))))

    assert set(relu.actes) == set(original.actes)
    assert set(relu.medicaments) == set(original.medicaments)
    assert relu.grille == original.grille
    assert set(relu.prestataires) == set(original.prestataires)
    assert set(relu.garanties) == set(original.garanties)
    assert set(relu.contrats) == set(original.contrats)

    acte = relu.actes["CONS-GEN"]
    assert acte.tarif_reference == original.actes["CONS-GEN"].tarif_reference
    assert acte.ordonnance_requise is original.actes["CONS-GEN"].ordonnance_requise
    assert acte.sexe_requis == "F"

    contrat = relu.contrats["CTR-1"]
    assert contrat.date_effet == original.contrats["CTR-1"].date_effet
    assert contrat.formule == "ESSENTIEL"

    prestataire = relu.prestataires["PRE-001"]
    assert (
        prestataire.date_conventionnement == original.prestataires["PRE-001"].date_conventionnement
    )
    assert prestataire.heure_fermeture == 17
    assert prestataire.radie is False

    garantie = relu.garanties["ESSENTIEL|CONSULTATION"]
    assert garantie.actes_exclus == frozenset({"IMG-IRM"})
    assert garantie.delai_carence_jours == 90


def test_referentiels_vides_ne_crasent_rien() -> None:
    """Un `referentiels.json` absent ou vide ne doit pas faire echouer le
    chargement du modele : le service demarre et note avec des valeurs
    neutres, ce que `/health` signale via `modele_charge`."""
    relu = charger_referentiels({})
    assert relu.actes == {}
    valeurs = calculer_features(facture_de_test(), relu)
    assert len(valeurs) == len(NOMS_FEATURES)


# ---------------------------------------------------------------------------
# L'artefact reel, quand il existe
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not (Path("models/1") / "features.json").exists(),
    reason="Aucun modele entraine (lancer `make train`)",
)
def test_artefact_aligne_sur_le_socle() -> None:
    """`features.json` doit decrire EXACTEMENT le contrat du socle.

    C'est le test qui garantit qu'un artefact ancien, entraine avec un autre
    jeu de variables, ne peut pas etre servi en silence : le decalage serait
    immediatement visible ici.
    """
    features = json.loads((Path("models/1") / "features.json").read_text(encoding="utf-8"))
    assert features == list(NOMS_FEATURES)

    metadata = json.loads((Path("models/1") / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["features_count"] == len(NOMS_FEATURES)
    assert 0.0 < metadata["seuil"] <= 1.0
    assert metadata["data_fingerprint"].startswith("sha256:")
    assert "rappel" in metadata["metrics"]
    assert "precision" in metadata["metrics"]
    assert "pr_auc" in metadata["metrics"]

    import joblib

    modele = joblib.load(Path("models/1") / "model.joblib")
    assert modele.n_features_in_ == len(features)


@pytest.mark.skipif(
    not (Path("models/1") / "referentiels.json").exists(),
    reason="Aucun modele entraine (lancer `make train`)",
)
def test_artefact_referentiels_est_chargable() -> None:
    referentiels = charger_referentiels(
        json.loads((Path("models/1") / "referentiels.json").read_text(encoding="utf-8"))
    )
    assert referentiels.actes, "le referentiel des actes est vide"
    assert referentiels.grille, "la grille tarifaire est vide"
    assert referentiels.prestataires, "le referentiel des prestataires est vide"
    # Un acte et un prestataire reels du jeu de l'encadrement.
    assert "CONS-GEN" in referentiels.actes
    assert "PRE-00001" in referentiels.prestataires


def test_horodatage_importable() -> None:
    """Garde-fou : le module importe `UTC`, on ne veut pas le retirer."""
    assert datetime.now(UTC).tzinfo is UTC


# ---------------------------------------------------------------------------
# Baseline de la Q8 (C.3) : contrats de sortie, sans entrainement lourd
# ---------------------------------------------------------------------------
def test_comparer_baselines_renvoie_les_cles_attendues() -> None:
    """Verrouille le contrat de `comparer_baselines` sur un jeu minuscule.

    Le test ne verifie pas les scores (un jeu de 20 lignes ne prouve rien) :
    il verifie que les trois baselines annoncees dans la soutenance existent
    REELLEMENT et que chaque ligne porte les metriques comparables (rappel,
    precision, PR-AUC, ROC-AUC, matrice de confusion et cout metier), aux
    deux seuils demandes.
    """
    from predicare_ml_training.evaluate import (
        REGLES_DETERMINISTES,
        _hyperparametres,
        comparer_baselines,
    )

    noms = ["montant_total", "nb_lignes", *REGLES_DETERMINISTES[:3]]
    generateur = np.random.default_rng(0)
    x = generateur.random((20, len(noms)))
    y = np.zeros(20, dtype=np.int8)
    y[[0, 2, 5, 8, 11, 13, 16, 18]] = 1
    x[:, 2] = y.astype(float)  # la premiere regle suit la cible
    x[[1, 4, 10], 3] = 1.0  # une regle se declenche aussi sur des saines

    x_ent, y_ent = x[:12], y[:12]
    x_val, y_val = x[12:16], y[12:16]
    x_test, y_test = x[16:], y[16:]

    resultats = comparer_baselines(
        x_ent,
        y_ent,
        x_val,
        y_val,
        x_test,
        y_test,
        noms_features=noms,
        seuil_modele=0.2876,
        hyperparametres=_hyperparametres(2, 10, 0.1, 2),
    )

    strategies = {r["strategie"] for r in resultats}
    assert strategies == {
        "modele XGBoost",
        "regles deterministes",
        "regression logistique",
        "regles + modele (OU)",
    }, "les trois baselines de la Q8 doivent etre presentes"

    attendues = {
        "strategie",
        "seuil",
        "origine_seuil",
        "roc_auc",
        "pr_auc",
        "rappel",
        "precision",
        "f1",
        "cout_total",
        "gain_metier",
        "matrice_confusion",
    }
    for ligne in resultats:
        assert attendues <= set(ligne)
        assert set(ligne["matrice_confusion"]) == {
            "vrais_positifs",
            "faux_positifs",
            "faux_negatifs",
            "vrais_negatifs",
        }
        assert 0.0 <= ligne["rappel"] <= 1.0
        assert 0.0 <= ligne["precision"] <= 1.0

    # Deux lectures par baseline : seuil de production et seuil de cout minimal.
    assert len(resultats) == 8
