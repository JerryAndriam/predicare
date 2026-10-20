"""Import du lot du jour J : resolution des references et horodatage.

Ces tests portent sur les fonctions pures de l'import. L'insertion complete
est verifiee par le runbook (``make import-factures``) sur une base reelle :
le point critique ici est le mapping ``ASS-...`` -> pseudonyme, sans lequel
toutes les factures du jury seraient rejetees.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from predicare.crypto import pseudonymize
from predicare_seed.import_factures import (
    FACTURES,
    LIGNES,
    _charger,
    _date_acte,
    _pseudonyme,
)


def test_pseudonyme_brut_utilise_le_meme_hmac_que_la_graine() -> None:
    assert _pseudonyme("ASS-123") == pseudonymize("assr", "ASS-123")


def test_pseudonyme_deja_calcule_reste_inchange() -> None:
    assert _pseudonyme("assr_dejaCalcule") == "assr_dejaCalcule"


def test_date_acte_recompose_l_heure_de_soin() -> None:
    assert _date_acte(datetime(2026, 10, 15), "09:45", None) == datetime(2026, 10, 15, 9, 0)


def test_date_acte_sans_date_soin_garde_l_horodatage_brut() -> None:
    brut = datetime(2026, 10, 15, 14, 30)
    assert _date_acte(None, None, brut) == brut


def test_charger_refuse_un_schema_incomplet(tmp_path) -> None:
    (tmp_path / FACTURES).write_text("facture_id\nFAC-1\n", encoding="utf-8")
    (tmp_path / LIGNES).write_text("facture_id\nFAC-1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Colonnes absentes"):
        _charger(tmp_path)
