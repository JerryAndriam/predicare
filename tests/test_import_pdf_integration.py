"""Le raccord reel : PDF -> `predicare.pdf_facture` -> route `/factures/import`.

`tests/test_pdf_facture.py` verrouille l'extraction seule, et
`tests/test_import_pdf_api.py` la route avec un faux module. Ce fichier
verifie le JOINT : de vrais octets PDF traversent le VRAI extracteur puis le
VRAI routeur.

Seuls deux points sont remplaces, parce qu'ils demandent une base et un
service :

* `session_scope` -> un contexte vide (les resolutions sont substituees) ;
* `_traiter_facture` -> une notation synthetique (l'inference est un autre
  service).

Tout le reste est le chemin de production : detection `%PDF-`, extraction par
ancres de libelles, reference deterministe, payload `InvoiceSubmission`,
isolation par fichier et mise en forme du bilan.
"""

from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from predicare.auth import TokenPayload
from predicare.dependencies import get_current_user
from predicare.http import register_exception_handlers
from predicare.rbac import Role
from predicare_core_api.billing import router as billing
from predicare_core_api.billing.router import SubmitAccepted

# ---------------------------------------------------------------------------
# Fabrique de PDF en memoire (meme technique que tests/test_pdf_facture.py)
# ---------------------------------------------------------------------------


def _chaine_pdf(texte: str) -> str:
    morceaux: list[str] = []
    for caractere in texte:
        code = ord(caractere)
        if caractere in "()\\":
            morceaux.append("\\" + caractere)
        elif 32 <= code < 127:
            morceaux.append(caractere)
        elif code < 256:
            morceaux.append(f"\\{code:03o}")
        else:
            morceaux.append("?")
    return "(" + "".join(morceaux) + ")"


def _pdf(lignes: list[str]) -> bytes:
    ecrivain = PdfWriter()
    page = ecrivain.add_blank_page(width=595, height=842)
    police = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
            NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
        }
    )
    reference_police = ecrivain._add_object(police)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): reference_police})}
    )

    contenu = ["BT", "/F1 10 Tf", "50 800 Td", "14 TL"]
    for ligne in lignes:
        contenu.append(f"{_chaine_pdf(ligne)} Tj")
        contenu.append("T*")
    contenu.append("ET")

    flux = DecodedStreamObject()
    flux.set_data("\n".join(contenu).encode("latin-1"))
    page[NameObject("/Contents")] = ecrivain._add_object(flux)

    tampon = BytesIO()
    ecrivain.write(tampon)
    return tampon.getvalue()


FACTURE_VALIDE = _pdf(
    [
        "FACTURE",
        "N° facture : FAC-PDF-001",
        "Patient : assr_Wv7VAUFiUXieeWwChWmGXB",
        "Prestataire : PRE-00155",
        "Date de facture : 20/10/2026",
        "Code acte : DENT-CONS",
        "Quantité : 1",
        "Prix unitaire : 19 000 Ar",
        "Montant total : 19 000 Ar",
    ]
)

#: Le champ « Code acte » manque : la facture est lisible mais incomplete.
FACTURE_SANS_ACTE = _pdf(
    [
        "FACTURE",
        "Patient : assr_Wv7VAUFiUXieeWwChWmGXB",
        "Prestataire : PRE-00155",
        "Date de facture : 20/10/2026",
        "Montant total : 19 000 Ar",
    ]
)

#: Une page blanche : aucune couche texte, donc un scan.
PDF_SCAN = _pdf([])

#: Un fichier qui n'est pas un PDF du tout.
NON_PDF = b"<?xml version='1.0'?><facture/>"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _admin() -> TokenPayload:
    return TokenPayload(
        subject="1",
        role=Role.ADMINISTRATEUR,
        insured_id=None,
        expires_at=datetime.now(UTC),
    )


def _succes(payload: dict) -> SubmitAccepted:
    return SubmitAccepted(
        facture_id=str(payload["facture_id"]),
        score_fraude=0.4213,
        is_fraud=True,
        seuil_applique=0.2876,
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Le vrai extracteur et le vrai routeur, sans base ni inference."""
    import predicare.pdf_facture as pdf_facture

    monkeypatch.setattr(billing, "session_scope", lambda: nullcontext(None))
    monkeypatch.setattr(pdf_facture, "resoudre_assure", lambda session, valeur: valeur)
    monkeypatch.setattr(pdf_facture, "resoudre_prestataire", lambda session, valeur, **_: valeur)
    monkeypatch.setattr(pdf_facture, "resoudre_acte", lambda session, valeur: valeur)
    monkeypatch.setattr(
        billing, "_traiter_facture", lambda payload, request, user: _succes(payload)
    )
    monkeypatch.setattr(billing, "journaliser", lambda session, **champs: None)

    app = FastAPI()
    app.state.service = "test"
    register_exception_handlers(app)
    app.include_router(billing.router)
    app.dependency_overrides[get_current_user] = _admin

    with TestClient(app) as test_client:
        yield test_client


def _fichiers(*elements: tuple[str, bytes]) -> list[tuple]:
    return [("fichiers", (nom, contenu, "application/pdf")) for nom, contenu in elements]


# ---------------------------------------------------------------------------
# Le joint
# ---------------------------------------------------------------------------


def test_un_pdf_reel_traverse_l_extraction_et_la_route(client: TestClient) -> None:
    """Un PDF texte est extrait, normalise et note, sans faux module."""
    reponse = client.post("/factures/import", files=_fichiers(("facture_001.pdf", FACTURE_VALIDE)))

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["total"] == 1
    assert corps["noted"] == 1
    assert corps["rejected"] == 0
    item = corps["items"][0]
    assert item["fichier"] == "facture_001.pdf"
    assert item["statut"] == "notee"
    # La reference est deterministe : elle derive des octets, pas du hasard.
    assert item["reference"].startswith("FAC-")
    assert len(item["reference"]) == len("FAC-") + 12
    assert item["seuil_applique"] == 0.2876


def test_la_reference_est_la_meme_au_rejeu(client: TestClient) -> None:
    """Le meme fichier rejoue garde la meme reference (idempotence du depot)."""
    premiere = client.post("/factures/import", files=_fichiers(("a.pdf", FACTURE_VALIDE)))
    seconde = client.post("/factures/import", files=_fichiers(("b.pdf", FACTURE_VALIDE)))

    assert premiere.json()["items"][0]["reference"] == seconde.json()["items"][0]["reference"], (
        "deux envois du meme contenu doivent produire la meme reference"
    )


def test_le_bilan_separe_les_rejets_des_echecs(client: TestClient) -> None:
    """Rejet metier, scan et fichier non-PDF sont trois statuts distincts."""
    reponse = client.post(
        "/factures/import",
        files=_fichiers(
            ("valide.pdf", FACTURE_VALIDE),
            ("incomplete.pdf", FACTURE_SANS_ACTE),
            ("scan.pdf", PDF_SCAN),
            ("autre.csv", NON_PDF),
        ),
    )

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["total"] == 4
    assert corps["noted"] == 1
    # Champ obligatoire manquant : c'est un rejet, la facture etant lisible.
    assert corps["rejected"] == 1
    # PDF scanne et fichier non-PDF : echecs de lecture.
    assert corps["failed"] == 2

    par_fichier = {item["fichier"]: item for item in corps["items"]}
    assert par_fichier["incomplete.pdf"]["statut"] == "rejetee"
    assert par_fichier["incomplete.pdf"]["champ"] == "lignes.0.code_acte"
    assert par_fichier["scan.pdf"]["statut"] == "echec"
    assert "OCR" in par_fichier["scan.pdf"]["message"]
    assert par_fichier["autre.csv"]["statut"] == "echec"
    assert "PDF" in par_fichier["autre.csv"]["message"]
    # Le fichier valide a bien ete traite malgre les trois autres.
    assert par_fichier["valide.pdf"]["statut"] == "notee"


def test_le_prestataire_impose_prime_sur_le_pdf(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un administrateur peut imposer un prestataire a tout le lot."""
    import predicare.pdf_facture as pdf_facture

    vus: list[dict[str, Any]] = []

    def _traiter(payload: dict, request: Any, user: TokenPayload) -> SubmitAccepted:
        vus.append(payload)
        return _succes(payload)

    monkeypatch.setattr(billing, "_traiter_facture", _traiter)
    monkeypatch.setattr(pdf_facture, "resoudre_prestataire", lambda session, valeur, **_: valeur)

    reponse = client.post(
        "/factures/import",
        files=_fichiers(("facture.pdf", FACTURE_VALIDE)),
        data={"prestataire_id": "PRE-00002"},
    )

    assert reponse.status_code == 200, reponse.text
    assert vus[0]["prestataire_id"] == "PRE-00002"
