"""Fonctions pures du script d'evaluation RAG.

Aucun appel HTTP ni LLM : la normalisation, la comparaison et les seuils
sont la partie qui doit rester verifiable en CI, hors infrastructure.
"""

from __future__ import annotations

import pytest

from scripts.eval_rag import (
    citation_ok,
    cout_par_million_depuis_env,
    estimer_cout,
    evaluer_reponse,
    mots_cles_presents,
    normaliser_texte,
    percentile,
    respecte_seuils_ci,
    valeur_ok,
)

# --------------------------------------------------------------- normalisation


def test_normalisation_casse_et_accents() -> None:
    assert normaliser_texte("Délai de CARENCE à 100 %") == "delai de carence a 100 %"


def test_normalisation_espaces_insecables_et_milliers() -> None:
    assert "616060" in normaliser_texte("616\u00a0060,00 Ar")
    assert "20000000" in normaliser_texte("20\u202f000\u202f000 Ar")
    assert "616060" in normaliser_texte("616 060 Ar")


def test_normalisation_espaces_multiples() -> None:
    assert (
        normaliser_texte("  plusieurs   espaces\tet\nretours  ") == "plusieurs espaces et retours"
    )


def test_normalisation_texte_vide() -> None:
    assert normaliser_texte("") == ""
    assert normaliser_texte(None) == ""


# --------------------------------------------------------------- mots-cles


def test_tous_les_mots_cles_doivent_etre_presents() -> None:
    assert mots_cles_presents("Le délai de maternité est de 90 jours.", ["90", "maternite"])
    assert not mots_cles_presents("Le délai est de 90 jours.", ["90", "maternite"])


def test_mots_cles_insensibles_aux_accents_et_a_la_casse() -> None:
    assert mots_cles_presents("DENTAIRE remboursée", ["dentaire", "rembourse"])


# --------------------------------------------------------------- citations


def test_citation_contrat_et_article() -> None:
    sources = [
        {
            "contrat": "Conditions Generales PREMIUM",
            "article": "Article 5 - Tableau des garanties",
        }
    ]

    assert citation_ok(sources, ["Conditions Generales PREMIUM", "Article 5"])


def test_citation_absente() -> None:
    sources = [{"contrat": "Conditions Generales CONFORT", "article": "Article 5"}]

    assert not citation_ok(sources, ["Conditions Generales PREMIUM"])


def test_citation_sans_attendu_est_non_applicable() -> None:
    assert citation_ok([], []) is None


# --------------------------------------------------------------- valeurs


def test_valeur_attendue_presente() -> None:
    assert valeur_ok("Le total remboursé est de 616 060 Ar.", ["616 060"])


def test_valeur_attendue_absente() -> None:
    assert not valeur_ok("Le total remboursé est de 500 000 Ar.", ["616 060"])


def test_valeur_regex() -> None:
    assert valeur_ok("Facture traitée le 22/07/2026.", ["re:22[/-]07[/-]2026"])
    assert not valeur_ok("Facture traitée le 21/07/2026.", ["re:22[/-]07[/-]2026"])


def test_valeur_sans_attendu_est_non_applicable() -> None:
    assert valeur_ok("Une reponse quelconque.", []) is None


# --------------------------------------------------------------- percentiles


def test_percentile_liste_vide() -> None:
    assert percentile([], 50) == 0.0


def test_percentile_median_et_p95() -> None:
    valeurs = [10.0, 20.0, 30.0, 40.0]

    assert percentile(valeurs, 50) == pytest.approx(25.0)
    assert percentile(valeurs, 95) == pytest.approx(38.5)


def test_percentile_une_seule_valeur() -> None:
    assert percentile([12.5], 95) == pytest.approx(12.5)


# --------------------------------------------------------------- cout


def test_estimation_cout_par_million() -> None:
    assert estimer_cout(1_000_000, 0.60) == pytest.approx(0.60)
    assert estimer_cout(500_000, 0.60) == pytest.approx(0.30)


def test_cout_par_million_lu_dans_l_environnement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_COUT_PAR_MILLION_USD", "1.25")

    assert cout_par_million_depuis_env() == pytest.approx(1.25)


def test_cout_par_million_valeur_par_defaut(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_COUT_PAR_MILLION_USD", raising=False)

    assert cout_par_million_depuis_env() == pytest.approx(0.60)


# --------------------------------------------------------------- seuils CI


def test_seuils_ci_atteints() -> None:
    assert respecte_seuils_ci(fidelite=0.80, citation=0.90, valeur=0.90)


def test_seuils_ci_fidelite_insuffisante() -> None:
    assert not respecte_seuils_ci(fidelite=0.79, citation=0.95, valeur=0.95)


def test_seuils_ci_citation_insuffisante() -> None:
    assert not respecte_seuils_ci(fidelite=0.95, citation=0.89, valeur=0.95)


def test_seuils_ci_valeur_insuffisante() -> None:
    assert not respecte_seuils_ci(fidelite=0.95, citation=0.95, valeur=0.89)


def test_seuils_ci_echoue_si_aucune_question_de_citation() -> None:
    """Un taux de 1.0 sur zero question ne doit jamais valider la CI."""
    assert not respecte_seuils_ci(
        fidelite=1.0, citation=1.0, valeur=1.0, citation_questions=0, valeur_questions=10
    )


def test_seuils_ci_echoue_si_aucune_question_de_valeur() -> None:
    assert not respecte_seuils_ci(
        fidelite=1.0, citation=1.0, valeur=1.0, citation_questions=10, valeur_questions=0
    )


def test_seuils_ci_avec_denominateurs_non_nuls() -> None:
    assert respecte_seuils_ci(
        fidelite=0.9, citation=0.95, valeur=0.95, citation_questions=20, valeur_questions=26
    )


# --------------------------------------------------------------- tokens et cache


def _question_vide() -> dict:
    return {
        "id": "Q00",
        "question": "Question ?",
        "mots_cles": [],
        "sources_attendues": [],
        "attendu_contient": [],
    }


def test_evaluer_reponse_somme_les_tokens_entree_et_sortie() -> None:
    resultat = evaluer_reponse(
        _question_vide(),
        {"reponse": "ok", "sources": [], "tokens_entree": 100, "tokens_sortie": 20},
        latence_ms=1.0,
    )

    assert resultat["tokens_entree"] == 100
    assert resultat["tokens_sortie"] == 20
    assert resultat["tokens"] == 120


def test_evaluer_reponse_repli_sur_l_ancien_champ_tokens() -> None:
    """Une API sans detail entree/sortie ne doit pas afficher zero token."""
    resultat = evaluer_reponse(
        _question_vide(),
        {"reponse": "ok", "sources": [], "tokens": 42},
        latence_ms=1.0,
    )

    assert resultat["tokens"] == 42


def test_evaluer_reponse_remonte_les_succes_de_cache() -> None:
    resultat = evaluer_reponse(
        _question_vide(),
        {"reponse": "ok", "sources": [], "cache_semantique": True},
        latence_ms=0.0,
    )

    assert resultat["cache_semantique"] is True


def test_evaluer_reponse_sans_cache_par_defaut() -> None:
    resultat = evaluer_reponse(_question_vide(), {"reponse": "ok", "sources": []}, latence_ms=1.0)

    assert resultat["cache_semantique"] is False
