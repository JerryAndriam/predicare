"""Import multipart de factures PDF : un appel HTTP pour tout le lot.

Ces tests tournent sans PostgreSQL et sans pile demarree. Le module
d'extraction `predicare.pdf_facture` est remplace par un faux module : le
contrat est verrouille ici, l'integration reelle est verifiee par
`tests/test_pdf_facture.py` quand le module est livre.

Ce qui est verrouille :

- 1..20 fichiers passent en UNE requete, avec le nom de chaque fichier
  conserve dans le bilan ;
- un fichier rejete (facture invalide) ou illisible (PDF scanne) n'arrete
  pas les suivants ;
- le champ fautif est remonte, et un PDF scanne produit un message distinct ;
- le `prestataire_id` du formulaire prime sur celui du PDF ;
- 0 fichier et plus de 100 fichiers sont refuses avant tout traitement.
"""

from __future__ import annotations

import sys
import types
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from predicare.auth import TokenPayload
from predicare.dependencies import get_current_user
from predicare.errors import InvalidInvoiceError
from predicare.http import register_exception_handlers
from predicare.rbac import Role
from predicare_core_api.billing import router as billing
from predicare_core_api.billing.router import SubmitAccepted

# ---------------------------------------------------------------------------
# Faux module d'extraction, conforme au contrat de `predicare.pdf_facture`
# ---------------------------------------------------------------------------


class FactureIllisibleError(ValueError):
    """Le fichier ne peut pas etre lu comme une facture."""


class PdfSansTexteError(FactureIllisibleError):
    """PDF scanne : aucune couche texte exploitable."""


class ChampIntrouvableError(FactureIllisibleError):
    """Une ancre de libelle manque dans le document."""


@dataclass(frozen=True)
class FactureExtraite:
    reference: str
    assure: str
    prestataire: str
    date_facture: str
    lignes: tuple[dict, ...]
    montant_total: float
    source: str


def _extraire_facture(donnees: bytes, *, nom: str = "") -> FactureExtraite:
    """Extrait une facture synthetique, ou simule un PDF illisible."""
    if b"SCAN" in donnees:
        raise PdfSansTexteError("PDF sans couche texte : OCR requis")
    if b"BAD" in donnees:
        raise FactureIllisibleError("En-tete de facture introuvable")

    reference = "FAC-" + "".join(c for c in nom.upper() if c.isalnum())[-12:]
    return FactureExtraite(
        reference=reference,
        assure="ASS-00001",
        prestataire="PRE-00001",
        date_facture="2026-10-20T10:00:00+00:00",
        lignes=(
            {
                "code_acte": "ACT-BRUT",
                "quantite": 1,
                "montant_unitaire": 100.0,
                "date_acte": "2026-10-20T09:00:00+00:00",
            },
        ),
        montant_total=100.0,
        source=nom,
    )


def _payload_de(
    extraite: FactureExtraite,
    *,
    assure_pseudonyme: str | None = None,
    prestataire_id: str | None = None,
) -> dict:
    """Construit le payload attendu par `/factures/soumettre`."""
    return {
        "facture_id": extraite.reference,
        "assure_pseudonyme": assure_pseudonyme or extraite.assure,
        "prestataire_id": prestataire_id or extraite.prestataire,
        "date_facture": extraite.date_facture,
        "montant_total": extraite.montant_total,
        "lignes": [dict(ligne) for ligne in extraite.lignes],
    }


def _resoudre_assure(session: Any, valeur: str) -> str:
    return "assr_test"


def _resoudre_prestataire(session: Any, valeur: str, *, ville: str | None = None) -> str:
    return valeur


def _resoudre_acte(session: Any, valeur: str) -> str:
    return "ACT-001"


def _est_pdf(donnees: bytes) -> bool:
    return donnees.startswith(b"%PDF-")


def _faux_module() -> types.ModuleType:
    """Module factice installe dans `sys.modules` avant l'appel de la route."""
    module = types.ModuleType("predicare.pdf_facture")
    module.FactureIllisibleError = FactureIllisibleError
    module.PdfSansTexteError = PdfSansTexteError
    module.ChampIntrouvableError = ChampIntrouvableError
    module.FactureExtraite = FactureExtraite
    module.est_pdf = _est_pdf
    module.extraire_facture = _extraire_facture
    module.payload_de = _payload_de
    module.resoudre_assure = _resoudre_assure
    module.resoudre_prestataire = _resoudre_prestataire
    module.resoudre_acte = _resoudre_acte
    return module


# ---------------------------------------------------------------------------
# Fixtures : application minimale, jeton admin, faux module, audit
# ---------------------------------------------------------------------------


def _admin() -> TokenPayload:
    return TokenPayload(
        subject="1",
        role=Role.ADMINISTRATEUR,
        insured_id=None,
        expires_at=datetime.now(UTC),
    )


@pytest.fixture
def pdf_facture(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Installe le faux module, meme si le vrai existe deja."""
    module = _faux_module()
    monkeypatch.setitem(sys.modules, "predicare.pdf_facture", module)
    import predicare

    monkeypatch.setattr(predicare, "pdf_facture", module, raising=False)
    return module


@pytest.fixture
def audit(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Capture les lignes d'audit sans toucher a la base."""
    lignes: list[dict] = []

    def _journaliser(session: Any, **champs: Any) -> None:
        lignes.append(champs)

    monkeypatch.setattr(billing, "journaliser", _journaliser)
    return lignes


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch, pdf_facture: types.ModuleType, audit: list[dict]
) -> TestClient:
    """Application minimale : la route d'import, un admin, aucune base."""
    monkeypatch.setattr(billing, "session_scope", lambda: nullcontext(None))

    app = FastAPI()
    app.state.service = "test"
    register_exception_handlers(app)
    app.include_router(billing.router)
    app.dependency_overrides[get_current_user] = _admin

    with TestClient(app) as test_client:
        yield test_client


def _fichiers(noms: list[str], contenu: bytes = b"%PDF-1.4 facture") -> list[tuple]:
    return [("fichiers", (nom, contenu, "application/pdf")) for nom in noms]


def _succes(payload: dict) -> SubmitAccepted:
    return SubmitAccepted(
        facture_id=str(payload["facture_id"]),
        score_fraude=0.4213,
        is_fraud=True,
        seuil_applique=0.2876,
    )


def _traiter_avec_rejets(payload: dict, request: Any, user: TokenPayload) -> SubmitAccepted:
    """Rejette les 5 derniers fichiers du lot de 20, note les autres."""
    reference = str(payload["facture_id"])
    if any(f"{rang:02d}" in reference for rang in range(16, 21)):
        raise InvalidInvoiceError(
            "Facture invalide - lignes.0.code_acte : valeur inconnue (ACTE-INCONNU)",
            details={"champ": "lignes.0.code_acte"},
        )
    return _succes(payload)


# ---------------------------------------------------------------------------
# Lot complet
# ---------------------------------------------------------------------------


def test_vingt_pdf_dont_cinq_rejetees_en_un_seul_appel(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    audit: list[dict],
) -> None:
    monkeypatch.setattr(billing, "_traiter_facture", _traiter_avec_rejets)
    noms = [f"facture_{rang:02d}.pdf" for rang in range(1, 21)]

    reponse = client.post("/factures/import", files=_fichiers(noms))

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["total"] == 20
    assert corps["noted"] == 15
    assert corps["rejected"] == 5
    assert corps["failed"] == 0
    assert [item["fichier"] for item in corps["items"]] == noms

    rejetes = [item for item in corps["items"] if item["statut"] == "rejetee"]
    assert len(rejetes) == 5
    assert all(item["champ"] == "lignes.0.code_acte" for item in rejetes)
    assert all(item["reference"] is not None for item in rejetes)

    notes = [item for item in corps["items"] if item["statut"] == "notee"]
    assert all(item["score_fraude"] == pytest.approx(0.4213) for item in notes)
    assert all(item["seuil_applique"] == pytest.approx(0.2876) for item in notes)

    # Une ligne d'audit par fichier, avec le nom source et le statut.
    assert len(audit) == 20
    assert {ligne["action"] for ligne in audit} == {"facture_importee"}
    assert {ligne["details"]["statut"] for ligne in audit} == {"notee", "rejetee"}
    assert {ligne["details"]["fichier"] for ligne in audit} == set(noms)


def test_un_pdf_scanne_echoue_sans_interrompre_les_autres(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(billing, "_traiter_facture", lambda p, r, u: _succes(p))
    fichiers = [
        ("fichiers", ("scanne.pdf", b"%PDF-1.4 SCAN", "application/pdf")),
        ("fichiers", ("illisible.pdf", b"%PDF-1.4 BAD", "application/pdf")),
        ("fichiers", ("lisible.pdf", b"%PDF-1.4 facture", "application/pdf")),
    ]

    reponse = client.post("/factures/import", files=fichiers)

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["total"] == 3
    assert corps["failed"] == 2
    assert corps["noted"] == 1
    assert corps["rejected"] == 0

    scanne, illisible, lisible = corps["items"]
    assert scanne["statut"] == "echec"
    assert "OCR requis" in scanne["message"]
    assert illisible["statut"] == "echec"
    assert illisible["message"] == "En-tete de facture introuvable"
    assert lisible["statut"] == "notee"
    assert lisible["fichier"] == "lisible.pdf"


def test_un_champ_introuvable_est_un_rejet_metier(
    client: TestClient,
    pdf_facture: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _extraire_incomplet(donnees: bytes, *, nom: str = "") -> FactureExtraite:
        raise ChampIntrouvableError(f"Champ introuvable dans le PDF ({nom}) : lignes.0.code_acte")

    monkeypatch.setattr(pdf_facture, "extraire_facture", _extraire_incomplet)

    reponse = client.post("/factures/import", files=_fichiers(["incomplet.pdf"]))

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["rejected"] == 1
    assert corps["failed"] == 0
    item = corps["items"][0]
    assert item["statut"] == "rejetee"
    assert item["champ"] == "lignes.0.code_acte"
    assert item["fichier"] == "incomplet.pdf"


def test_le_prestataire_du_formulaire_prime_et_les_actes_sont_resolus(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captures: list[dict] = []

    def _capturer(payload: dict, request: Any, user: TokenPayload) -> SubmitAccepted:
        captures.append(payload)
        return _succes(payload)

    monkeypatch.setattr(billing, "_traiter_facture", _capturer)

    reponse = client.post(
        "/factures/import",
        files=_fichiers(["facture.pdf"]),
        data={"prestataire_id": "PRE-IMPOSE"},
    )

    assert reponse.status_code == 200
    assert len(captures) == 1
    payload = captures[0]
    assert payload["prestataire_id"] == "PRE-IMPOSE"
    assert payload["assure_pseudonyme"] == "assr_test"
    assert payload["lignes"][0]["code_acte"] == "ACT-001"


# ---------------------------------------------------------------------------
# Bornes du lot
# ---------------------------------------------------------------------------


def test_zero_fichier_est_refuse(client: TestClient) -> None:
    reponse = client.post("/factures/import", files=[])

    assert reponse.status_code == 422


def test_plus_de_cent_fichiers_est_refuse(client: TestClient) -> None:
    noms = [f"facture_{rang:03d}.pdf" for rang in range(1, 102)]

    reponse = client.post("/factures/import", files=_fichiers(noms))

    assert reponse.status_code == 413
    assert reponse.json()["code"] == "too_many_files"
