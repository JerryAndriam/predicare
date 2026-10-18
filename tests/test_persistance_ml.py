"""Persistance des predictions, des rapports SHAP et du registre de modeles.

Deux familles de tests, volontairement separees :

- les tests SANS BASE verifient le contrat : une panne d'ecriture ne fait
  jamais echouer une inference, et le seuil effectif suit l'ordre de priorite
  annonce ;
- les tests AVEC BASE font un aller-retour reel sur PostgreSQL et sautent
  proprement quand la plateforme n'est pas demarree (meme regle que
  `tests/e2e/README.md`). La CI n'a pas de base : ils y sautent, et c'est
  voulu -- ils servent a verifier le SQL, pas a le simuler.
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import pytest
import xgboost as xgb
from sqlalchemy import text

from predicare import db
from predicare.config import Settings, get_settings
from predicare.errors import ModelNotReadyError
from predicare.persistance_ml import (
    SEUIL_PAR_DEFAUT,
    activer_version,
    amorcer_seuil_effectif,
    declarer_version,
    lire_seuil_effectif,
    persister_prediction,
)
from predicare.schemas import ShapContribution
from predicare_inference_api.registry import ModelRegistry


def contribution(rang: int = 1) -> ShapContribution:
    return ShapContribution(
        feature=f"variable_{rang}",
        value=float(rang),
        shap_value=0.5 / rang,
        base_value=-2.0,
        direction="pousse_vers_fraude",
        human_readable=f"explication {rang}",
    )


def modele_de_test() -> xgb.XGBClassifier:
    """Un vrai booster, minuscule : `joblib.load` doit rendre un objet reel."""
    return xgb.XGBClassifier(n_estimators=5, max_depth=2, random_state=0)


def ecrire_artefact(dossier: Path, *, seuil: float | None) -> None:
    dossier.mkdir(parents=True, exist_ok=True)
    joblib.dump(modele_de_test(), dossier / "model.joblib")
    (dossier / "features.json").write_text(json.dumps(["a", "b"]), encoding="utf-8")
    metadata: dict[str, object] = {"metrics": {"rappel": 0.87}, "data_fingerprint": "sha256:x"}
    if seuil is not None:
        metadata["seuil"] = seuil
    (dossier / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")


# ---------------------------------------------------------------------------
# Contrat : aucune panne d'ecriture ne remonte jusqu'a l'appelant
# ---------------------------------------------------------------------------
def _base_indisponible(monkeypatch: pytest.MonkeyPatch) -> None:
    import predicare.persistance_ml as module

    def _explose() -> None:
        raise RuntimeError("base injoignable")

    monkeypatch.setattr(module, "session_scope", _explose)


def test_prediction_non_stockee_ne_leve_pas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Une base en panne prive d'alerte stockee, jamais de score rendu."""
    _base_indisponible(monkeypatch)
    resultat = persister_prediction(
        reference="FAC-00000001",
        model_version="1",
        score=0.9,
        seuil=0.2876,
        is_fraud=True,
        contributions=[contribution()],
    )
    assert resultat is None


def test_version_non_declaree_ne_leve_pas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un entrainement doit aboutir meme si le registre est injoignable."""
    _base_indisponible(monkeypatch)
    assert (
        declarer_version(
            version="9", artefact_path="models/9", empreinte_donnees="sha256:x", metriques={}
        )
        is False
    )


def test_bascule_sans_base_ne_leve_pas(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_indisponible(monkeypatch)
    assert activer_version("9") is False


def test_seuil_illisible_ne_leve_pas(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_indisponible(monkeypatch)
    assert lire_seuil_effectif() is None
    assert amorcer_seuil_effectif(0.5) is False


# ---------------------------------------------------------------------------
# Seuil : une seule verite, et le modele arrive avec la sienne
# ---------------------------------------------------------------------------
def test_seuil_vide_dans_l_environnement_est_accepte() -> None:
    """`FRAUD_ALERT_THRESHOLD=` (vide) signifie « le seuil du modele »."""
    assert Settings(fraud_alert_threshold="").fraud_alert_threshold is None


def test_seuil_par_defaut_quand_rien_n_est_configure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sans base et sans configuration, le seuil ne peut pas valoir `None`."""
    from predicare import dependencies

    monkeypatch.setattr(dependencies, "lire_seuil_effectif", lambda: None)
    monkeypatch.setattr(get_settings(), "fraud_alert_threshold", None)
    assert dependencies.get_threshold() == SEUIL_PAR_DEFAUT


def test_seuil_configure_prime_sur_le_defaut(monkeypatch: pytest.MonkeyPatch) -> None:
    from predicare import dependencies

    monkeypatch.setattr(dependencies, "lire_seuil_effectif", lambda: None)
    monkeypatch.setattr(get_settings(), "fraud_alert_threshold", 0.42)
    assert dependencies.get_threshold() == 0.42


def test_le_modele_impose_son_seuil(tmp_path: Path) -> None:
    """Le seuil arbitre en Phase 2.5 est celui qui alerte, pas un 0.8 herite."""
    ecrire_artefact(tmp_path / "1", seuil=0.2876)
    registre = ModelRegistry(model_dir=tmp_path)
    registre.load_version("1")
    assert registre.threshold == pytest.approx(0.2876)
    assert registre.state()["threshold"] == pytest.approx(0.2876)


def test_le_seuil_impose_prime_sur_celui_du_modele(tmp_path: Path) -> None:
    ecrire_artefact(tmp_path / "1", seuil=0.2876)
    registre = ModelRegistry(model_dir=tmp_path, threshold=0.6)
    registre.load_version("1")
    assert registre.threshold == pytest.approx(0.6)
    assert registre.seuil_impose == pytest.approx(0.6)


def test_le_seuil_choisi_a_chaud_prime_sur_tout(tmp_path: Path) -> None:
    """L'ecran d'administration doit gagner, sans redemarrage."""
    ecrire_artefact(tmp_path / "1", seuil=0.2876)
    registre = ModelRegistry(model_dir=tmp_path, threshold=0.6)
    registre.load_version("1")
    registre.set_threshold(0.15)
    assert registre.threshold == pytest.approx(0.15)


def test_artefact_sans_seuil_retombe_sur_le_defaut(tmp_path: Path) -> None:
    ecrire_artefact(tmp_path / "1", seuil=None)
    registre = ModelRegistry(model_dir=tmp_path)
    registre.load_version("1")
    assert registre.threshold == pytest.approx(SEUIL_PAR_DEFAUT)


def test_version_inconnue_leve_toujours(tmp_path: Path) -> None:
    """Le seuil est tolerant, le chargement du modele ne l'est pas."""
    registre = ModelRegistry(model_dir=tmp_path)
    with pytest.raises(ModelNotReadyError):
        registre.load_version("42")


# ---------------------------------------------------------------------------
# Aller-retour reel sur PostgreSQL (saute sans plateforme demarree)
# ---------------------------------------------------------------------------
@pytest.fixture
def base_de_donnees() -> None:
    """Saute le test quand la base n'est pas joignable ou n'est pas chargee."""
    try:
        joignable = db.check_database()
    except Exception:
        joignable = False
    if not joignable:
        pytest.skip("Base injoignable : ces tests verifient le SQL, pas un simulacre.")

    with db.session_scope() as session:
        reference = session.execute(
            text("SELECT reference FROM core.facture ORDER BY id LIMIT 1")
        ).scalar()
    if reference is None:
        pytest.skip("Jeu de donnees absent : lancer `make up-light` (service `seed`).")


def test_aller_retour_prediction_et_shap(base_de_donnees: None) -> None:
    from predicare.persistance_ml import stocker_prediction

    with db.session_scope() as session:
        reference = session.execute(
            text("SELECT reference FROM core.facture ORDER BY id LIMIT 1")
        ).scalar()

    prediction_id = None
    try:
        with db.session_scope() as session:
            prediction_id = stocker_prediction(
                session,
                reference=reference,
                model_version="test",
                score=0.91,
                seuil=0.2876,
                is_fraud=True,
                contributions=[contribution(1), contribution(2)],
            )
            assert prediction_id is not None
            lignes = (
                session.execute(
                    text(
                        """
                        SELECT rang, feature, libelle FROM ml.shap_explication
                        WHERE prediction_id = :id ORDER BY rang
                        """
                    ),
                    {"id": prediction_id},
                )
                .mappings()
                .all()
            )
        assert [ligne["rang"] for ligne in lignes] == [1, 2]
        assert lignes[0]["libelle"] == "explication 1"

        # Re-notation : la meme facture ne doit PAS produire une deuxieme
        # alerte dans la file du gestionnaire.
        with db.session_scope() as session:
            rejoue = stocker_prediction(
                session,
                reference=reference,
                model_version="test",
                score=0.5,
                seuil=0.2876,
                is_fraud=True,
                contributions=[contribution(1)],
            )
        assert rejoue == prediction_id

        with db.session_scope() as session:
            total_predictions = session.execute(
                text(
                    """
                    SELECT count(*) FROM ml.prediction
                    WHERE id = :id
                    """
                ),
                {"id": prediction_id},
            ).scalar()
            total_shap = session.execute(
                text("SELECT count(*) FROM ml.shap_explication WHERE prediction_id = :id"),
                {"id": prediction_id},
            ).scalar()
        assert total_predictions == 1
        assert total_shap == 1, "les explications de l'ancien score doivent disparaitre"
    finally:
        if prediction_id is not None:
            with db.session_scope() as session:
                session.execute(
                    text("DELETE FROM ml.shap_explication WHERE prediction_id = :id"),
                    {"id": prediction_id},
                )
                session.execute(
                    text("DELETE FROM ml.prediction WHERE id = :id"), {"id": prediction_id}
                )


def test_facture_inconnue_est_ignoree(base_de_donnees: None) -> None:
    from predicare.persistance_ml import stocker_prediction

    with db.session_scope() as session:
        resultat = stocker_prediction(
            session,
            reference="FAC-INEXISTANTE-0000",
            model_version="test",
            score=0.9,
            seuil=0.2876,
            is_fraud=True,
            contributions=[contribution()],
        )
    assert resultat is None


def test_registre_de_versions_suit_la_bascule(base_de_donnees: None) -> None:
    from predicare.persistance_ml import enregistrer_version, marquer_version_active

    version = "test-999"
    # Le registre est une donnee d'exploitation, pas un brouillon de test :
    # la promotion de la version de test archiverait la version reellement en
    # service. On photographie l'etat et on le remet en place.
    with db.session_scope() as session:
        avant = (
            session.execute(text("SELECT version, statut, promu_le FROM ml.modele_version"))
            .mappings()
            .all()
        )
    try:
        with db.session_scope() as session:
            enregistrer_version(
                session,
                version=version,
                artefact_path="models/test-999",
                empreinte_donnees="sha256:test",
                metriques={"rappel": 0.9},
            )
        with db.session_scope() as session:
            statut = session.execute(
                text("SELECT statut FROM ml.modele_version WHERE version = :v"), {"v": version}
            ).scalar()
            metriques = session.execute(
                text("SELECT metriques FROM ml.modele_version WHERE version = :v"),
                {"v": version},
            ).scalar()
        assert statut == "candidat"
        assert metriques["rappel"] == pytest.approx(0.9)

        with db.session_scope() as session:
            marquer_version_active(session, version)
        with db.session_scope() as session:
            promue = session.execute(
                text("SELECT statut, promu_le FROM ml.modele_version WHERE version = :v"),
                {"v": version},
            ).one()
        assert promue.statut == "promu"
        assert promue.promu_le is not None
    finally:
        with db.session_scope() as session:
            session.execute(
                text("DELETE FROM ml.modele_version WHERE version = :v"), {"v": version}
            )
            for ligne in avant:
                session.execute(
                    text(
                        """
                        UPDATE ml.modele_version SET statut = :s, promu_le = :p
                        WHERE version = :v
                        """
                    ),
                    {"s": ligne["statut"], "p": ligne["promu_le"], "v": ligne["version"]},
                )


def test_amorcage_du_seuil_ne_rejoue_pas(base_de_donnees: None) -> None:
    """Amorcer deux fois n'ecrase pas un seuil deja enregistre."""
    from predicare.persistance_ml import CLE_SEUIL_ALERTE, amorcer_seuil_alerte, lire_seuil_alerte

    # La plateforme en service a deja amorce ce parametre : le test doit
    # partir de l'etat « absent », puis remettre la valeur d'origine.
    with db.session_scope() as session:
        ancien = lire_seuil_alerte(session)
        session.execute(
            text("DELETE FROM audit.parametre WHERE cle = :cle"), {"cle": CLE_SEUIL_ALERTE}
        )

    try:
        with db.session_scope() as session:
            assert amorcer_seuil_alerte(session, 0.1111) is True
            assert lire_seuil_alerte(session) == pytest.approx(0.1111)
        with db.session_scope() as session:
            assert amorcer_seuil_alerte(session, 0.9999) is False
            assert lire_seuil_alerte(session) == pytest.approx(0.1111)
    finally:
        with db.session_scope() as session:
            session.execute(
                text("DELETE FROM audit.parametre WHERE cle = :cle"), {"cle": CLE_SEUIL_ALERTE}
            )
            if ancien is not None:
                session.execute(
                    text(
                        """
                        INSERT INTO audit.parametre (cle, valeur, modifie_par)
                        VALUES (:cle, :v, 'test')
                        """
                    ),
                    {"v": str(ancien), "cle": CLE_SEUIL_ALERTE},
                )
