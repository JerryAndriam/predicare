"""Lot de 20 factures inedites du CDC (F17) : format, portes et client.

Ces tests portent sur des fonctions pures et sur un transport HTTP simule :
ils tournent sans PostgreSQL et sans pile demarree. Ce qu'ils verrouillent :

- le fichier de lot est unique, complet et versionne (15 valides, 5 invalides) ;
- chaque facture invalide est bien rejetee par la porte attendue (schema,
  validation metier ou verification de reference), en nommant le champ ;
- chaque facture valide passe la porte d'entree ;
- le client confronte la reponse de l'API au resultat attendu, au lieu de
  considerer qu'un HTTP 202 suffit.

Le parcours reel (notation, persistance, file d'alertes, decision) est couvert
par `tests/e2e/test_lot_jury_e2e.py`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from predicare.errors import InvalidInvoiceError
from predicare.schemas import InvoiceSubmission
from predicare_inference_api.validation import validate_invoice
from predicare_seed.lot_jury import (
    CasLot,
    LotInvalideError,
    charger_lot,
    executer,
    rapport,
    soumettre,
)

LOT = Path("data/seed/lot_20_factures.json")
REFERENTIELS = Path("models/1/referentiels.json")

#: Date de reference du lot : les factures ont ete generees le 2026-10-20.
MAINTENANT = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def lot() -> list[CasLot]:
    return charger_lot(LOT)


@pytest.fixture(scope="module")
def referentiels() -> dict:
    return json.loads(REFERENTIELS.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Le fichier est la source unique
# ---------------------------------------------------------------------------
def test_le_lot_contient_20_factures_dont_5_invalides(lot: list[CasLot]) -> None:
    assert len(lot) == 20
    assert sum(1 for cas in lot if cas.valide) == 15
    assert sum(1 for cas in lot if not cas.valide) == 5


def test_les_identifiants_sont_uniques_et_reserves_au_jury(lot: list[CasLot]) -> None:
    identifiants = [cas.facture_id for cas in lot]

    assert len(set(identifiants)) == len(identifiants)
    assert all(identifiant.startswith("FAC-JURY-") for identifiant in identifiants)


def test_le_lot_documente_7_alertes_et_8_factures_conformes(lot: list[CasLot]) -> None:
    attendus = [cas.alerte_attendue for cas in lot if cas.valide]

    assert attendus.count(True) == 7
    assert attendus.count(False) == 8


# ---------------------------------------------------------------------------
# Porte d'entree des factures valides
# ---------------------------------------------------------------------------
def test_les_15_valides_passent_la_porte_d_entree(lot: list[CasLot]) -> None:
    for cas in lot:
        if not cas.valide:
            continue

        invoice = InvoiceSubmission.model_validate(cas.payload)
        validate_invoice(invoice, now=MAINTENANT)

        assert invoice.montant_calcule == pytest.approx(cas.payload["montant_total"], abs=0.01), (
            f"{cas.facture_id} : montant total incoherent avec les lignes"
        )


def test_les_references_des_valides_existent_au_referentiel(
    lot: list[CasLot], referentiels: dict
) -> None:
    connus = set(referentiels["actes"]) | set(referentiels["medicaments"])

    for cas in lot:
        if not cas.valide:
            continue
        assert cas.payload["prestataire_id"] in referentiels["prestataires"], cas.facture_id
        for ligne in cas.payload["lignes"]:
            assert ligne["code_acte"] in connus, f"{cas.facture_id} : {ligne['code_acte']}"


# ---------------------------------------------------------------------------
# Porte d'entree des factures invalides
# ---------------------------------------------------------------------------
def _message_pydantic(exc: ValidationError) -> str:
    return " ; ".join(
        f"{'.'.join(str(partie) for partie in erreur['loc'])} : {erreur['msg']}"
        for erreur in exc.errors()
    )


def test_chaque_invalide_est_rejete_en_nommant_le_champ(
    lot: list[CasLot], referentiels: dict
) -> None:
    """Chaque cas invalide doit etre refuse par la porte annoncee.

    Trois portes existent, dans cet ordre :

    1. le schema `InvoiceSubmission` (bornes, quantite, types) ;
    2. la validation metier de l'inference (dates, coherence des montants) ;
    3. la verification des references d'api-core (`core.acte`).

    Un code d'acte inconnu franchit les deux premieres : c'est api-core qui le
    refuse. Le test le prouve en verifiant que le code est absent du
    referentiel, ce qui rend le rejet inevitable.
    """
    connus = set(referentiels["actes"]) | set(referentiels["medicaments"])

    for cas in lot:
        if cas.valide:
            continue
        champ = cas.champ_attendu
        try:
            invoice = InvoiceSubmission.model_validate(cas.payload)
        except ValidationError as exc:
            assert champ in _message_pydantic(exc), cas.facture_id
            continue

        try:
            validate_invoice(invoice, now=MAINTENANT)
        except InvalidInvoiceError as exc:
            assert champ in exc.message, cas.facture_id
            continue

        # Ni le schema ni la validation metier ne rejettent : la seule porte
        # restante est la verification de reference d'api-core.
        assert champ == "lignes.0.code_acte", cas.facture_id
        assert cas.payload["lignes"][0]["code_acte"] not in connus, cas.facture_id


# ---------------------------------------------------------------------------
# Chargement : le format d'echange est verifie tot
# ---------------------------------------------------------------------------
def _document_minimal() -> dict:
    return {
        "version": 1,
        "factures": [
            {
                "cas_attendu": "valide",
                "attendu": {"alerte": False},
                "facture_id": "FAC-JURY-999",
                "assure_pseudonyme": "assr_test",
                "prestataire_id": "PRE-00001",
                "date_facture": "2026-10-15T12:00:00+03:00",
                "montant_total": 2000.0,
                "lignes": [
                    {
                        "code_acte": "MED-PARA500",
                        "quantite": 1,
                        "montant_unitaire": 2000.0,
                        "date_acte": "2026-10-15T10:00:00+03:00",
                    }
                ],
            }
        ],
    }


def _ecrire(tmp_path: Path, document: object) -> Path:
    chemin = tmp_path / "lot.json"
    chemin.write_text(json.dumps(document), encoding="utf-8")
    return chemin


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(lambda d: d.update(version=2), id="version-inconnue"),
        pytest.param(lambda d: d.update(factures=[]), id="lot-vide"),
        pytest.param(lambda d: d["factures"][0].pop("cas_attendu"), id="meta-absente"),
        pytest.param(lambda d: d["factures"][0].update(cas_attendu="peut-etre"), id="cas-inconnu"),
        pytest.param(
            lambda d: d["factures"].append(dict(d["factures"][0])), id="identifiant-double"
        ),
        pytest.param(
            lambda d: d["factures"][0].update(attendu={"motif": "sans verdict"}),
            id="verdict-absent",
        ),
        pytest.param(
            lambda d: d["factures"][0].update(
                cas_attendu="invalide:montant_total", attendu={"motif": "sans champ"}
            ),
            id="champ-absent",
        ),
    ],
)
def test_charger_lot_refuse_un_document_mal_forme(tmp_path: Path, mutation) -> None:
    document = _document_minimal()
    mutation(document)

    with pytest.raises(LotInvalideError):
        charger_lot(_ecrire(tmp_path, document))


def test_charger_lot_refuse_un_fichier_absent(tmp_path: Path) -> None:
    with pytest.raises(LotInvalideError):
        charger_lot(tmp_path / "absent.json")


def test_charger_lot_refuse_une_racine_non_objet(tmp_path: Path) -> None:
    with pytest.raises(LotInvalideError):
        charger_lot(_ecrire(tmp_path, []))


# ---------------------------------------------------------------------------
# Client : un 202 ne suffit pas, il faut le resultat attendu
# ---------------------------------------------------------------------------
def _cas(cas_attendu: str, alerte: bool = False) -> CasLot:
    attendu = {"alerte": alerte} if cas_attendu == "valide" else {"champ": "montant_total"}
    return CasLot(
        facture_id="FAC-JURY-999",
        cas_attendu=cas_attendu,
        attendu=attendu,
        payload={"facture_id": "FAC-JURY-999"},
    )


def _client(reponse: httpx.Response) -> httpx.Client:
    return httpx.Client(
        base_url="http://test",
        transport=httpx.MockTransport(lambda request: reponse),
    )


def _acceptee(alerte: bool) -> httpx.Response:
    return httpx.Response(
        202,
        json={
            "facture_id": "FAC-JURY-999",
            "score_fraude": 0.91 if alerte else 0.05,
            "is_fraud": alerte,
            "seuil_applique": 0.2876,
            "model_version": "1",
        },
    )


def test_une_valide_alerte_comme_attendu_est_conforme() -> None:
    resultat = soumettre(_client(_acceptee(True)), _cas("valide", alerte=True))

    assert resultat.conforme
    assert resultat.statut == "notee"
    assert resultat.alerte is True


def test_une_valide_sans_l_alerte_attendue_est_un_ecart() -> None:
    resultat = soumettre(_client(_acceptee(False)), _cas("valide", alerte=True))

    assert not resultat.conforme
    assert "alerte attendue" in resultat.message


def test_un_invalide_rejete_en_nommant_le_champ_est_conforme() -> None:
    reponse = httpx.Response(
        422,
        json={"message": "Facture invalide - montant_total : incoherent"},
    )

    resultat = soumettre(_client(reponse), _cas("invalide:montant_total"))

    assert resultat.conforme
    assert resultat.statut == "rejetee"


def test_un_invalide_rejete_sans_le_bon_champ_est_un_ecart() -> None:
    reponse = httpx.Response(
        422,
        json={"message": "Facture invalide - prestataire_id : valeur inconnue"},
    )

    resultat = soumettre(_client(reponse), _cas("invalide:montant_total"))

    assert not resultat.conforme


def test_un_invalide_accepte_est_un_ecart() -> None:
    resultat = soumettre(_client(_acceptee(False)), _cas("invalide:montant_total"))

    assert not resultat.conforme
    assert resultat.statut == "acceptee"


def test_une_valide_rejetee_est_un_ecart() -> None:
    reponse = httpx.Response(422, json={"message": "Facture invalide - lignes.0.quantite"})

    resultat = soumettre(_client(reponse), _cas("valide"))

    assert not resultat.conforme
    assert resultat.statut == "rejetee"


def test_une_panne_http_est_un_echec() -> None:
    resultat = soumettre(_client(httpx.Response(500, text="boom")), _cas("valide"))

    assert not resultat.conforme
    assert resultat.statut == "echec"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def test_executer_ignore_une_facture_deja_notee_sans_appeler_l_api() -> None:
    appels: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        appels.append(request)
        return _acceptee(False)

    client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))
    cas = _cas("valide")

    resultats = executer(client, [cas], deja_notees={cas.facture_id})

    assert [r.statut for r in resultats] == ["ignoree"]
    assert resultats[0].conforme
    assert appels == []


def test_executer_rejoue_une_facture_ignoree_avec_forcer() -> None:
    appels: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        appels.append(request)
        return _acceptee(False)

    client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))
    cas = _cas("valide")

    resultats = executer(client, [cas], forcer=True, deja_notees={cas.facture_id})

    assert [r.statut for r in resultats] == ["notee"]
    assert len(appels) == 1


def test_le_rapport_est_faux_des_qu_un_cas_derive() -> None:
    lignes: list[str] = []
    resultats = executer(
        _client(_acceptee(True)),
        [_cas("valide", alerte=True), _cas("invalide:montant_total")],
        deja_notees=set(),
    )

    assert not rapport(resultats, flux=lignes.append)
    assert any("ECARTS" in ligne for ligne in lignes)
