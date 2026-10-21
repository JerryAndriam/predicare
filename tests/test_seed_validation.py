"""Porte de validation du chargement initial.

Ces tests ne touchent ni PostgreSQL ni Docker : ils eclairent des fonctions
pures, comme le reste de la suite.

Pourquoi la validation merite des tests alors que le jeu fourni est propre

Le jeu de l'encadrement ne presente aucun defaut : zero doublon, zero cle
etrangere orpheline, zero inversion de dates. Une suite qui ne testerait que
"le jeu passe" ne prouverait rien -- elle constaterait un fait deja connu.

Ce qui compte ici, c'est l'inverse : que la porte REFUSE un jeu douteux. C'est
la seule situation reellement dangerousse, parce que charger la moitie d'un
jeu incoherent laisse la base dans un etat plus difficile a diagnostiquer
qu'une base vide : les tables paraissent peuplees.

D'ou les trois proprietes verifiees :

1. une anomalie reelle est detectee et nommee ;
2. un jeu propre passe sans anomalie, y compris ses valeurs manquantes, qui
   sont information et pas salete ;
3. la validation s'arrete a la premiere famille d'anomalies, pour ne pas
   noyer l'utilisateur sous un bruit de hundreds de messages en cascade.
"""

from __future__ import annotations

import pandas as pd
import pytest

from predicare_seed.validation import (
    COLONNES_ATTENDUES,
    controler_dates,
    controler_integrite,
    controler_labels,
    controler_numeriques,
    controler_schema,
    controler_unicite,
    valider,
)


def _rapport():
    """Rapport vierge, pour appeler un controle isolement."""
    from predicare_seed.validation import Rapport

    return Rapport()


def _jeu_valide() -> dict[str, pd.DataFrame]:
    """Petit jeu complet et coherent, 2 lignes par table."""
    return {
        "referentiel_actes.csv": pd.DataFrame(
            {"code_acte": ["ACTE-1", "ACTE-2"], "libelle": ["A", "B"], "tarif_reference": [10, 20]}
        ),
        "referentiel_medicaments.csv": pd.DataFrame(
            {"code_medicament": ["MED-1"], "libelle": ["M"], "prix_reference": [5]}
        ),
        "prestataires.csv": pd.DataFrame(
            {
                "prestataire_id": ["PRE-1", "PRE-2"],
                "nom": ["P1", "P2"],
                "type_prestataire": ["PHARMACIE", "CLINIQUE"],
            }
        ),
        "contrats.csv": pd.DataFrame(
            {
                "contrat_id": ["CTR-1", "CTR-2"],
                "formule": ["ESSENTIEL", "CONFORT"],
                "date_effet": ["2024-01-01", "2024-01-01"],
            }
        ),
        "assures.csv": pd.DataFrame(
            {
                "assure_id": ["ASS-1", "ASS-2"],
                "contrat_id": ["CTR-1", "CTR-2"],
                "sexe": ["F", "M"],
                "date_adhesion": ["2024-01-01", "2024-01-01"],
                "date_radiation": [None, None],
            }
        ),
        "identites_pii.csv": pd.DataFrame(
            {
                "assure_id": ["ASS-1", "ASS-2"],
                "nom": ["N1", "N2"],
                "date_naissance": ["1980-01-01", "1990-01-01"],
            }
        ),
        "ordonnances.csv": pd.DataFrame(
            {
                "ordonnance_id": ["ORD-1"],
                "assure_id": ["ASS-1"],
                "date_prescription": ["2024-01-01"],
            }
        ),
        "ordonnance_lignes.csv": pd.DataFrame(
            {"ordonnance_id": ["ORD-1"], "num_ligne": [1], "code": ["ACTE-1"]}
        ),
        "factures.csv": pd.DataFrame(
            {
                "facture_id": ["FAC-1", "FAC-2"],
                "prestataire_id": ["PRE-1", "PRE-2"],
                "assure_id": ["ASS-1", "ASS-2"],
                "montant_total": [100, 200],
                "date_soin": ["2024-01-02", "2024-01-02"],
                "date_facture": ["2024-01-03", "2024-01-03"],
                "date_reception": ["2024-01-04", "2024-01-04"],
            }
        ),
        "lignes_facture.csv": pd.DataFrame(
            {
                "ligne_id": ["LIG-1"],
                "facture_id": ["FAC-1"],
                "code": ["ACTE-1"],
                "quantite": [1],
                "prix_unitaire": [100],
                "montant": [100],
            }
        ),
        "garanties.csv": pd.DataFrame(
            {"formule": ["ESSENTIEL"], "categorie": ["CONSULTATION"], "taux_remboursement": [80]}
        ),
        "grille_tarifaire.csv": pd.DataFrame(
            {"prestataire_id": ["PRE-1"], "code": ["ACTE-1"], "tarif_pratique": [12]}
        ),
        "labels_fraude.csv": pd.DataFrame({"facture_id": ["FAC-1", "FAC-2"], "est_fraude": [0, 1]}),
        "labels_prestataires.csv": pd.DataFrame(
            {"prestataire_id": ["PRE-1", "PRE-2"], "est_suspect": [0, 1]}
        ),
    }


# --------------------------------------------------------------------- nominal


def test_jeu_propre_valide() -> None:
    rapport = valider(_jeu_valide())
    assert rapport.ok, f"jeu valide refuse : {rapport.anomalies}"
    assert rapport.anomalies == []


def test_valeurs_manquantes_non_considerees_comme_anomalies() -> None:
    """44 % des factures du jeu n'ont pas d'ordonnance : ce n'est pas sale.

    Une porte de validation qui traiterait ces NULL comme des defauts ferait
    echouer le chargement du jeu officiel, alors qu'ils portent l'information
    "cet acte n'exige pas de prescription".
    """
    jeu = _jeu_valide()
    jeu["factures.csv"] = jeu["factures.csv"].assign(ordonnance_id=[None, None])
    rapport = valider(jeu)
    assert rapport.ok, f"valeurs manquantes signalees a tort : {rapport.anomalies}"


# ----------------------------------------------------------------- detections


def test_colonne_manquante_detectee() -> None:
    jeu = _jeu_valide()
    del jeu["factures.csv"]["montant_total"]
    rapport = valider(jeu)
    assert not rapport.ok
    assert any("montant_total" in a for a in rapport.anomalies)


def test_doublon_de_cle_primaire_detecte() -> None:
    jeu = _jeu_valide()
    jeu["factures.csv"] = pd.concat(
        [jeu["factures.csv"], jeu["factures.csv"].iloc[[0]]], ignore_index=True
    )
    rapport = valider(jeu)
    assert not rapport.ok
    assert any("facture_id" in a and "doublon" in a for a in rapport.anomalies)


def test_prestataire_orphelin_detecte() -> None:
    jeu = _jeu_valide()
    jeu["factures.csv"].loc[0, "prestataire_id"] = "PRE-999"
    rapport = valider(jeu)
    assert not rapport.ok
    assert any("prestataire_id" in a for a in rapport.anomalies)


def test_code_acte_inconnu_detecte() -> None:
    jeu = _jeu_valide()
    jeu["lignes_facture.csv"].loc[0, "code"] = "ACTE-404"
    rapport = valider(jeu)
    assert not rapport.ok
    assert any("ACTE-404" in a or "code(s) absent(s)" in a for a in rapport.anomalies)


def test_facture_sans_label_detectee() -> None:
    """Une cible supervisee incomplete biaiserait l'entrainement."""
    jeu = _jeu_valide()
    jeu["labels_fraude.csv"] = jeu["labels_fraude.csv"].iloc[[0]]
    rapport = valider(jeu)
    assert not rapport.ok
    assert any("sans label" in a for a in rapport.anomalies)


def test_label_hors_binaire_refuse() -> None:
    jeu = _jeu_valide()
    jeu["labels_fraude.csv"].loc[0, "est_fraude"] = 2
    rapport = valider(jeu)
    assert not rapport.ok
    assert any("est_fraude" in a for a in rapport.anomalies)


# ------------------------------------------------------------------- dates


def test_facture_anterieure_au_soin_refusee() -> None:
    jeu = _jeu_valide()
    jeu["factures.csv"].loc[0, "date_facture"] = "2023-01-01"
    rapport = valider(jeu)
    assert not rapport.ok
    assert any("anterieure(s) au soin" in a for a in rapport.anomalies)


def test_radiation_anterieure_a_adhesion_refusee() -> None:
    jeu = _jeu_valide()
    jeu["assures.csv"].loc[0, "date_radiation"] = "2023-01-01"
    rapport = valider(jeu)
    assert not rapport.ok
    assert any("radiation" in a for a in rapport.anomalies)


def test_dates_coherentes_acceptees() -> None:
    """Les controles mutent le rapport fourni : ils ne renvoient rien.

    L'API est volontairement `controler(tables, rapport)` plutot que
    `controler(tables) -> Rapport`, pour que `valider()` puisse empiler les
    controles sur un meme rapport sans allouer un objet par famille.
    """
    rapport = _rapport()
    assert controler_dates(_jeu_valide(), rapport) is None
    assert rapport.ok


# ------------------------------------------------------------------ numerique


def test_numerique_avec_texte_refuse() -> None:
    jeu = _jeu_valide()
    jeu["factures.csv"]["montant_total"] = ["100", "beaucoup"]
    rapport = valider(jeu)
    assert not rapport.ok
    assert any("non numerique" in a for a in rapport.anomalies)


# ------------------------------------------------------------------- etapes


def test_presence_signale_les_fichiers_manquants(tmp_path) -> None:
    from predicare_seed.validation import controler_presence

    presents, manquants = controler_presence(tmp_path)
    assert presents == []
    assert set(manquants) == set(COLONNES_ATTENDUES)


def test_detection_s_arrete_a_la_premiere_famille() -> None:
    """Deux anomalies de familles differentes ne doivent pas s'empiler.

    Une base vide de reference amene trois signalements d'un coup ; annoncer
    en meme temps un schema incomplet, des doublons et des dates incoherentes
    n'aide personne a decider par quoi commencer.
    """
    jeu = _jeu_valide()
    del jeu["factures.csv"]["montant_total"]
    jeu["factures.csv"] = pd.concat(
        [jeu["factures.csv"], jeu["factures.csv"].iloc[[0]]], ignore_index=True
    )
    rapport = valider(jeu)
    assert len(rapport.anomalies) == 1, rapport.anomalies


# ------------------------------------------------------------------ helpers


def test_controles_individuels_disponibles() -> None:
    """Chaque famille de controle doit rester appelable isolement."""
    jeu = _jeu_valide()
    for controle in (
        controler_schema,
        controler_unicite,
        controler_integrite,
        controler_dates,
        controler_numeriques,
        controler_labels,
    ):
        rapport = _rapport()
        controle(jeu, rapport)
        assert rapport.ok, f"{controle.__name__} a signale : {rapport.anomalies}"


@pytest.mark.parametrize("nom", sorted(COLONNES_ATTENDUES))
def test_chaque_fichier_attendu_a_des_colonnes_requises(nom: str) -> None:
    assert COLONNES_ATTENDUES[nom], f"{nom} n'exige aucune colonne : le controle serait vide"


# ------------------------------------------------- indexation RAG automatique


def _ingest_rag_interdit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Module factice : si l'indexation l'appelle, le test echoue."""
    import sys
    import types

    module = types.ModuleType("predicare_seed.ingest_rag")

    def appliquer(*_args: object, **_kwargs: object) -> dict[str, int]:
        pytest.fail("l'index RAG ne doit pas etre reconstruit")

    module.appliquer = appliquer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "predicare_seed.ingest_rag", module)


def test_indexation_rag_desactivable(monkeypatch: pytest.MonkeyPatch) -> None:
    """`SEED_RAG_AUTO=0` n'interroge meme pas la table vectorielle."""
    from predicare_seed import load_initial_data

    monkeypatch.setenv("SEED_RAG_AUTO", "0")
    monkeypatch.setattr(
        load_initial_data,
        "_nombre_documents_indexes",
        lambda: pytest.fail("la table ne doit pas etre lue quand l'indexation est desactivee"),
    )
    _ingest_rag_interdit(monkeypatch)

    load_initial_data.indexer_rag_si_vide()


def test_indexation_rag_ignoree_si_table_deja_peuplee(monkeypatch: pytest.MonkeyPatch) -> None:
    """470 documents deja presents : le second passage ne reindexe rien."""
    from predicare_seed import load_initial_data

    monkeypatch.setenv("SEED_RAG_AUTO", "1")
    monkeypatch.setattr(load_initial_data, "_nombre_documents_indexes", lambda: 470)
    _ingest_rag_interdit(monkeypatch)

    load_initial_data.indexer_rag_si_vide()


def test_indexation_rag_construit_quand_table_vide(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Table vide : `ingest_rag.appliquer` recoit le corpus et les 470 segments."""
    import sys
    import types

    from predicare_seed import load_initial_data

    appels: dict[str, object] = {}

    def appliquer(corpus: object) -> dict[str, int]:
        appels["corpus"] = corpus
        return {"segments": 470, "ignores": 0, "force": False}

    module = types.ModuleType("predicare_seed.ingest_rag")
    module.appliquer = appliquer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "predicare_seed.ingest_rag", module)

    monkeypatch.setenv("SEED_RAG_AUTO", "1")
    monkeypatch.setattr(load_initial_data, "_nombre_documents_indexes", lambda: 0)
    monkeypatch.setattr(load_initial_data, "_corpus_rag", lambda: tmp_path)
    monkeypatch.setattr(load_initial_data, "_embedding_disponible", lambda: True)

    load_initial_data.indexer_rag_si_vide()

    assert appels["corpus"] == tmp_path


def test_indexation_rag_ne_bloque_pas_sans_cle_embedding(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Sans cle, le seed reussit et l'index reste vide."""
    from predicare_seed import load_initial_data

    monkeypatch.setenv("SEED_RAG_AUTO", "1")
    monkeypatch.setattr(load_initial_data, "_nombre_documents_indexes", lambda: 0)
    monkeypatch.setattr(load_initial_data, "_corpus_rag", lambda: tmp_path)
    monkeypatch.setattr(load_initial_data, "_embedding_disponible", lambda: False)
    _ingest_rag_interdit(monkeypatch)

    load_initial_data.indexer_rag_si_vide()
