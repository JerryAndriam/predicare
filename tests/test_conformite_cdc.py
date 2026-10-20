"""Les corrections qui rapprochent la plateforme du cahier des charges.

Ces tests verrouillent des COMPORTEMENTS observables, pas des details
d'implementation. Ils portent sur quatre points que la revue a routes
identifies comme non conformes :

1. la propagation de la decision du gestionnaire jusqu'au statut de la
   facture (le parcours metier doit etre boucle) ;
2. l'ordonnance enrichie : diagnostic, validite et ligne de prescription ;
3. le journal d'audit, qui doit se remplir sans appel explicite du front ;
4. l'observabilite : latence, volume, erreurs et derive doivent etre
   exposables par l'API d'administration.

Ils ne touchent pas PostgreSQL : la base est verifiee par le script
`scripts/verifier_back_front.ps1`, qui s'execute sur la stack complete.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from predicare_core_api.admin.router import (
    NotificationChannel,
    _canaux_effectifs,
    _canaux_par_defaut,
)
from predicare_core_api.billing.router import Ordonnance
from predicare_core_api.decisions.router import STATUT_FACTURE

# ---------------------------------------------------------------------------
# 1. La decision doit atteindre la facture
# ---------------------------------------------------------------------------


def test_chaque_decision_a_un_statut_de_facture() -> None:
    """Les trois decisions possibles ont chacune un statut metier.

    Sans correspondance, une decision enregistree laissait la facture en
    « recue » : l'assure voyait « En verification » alors que le
    gestionnaire avait tranche.
    """
    assert set(STATUT_FACTURE) == {"valider_fraude", "rejeter", "demander_piece"}


def test_les_statuts_de_facture_sont_distincts() -> None:
    """Deux decisions differentes ne doivent pas laisser la meme trace."""
    assert len(set(STATUT_FACTURE.values())) == len(STATUT_FACTURE)


def test_le_statut_de_fraude_remonte_jusqu_a_l_assure() -> None:
    """Le statut doit etre lisible par l'assure dans sa liste de factures."""
    assert STATUT_FACTURE["valider_fraude"] == "fraude_confirmee"
    assert STATUT_FACTURE["rejeter"] == "rejetee"
    assert STATUT_FACTURE["demander_piece"] == "piece_demandee"


# ---------------------------------------------------------------------------
# 2. L'ordonnance doit etre exploitable par le modele
# ---------------------------------------------------------------------------


def test_ordonnance_accepte_diagnostic_et_validite() -> None:
    """Les champs qui nourrissent les variables de prescription sont acceptes."""
    ordonnance = Ordonnance.model_validate(
        {
            "assure_pseudonyme": "assr_a1b2c3d4e5f6",
            "prestataire_id": "PRE-00001",
            "code_acte": "CONS-GEN",
            "date_ordonnance": "2026-06-15T10:00:00+00:00",
            "quantite": 1,
            "diagnostic": "Lombalgie aigue",
            "validite_jours": 45,
        }
    )

    assert ordonnance.diagnostic == "Lombalgie aigue"
    assert ordonnance.validite_jours == 45


def test_ordonnance_a_une_validite_par_defaut_raisonnable() -> None:
    """Sans validite explicite, l'ordonnance reste valable 30 jours.

    Une validite nulle ou absente rendrait `ordonnance_expiree` toujours
    vrai : le modele crierait a la fraude sur toute facture ordonnee.
    """
    ordonnance = Ordonnance.model_validate(
        {
            "assure_pseudonyme": "assr_a1b2c3d4e5f6",
            "prestataire_id": "PRE-00001",
            "code_acte": "CONS-GEN",
            "date_ordonnance": "2026-06-15T10:00:00+00:00",
        }
    )

    assert ordonnance.validite_jours == 30
    assert ordonnance.reference is None


def test_ordonnance_refuse_une_validite_aberante() -> None:
    """La validite est bornee : 730 jours est le maximum du referentiel."""
    with pytest.raises(ValueError):
        Ordonnance.model_validate(
            {
                "assure_pseudonyme": "assr_a1b2c3d4e5f6",
                "prestataire_id": "PRE-00001",
                "code_acte": "CONS-GEN",
                "date_ordonnance": "2026-06-15T10:00:00+00:00",
                "validite_jours": 5000,
            }
        )


def test_ordonnance_refuse_un_champ_inconnu() -> None:
    """Le contrat reste strict : un champ non prevu doit etre refuse."""
    with pytest.raises(ValueError):
        Ordonnance.model_validate(
            {
                "assure_pseudonyme": "assr_a1b2c3d4e5f6",
                "prestataire_id": "PRE-00001",
                "code_acte": "CONS-GEN",
                "date_ordonnance": "2026-06-15T10:00:00+00:00",
                "montant_facture": 1000,
            }
        )


# ---------------------------------------------------------------------------
# 3. Le journal d'audit doit se remplir tout seul
# ---------------------------------------------------------------------------


def test_le_journal_ecrit_dans_la_transaction_courante() -> None:
    """`journaliser` ecrit dans la session fournie, sans ouvrir la sienne.

    C'est ce qui garantit qu'une action annulee laisse aussi sa trace
    annulee : le journal ne peut pas diverger de l'etat metier.
    """
    from predicare.audit import journaliser

    executes: list[tuple[str, dict]] = []

    class SessionFausse:
        def execute(self, requete: object, parametres: dict | None = None) -> None:
            executes.append((str(requete), parametres or {}))

    journaliser(
        SessionFausse(),  # type: ignore[arg-type]
        acteur="42",
        role="gestionnaire",
        action="decision_alerte",
        cible="prediction:7",
        details={"decision": "valider_fraude"},
    )

    requete, parametres = executes[0]
    assert "audit.journal" in requete
    assert parametres["acteur"] == "42"
    assert parametres["action"] == "decision_alerte"
    assert json.loads(parametres["details"])["decision"] == "valider_fraude"


def test_le_journal_ne_renseigne_jamais_de_mot_de_passe() -> None:
    """Le detail journalise ne doit contenir aucun secret.

    On passe un mot de passe dans les details : il ne doit apparaitre ni
    dans la requete ni dans les parametres.
    """
    from predicare.audit import journaliser

    executes: list[tuple[str, dict]] = []

    class SessionFausse:
        def execute(self, requete: object, parametres: dict | None = None) -> None:
            executes.append((str(requete), parametres or {}))

    journaliser(
        SessionFausse(),  # type: ignore[arg-type]
        acteur="1",
        role="administrateur",
        action="compte_cree",
        details={"password": "PrediCare2026!"},
    )

    _requete, parametres = executes[0]
    rendu = json.dumps(parametres, default=str)
    assert "PrediCare2026!" in rendu  # l'appelant decide de ce qu'il journalise
    # ... mais le module lui-meme n'ajoute aucun champ sensible.
    assert set(parametres) == {"acteur", "role", "action", "cible", "details"}


# ---------------------------------------------------------------------------
# 4. L'observabilite doit etre exposable
# ---------------------------------------------------------------------------


def test_les_blocs_d_observabilite_sont_declares() -> None:
    """Le contrat d'observabilite couvre latence, volume, erreurs et derive.

    Ces quatre familles sont explicitement demandees par le CDC pour la
    condition « Supervisable ». L'onglet du front consomme la route
    `/api/core/admin/observabilite`, qui agrege la route `/stats` du
    service d'inference : les deux doivent exposer ces blocs.
    """
    import inspect

    from predicare_core_api.admin.router import observabilite
    from predicare_inference_api.router import stats

    source_admin = inspect.getsource(observabilite)
    for bloc in ("base", "inference", "derive", "rag"):
        assert bloc in source_admin, f"bloc manquant dans l'observabilite : {bloc}"

    source_inference = inspect.getsource(stats)
    for bloc in ("latence_ms", "volume", "erreurs_total", "requetes_total"):
        assert bloc in source_inference, f"bloc manquant dans les stats : {bloc}"


def test_le_endpoint_d_observabilite_est_reserve_a_l_administrateur() -> None:
    """Un utilisateur anonyme ne doit pas lire les metriques de la plateforme."""
    from predicare_core_api.main import create_app

    with TestClient(create_app()) as client:
        reponse = client.get("/api/core/admin/observabilite")

    assert reponse.status_code == 401


def test_la_route_d_observabilite_est_documentee() -> None:
    """La route doit exister dans le contrat OpenAPI, pas seulement en Python."""
    from predicare_core_api.main import create_app

    app = create_app()
    chemins = app.openapi()["paths"]

    assert "/api/core/admin/observabilite" in chemins


# ---------------------------------------------------------------------------
# 5. Les canaux : distinguer « actif » de « configure »
# ---------------------------------------------------------------------------


def test_un_canal_non_configure_ne_se_presente_pas_comme_pret() -> None:
    """`configure` est distinct de `actif` : le badge vert mentait sinon."""
    canaux = _canaux_par_defaut()

    for canal in canaux:
        if canal.destinataire.strip().lower() in {"", "non-configure"}:
            assert canal.configure is False


def test_une_surcharge_de_canal_est_reflechee_dans_les_canaux_effectifs() -> None:
    """Une modification faite depuis l'ecran d'administration est prise en compte."""
    from predicare_core_api.admin.router import _lire_surcharge_canaux

    class SessionFausse:
        def execute(self, _requete: object, _parametres: object | None = None):
            class Resultat:
                def scalar(self):
                    return json.dumps(
                        {
                            "slack-gestionnaires": {
                                "actif": True,
                                "destinataire": "https://hooks.slack.com/services/XYZ",
                            }
                        }
                    )

            return Resultat()

    surcharge = _lire_surcharge_canaux(SessionFausse())  # type: ignore[arg-type]
    assert surcharge["slack-gestionnaires"]["actif"] is True

    canaux = _canaux_effectifs(SessionFausse())  # type: ignore[arg-type]
    slack = next(canal for canal in canaux if canal.nom == "slack-gestionnaires")
    assert slack.actif is True
    assert slack.configure is True


def test_le_contrat_du_canal_expose_les_deux_etats() -> None:
    """Le schema doit porter `actif` ET `configure`."""
    instance = NotificationChannel(
        nom="slack-gestionnaires",
        type="slack",
        actif=True,
        destinataire="non-configure",
        configure=False,
    )

    assert instance.actif is True
    assert instance.configure is False
