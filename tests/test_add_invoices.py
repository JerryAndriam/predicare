"""L'adaptateur multi-format : le format s'adapte, la porte non.

Ces tests ne touchent ni PostgreSQL ni HTTP : ils verifient la DETECTION et
la NORMALISATION, c'est-a-dire que les trois formats que la plateforme sait
lire produisent la meme structure interne. C'est la garantie qui compte pour
le jour J : le jury peut donner son fichier dans un format ou dans un autre,
le resultat est le meme.

Le reste (le depot par l'API, la notation, l'alerte) est couvert par les
tests du lot du jury et par le parcours e2e.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from predicare.crypto import pseudonymize
from predicare_seed.add_invoices import (
    FORMAT_CSV_FRONT,
    FORMAT_CSV_RAW,
    FORMAT_JSON,
    FichierInvalideError,
    detecter_format,
    lire_fichier,
)

LOT = Path("data/seed/lot_20_factures.json")

#: Un CSV au format du front (une facture par ligne, un acte).
CSV_FRONT = """assure_pseudonyme;prestataire_id;date_facture;code_acte;quantite;montant_unitaire;date_acte
assr_Wv7VAUFiUXieeWwChWmGXB;PRE-00155;2026-10-18;DENT-CONS;1;19000;2026-10-18
"""

#: Un CSV au schema du chargement initial (deux fichiers).
CSV_RAW_FACTURES = """facture_id;assure_id;prestataire_id;date_facture;montant_total;devise
FAC-TEST-001;ASS-9CAA1484E0;PRE-00155;2026-10-18;19000;MGA
"""

CSV_RAW_LIGNES = """facture_id;code;quantite;prix_unitaire;date_acte
FAC-TEST-001;DENT-CONS;1;19000;2026-10-18
FAC-TEST-001;DENT-EXTRACT;1;34000;2026-10-18
"""


def _ecrire(tmp_path: Path, nom: str, contenu: str) -> Path:
    chemin = tmp_path / nom
    chemin.write_text(contenu, encoding="utf-8")
    return chemin


def test_le_format_du_lot_canonique_est_json() -> None:
    """Le lot versionne est un JSON : c'est le format par defaut."""
    assert detecter_format(LOT) == FORMAT_JSON


def test_le_format_csv_front_est_reconnu(tmp_path: Path) -> None:
    """Le CSV que l'onglet « Import de lot » du front sait lire."""
    chemin = _ecrire(tmp_path, "lot.csv", CSV_FRONT)
    assert detecter_format(chemin) == FORMAT_CSV_FRONT


def test_le_format_csv_data_raw_est_reconnu(tmp_path: Path) -> None:
    """Le CSV du chargement initial, avec son en-tete `facture_id`."""
    chemin = _ecrire(tmp_path, "factures.csv", CSV_RAW_FACTURES)
    assert detecter_format(chemin) == FORMAT_CSV_RAW


def test_les_trois_formats_donnent_la_meme_structure(tmp_path: Path) -> None:
    """Une facture normalisee a toujours la meme forme, quel que soit le format.

    C'est LA garantie du jour J : le fichier du jury peut etre dans un format
    ou dans un autre, la porte d'entree recoit la meme chose.
    """
    format_lot, lot = lire_fichier(LOT)
    format_front, front = lire_fichier(_ecrire(tmp_path, "front.csv", CSV_FRONT))
    _ecrire(tmp_path, "lignes_facture.csv", CSV_RAW_LIGNES)
    format_raw, raw = lire_fichier(_ecrire(tmp_path, "factures.csv", CSV_RAW_FACTURES))

    assert format_lot == FORMAT_JSON
    assert format_front == FORMAT_CSV_FRONT
    assert format_raw == FORMAT_CSV_RAW

    for factures in (lot, front, raw):
        assert factures, "chaque format doit produire au moins une facture"
        for facture in factures:
            assert facture.facture_id
            assert facture.payload["prestataire_id"]
            assert facture.payload["date_facture"]
            assert facture.payload["assure_pseudonyme"].startswith("assr_")
            assert facture.payload["lignes"]
            for ligne in facture.payload["lignes"]:
                assert ligne["code_acte"]
                # La quantite peut valoir 0 : c'est l'un des cas invalides
                # du lot (une quantite nulle doit etre REJETEE par l'API,
                # pas corrigee a la lecture).
                assert int(ligne["quantite"]) >= 0
                if facture.cas_attendu == "valide":
                    assert int(ligne["quantite"]) >= 1


def test_le_csv_data_raw_regroupe_les_lignes_de_la_facture(tmp_path: Path) -> None:
    """Les lignes de prestation sont regroupees sous leur facture.

    Un CSV du chargement initial a UNE ligne par acte : la normalisation
    doit les regrouper, sinon la facture arrive a la porte avec un seul acte.
    """
    _ecrire(tmp_path, "lignes_facture.csv", CSV_RAW_LIGNES)
    _, factures = lire_fichier(_ecrire(tmp_path, "factures.csv", CSV_RAW_FACTURES))
    assert len(factures) == 1
    assert len(factures[0].payload["lignes"]) == 2


def test_un_identifiant_brut_est_pseudonymise(tmp_path: Path) -> None:
    """Un fichier portant l'identifiant brut est pseudonymise a la lecture.

    La base ne contient que des pseudonymes : un fichier du jury peut porter
    l'identifiant brut, il est converti par le meme HMAC que la graine.
    """
    contenu = [
        {
            "facture_id": "FAC-JSON-002",
            "assure_id": "ASS-9CAA1484E0",
            "prestataire_id": "PRE-00155",
            "date_facture": "2026-10-18",
            "lignes": [{"code_acte": "DENT-CONS", "quantite": 1, "montant_unitaire": 19000}],
        }
    ]
    _, factures = lire_fichier(_ecrire(tmp_path, "lot.json", json.dumps(contenu)))
    assert factures[0].payload["assure_pseudonyme"] == pseudonymize("assr", "ASS-9CAA1484E0")


def test_un_pseudonyme_deja_calcule_reste_inchange(tmp_path: Path) -> None:
    """Un pseudonyme deja calcule n'est pas retransforme."""
    contenu = [
        {
            "facture_id": "FAC-JSON-003",
            "assure_pseudonyme": "assr_dejaCalcule",
            "prestataire_id": "PRE-00155",
            "date_facture": "2026-10-18",
            "lignes": [{"code_acte": "DENT-CONS", "quantite": 1, "montant_unitaire": 19000}],
        }
    ]
    _, factures = lire_fichier(_ecrire(tmp_path, "lot.json", json.dumps(contenu)))
    assert factures[0].payload["assure_pseudonyme"] == "assr_dejaCalcule"


def test_le_lot_canonique_conserve_les_resultats_attendus() -> None:
    """Le lot porte ses attendus : ils doivent survivre a la normalisation.

    C'est ce qui permet au rapport de dire « ecarts » quand le resultat
    s'ecarte de l'attendu.
    """
    _, lot = lire_fichier(LOT)
    avec_attendu = [cas for cas in lot if cas.attendu]
    assert len(avec_attendu) == len(lot)
    assert any(cas.cas_attendu.startswith("invalide:") for cas in lot)
    assert any(cas.alerte_attendue is True for cas in lot)


def test_un_json_de_lot_sans_enveloppe_est_accepte(tmp_path: Path) -> None:
    """Un tableau de factures est accepte comme un lot.

    Le jury peut donner un simple tableau JSON : c'est le meme contenu, sans
    l'enveloppe. Refuser serait un refus de l'exigence, pas de la rigueur.
    """
    contenu = [
        {
            "facture_id": "FAC-JSON-001",
            "assure_pseudonyme": "assr_Wv7VAUFiUXieeWwChWmGXB",
            "prestataire_id": "PRE-00155",
            "date_facture": "2026-10-18",
            "lignes": [{"code_acte": "DENT-CONS", "quantite": 1, "montant_unitaire": 19000}],
        }
    ]
    _, factures = lire_fichier(_ecrire(tmp_path, "lot.json", json.dumps(contenu)))
    assert len(factures) == 1
    assert factures[0].facture_id == "FAC-JSON-001"


def test_un_fichier_absent_est_refuse(tmp_path: Path) -> None:
    """Un fichier introuvable le dit, il ne devine pas."""
    with pytest.raises(FichierInvalideError):
        lire_fichier(tmp_path / "absent.json")


def test_un_json_illisible_est_refuse(tmp_path: Path) -> None:
    """Un JSON casse est refuse avec la raison."""
    with pytest.raises(FichierInvalideError):
        lire_fichier(_ecrire(tmp_path, "lot.json", "{ pas du json"))


def test_la_reference_voyage_avec_la_facture(tmp_path: Path) -> None:
    """Chaque format doit porter la reference dans la charge envoyee.

    C'est la reference qui rend le depot IDEMPOTENT : la porte d'entree la
    prend comme identifiant metier, et refuse d'ecrire si la facture existe
    deja. Sans elle, l'API tire une reference aleatoire et le meme fichier
    creerait une NOUVELLE facture a chaque passage.
    """
    _ecrire(tmp_path, "lignes_facture.csv", CSV_RAW_LIGNES)
    _, brutes = lire_fichier(_ecrire(tmp_path, "factures.csv", CSV_RAW_FACTURES))
    _, front = lire_fichier(_ecrire(tmp_path, "front.csv", CSV_FRONT))
    _, lot = lire_fichier(LOT)

    for factures in (brutes, front, lot):
        for facture in factures:
            assert facture.payload.get("facture_id") == facture.facture_id


def test_le_montant_total_est_calcule_pour_le_format_front(tmp_path: Path) -> None:
    """Le CSV du front ne porte pas de total : l'adaptateur le calcule.

    L'interface fait de meme -- le total s'affiche sous les yeux du
    professionnel. Sans ce calcul, la porte refuse la facture pour un champ
    absent, alors que le fichier est valide.
    """
    _, factures = lire_fichier(_ecrire(tmp_path, "front.csv", CSV_FRONT))
    assert factures[0].payload["montant_total"] == 19000.0
