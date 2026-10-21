"""Decoupage du corpus RAG : nettoyage et metadonnees.

Les tests utilisent les vrais PDF du corpus lorsqu'ils sont presents. Ils
n'appellent jamais OpenAI : seules les fonctions de lecture et de decoupage
sont exercees, pas l'indexation.
"""

from __future__ import annotations

import unicodedata
from contextlib import contextmanager
from pathlib import Path

import pytest

from predicare_seed import ingest_rag

CORPUS = Path(__file__).resolve().parents[1] / "data" / "rag_corpus"
PLAFONDS_GLOBAUX = {
    "Conditions_Generales_PREMIUM.pdf": "20 000 000 Ar",
    "Conditions_Generales_CONFORT.pdf": "8 000 000 Ar",
    "Conditions_Generales_ESSENTIEL.pdf": "3 000 000 Ar",
}
CATEGORIES_ARTICLE_5 = (
    "Consultation",
    "Pharmacie",
    "Laboratoire",
    "Imagerie",
    "Hospitalisation",
    "Maternite",
    "Dentaire",
    "Optique",
    "Kinesitherapie",
)
SECTIONS_GUIDE = (
    "PHARMACIES",
    "GÉNÉRALISTES (CABINETS MÉDICAUX)",
    "SPÉCIALISTES",
    "CLINIQUES ET CENTRES MÉDICAUX",
    "LABORATOIRES",
    "IMAGERIE MÉDICALE",
    "DENTISTES",
    "OPTICIENS",
    "KINÉSITHÉRAPIE",
    "MATERNITÉS",
    "CONTACTS PREDICARE TPA",
)


def _chemin(nom: str) -> Path:
    chemin = CORPUS / nom
    if not chemin.exists():
        pytest.skip(f"PDF absent du corpus : {chemin}")
    return chemin


def _sans_accents(texte: str) -> str:
    """Compare les libelles sans se soucier des accents du PDF."""
    decompose = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in decompose if not unicodedata.combining(c)).lower()


def test_nettoyage_supprime_le_boilerplate():
    texte = """
    DOCUMENT FICTIF – données synthétiques PrediCare TPA – aucune donnée réelle
    Page 12
    GUIDE DU RÉSEAU – DONNÉES FICTIVES – noms, adresses et numéros inventés
    N°
    Prestataire
    Horaires
    Contact
    Adresse
    Tarifs
    Pharmacie Kintana – Lot II W 177 Bis Ilafy
    Consultation ophtalmologie – tarif élevé
    """
    propre = ingest_rag._nettoyer(texte)
    assert "DOCUMENT FICTIF" not in propre
    assert "Page 12" not in propre
    assert "GUIDE DU RÉSEAU" not in propre
    assert "Prestataire" not in propre
    assert "Pharmacie Kintana - Lot II W 177 Bis Ilafy" in propre
    assert "ophtalmologie" in propre
    assert "élevé" in propre  # les accents sont conserves


def test_article_5_une_segment_par_categorie():
    for nom in (
        "Conditions_Generales_PREMIUM.pdf",
        "Conditions_Generales_CONFORT.pdf",
        "Conditions_Generales_ESSENTIEL.pdf",
    ):
        segments = ingest_rag._segments_pour_fichier(_chemin(nom))
        tableaux = [
            s
            for s in segments
            if s.article.startswith("Article 5") and "vue globale" not in s.article
        ]
        assert len(tableaux) == len(CATEGORIES_ARTICLE_5), nom
        assert {s.garantie for s in tableaux} == set(CATEGORIES_ARTICLE_5), nom
        plafond_attendu = PLAFONDS_GLOBAUX[nom]
        for segment in tableaux:
            assert segment.article == "Article 5 - Tableau des garanties"
            assert segment.page == 1
            assert "Article 5 – Tableau des garanties" in segment.texte
            assert segment.garantie in segment.texte
            for attendu in (
                "Taux",
                "Plafond annuel",
                "Franchise",
                "Carence",
                "Délai de carence",
                "Plafond annuel global par bénéficiaire",
            ):
                assert attendu in segment.texte, (nom, segment.garantie, attendu)
            # Regression : le plafond global du PDF est coupe sur deux lignes.
            assert plafond_attendu in segment.texte, (nom, segment.garantie)
            assert "non precise" not in segment.texte, (nom, segment.garantie)


def test_article_5_vue_globale():
    for nom, plafond_attendu in PLAFONDS_GLOBAUX.items():
        segments = ingest_rag._segments_pour_fichier(_chemin(nom))
        global_segment = next(s for s in segments if "vue globale" in s.article)
        assert global_segment.garantie == "Global"
        assert f"Plafond annuel global par bénéficiaire : {plafond_attendu}" in (
            global_segment.texte
        )
        assert "non precise" not in global_segment.texte


def test_article_6_synthese_des_carences():
    """Le tableau de l'article 5 porte les carences ; l'article 6 les resume.

    Sans ce resume, la question « delai de carence maternite » ne depasse
    pas le seuil de similarite : l'article 6 generique ne contient aucune
    duree, et le segment Maternite de l'article 5 est trop loin dans le
    classement.
    """
    attendus = {
        "Conditions_Generales_PREMIUM.pdf": {
            "Maternité : 90 jours",
            "Dentaire : 30 jours",
            "Optique : 60 jours",
        },
        "Conditions_Generales_CONFORT.pdf": {
            "Maternité : 180 jours",
            "Dentaire : 60 jours",
            "Optique : 90 jours",
        },
        "Conditions_Generales_ESSENTIEL.pdf": {
            "Maternité : 270 jours",
            "Dentaire : 90 jours",
            "Optique : 180 jours",
        },
    }
    for nom, valeurs in attendus.items():
        segments = ingest_rag._segments_pour_fichier(_chemin(nom))
        syntheses = [
            s for s in segments if s.article == "Article 6 - Délais de carence par catégorie"
        ]
        assert len(syntheses) == 1, nom
        synthese = syntheses[0]
        assert synthese.garantie == "-"
        assert synthese.source_fichier == nom
        for valeur in valeurs:
            assert valeur in synthese.texte, (nom, valeur)
        assert "Consultation : aucune carence" in synthese.texte


def test_article_7_un_segment_par_type_de_soins():
    """L'article 7 est decoupe par type de soins.

    Sans ce decoupage, une question sur l'optique compete avec les sept
    autres types dans le meme embedding : le bon passage passait sous le
    seuil de similarite et la reponse citait le guide plutot que l'article.
    """
    for nom in (
        "Conditions_Generales_PREMIUM.pdf",
        "Conditions_Generales_CONFORT.pdf",
        "Conditions_Generales_ESSENTIEL.pdf",
    ):
        segments = ingest_rag._segments_pour_fichier(_chemin(nom))
        par_type = [s for s in segments if s.article.startswith("Article 7") and s.garantie != "-"]
        assert len(par_type) == len(CATEGORIES_ARTICLE_5), nom
        assert {s.garantie for s in par_type} == set(CATEGORIES_ARTICLE_5), nom
        for segment in par_type:
            assert segment.article.startswith("Article 7 - Pièces justificatives")
            assert segment.contrat == f"{ingest_rag.CONTRAT_CG} {nom.split('_')[-1][:-4]}"
            assert segment.source_fichier == nom
            assert _sans_accents(segment.garantie) in _sans_accents(segment.texte)
            assert "Pièces justificatives" in segment.texte
            assert 0 < len(segment.texte) <= 500, (nom, segment.garantie)

        # Les regles generales restent disponibles dans un segment dedie.
        general = [
            s
            for s in segments
            if s.article == "Article 7 - Pièces justificatives par type de soins"
        ]
        assert len(general) == 1, nom
        assert "Validité des ordonnances" in general[0].texte
        assert "Pièces exigées" in general[0].texte

        # Aucune perte : chaque type garde une piece justificative precise.
        for attendu in (
            "feuille de soins",
            "numéro d'ordre (ONM)",
            "Billet d'accouchement",
            "Devis",
            "proforma",
        ):
            assert any(attendu in s.texte for s in par_type), (nom, attendu)


def test_le_decoupage_par_type_ne_s_applique_qu_aux_articles_concernes():
    """Seuls les articles listes par type sont concernes.

    Les autres articles des CG gardent leur decoupage generique : on ne veut
    pas fragmenter un article qui n'a pas cette structure.
    """
    segments = ingest_rag._segments_pour_fichier(_chemin("Conditions_Generales_PREMIUM.pdf"))
    generiques = {s.article for s in segments if s.article.startswith("Article 8")}
    assert generiques == {"Article 8 - Fonctionnement du tiers payant"}
    assert all(s.garantie == "-" for s in segments if s.article.startswith("Article 8"))


def test_bareme_groupement_par_categorie():
    segments = ingest_rag._segments_pour_fichier(_chemin("Bareme_Reference_Actes.pdf"))
    assert len(segments) >= 8
    categories = {s.garantie for s in segments}
    for categorie in (
        "CONSULTATION",
        "IMAGERIE",
        "LABORATOIRE",
        "KINESITHERAPIE",
        "DENTAIRE",
        "OPTIQUE",
        "HOSPITALISATION",
        "MATERNITE",
    ):
        assert categorie in categories
    for segment in segments:
        assert segment.contrat == "Bareme_Reference_Actes"
        assert segment.article == f"Barème - {segment.garantie}"
        assert segment.texte.startswith(f"Barème de référence des actes – {segment.garantie}")
        assert segment.source_fichier == "Bareme_Reference_Actes.pdf"
        assert "DOCUMENT FICTIF" not in segment.texte
        assert 0 < len(segment.texte) <= 500


def test_guide_decoupage_par_section():
    for nom in (
        "Guide_Reseau_Soins_Antananarivo.pdf",
        "Guide_Reseau_Soins_National.pdf",
    ):
        segments = ingest_rag._segments_pour_fichier(_chemin(nom))
        sections = {s.garantie for s in segments}
        assert set(SECTIONS_GUIDE) <= sections, nom
        for segment in segments:
            assert segment.article == f"Guide - {segment.garantie}"
            assert segment.contrat == Path(nom).stem
            assert segment.source_fichier == nom
            assert segment.texte.startswith(segment.garantie)
            assert "DOCUMENT FICTIF" not in segment.texte
            assert 0 < len(segment.texte) <= 500


def test_conditions_particulieres_synthese_et_beneficiaires():
    nom = "CP_CTR-000048.pdf"
    segments = ingest_rag._segments_pour_fichier(_chemin(f"conditions_particulieres/{nom}"))
    par_article = {s.article: s for s in segments}
    assert set(par_article) == {
        "Conditions particulieres - synthese",
        "Conditions particulieres - beneficiaires",
    }
    synthese = par_article["Conditions particulieres - synthese"]
    assert synthese.contrat == "CTR-000048"
    assert synthese.source_fichier == nom
    for attendu in (
        "CTR-000048",
        "POL-2022-2780",
        "PREMIUM",
        "Zebu Telecom SARL",
        "2023-01-16",
        "20 000 000 Ar",
        "2 100 000 Ar",
    ):
        assert attendu in synthese.texte
    beneficiaires = par_article["Conditions particulieres - beneficiaires"]
    assert beneficiaires.contrat == "CTR-000048"
    assert "ASS-C60624BAFB" in beneficiaires.texte
    assert "ASSURE_PRINCIPAL" in beneficiaires.texte
    assert "ENFANT" in beneficiaires.texte


def test_segments_generiques_sans_boilerplate():
    # Le corpus ne contient que des familles connues ; on verifie malgre tout
    # l'absence de boilerplate sur l'ensemble des PDF lus.
    for chemin in sorted(CORPUS.rglob("*.pdf")):
        for segment in ingest_rag._segments_pour_fichier(chemin):
            assert segment.source_fichier == chemin.name
            assert "DOCUMENT FICTIF" not in segment.texte
            assert "GUIDE DU RÉSEAU" not in segment.texte
            assert len(segment.texte.strip()) > 0


def test_decouper_texte_chevauche_et_couvre():
    texte = " ".join(f"mot{index:04d}" for index in range(150))
    morceaux = ingest_rag._decouper_texte(texte, cible=200, chevauchement=50)
    assert len(morceaux) > 1
    assert all(len(morceau) <= 200 for morceau in morceaux)
    jetons = [set(morceau.split()) for morceau in morceaux]
    assert set(texte.split()) <= set().union(*jetons)
    assert all(jetons[index] & jetons[index + 1] for index in range(len(jetons) - 1))


def test_pdf_recognise_sans_segment_bascule_generique(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    chemin = tmp_path / "Conditions_Generales_VIDE.pdf"
    evenements: list[str] = []
    monkeypatch.setattr(
        ingest_rag.logger,
        "warning",
        lambda evenement, **_: evenements.append(evenement),
    )
    monkeypatch.setattr(
        ingest_rag,
        "_lire_pdf",
        lambda _: [
            (
                1,
                "Contenu generique sans article mais suffisamment long pour "
                "produire un segment valide.",
            )
        ],
    )
    segments = ingest_rag._segments_pour_fichier(chemin)
    assert len(segments) == 1
    assert segments[0].article == "Section 1"
    assert "pdf.aucun_segment" in evenements


def test_pdf_illisible_est_ignore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    chemin = tmp_path / "cassee.pdf"
    chemin.write_bytes(b"ceci n'est pas un PDF")
    evenements: list[str] = []
    monkeypatch.setattr(
        ingest_rag.logger,
        "warning",
        lambda evenement, **_: evenements.append(evenement),
    )
    segments = ingest_rag.collecter_segments(tmp_path)
    assert segments == []
    assert "pdf.erreur" in evenements


class _ResultatFaux:
    def __init__(self, valeur: int) -> None:
        self._valeur = valeur

    def scalar(self) -> int:
        return self._valeur


class _SessionFausse:
    def __init__(self, valeur: int = 0) -> None:
        self._valeur = valeur
        self.requetes: list[str] = []

    def execute(self, requete: object, _parametres: object | None = None) -> _ResultatFaux:
        self.requetes.append(str(requete))
        return _ResultatFaux(self._valeur)


def _faux_scope(session: _SessionFausse):
    @contextmanager
    def _scope():
        yield session

    return _scope


def test_appliquer_refuse_ecriture_si_aucun_segment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    session = _SessionFausse()
    evenements: list[str] = []
    monkeypatch.setattr(ingest_rag, "session_scope", _faux_scope(session))
    monkeypatch.setattr(
        ingest_rag.logger,
        "error",
        lambda evenement, **_: evenements.append(evenement),
    )
    resultat = ingest_rag.appliquer(tmp_path, force=True, segments=[])
    assert resultat == {"segments": 0, "ignores": 0, "force": True}
    assert len(session.requetes) == 1
    assert "TRUNCATE" not in session.requetes[0].upper()
    assert "ingestion.aucun_segment" in evenements


def test_appliquer_noop_ne_parse_pas_le_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    session = _SessionFausse(valeur=5)
    monkeypatch.setattr(ingest_rag, "session_scope", _faux_scope(session))

    def _interdit(_: Path) -> list[ingest_rag.Segment]:
        pytest.fail("le corpus ne doit pas etre parse quand l'index est deja peuple")

    monkeypatch.setattr(ingest_rag, "collecter_segments", _interdit)
    resultat = ingest_rag.appliquer(tmp_path, force=False)
    assert resultat == {"segments": 0, "ignores": 5, "force": False}
