"""Estimation du cout LLM : calcul lineaire, tokens nuls et conversion EUR.

Le dossier FinOps doit pouvoir refaire le calcul a la main. Ces tests
verifient la formule et les valeurs par defaut, pas un tarif fournisseur
particulier (les prix sont configurables et evoluent).
"""

from __future__ import annotations

import pytest

from predicare_rag_api.finops import (
    PRIX_ENTREE_DEFAUT_USD_PAR_MILLION,
    TAUX_USD_EUR_DEFAUT,
    estimer_cout,
)


def test_un_million_de_tokens_entree() -> None:
    cout = estimer_cout(1_000_000, 0)

    assert cout["cout_entree_usd"] == pytest.approx(PRIX_ENTREE_DEFAUT_USD_PAR_MILLION)
    assert cout["cout_sortie_usd"] == 0.0
    assert cout["cout_total_usd"] == pytest.approx(0.15)
    assert cout["cout_entree_eur"] == pytest.approx(0.15 * TAUX_USD_EUR_DEFAUT)
    assert cout["cout_total_eur"] == pytest.approx(0.15 * TAUX_USD_EUR_DEFAUT)


def test_un_million_de_tokens_sortie() -> None:
    cout = estimer_cout(0, 1_000_000)

    assert cout["cout_entree_usd"] == 0.0
    assert cout["cout_total_usd"] == pytest.approx(0.60)
    assert cout["cout_sortie_eur"] == pytest.approx(0.60 * TAUX_USD_EUR_DEFAUT)
    assert cout["cout_total_eur"] == pytest.approx(0.60 * TAUX_USD_EUR_DEFAUT)


def test_les_couts_eur_par_sens_s_additionnent() -> None:
    cout = estimer_cout(500_000, 500_000)

    assert cout["cout_total_eur"] == pytest.approx(
        cout["cout_entree_eur"] + cout["cout_sortie_eur"]
    )


def test_entree_et_sortie_sont_additionnees() -> None:
    cout = estimer_cout(500_000, 500_000)

    assert cout["cout_entree_usd"] == pytest.approx(0.075)
    assert cout["cout_sortie_usd"] == pytest.approx(0.30)
    assert cout["cout_total_usd"] == pytest.approx(0.375)


def test_tokens_nuls_donnent_un_cout_nul() -> None:
    cout = estimer_cout(0, 0)

    assert cout == {
        "cout_entree_usd": 0.0,
        "cout_sortie_usd": 0.0,
        "cout_total_usd": 0.0,
        "cout_total_usd_brut": 0.0,
        "cout_entree_eur": 0.0,
        "cout_sortie_eur": 0.0,
        "cout_total_eur": 0.0,
    }


def test_prix_et_taux_configurables() -> None:
    cout = estimer_cout(
        1_000_000,
        1_000_000,
        prix_entree_par_million_usd=1.0,
        prix_sortie_par_million_usd=2.0,
        taux_usd_eur=0.5,
    )

    assert cout["cout_total_usd"] == pytest.approx(3.0)
    assert cout["cout_total_eur"] == pytest.approx(1.5)


def test_tokens_negatifs_traites_comme_zero() -> None:
    """Un compteur defectueux ne doit pas produire un cout negatif."""
    cout = estimer_cout(-100, -200)

    assert cout["cout_total_usd"] == 0.0
    assert cout["cout_total_eur"] == 0.0
