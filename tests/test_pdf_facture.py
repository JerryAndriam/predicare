"""Extraction des factures PDF : ancres de libelles, pas colonnes.

Ces tests ne touchent ni PostgreSQL ni reseau. Les PDF sont fabriques EN
MEMOIRE avec `pypdf` : une page blanche, une police Helvetica et un flux de
contenu qui ecrit une ligne par libelle. C'est exactement la forme que
`pypdf` rend a la lecture (les tableaux sont aplatis), donc le test verrouille
le vrai comportement de l'extracteur, pas une maquette complaisante.

Trois gabarits de mise en page sont couverts :

1. libelle et valeur sur la meme ligne, separes par `:` ;
2. libelle seul, valeur a la ligne suivante ;
3. plusieurs actes dans le meme document (une ligne par occurrence).

Les resolutions en base utilisent une fausse session : aucun test ne doit
exiger une base joignable.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from predicare.crypto import pseudonymize
from predicare.pdf_facture import (
    ChampIntrouvableError,
    DocumentNonFactureError,
    FactureIllisibleError,
    PdfSansTexteError,
    detecter_scan,
    est_pdf,
    extraire_facture,
    extraire_texte,
    normaliser_date,
    normaliser_montant,
    payload_de,
    reference_deterministe,
    resoudre_acte,
    resoudre_assure,
    resoudre_prestataire,
    resoudre_prestataire_parmi,
)


# ---------------------------------------------------------------------------
# Fabrique de PDF en memoire
# ---------------------------------------------------------------------------
def _chaine_pdf(texte: str) -> str:
    """Une chaine littérale PDF, accents compris.

    La police declare `WinAnsiEncoding` : les octets 0xE9 etc. sont donc lus
    comme des accents français par `pypdf`, pas comme du PDFDocEncoding.
    """
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
    """Un PDF texte d'une page, une ligne par element."""
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


def _pdf_tableau(
    lignes: list[list[tuple[int, str]]],
    *,
    y_depart: int = 800,
    interligne: int = 14,
) -> bytes:
    """Un PDF texte dont les cellules sont placees a des abscisses explicites."""
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

    contenu = ["BT", "/F1 9 Tf"]
    y = y_depart
    for cellules in lignes:
        for x, texte in cellules:
            contenu.append(f"1 0 0 1 {x} {y} Tm")
            contenu.append(f"{_chaine_pdf(texte)} Tj")
        y -= interligne
    contenu.append("ET")

    flux = DecodedStreamObject()
    flux.set_data("\n".join(contenu).encode("latin-1"))
    page[NameObject("/Contents")] = ecrivain._add_object(flux)

    tampon = BytesIO()
    ecrivain.write(tampon)
    return tampon.getvalue()


#: Gabarit 1 : libelle et valeur sur la meme ligne, separes par `:`.
GABARIT_COLON = _pdf(
    [
        "FACTURE",
        "N° facture : FAC-PDF-001",
        "Patient : assr_Wv7VAUFiUXieeWwChWmGXB",
        "Prestataire : PRE-00155",
        "Date de facture : 20/10/2026",
        "Code acte : DENT-CONS",
        "Quantité : 1",
        "P.U. : 19 000 Ar",
        "Total : 19 000 Ar",
    ]
)

#: Gabarit 2 : libelle seul, valeur a la ligne suivante.
GABARIT_LIGNE_SUIVANTE = _pdf(
    [
        "Référence",
        "FAC-PDF-002",
        "Assuré",
        "ASS-9CAA1484E0",
        "Établissement",
        "PRE-00155",
        "Date",
        "20 octobre 2026",
        "Code acte",
        "DENT-EXTRACT",
        "Quantité",
        "2",
        "Prix unitaire",
        "34 000 MGA",
        "Net à payer",
        "68 000 MGA",
    ]
)

#: Gabarit 3 : deux actes, donc deux lignes de facture.
GABARIT_MULTI_ACTES = _pdf(
    [
        "N° de facture: FAC-PDF-003",
        "Bénéficiaire: assr_Wv7VAUFiUXieeWwChWmGXB",
        "Pharmacie: PRE-00155",
        "Date des soins: 2026-10-20",
        "Code acte: DENT-CONS",
        "Qté: 1",
        "Montant unitaire: 19 000 Ar",
        "Code acte: DENT-EXTRACT",
        "Qté: 2",
        "Montant unitaire: 34 000 MGA",
        "Total TTC: 87 000 Ar",
    ]
)


# ---------------------------------------------------------------------------
# Lecture et detection
# ---------------------------------------------------------------------------
def test_est_pdf_tolere_un_bom_et_des_espaces() -> None:
    assert est_pdf(GABARIT_COLON)
    assert est_pdf(b"\xef\xbb\xbf  \n" + GABARIT_COLON)
    assert not est_pdf(b"Ceci n'est pas un PDF")
    assert not est_pdf(b"")


def test_extraire_texte_conserve_les_lignes_et_les_accents() -> None:
    texte = extraire_texte(GABARIT_COLON)

    assert "N° facture : FAC-PDF-001" in texte
    assert "Quantité" in texte
    assert detecter_scan(texte) is False


def test_un_texte_trop_court_est_un_scan() -> None:
    assert detecter_scan("") is True
    assert detecter_scan("Page 1") is True
    assert detecter_scan("   \n\t ") is True
    assert detecter_scan("Facture n° 12 du 20/10/2026") is False


def test_un_fichier_non_pdf_est_refuse() -> None:
    with pytest.raises(FactureIllisibleError):
        extraire_facture(b"PK\x03\x04 contenu zip", nom="facture.pdf")


def test_une_page_vide_est_un_scan_sans_couche_texte() -> None:
    ecrivain = PdfWriter()
    ecrivain.add_blank_page(width=595, height=842)
    tampon = BytesIO()
    ecrivain.write(tampon)

    with pytest.raises(PdfSansTexteError, match="OCR requis"):
        extraire_facture(tampon.getvalue(), nom="scan.pdf")


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("brut", "attendu"),
    [
        ("20 000 Ar", 20000.0),
        ("39000", 39000.0),
        ("39 000,50 MGA", 39000.50),
        ("1 234.56", 1234.56),
        ("20\u00a0000\u00a0Ar", 20000.0),
        ("1\u202f234,56", 1234.56),
        ("  0  ", 0.0),
        ("(1 500)", -1500.0),
    ],
)
def test_normaliser_montant(brut: str, attendu: float) -> None:
    assert normaliser_montant(brut) == pytest.approx(attendu)


def test_normaliser_montant_refuse_le_vide() -> None:
    with pytest.raises(ValueError):
        normaliser_montant("Ar")


@pytest.mark.parametrize(
    ("brut", "attendu"),
    [
        ("20/10/2026", "2026-10-20T00:00:00"),
        ("2026-10-20", "2026-10-20T00:00:00"),
        ("20 octobre 2026", "2026-10-20T00:00:00"),
        ("1er janvier 2026", "2026-01-01T00:00:00"),
        ("20-10-2026", "2026-10-20T00:00:00"),
    ],
)
def test_normaliser_date(brut: str, attendu: str) -> None:
    assert normaliser_date(brut) == attendu


@pytest.mark.parametrize("brut", ["pas une date", "32/13/2026", ""])
def test_normaliser_date_refuse_une_date_illisible(brut: str) -> None:
    with pytest.raises(ValueError):
        normaliser_date(brut)


# ---------------------------------------------------------------------------
# Extraction nominale
# ---------------------------------------------------------------------------
def test_extraction_libelles_suivis_de_deux_points() -> None:
    facture = extraire_facture(GABARIT_COLON, nom="facture_001.pdf")

    assert facture.assure == "assr_Wv7VAUFiUXieeWwChWmGXB"
    assert facture.prestataire == "PRE-00155"
    assert facture.date_facture == "2026-10-20T00:00:00"
    assert facture.montant_total == 19000.0
    assert facture.source == "facture_001.pdf"
    assert facture.reference.startswith("FAC-")
    assert len(facture.lignes) == 1
    assert facture.lignes[0] == {
        "code_acte": "DENT-CONS",
        "quantite": 1,
        "montant_unitaire": 19000.0,
        "date_acte": "2026-10-20T00:00:00",
    }


def test_extraction_valeur_a_la_ligne_suivante() -> None:
    facture = extraire_facture(GABARIT_LIGNE_SUIVANTE, nom="facture_002.pdf")

    assert facture.assure == "ASS-9CAA1484E0"
    assert facture.prestataire == "PRE-00155"
    assert facture.date_facture == "2026-10-20T00:00:00"
    assert facture.montant_total == 68000.0
    assert facture.lignes == (
        {
            "code_acte": "DENT-EXTRACT",
            "quantite": 2,
            "montant_unitaire": 34000.0,
            "date_acte": "2026-10-20T00:00:00",
        },
    )


def test_l_enseigne_en_tete_ne_devient_pas_le_prestataire() -> None:
    """« CABINET MEDICAL ESPOIR » est une en-tete, pas la valeur du champ.

    Constat sur un PDF reel : l'ancre « Cabinet » matchait l'en-tete et la
    facture etait rejetee sur `prestataire_id : valeur inconnue (MEDICAL
    ESPOIR)`, alors que la ligne « Prestataire : PRE-00062 » etait juste en
    dessous.
    """
    avec_enseigne = _pdf(
        [
            "CABINET MEDICAL ESPOIR",
            "N° facture : FAC-PDF-001",
            "Patient : assr_Wv7VAUFiUXieeWwChWmGXB",
            "Prestataire : PRE-00062",
            "Date de facture : 21/10/2026",
            "Code acte : CONS-GEN",
            "Quantité : 1",
            "Prix unitaire : 25 000 Ar",
            "Montant total : 25 000 Ar",
        ]
    )

    facture = extraire_facture(avec_enseigne, nom="enseigne.pdf")

    assert facture.prestataire == "PRE-00062"
    assert facture.assure == "assr_Wv7VAUFiUXieeWwChWmGXB"
    assert facture.lignes[0]["code_acte"] == "CONS-GEN"


def test_une_pharmacie_sans_ligne_prestataire_reste_lisible() -> None:
    """Sans ligne « Prestataire », l'enseigne generique est le dernier recours."""
    sans_ligne = _pdf(
        [
            "Pharmacie Vatolampy",
            "Patient : assr_Wv7VAUFiUXieeWwChWmGXB",
            "Date de facture : 21/10/2026",
            "Code acte : MED-PARA500",
            "Quantité : 1",
            "Prix unitaire : 5 000 Ar",
            "Montant total : 5 000 Ar",
        ]
    )

    facture = extraire_facture(sans_ligne, nom="pharmacie.pdf")

    assert facture.prestataire == "Pharmacie Vatolampy"


def test_extraction_plusieurs_actes() -> None:
    facture = extraire_facture(GABARIT_MULTI_ACTES, nom="facture_003.pdf")

    assert [ligne["code_acte"] for ligne in facture.lignes] == ["DENT-CONS", "DENT-EXTRACT"]
    assert [ligne["quantite"] for ligne in facture.lignes] == [1, 2]
    assert [ligne["montant_unitaire"] for ligne in facture.lignes] == [19000.0, 34000.0]
    assert facture.montant_total == 87000.0


def test_le_total_absent_est_calcule_depuis_les_lignes() -> None:
    sans_total = _pdf(
        [
            "Patient : assr_Wv7VAUFiUXieeWwChWmGXB",
            "Prestataire : PRE-00155",
            "Date facture : 20/10/2026",
            "Code acte : DENT-EXTRACT",
            "Quantité : 2",
            "Prix unitaire : 34 000 MGA",
        ]
    )
    facture = extraire_facture(sans_total, nom="sans_total.pdf")

    assert facture.montant_total == 68000.0


def test_un_total_different_de_la_somme_est_conserve() -> None:
    """Le total du document fait foi ; l'API rejette l'incoherence, pas nous."""
    incoherent = _pdf(
        [
            "Patient : assr_Wv7VAUFiUXieeWwChWmGXB",
            "Prestataire : PRE-00155",
            "Date facture : 20/10/2026",
            "Code acte : DENT-EXTRACT",
            "Quantité : 2",
            "Prix unitaire : 34 000 MGA",
            "Total : 70 000 MGA",
        ]
    )
    facture = extraire_facture(incoherent, nom="incoherent.pdf")

    assert facture.montant_total == 70000.0


# ---------------------------------------------------------------------------
# Champs manquants : le message nomme le champ technique
# ---------------------------------------------------------------------------
def test_un_assure_absent_nomme_assure_pseudonyme() -> None:
    document = _pdf(
        [
            "Prestataire : PRE-00155",
            "Date facture : 20/10/2026",
            "Code acte : DENT-CONS",
            "P.U. : 19 000 Ar",
            "Total : 19 000 Ar",
        ]
    )

    with pytest.raises(ChampIntrouvableError, match="assure_pseudonyme"):
        extraire_facture(document, nom="facture_sans_assure.pdf")


def test_un_prestataire_absent_nomme_prestataire_id() -> None:
    document = _pdf(
        [
            "Patient : assr_Wv7VAUFiUXieeWwChWmGXB",
            "Date facture : 20/10/2026",
            "Code acte : DENT-CONS",
            "P.U. : 19 000 Ar",
            "Total : 19 000 Ar",
        ]
    )

    with pytest.raises(ChampIntrouvableError, match="prestataire_id"):
        extraire_facture(document, nom="facture_sans_prestataire.pdf")


def test_une_date_absente_nomme_date_facture() -> None:
    document = _pdf(
        [
            "Patient : assr_Wv7VAUFiUXieeWwChWmGXB",
            "Prestataire : PRE-00155",
            "Code acte : DENT-CONS",
            "P.U. : 19 000 Ar",
            "Total : 19 000 Ar",
        ]
    )

    with pytest.raises(ChampIntrouvableError, match="date_facture"):
        extraire_facture(document, nom="facture_sans_date.pdf")


def test_un_code_acte_absent_nomme_lignes_0_code_acte() -> None:
    document = _pdf(
        [
            "Patient : assr_Wv7VAUFiUXieeWwChWmGXB",
            "Prestataire : PRE-00155",
            "Date facture : 20/10/2026",
            "Total : 19 000 Ar",
        ]
    )

    with pytest.raises(ChampIntrouvableError, match=r"lignes\.0\.code_acte"):
        extraire_facture(document, nom="facture_017.pdf")


def test_un_total_sans_prix_unitaire_nomme_montant_total() -> None:
    document = _pdf(
        [
            "Patient : assr_Wv7VAUFiUXieeWwChWmGXB",
            "Prestataire : PRE-00155",
            "Date facture : 20/10/2026",
            "Code acte : DENT-CONS",
            "Quantité : 1",
        ]
    )

    with pytest.raises(ChampIntrouvableError, match="montant_total"):
        extraire_facture(document, nom="facture_sans_total.pdf")


# ---------------------------------------------------------------------------
# Reference deterministe
# ---------------------------------------------------------------------------
def test_reference_deterministe_est_stable_et_sensible_aux_octets() -> None:
    premiere = reference_deterministe(GABARIT_COLON)
    seconde = reference_deterministe(GABARIT_COLON)
    autre = reference_deterministe(GABARIT_LIGNE_SUIVANTE)

    assert premiere == seconde
    assert premiere.startswith("FAC-")
    assert len(premiere) == len("FAC-") + 12
    assert premiere != autre
    assert extraire_facture(GABARIT_COLON).reference == premiere


# ---------------------------------------------------------------------------
# Payload de la porte d'entree
# ---------------------------------------------------------------------------
def test_payload_de_respecte_les_surcharges() -> None:
    facture = extraire_facture(GABARIT_COLON, nom="facture_001.pdf")

    payload = payload_de(
        facture,
        assure_pseudonyme=pseudonymize("assr", "ASS-9CAA1484E0"),
        prestataire_id="PRE-00001",
    )

    assert payload["facture_id"] == facture.reference
    assert payload["assure_pseudonyme"] == pseudonymize("assr", "ASS-9CAA1484E0")
    assert payload["prestataire_id"] == "PRE-00001"
    assert payload["date_facture"] == "2026-10-20T00:00:00"
    assert payload["montant_total"] == 19000.0
    assert isinstance(payload["lignes"], list)
    assert payload["lignes"][0]["code_acte"] == "DENT-CONS"


def test_payload_de_sans_surcharge_garde_les_valeurs_brutes() -> None:
    facture = extraire_facture(GABARIT_COLON, nom="facture_001.pdf")
    payload = payload_de(facture)

    assert payload["assure_pseudonyme"] == "assr_Wv7VAUFiUXieeWwChWmGXB"
    assert payload["prestataire_id"] == "PRE-00155"


# ---------------------------------------------------------------------------
# Resolution : fausse session, aucune base requise
# ---------------------------------------------------------------------------
class _Resultat:
    def __init__(self, *, scalaire: object = None, lignes: object = ()) -> None:
        self._scalaire = scalaire
        self._lignes = list(lignes)

    def scalar(self) -> object:
        return self._scalaire

    def all(self) -> list[object]:
        return self._lignes

    def __iter__(self):
        return iter(self._lignes)


class _Session:
    """Une session SQLAlchemy minimale, pilotee par le texte de la requete."""

    def __init__(
        self,
        *,
        assure_existe: bool = True,
        prestataire_existe: bool = True,
        prestataires: list[tuple] | None = None,
        actes: list[tuple] | None = None,
        medicaments: list[tuple] | None = None,
    ) -> None:
        self.assure_existe = assure_existe
        self.prestataire_existe = prestataire_existe
        self.prestataires = prestataires or []
        self.actes = actes or []
        self.medicaments = medicaments or []
        self.requetes: list[str] = []

    def execute(self, requete, parametres=None):
        sql = str(requete)
        self.requetes.append(sql)
        if "FROM core.assure" in sql:
            return _Resultat(scalaire=1 if self.assure_existe else None)
        if "FROM core.prestataire WHERE code" in sql:
            return _Resultat(scalaire=parametres["valeur"] if self.prestataire_existe else None)
        if "FROM core.prestataire" in sql:
            return _Resultat(lignes=self.prestataires)
        for table, referentiel in (
            ("core.acte", self.actes),
            ("core.medicament", self.medicaments),
        ):
            if f"FROM {table} WHERE" in sql:
                cible = str(parametres["valeur"]).upper()
                for code, _libelle in referentiel:
                    if code.upper() == cible:
                        return _Resultat(scalaire=code)
                return _Resultat(scalaire=None)
        if "FROM core.acte" in sql:
            return _Resultat(lignes=self.actes)
        if "FROM core.medicament" in sql:
            return _Resultat(lignes=self.medicaments)
        raise AssertionError(f"Requete inattendue : {sql}")


def test_resoudre_assure_accepte_un_pseudonyme_existant() -> None:
    session = _Session(assure_existe=True)

    assert resoudre_assure(session, "assr_dejaCalcule") == "assr_dejaCalcule"


def test_resoudre_assure_pseudonymise_un_identifiant_brut() -> None:
    session = _Session(assure_existe=True)

    attendu = pseudonymize("assr", "ASS-9CAA1484E0")
    assert resoudre_assure(session, "ASS-9CAA1484E0") == attendu


def test_resoudre_assure_inconnu_nomme_assure_pseudonyme() -> None:
    session = _Session(assure_existe=False)

    with pytest.raises(ChampIntrouvableError, match="assure_pseudonyme"):
        resoudre_assure(session, "assr_inconnu")


def test_resoudre_assure_par_nom_utilise_l_index_pii(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = tmp_path / "identites_pii.csv"
    index.write_text(
        "assure_id,nom,prenoms,sexe,date_naissance\n"
        "ASS-9CAA1484E0,RANDRIASOLOFO,Thierry Ny Aina,M,1970-09-26\n"
        "ASS-DECEFA847B,RANDRIA,Harisoa,F,2017-10-06\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("IDENTITES_PII", str(index))
    session = _Session(assure_existe=True)

    assert resoudre_assure(session, "Randriasolofo Thierry Ny Aina") == pseudonymize(
        "assr", "ASS-9CAA1484E0"
    )
    # L'ordre inverse doit aussi fonctionner.
    assert resoudre_assure(session, "Thierry Ny Aina RANDRIASOLOFO") == pseudonymize(
        "assr", "ASS-9CAA1484E0"
    )


def test_resoudre_assure_par_nom_inconnu_est_un_rejet(tmp_path: Path, monkeypatch) -> None:
    index = tmp_path / "identites_pii.csv"
    index.write_text(
        "assure_id,nom,prenoms\nASS-9CAA1484E0,RANDRIASOLOFO,Thierry\n", encoding="utf-8"
    )
    monkeypatch.setenv("IDENTITES_PII", str(index))

    with pytest.raises(ChampIntrouvableError, match="assure_pseudonyme"):
        resoudre_assure(_Session(assure_existe=True), "NOM INCONNU")


def test_resoudre_assure_par_nom_ambigu_nomme_les_candidats(tmp_path: Path, monkeypatch) -> None:
    index = tmp_path / "identites_pii.csv"
    index.write_text(
        "assure_id,nom,prenoms\n"
        "ASS-AAAA1111,RANDRIASOLOFO,Thierry\n"
        "ASS-BBBB2222,RANDRIASOLOFO,Thierry\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("IDENTITES_PII", str(index))

    with pytest.raises(ChampIntrouvableError) as capture:
        resoudre_assure(_Session(assure_existe=True), "RANDRIASOLOFO Thierry")

    assert "ASS-AAAA1111" in str(capture.value)
    assert "ASS-BBBB2222" in str(capture.value)


def test_resoudre_assure_sans_index_est_une_erreur_explicite(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("IDENTITES_PII", str(tmp_path / "absent.csv"))

    with pytest.raises(ChampIntrouvableError, match="index des identites introuvable"):
        resoudre_assure(_Session(), "RANDRIASOLOFO Thierry")


PRESTATAIRES = [
    ("PRE-00155", "Cabinet Dentaire", "Antananarivo", "ONM-155", "NIF-155"),
    ("PRE-00002", "Cabinet Dentaire", "Toamasina", "ONM-002", "NIF-002"),
    ("PRE-00003", "Pharmacie Centrale", "Antananarivo", "ONM-003", "NIF-003"),
]


def test_resoudre_prestataire_accepte_un_code_existant() -> None:
    session = _Session(prestataire_existe=True)

    assert resoudre_prestataire(session, "PRE-00155") == "PRE-00155"


def test_resoudre_prestataire_par_nom_et_ville() -> None:
    session = _Session(prestataires=PRESTATAIRES)

    assert resoudre_prestataire(session, "Pharmacie Centrale") == "PRE-00003"
    assert resoudre_prestataire(session, "Cabinet Dentaire", ville="Toamasina") == "PRE-00002"


def test_resoudre_prestataire_ambigu_nomme_les_candidats() -> None:
    session = _Session(prestataires=PRESTATAIRES)

    with pytest.raises(ChampIntrouvableError) as capture:
        resoudre_prestataire(session, "Cabinet Dentaire")

    message = str(capture.value)
    assert "prestataire_id" in message
    assert "PRE-00155" in message
    assert "PRE-00002" in message


def test_resoudre_prestataire_inconnu_est_un_rejet() -> None:
    with pytest.raises(ChampIntrouvableError, match="prestataire_id"):
        resoudre_prestataire(_Session(prestataires=PRESTATAIRES), "Inconnu SARL")


def test_resoudre_acte_par_code_ou_libelle() -> None:
    actes = [
        ("DENT-CONS", "Consultation dentaire"),
        ("DENT-EXTRACT", "Extraction dentaire"),
    ]
    session = _Session(actes=actes)

    assert resoudre_acte(session, "dent-cons") == "DENT-CONS"
    assert resoudre_acte(session, "Extraction dentaire") == "DENT-EXTRACT"


def test_resoudre_acte_inconnu_nomme_lignes_0_code_acte() -> None:
    actes = [("DENT-CONS", "Consultation dentaire")]

    with pytest.raises(ChampIntrouvableError, match=r"lignes\.0\.code_acte"):
        resoudre_acte(_Session(actes=actes), "ACTE-INCONNU")


# ---------------------------------------------------------------------------
# Garde-fou : l'extraction ne prend aucune session
# ---------------------------------------------------------------------------
def test_extraction_pure_ne_touche_pas_a_la_base() -> None:
    """`extraire_facture` et `payload_de` ne prennent aucune session."""
    facture = extraire_facture(GABARIT_COLON)
    payload = payload_de(facture)

    assert payload["lignes"]
    assert payload["facture_id"] == facture.reference


# ---------------------------------------------------------------------------
# Lecture d'un tableau mis en page (le vrai gabarit du jury)
# ---------------------------------------------------------------------------

GABARIT_TABLEAU = _pdf_tableau(
    [
        [(40, "DOCUMENT FICTIF - donnees synthetiques PrediCare TPA")],
        [(40, "Page 1")],
        [(40, "BIO-LABO ANDRIMASO")],
        [(40, "Lot V G 211 Bis Ambanidia - Antananarivo")],
        [(40, "FACTURE N° BA177/2026/00043")],
        [(40, "Date des soins"), (220, "2026-01-30")],
        [(40, "Date de facture"), (220, "2026-02-05")],
        [(40, "Patient"), (220, "RASOATIANA Isabelle")],
        [(40, "N° assuré"), (220, "ASS-AA878F0B2E")],
        [
            (40, "Code"),
            (110, "Désignation"),
            (330, "Qté"),
            (380, "P.U."),
            (470, "Montant"),
        ],
        [
            (40, "LAB-NFS"),
            (110, "Numération formule sanguine"),
            (330, "1"),
            (380, "11 500 Ar"),
            (470, "11 500 Ar"),
        ],
        [
            (40, "LAB-CRP"),
            (110, "Protéine C réactive"),
            (330, "1"),
            (380, "11 500 Ar"),
            (470, "11 500 Ar"),
        ],
        [(40, "TOTAL"), (470, "23 000 Ar")],
        [(40, "Arrêtée la présente facture à la somme de : vingt-trois mille ariary")],
    ]
)


def test_un_tableau_mis_en_page_est_lu_ligne_a_ligne() -> None:
    extraite = extraire_facture(GABARIT_TABLEAU, nom="facture_tableau.pdf")

    assert extraite.date_facture == "2026-02-05T00:00:00"
    assert extraite.assure == "ASS-AA878F0B2E"
    assert extraite.prestataire == "BIO-LABO ANDRIMASO"
    assert extraite.prestataires == ("BIO-LABO ANDRIMASO",)
    assert extraite.montant_total == 23000.0
    assert len(extraite.lignes) == 2
    assert [ligne["code_acte"] for ligne in extraite.lignes] == ["LAB-NFS", "LAB-CRP"]
    assert all(ligne["quantite"] == 1 for ligne in extraite.lignes)


def test_un_tableau_aux_colonnes_desordonnees_est_lu() -> None:
    document = _pdf_tableau(
        [
            [(40, "DOCUMENT FICTIF - donnees synthetiques PrediCare TPA")],
            [(40, "Page 1")],
            [(40, "PHARMACIE VONINKAZO")],
            [(40, "FACTURE N° X")],
            [(40, "Date de facture"), (220, "2026-02-05")],
            [(40, "Patient"), (220, "ASS-5C99024388")],
            [(40, "N° assuré"), (220, "ASS-5C99024388")],
            [(40, "Montant"), (110, "P.U."), (180, "Qté"), (240, "Code"), (320, "Désignation")],
            [(40, "12 100 Ar"), (110, "7 900 Ar"), (180, "1"), (240, "MED-ACT"), (320, "Actif")],
            [
                (40, "4 200 Ar"),
                (110, "2 100 Ar"),
                (180, "2"),
                (240, "MED-PARA500"),
                (320, "Paracetamol"),
            ],
            [(40, "TOTAL"), (110, "16 300 Ar")],
        ]
    )
    extraite = extraire_facture(document, nom="facture_desordre.pdf")

    assert extraite.prestataire == "PHARMACIE VONINKAZO"
    assert [ligne["code_acte"] for ligne in extraite.lignes] == ["MED-ACT", "MED-PARA500"]
    assert [ligne["quantite"] for ligne in extraite.lignes] == [1, 2]
    assert extraite.montant_total == 16300.0


def test_le_total_du_tableau_sert_de_montant_total() -> None:
    document = _pdf_tableau(
        [
            [(40, "DOCUMENT FICTIF - donnees synthetiques PrediCare TPA")],
            [(40, "Page 1")],
            [(40, "PHARMACIE VONINKAZO")],
            [(40, "FACTURE N° X")],
            [(40, "Date de facture"), (220, "2026-02-05")],
            [(40, "Patient"), (220, "ASS-5C99024388")],
            [(40, "N° assuré"), (220, "ASS-5C99024388")],
            [(40, "Code"), (110, "Désignation"), (330, "Qté"), (380, "P.U."), (470, "Montant")],
            [(40, "MED-ACT"), (110, "Actif"), (330, "1"), (380, "7 900 Ar"), (470, "7 900 Ar")],
            [(40, "TOTAL"), (470, "7 900 Ar")],
        ]
    )
    extraite = extraire_facture(document, nom="facture_sans_ancre_total.pdf")

    assert extraite.montant_total == 7900.0
    assert len(extraite.lignes) == 1


def test_une_facture_sans_tableau_ni_prix_est_rejetee() -> None:
    document = _pdf(
        [
            "DOCUMENT FICTIF - donnees synthetiques PrediCare TPA",
            "Page 1",
            "Patient : assr_Wv7VAUFiUXieeWwChWmGXB",
            "Prestataire : PRE-00155",
            "Date facture : 20/10/2026",
            "Code acte : DENT-CONS",
            "Quantité : 1",
        ]
    )
    with pytest.raises(ChampIntrouvableError, match="montant_total"):
        extraire_facture(document, nom="facture_sans_prix.pdf")


# ---------------------------------------------------------------------------
# Resolution des medicaments
# ---------------------------------------------------------------------------


def test_resoudre_acte_accepte_un_medicament() -> None:
    session = _Session(
        actes=[("DENT-CONS", "Consultation dentaire")],
        medicaments=[("MED-ACT", "Actif")],
    )

    assert resoudre_acte(session, "MED-ACT") == "MED-ACT"
    assert resoudre_acte(session, "Actif") == "MED-ACT"
    assert resoudre_acte(session, "DENT-CONS") == "DENT-CONS"


def test_resoudre_acte_inconnu_nomme_lignes_0_code_acte_avec_medicaments() -> None:
    session = _Session(
        actes=[("DENT-CONS", "Consultation dentaire")],
        medicaments=[("MED-ACT", "Actif")],
    )

    with pytest.raises(ChampIntrouvableError, match=r"lignes\.0\.code_acte"):
        resoudre_acte(session, "MED-INCONNU")


def test_resoudre_prestataire_parmi_essaie_les_suivants() -> None:
    session = _Session(
        prestataires=[("PRE-00001", "Pharmacie Z", "Antananarivo", "ONM-1", "111")],
    )

    assert resoudre_prestataire_parmi(session, ("Enseigne inconnue", "111")) == "PRE-00001"


def test_resoudre_prestataire_parmi_propage_le_dernier_rejet() -> None:
    session = _Session(prestataires=[])

    with pytest.raises(ChampIntrouvableError, match="prestataire_id"):
        resoudre_prestataire_parmi(session, ("Inconnu A", "Inconnu B"))


# ---------------------------------------------------------------------------
# Date sans libelle, et ordonnance
# ---------------------------------------------------------------------------


def test_une_date_sans_libelle_est_lue_par_motif() -> None:
    # Gabarit du jury : la date de facture n'a pas de libelle, elle est dans
    # la formule « <ville>, le <date> ».
    document = _pdf(
        [
            "PHARMACIE VONINKAZO",
            "Antananarivo, le 2026-03-02",
            "Patient : ASS-5C99024388",
            "N° assuré : ASS-5C99024388",
            "Code acte : MED-ACT",
            "Quantité : 1",
            "P.U. : 7 900 Ar",
            "Total : 7 900 Ar",
        ]
    )

    extraite = extraire_facture(document, nom="jury_sans_libelle.pdf")

    assert extraite.date_facture == "2026-03-02T00:00:00"
    assert extraite.assure == "ASS-5C99024388"
    assert len(extraite.lignes) == 1


def test_la_date_de_facture_prime_sur_la_date_des_soins() -> None:
    document = _pdf(
        [
            "PHARMACIE VONINKAZO",
            "Date des soins : 2026-01-30",
            "Date de facture : 2026-02-05",
            "Antananarivo, le 2026-03-02",
            "Patient : ASS-5C99024388",
            "Code acte : MED-ACT",
            "Quantité : 1",
            "P.U. : 7 900 Ar",
            "Total : 7 900 Ar",
        ]
    )

    extraite = extraire_facture(document, nom="priorite_date.pdf")

    assert extraite.date_facture == "2026-02-05T00:00:00"


def test_une_ordonnance_est_rejetee_clairement() -> None:
    document = _pdf(
        [
            "Docteur RANAIVOMALALA Felana",
            "ORDONNANCE",
            "Antananarivo, le 2026-02-02",
            "Patient : RASOATIANA Isabelle - 33 ans",
            "Renseignement clinique : Suspicion infection respiratoire aiguë",
            "1. Numération formule sanguine - Qté : 1",
            "Validité : 10 jours - Réf. ORD-0003289",
            "Signature et cachet du médecin",
        ]
    )

    with pytest.raises(DocumentNonFactureError, match="ORDONNANCE"):
        extraire_facture(document, nom="ORD-0003289.pdf")


def test_une_facture_qui_mentionne_une_ordonnance_n_est_pas_rejetee() -> None:
    # Une facture peut porter « Ordonnance : ORD-0003289 » comme champ :
    # elle doit rester importable.
    document = _pdf(
        [
            "PHARMACIE VONINKAZO",
            "Antananarivo, le 2026-03-02",
            "Patient : ASS-5C99024388",
            "Ordonnance : ORD-0003289",
            "Code acte : MED-ACT",
            "Quantité : 1",
            "P.U. : 7 900 Ar",
            "Total : 7 900 Ar",
        ]
    )

    extraite = extraire_facture(document, nom="facture_avec_ordonnance.pdf")

    assert extraite.date_facture == "2026-03-02T00:00:00"
