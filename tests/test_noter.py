"""Notation en lot : les deux informations que la payload HTTP ne transporte pas.

Le job a ete ecrit apres avoir mesure une divergence : la meme facture notee
0,06 par l'entrainement et 0,998 par `/predire`. Deux causes, toutes deux dans
le contexte que la payload de soumission ne porte pas :

- l'ordonnance : le service choisit « la plus recente du couple
  assure/prestataire » ; sur une facture qui n'en reference aucune, il en
  invente une, et `taux_lignes_non_prescrites` passe a 1 ;
- l'heure du soin : les lignes stockees portent une date a minuit, donc un
  soin de 10:35 est vu « hors horaire ».

Ces tests verrouillent l'assemblage, pas la base : ils tournent sans
PostgreSQL, conformement a la regle de `tests/conftest.py`.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from predicare.features import Ordonnance, calculer_features, charger_referentiels
from predicare_inference_api.noter import (
    FENETRE_VALIDATION_JOURS,
    _depuis,
    construire_facture,
    heure_depuis,
)


def _referentiels() -> dict:
    """Referentiel du modele ACTIF, resolu a l'execution.

    Les artefacts de modele sont volatils (`.gitignore`) et leur numero de
    version change a chaque entrainement : un chemin fige echouerait sur
    toute machine ou la version 2 est active.
    """
    from conftest import chemin_referentiels

    return json.loads(chemin_referentiels().read_text(encoding="utf-8"))


def _referentiels_disponible() -> bool:
    """Vrai si un artefact de modele est present sur ce poste."""
    try:
        from conftest import chemin_referentiels

        return chemin_referentiels().exists()
    except FileNotFoundError:
        return False


# ---------------------------------------------------------------------------
# Lecture de l'heure
# ---------------------------------------------------------------------------
def test_heure_depuis_les_formats_du_csv():
    assert heure_depuis("10:35") == 10
    assert heure_depuis("10:35:00") == 10
    assert heure_depuis("10h35") == 10


def test_heure_absente_ou_illisible_vaut_minuit_comme_l_entrainement():
    assert heure_depuis(None) == 0
    assert heure_depuis("") == 0
    assert heure_depuis("midi") == 0


def test_depuis_par_defaut_est_la_fenetre_de_selection():
    maintenant = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)

    assert _depuis(None, maintenant=maintenant) == maintenant - timedelta(
        days=FENETRE_VALIDATION_JOURS
    )


def test_depuis_normalise_une_date_avec_fuseau():
    assert _depuis("2026-01-01T00:00:00+02:00") == datetime(2025, 12, 31, 22, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Assemblage de la facture
# ---------------------------------------------------------------------------
def _facture(ordonnance: Ordonnance | None = None):
    """La facture reelle FAC-00063774, telle qu'elle est stockee."""
    return construire_facture(
        montant_total=17_500.0,
        date_facture=date(2026, 10, 4),
        date_soin=date(2026, 9, 30),
        heure_soin="10:35",
        lignes=[("CONS-GEN", 1, 17_500.0)],
        ordonnance=ordonnance,
        contrat=None,
        prestataire=None,
        prestataire_id="PRE-00161",
        assure_annee_naissance=1980,
        assure_sexe="F",
    )


def test_la_ligne_porte_l_heure_du_soin_pas_minuit():
    facture = _facture()

    assert facture.lignes[0].date_acte == datetime(2026, 9, 30, 10, 0)
    assert facture.ordonnance is None


def test_une_facture_sans_ordonnance_n_en_invente_pas():
    # C'est exactement le bug mesure : le service resolvait une ordonnance de
    # medicaments que la facture ne reference pas.
    assert _facture().ordonnance is None


@pytest.mark.skipif(
    not _referentiels_disponible(), reason="Aucun modele entraine (lancer `make train`)"
)
def test_une_facture_sans_ordonnance_ne_produit_aucune_ligne_non_prescrite():
    referentiels = charger_referentiels(_referentiels())

    valeurs = calculer_features(_facture(), referentiels)

    assert valeurs["taux_lignes_non_prescrites"] == 0.0
    # 10:35 un mercredi, dans les horaires : le soin n'est pas hors horaire.
    assert valeurs["soin_hors_horaire"] == 0.0
    assert valeurs["montant_total"] == 17_500.0


@pytest.mark.skipif(
    not _referentiels_disponible(), reason="Aucun modele entraine (lancer `make train`)"
)
def test_une_ordonnance_qui_ne_prescrit_pas_l_acte_est_bien_signalee():
    referentiels = charger_referentiels(_referentiels())
    ordonnance = Ordonnance(
        prescripteur_id="PRE-00161",
        date_prescription=date(2026, 9, 30),
        validite_jours=10,
        codes_prescrits=frozenset({"MED-DICLO"}),
    )

    valeurs = calculer_features(_facture(ordonnance), referentiels)

    assert valeurs["taux_lignes_non_prescrites"] == 1.0


@pytest.mark.skipif(
    not _referentiels_disponible(), reason="Aucun modele entraine (lancer `make train`)"
)
def test_l_ordonnance_referencee_qui_prescrit_l_acte_ne_signale_rien():
    referentiels = charger_referentiels(_referentiels())
    ordonnance = Ordonnance(
        prescripteur_id="PRE-00161",
        date_prescription=date(2026, 9, 30),
        validite_jours=10,
        codes_prescrits=frozenset({"CONS-GEN"}),
    )

    valeurs = calculer_features(_facture(ordonnance), referentiels)

    assert valeurs["taux_lignes_non_prescrites"] == 0.0
    assert valeurs["ordonnance_absente_requis"] == 0.0
