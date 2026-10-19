"""Ingestion du corpus de contrats PDF dans `core.document_vectorise`.

Phase 5.1 et 5.2 du plan d'action. Decoupe les PDF en segments, calcule
les embeddings et les indexe dans pgvector. Le module est idempotent :
relance sans `--force` ne fait rien si la table est deja peuplee.

Le decoupage est adapte a la nature de chaque document :
- Conditions Generales : un segment par article, et un segment par garantie
  pour l'article 5 ;
- Conditions particulieres : une synthese contractuelle et un tableau des
  beneficiaires ;
- Bareme : un groupe de lignes par categorie d'actes ;
- Guides reseau : un groupe d'entrees par section (pharmacies, laboratoires,
  etc.) avec le titre de section repete dans chaque segment ;
- autres PDF : decoupage generique par paragraphes.

Usage :
    python -m predicare_seed.ingest_rag --dry-run
    python -m predicare_seed.ingest_rag --apply
    python -m predicare_seed.ingest_rag --apply --force
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import SecretStr
from pypdf import PdfReader
from sqlalchemy import text
from sqlalchemy.orm import Session

from predicare.config import get_settings
from predicare.db import session_scope
from predicare.logging_config import configure_logging, get_logger

if TYPE_CHECKING:
    from langchain_openai import OpenAIEmbeddings

logger = get_logger("seed.ingest_rag")

CORPUS_DEFAULT = os.getenv("RAG_CORPUS_DIR", "/data/rag_corpus")
BATCH_SIZE = 64
TAILLE_CIBLE = 450  # caracteres approximatifs par segment generique
TAILLE_ARTICLE = 800  # plafond demande pour les articles des CG
CHEVAUCHEMENT = 50

#: Nom du contrat tel qu'il apparait dans les citations. Une seule chaine :
#: deux orthographes casseraient le regroupement par contrat et les sources
#: citees par l'assure.
CONTRAT_CG = "Conditions Generales"

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

#: Types de soins servant de sous-intitules dans certains articles (article 7
#: des CG : "Optique", "Pharmacie", ...). Une question portant sur un seul type
#: ne doit pas concourir avec tous les autres dans le meme embedding.
TYPES_SOINS = CATEGORIES_ARTICLE_5

#: Phrase generale d'un article ("Validité des ordonnances : 10 jours ...").
#: Elle n'appartient pas a un type de soins : elle clot la liste des entrees.
RE_PHRASE_GENERALE = re.compile(r"^[A-ZÉÀÜ][^:;.]{3,60}\s:\s")

#: Libelles accentues utilises dans la phrase de chaque segment de l'article 5.
LIBELLES_ARTICLE_5 = {
    "Consultation": "consultation",
    "Pharmacie": "pharmacie",
    "Laboratoire": "laboratoire",
    "Imagerie": "imagerie",
    "Hospitalisation": "hospitalisation",
    "Maternite": "maternité",
    "Dentaire": "dentaire",
    "Optique": "optique",
    "Kinesitherapie": "kinésithérapie",
}

CATEGORIES_BAREME = (
    "CONSULTATION",
    "IMAGERIE",
    "LABORATOIRE",
    "KINESITHERAPIE",
    "DENTAIRE",
    "OPTIQUE",
    "HOSPITALISATION",
    "MATERNITE",
)

#: Sections des guides reseau. La cle est normalisee (sans accents, en
#: majuscules) pour tolerer les variantes de casse des PDF.
SECTIONS_GUIDE = {
    "PHARMACIES": "PHARMACIES",
    "GENERALISTES (CABINETS MEDICAUX)": "GÉNÉRALISTES (CABINETS MÉDICAUX)",
    "SPECIALISTES": "SPÉCIALISTES",
    "CLINIQUES ET CENTRES MEDICAUX": "CLINIQUES ET CENTRES MÉDICAUX",
    "LABORATOIRES": "LABORATOIRES",
    "IMAGERIE MEDICALE": "IMAGERIE MÉDICALE",
    "DENTISTES": "DENTISTES",
    "OPTICIENS": "OPTICIENS",
    "KINESITHERAPIE": "KINÉSITHÉRAPIE",
    "MATERNITES": "MATERNITÉS",
    "CONTACTS PREDICARE TPA (FICTIFS)": "CONTACTS PREDICARE TPA",
}

#: Lignes isolees qui repettent un entete de tableau d'une page a l'autre.
ENTETES_TABLEAU = {
    "N°",
    "N",
    "PRESTATAIRE",
    "SPÉCIALITÉ / PRESTATAIRE",
    "SPECIALITE / PRESTATAIRE",
    "HORAIRES",
    "CONTACT",
    "ADRESSE",
    "TARIFS",
    "CODE",
    "LIBELLÉ",
    "LIBELLE",
    "CATÉGORIE",
    "CATEGORIE",
    "MIN",
    "RÉFÉRENCE",
    "REFERENCE",
    "MAX",
    "ORDONNANCE",
    "ENTENTE",
    "RESTRICTION",
    "TAUX",
    "PLAFOND ANNUEL",
    "FRANCHISE / FACTURE",
    "CARENCE",
}

#: Rangs et sexes acceptes dans le tableau des beneficiaires des CP.
RANGS_BENEFICIAIRE = {"ASSURE_PRINCIPAL", "CONJOINT", "ENFANT"}
SEXES_BENEFICIAIRE = {"M", "F"}


@dataclass
class Segment:
    contrat: str
    contrat_id: int | None
    article: str
    garantie: str
    texte: str
    page: int | None
    source_fichier: str


@dataclass
class Article:
    """Un article des Conditions Generales, avec la page de chaque ligne."""

    numero: int
    titre: str
    page: int
    lignes: list[tuple[int, str]] = field(default_factory=list)


@dataclass
class SectionGuide:
    """Une section du guide reseau (pharmacies, laboratoires, etc.)."""

    cle: str
    titre: str
    page: int
    lignes: list[tuple[int, str]] = field(default_factory=list)


def _lire_pdf(chemin: Path) -> list[tuple[int, str]]:
    lecteur = PdfReader(str(chemin))
    pages: list[tuple[int, str]] = []
    for index, page in enumerate(lecteur.pages, start=1):
        texte = page.extract_text() or ""
        pages.append((index, texte.strip()))
    return pages


def _normaliser_typographie(texte: str) -> str:
    """Remplace les tirets typographiques et les espaces insecables.

    Les accents sont conserves : ils portent du sens dans le corpus
    (notamment pour les libelles de garanties et les noms de sections).
    """
    texte = texte.replace("\u00a0", " ").replace("\u202f", " ")
    texte = texte.replace("\u00ad", "")
    for tiret in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015"):
        texte = texte.replace(tiret, " - ")
    return texte


def _cle_normalisee(texte: str) -> str:
    """Cle de comparaison sans accents ni casse, mais texte source intact."""
    decompose = unicodedata.normalize("NFKD", texte)
    sans_accents = "".join(c for c in decompose if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sans_accents).strip().upper()


def _est_boilerplate(ligne: str) -> bool:
    if ligne.upper().startswith("DOCUMENT FICTIF"):
        return True
    if re.fullmatch(r"Page\s+\d+", ligne, flags=re.IGNORECASE):
        return True
    cle = _cle_normalisee(ligne)
    if "GUIDE DU RESEAU" in cle and "DONNEES FICTIVES" in cle:
        return True
    return cle in ENTETES_TABLEAU


def _nettoyer_lignes(texte: str) -> str:
    """Supprime le boilerplate ligne par ligne, en gardant la structure."""
    texte = _normaliser_typographie(texte)
    lignes: list[str] = []
    for brute in texte.splitlines():
        ligne = re.sub(r"\s+", " ", brute).strip()
        if not ligne or _est_boilerplate(ligne):
            continue
        lignes.append(ligne)
    return "\n".join(lignes)


def _nettoyer(texte: str) -> str:
    """Nettoyage complet : boilerplate, tirets et espaces ; accents conserves."""
    return re.sub(r"\s+", " ", _nettoyer_lignes(texte)).strip()


def _lignes_avec_pages(pages: list[tuple[int, str]]) -> list[tuple[int, str]]:
    lignes: list[tuple[int, str]] = []
    for page, texte in pages:
        for ligne in _nettoyer_lignes(texte).splitlines():
            if ligne:
                lignes.append((page, ligne))
    return lignes


def _bloc(lignes: list[str]) -> str:
    """Assemble des lignes deja nettoyees sans perdre les retours a la ligne."""
    return "\n".join(ligne.strip() for ligne in lignes if ligne.strip()).strip()


def _decouper_texte(
    texte: str, cible: int = TAILLE_CIBLE, chevauchement: int = CHEVAUCHEMENT
) -> list[str]:
    """Decoupe un texte en morceaux d'environ `cible` caracteres.

    Les coupures tombent de preference sur un espace pour ne pas tronquer un
    mot. `chevauchement` caracteres sont repris au debut du morceau suivant.
    """
    texte = re.sub(r"\s+", " ", texte).strip()
    if not texte:
        return []
    if len(texte) <= cible:
        return [texte]

    morceaux: list[str] = []
    debut = 0
    while debut < len(texte):
        fin = min(debut + cible, len(texte))
        if fin < len(texte):
            espace = texte.rfind(" ", debut + cible // 2, fin)
            if espace > debut:
                fin = espace
        morceau = texte[debut:fin].strip()
        if morceau:
            morceaux.append(morceau)
        if fin >= len(texte):
            break
        debut = max(fin - chevauchement, debut + 1)
        if debut < len(texte) and texte[debut - 1] != " ":
            espace = texte.find(" ", debut)
            if espace != -1:
                debut = espace + 1
    return morceaux


def _grouper_elements(elements: list[str], cible: int) -> list[str]:
    """Groupe des elements entiers (lignes ou entrees) sans les couper."""
    blocs: list[str] = []
    courant: list[str] = []
    taille = 0
    for element in elements:
        element = element.strip()
        if not element:
            continue
        if len(element) > cible:
            if courant:
                blocs.append("\n".join(courant))
                courant = []
                taille = 0
            blocs.extend(_decouper_texte(element, cible, 0))
            continue
        ajout = len(element) + (1 if courant else 0)
        if courant and taille + ajout > cible:
            blocs.append("\n".join(courant))
            courant = []
            taille = 0
            ajout = len(element)
        courant.append(element)
        taille += ajout
    if courant:
        blocs.append("\n".join(courant))
    return blocs


def _formule_depuis_nom(nom: str) -> str:
    for formule in ("PREMIUM", "CONFORT", "ESSENTIEL"):
        if formule in nom.upper():
            return formule
    return "INCONNU"


def _articles_avec_pages(pages: list[tuple[int, str]]) -> list[Article]:
    """Regroupe les lignes des Conditions Generales par article."""
    articles: list[Article] = []
    courant: Article | None = None
    for page, ligne in _lignes_avec_pages(pages):
        correspondance = re.match(r"Article\s+(\d+)\s*-\s*(.+)$", ligne, flags=re.IGNORECASE)
        if correspondance:
            if courant is not None:
                articles.append(courant)
            courant = Article(
                numero=int(correspondance.group(1)),
                titre=correspondance.group(2).strip(),
                page=page,
                lignes=[(page, ligne)],
            )
        elif courant is not None:
            courant.lignes.append((page, ligne))
    if courant is not None:
        articles.append(courant)
    return articles


def _decouper_par_type(
    article: Article,
) -> tuple[list[str], list[tuple[str, list[str]]], list[str]]:
    """Separe un article en (avant, entrees par type, apres).

    Certains articles listent des regles precedees d'un intitule seul sur sa
    ligne ("Optique", "Pharmacie", ...). Ce decoupage les isole : sans lui,
    une question sur un type de soins compete avec tous les autres dans le
    meme embedding, et le bon passage passe sous le seuil de similarite.
    """
    avant: list[str] = []
    entrees: list[tuple[str, list[str]]] = []
    apres: list[str] = []
    en_general = False
    for _, ligne in article.lignes[1:]:
        libelle = ligne.strip()
        if libelle in TYPES_SOINS and not en_general:
            entrees.append((libelle, []))
            continue
        if not entrees:
            avant.append(libelle)
            continue
        if RE_PHRASE_GENERALE.match(libelle):
            en_general = True
        if en_general:
            apres.append(libelle)
            continue
        entrees[-1][1].append(libelle)
    return avant, entrees, apres


def _segments_article_par_type(chemin: Path, formule: str, article: Article) -> list[Segment]:
    """Un segment par type de soins, plus un segment pour les regles generales.

    Renvoie une liste vide si l'article n'a pas cette structure : l'appelant
    garde alors le decoupage generique.
    """
    avant, entrees, apres = _decouper_par_type(article)
    if len(entrees) < 2:
        return []

    titre = f"Article {article.numero} - {article.titre}"[:128]
    contrat = f"{CONTRAT_CG} {formule}"
    segments: list[Segment] = []

    generales = [ligne for ligne in [*avant, *apres] if ligne.strip()]
    if generales:
        segments.append(
            Segment(
                contrat=contrat,
                contrat_id=None,
                article=titre,
                garantie="-",
                texte=_bloc([f"Formule {formule} - {titre}", *generales]),
                page=article.page,
                source_fichier=chemin.name,
            )
        )

    for libelle, contenu in entrees:
        corps = re.sub(r"\s+", " ", " ".join(contenu)).strip()
        if not corps:
            continue
        affiche = LIBELLES_ARTICLE_5.get(libelle, libelle).capitalize()
        segments.append(
            Segment(
                contrat=contrat,
                contrat_id=None,
                article=f"{titre} - {libelle}"[:128],
                garantie=libelle,
                texte=_bloc(
                    [
                        f"Formule {formule} - {titre} - {affiche}",
                        f"Pièces justificatives - {affiche} : {corps}",
                    ]
                ),
                page=article.page,
                source_fichier=chemin.name,
            )
        )
    return segments


def _segments_article_5(chemin: Path, formule: str, article: Article) -> list[Segment]:
    lignes = article.lignes
    # Le PDF coupe la phrase du plafond sur deux lignes : on aplatit les
    # espaces avant la recherche, sinon le plafond global reste introuvable.
    texte_entier = re.sub(r"\s+", " ", _bloc([ligne for _, ligne in lignes]))
    plafond_global = re.search(
        r"Plafond annuel global par bénéficiaire\s*:\s*([\d\s]+Ar)", texte_entier
    )
    if plafond_global is None:
        logger.warning("article5.plafond.introuvable", fichier=chemin.name)
        plafond = "non precise"
    else:
        plafond = plafond_global.group(1).strip()

    premiere_categorie = next(
        (index for index, (_, ligne) in enumerate(lignes) if ligne.strip() in CATEGORIES_ARTICLE_5),
        len(lignes),
    )
    intro = _nettoyer(" ".join(ligne for _, ligne in lignes[1:premiere_categorie]))
    if "Plafond annuel global" not in intro:
        intro = f"{intro} Plafond annuel global par bénéficiaire : {plafond}.".strip()

    segments: list[Segment] = [
        Segment(
            contrat=f"{CONTRAT_CG} {formule}",
            contrat_id=None,
            article="Article 5 - Tableau des garanties (vue globale)",
            garantie="Global",
            texte=_bloc(
                [
                    "Article 5 – Tableau des garanties (vue globale)",
                    f"Formule {formule}",
                    intro,
                ]
            ),
            page=article.page,
            source_fichier=chemin.name,
        )
    ]

    for index, (page, ligne) in enumerate(lignes):
        categorie = ligne.strip()
        if categorie not in CATEGORIES_ARTICLE_5:
            continue
        valeurs = [valeur for _, valeur in lignes[index + 1 : index + 6]]
        if len(valeurs) < 4:
            logger.warning("article5.ligne.incomplete", fichier=chemin.name, categorie=categorie)
            continue
        taux, plafond_categorie, franchise, carence = valeurs[:4]
        libelle = LIBELLES_ARTICLE_5[categorie]
        texte = _bloc(
            [
                f"Article 5 – Tableau des garanties – Formule {formule} – Catégorie {categorie}",
                f"Taux de remboursement {libelle} dans la formule {formule.lower()} : {taux}.",
                f"Plafond annuel : {plafond_categorie}. Franchise : {franchise}. "
                f"Délai de carence : {carence}. Carence : {carence}. "
                f"Plafond annuel global par bénéficiaire : {plafond}.",
            ]
        )
        segments.append(
            Segment(
                contrat=f"{CONTRAT_CG} {formule}",
                contrat_id=None,
                article="Article 5 - Tableau des garanties",
                garantie=categorie,
                texte=texte,
                page=page,
                source_fichier=chemin.name,
            )
        )
    return segments


def _carences_par_categorie(article: Article) -> dict[str, str]:
    """Extrait la duree de carence de chaque categorie de l'article 5."""
    carences: dict[str, str] = {}
    lignes = article.lignes
    for index, (_, ligne) in enumerate(lignes):
        categorie = ligne.strip()
        if categorie not in CATEGORIES_ARTICLE_5:
            continue
        valeurs = [valeur for _, valeur in lignes[index + 1 : index + 6]]
        if len(valeurs) >= 4:
            carences[categorie] = valeurs[3]
    return carences


def _segment_article_6_synthese(
    chemin: Path, formule: str, article: Article, carences: dict[str, str]
) -> Segment:
    """Resume les carences de toutes les categories dans un seul segment.

    L'article 6 du PDF ne contient aucune duree : il renvoie au tableau de
    l'article 5. Sans ce resume, une question sur la carence maternite ne
    trouve que des segments disperses, sous le seuil de similarite.
    """
    titre = "Article 6 - Délais de carence par catégorie"
    lignes = [
        f"Formule {formule} - {titre}",
        "Récapitulatif des délais de carence par catégorie de soins, "
        "à compter de la date d'adhésion de chaque bénéficiaire :",
    ]
    for categorie in CATEGORIES_ARTICLE_5:
        libelle = LIBELLES_ARTICLE_5[categorie].capitalize()
        carence = carences.get(categorie, "Aucune").strip()
        if carence.lower() in {"aucune", "aucun", "non", ""}:
            lignes.append(f"- {libelle} : aucune carence.")
        else:
            lignes.append(f"- {libelle} : {carence}.")
    return Segment(
        contrat=f"{CONTRAT_CG} {formule}",
        contrat_id=None,
        article=titre,
        garantie="-",
        texte=_bloc(lignes),
        page=article.page,
        source_fichier=chemin.name,
    )


def _segments_conditions_generales(chemin: Path, pages: list[tuple[int, str]]) -> list[Segment]:
    formule = _formule_depuis_nom(chemin.name)
    segments: list[Segment] = []
    articles = _articles_avec_pages(pages)
    carences: dict[str, str] = {}
    for article in articles:
        if article.numero == 5:
            carences = _carences_par_categorie(article)
            segments.extend(_segments_article_5(chemin, formule, article))
            continue

        segments_par_type = _segments_article_par_type(chemin, formule, article)
        if segments_par_type:
            segments.extend(segments_par_type)
            continue

        titre = f"Article {article.numero} - {article.titre}"[:128]
        prefixe = f"Formule {formule} - {titre}"
        corps = _bloc([ligne for _, ligne in article.lignes[1:]])
        texte_complet = _bloc([prefixe, corps])
        if len(texte_complet) <= TAILLE_ARTICLE:
            morceaux = [texte_complet]
        else:
            cible = max(200, TAILLE_ARTICLE - len(prefixe) - 1)
            morceaux = [f"{prefixe}\n{morceau}" for morceau in _decouper_texte(corps, cible)]

        for morceau in morceaux:
            if len(morceau) < 40:
                continue
            segments.append(
                Segment(
                    contrat=f"{CONTRAT_CG} {formule}",
                    contrat_id=None,
                    article=titre,
                    garantie="-",
                    texte=morceau,
                    page=article.page,
                    source_fichier=chemin.name,
                )
            )

    article_6 = next((article for article in articles if article.numero == 6), None)
    if article_6 is not None:
        segments.append(_segment_article_6_synthese(chemin, formule, article_6, carences))
    return segments


def _extraire(regex: str, texte: str, defaut: str = "non precise") -> str:
    correspondance = re.search(regex, texte, flags=re.IGNORECASE)
    return correspondance.group(1).strip() if correspondance else defaut


def _segments_conditions_particulieres(chemin: Path, pages: list[tuple[int, str]]) -> list[Segment]:
    lignes = _nettoyer_lignes("\n".join(contenu for _, contenu in pages)).splitlines()
    texte = re.sub(r"\s+", " ", " ".join(lignes)).strip()
    numero_contrat = _extraire(r"Contrat\s+(CTR-\d+)", texte, chemin.stem)
    police = _extraire(r"Police\s+([A-Z0-9-]+)", texte)
    formule = _extraire(r"Formule\s+([A-Z]+)", texte)
    souscripteur = _extraire(r"Souscripteur\s*:\s*(.+?)\s+Date d'effet", texte)
    date_police = _extraire(r"Date d'effet de la police\s*:\s*([0-9-]+)", texte)
    date_contrat = _extraire(r"Date d'effet du contrat\s*:\s*([0-9-]+)", texte)
    fin = _extraire(r"Fin\s*:\s*(.+?)\s+-\s+Statut", texte, "tacite reconduction")
    statut = _extraire(r"Statut\s*:\s*([A-Z]+)", texte)
    prime = _extraire(r"Prime annuelle\s*:\s*(.+?\.)", texte)
    plafond = _extraire(r"Plafond annuel global par bénéficiaire\s*:\s*([\d\s]+Ar)", texte)

    synthese = _bloc(
        [
            "Conditions particulieres - synthese",
            f"Contrat : {numero_contrat}",
            f"Police : {police}",
            f"Formule : {formule}",
            f"Souscripteur : {souscripteur}",
            f"Date d'effet de la police : {date_police}",
            f"Date d'effet du contrat : {date_contrat}",
            f"Fin : {fin}",
            f"Statut : {statut}",
            f"Prime annuelle : {prime}",
            f"Plafond annuel global par bénéficiaire : {plafond}",
            "Les garanties, exclusions et procedures sont celles des "
            f"{CONTRAT_CG} de la formule {formule}.",
        ]
    )

    beneficiaires: list[str] = []
    index = 0
    while index < len(lignes):
        ligne = lignes[index]
        if re.fullmatch(r"ASS-[A-Z0-9]+", ligne):
            champs = lignes[index + 1 : index + 6]
            if len(champs) == 5:
                index += 6
                rang, sexe, annee, adhesion, radiation = champs
                if (
                    rang not in RANGS_BENEFICIAIRE
                    or sexe not in SEXES_BENEFICIAIRE
                    or not annee.isdigit()
                ):
                    logger.warning(
                        "cp.beneficiaire.invalide",
                        fichier=chemin.name,
                        identifiant=ligne,
                    )
                    continue
                beneficiaires.append(
                    f"{ligne} | Rang : {rang} | Sexe : {sexe} | "
                    f"Année naiss. : {annee} | Adhésion : {adhesion} | "
                    f"Radiation : {radiation}"
                )
                continue
        index += 1

    beneficiaires_texte = _bloc(
        [
            "Conditions particulieres - beneficiaires",
            f"Contrat : {numero_contrat}",
            "Bénéficiaires (identifiants pseudonymisés) :",
            *beneficiaires,
        ]
    )

    return [
        Segment(
            contrat=numero_contrat,
            contrat_id=None,
            article="Conditions particulieres - synthese",
            garantie="-",
            texte=synthese,
            page=1,
            source_fichier=chemin.name,
        ),
        Segment(
            contrat=numero_contrat,
            contrat_id=None,
            article="Conditions particulieres - beneficiaires",
            garantie="-",
            texte=beneficiaires_texte,
            page=1,
            source_fichier=chemin.name,
        ),
    ]


def _segments_bareme(chemin: Path, pages: list[tuple[int, str]]) -> list[Segment]:
    motif_code = re.compile(r"^(?:(?:CONS|IMG|LAB|KINE|DENT|OPT|HOSP|ACC|MED)-[A-Z0-9]+|DIALYSE)$")
    lignes = _lignes_avec_pages(pages)
    lignes_par_categorie: dict[str, list[tuple[int, str]]] = {}

    ligne_courante: list[str] = []
    page_courante = 1

    def _enregistrer() -> None:
        if not ligne_courante:
            return
        categorie = "MEDICAMENTS"
        for valeur in ligne_courante[1:]:
            cle = _cle_normalisee(valeur)
            if cle in CATEGORIES_BAREME:
                categorie = cle
                break
        lignes_par_categorie.setdefault(categorie, []).append(
            (page_courante, " | ".join(ligne_courante))
        )

    for page, ligne in lignes:
        if motif_code.match(ligne):
            _enregistrer()
            ligne_courante = [ligne]
            page_courante = page
        elif ligne_courante:
            ligne_courante.append(ligne)
    _enregistrer()

    segments: list[Segment] = []
    for categorie, rangees in lignes_par_categorie.items():
        prefixe = f"Barème de référence des actes – {categorie}"
        cible = max(120, TAILLE_CIBLE - len(prefixe) - 1)
        blocs = _grouper_elements([contenu for _, contenu in rangees], cible)
        for bloc in blocs:
            segments.append(
                Segment(
                    contrat=chemin.stem,
                    contrat_id=None,
                    article=f"Barème - {categorie}"[:128],
                    garantie=categorie,
                    texte=f"{prefixe}\n{bloc}",
                    page=rangees[0][0],
                    source_fichier=chemin.name,
                )
            )
    return segments


def _entrees_guide(lignes: list[str]) -> list[str]:
    """Regroupe les lignes d'une section en entrees (index, nom, adresse...)."""
    entrees: list[str] = []
    courante: list[str] = []
    for ligne in lignes:
        if re.fullmatch(r"\d{1,3}", ligne) and courante:
            entrees.append("\n".join(courante))
            courante = [ligne]
        else:
            courante.append(ligne)
    if courante:
        entrees.append("\n".join(courante))
    return entrees


def _segments_guide(chemin: Path, pages: list[tuple[int, str]]) -> list[Segment]:
    sections: list[SectionGuide] = []
    courante: SectionGuide | None = None
    for page, ligne in _lignes_avec_pages(pages):
        cle = _cle_normalisee(ligne)
        if cle in SECTIONS_GUIDE:
            titre = SECTIONS_GUIDE[cle]
            if courante is not None and courante.cle == cle:
                # Titre repete apres un saut de page : la section continue.
                continue
            courante = SectionGuide(cle=cle, titre=titre, page=page)
            sections.append(courante)
        elif courante is not None:
            courante.lignes.append((page, ligne))

    segments: list[Segment] = []
    for section in sections:
        titre = section.titre
        lignes = [ligne for _, ligne in section.lignes]
        premiere_entree = next(
            (index for index, ligne in enumerate(lignes) if re.fullmatch(r"\d{1,3}", ligne)),
            len(lignes),
        )
        intro = lignes[:premiere_entree]
        entrees = _entrees_guide(lignes[premiere_entree:]) if premiere_entree < len(lignes) else []

        prefixe = titre
        if intro:
            prefixe = f"{titre}\n{_bloc(intro)}"
        cible = max(120, TAILLE_CIBLE - len(prefixe) - 1)

        if entrees:
            elements = entrees
        else:
            # Section sans tableau (contacts) : le contenu est son propre texte.
            elements = intro
            prefixe = titre
            cible = max(120, TAILLE_CIBLE - len(prefixe) - 1)

        for bloc in _grouper_elements(elements, cible):
            segments.append(
                Segment(
                    contrat=chemin.stem,
                    contrat_id=None,
                    article=f"Guide - {titre}"[:128],
                    garantie=titre,
                    texte=f"{prefixe}\n{bloc}" if bloc != prefixe else bloc,
                    page=section.page,
                    source_fichier=chemin.name,
                )
            )
    return segments


def _segments_generique(chemin: Path, pages: list[tuple[int, str]]) -> list[Segment]:
    texte = _nettoyer("\n".join(contenu for _, contenu in pages))
    segments: list[Segment] = []
    for index, morceau in enumerate(_decouper_texte(texte), start=1):
        if len(morceau) < 40:
            continue
        segments.append(
            Segment(
                contrat=chemin.stem,
                contrat_id=None,
                article=f"Section {index}",
                garantie="-",
                texte=morceau,
                page=None,
                source_fichier=chemin.name,
            )
        )
    return segments


def _segments_pour_fichier(chemin: Path) -> list[Segment]:
    pages = _lire_pdf(chemin)
    nom = chemin.name
    if nom.startswith("Conditions_Generales"):
        segments = _segments_conditions_generales(chemin, pages)
    elif nom.startswith("CP_") or "conditions_particulieres" in str(chemin):
        segments = _segments_conditions_particulieres(chemin, pages)
    elif nom.startswith("Bareme_Reference"):
        segments = _segments_bareme(chemin, pages)
    elif nom.startswith("Guide_Reseau"):
        segments = _segments_guide(chemin, pages)
    else:
        segments = _segments_generique(chemin, pages)

    if not segments:
        logger.warning("pdf.aucun_segment", fichier=chemin.name, pages=len(pages))
        segments = _segments_generique(chemin, pages)
    return segments


def _resoudre_contrat_id(session: Session, numero: str) -> int | None:
    if not numero.startswith("CTR-"):
        return None
    row = session.execute(
        text("SELECT id FROM core.contrat WHERE numero = :numero LIMIT 1"),
        {"numero": numero},
    ).scalar()
    return int(row) if row is not None else None


def _embedder() -> OpenAIEmbeddings:
    from langchain_openai import OpenAIEmbeddings

    settings = get_settings()
    cle = settings.embedding_api_key
    if not cle:
        raise RuntimeError("EMBEDDING_API_KEY manquante : impossible de calculer les embeddings.")
    return OpenAIEmbeddings(
        base_url=settings.embedding_api_base or None,
        api_key=SecretStr(cle),
        model=settings.embedding_model,
    )


def collecter_segments(corpus_dir: Path) -> list[Segment]:
    segments: list[Segment] = []
    for chemin in sorted(corpus_dir.rglob("*.pdf")):
        try:
            segments.extend(_segments_pour_fichier(chemin))
        except Exception as exc:
            logger.warning("pdf.erreur", fichier=str(chemin), erreur=str(exc))
    # Resolution des contrat_id : une seule lecture pour tous les contrats.
    if any(seg.contrat.startswith("CTR-") for seg in segments):
        with session_scope() as session:
            for seg in segments:
                if seg.contrat.startswith("CTR-"):
                    seg.contrat_id = _resoudre_contrat_id(session, seg.contrat)
    return segments


def appliquer(
    corpus_dir: Path,
    force: bool = False,
    segments: list[Segment] | None = None,
) -> dict[str, int | bool]:
    # L'idempotence se decide AVANT de parser le corpus : une relance sans
    # `--force` ne doit ni relire les PDF ni ouvrir de transaction d'ecriture.
    with session_scope() as session:
        existants = int(
            session.execute(text("SELECT count(*) FROM core.document_vectorise")).scalar() or 0
        )
        if existants and not force:
            logger.info("ingestion.ignoree", existants=existants)
            return {"segments": 0, "ignores": existants, "force": force}

    if segments is None:
        segments = collecter_segments(corpus_dir)
    logger.info("ingestion.segments", nombre=len(segments))

    if not segments:
        logger.error("ingestion.aucun_segment", corpus=str(corpus_dir))
        return {"segments": 0, "ignores": existants, "force": force}

    # Une seule transaction pour tout l'index : en cas d'echec, aucun lot
    # partiel ne subsiste et une relance sans --force ne prend pas cet index
    # incomplet pour un index complet.
    with session_scope() as session:
        if force and existants:
            session.execute(text("TRUNCATE core.document_vectorise RESTART IDENTITY"))

        embedder = _embedder()
        modeles = get_settings().embedding_model
        inseres = 0
        for debut in range(0, len(segments), BATCH_SIZE):
            lot = segments[debut : debut + BATCH_SIZE]
            vecteurs = embedder.embed_documents([s.texte for s in lot])
            for seg, vecteur in zip(lot, vecteurs, strict=True):
                session.execute(
                    text(
                        """
                        INSERT INTO core.document_vectorise
                            (contrat_id, contrat, article, garantie, texte, page,
                             embedding, modele_embedding, source_fichier)
                        VALUES
                            (:contrat_id, :contrat, :article, :garantie, :texte, :page,
                             :embedding, :modele, :source_fichier)
                        """
                    ),
                    {
                        "contrat_id": seg.contrat_id,
                        "contrat": seg.contrat,
                        "article": seg.article,
                        "garantie": seg.garantie,
                        "texte": seg.texte,
                        "page": seg.page,
                        "embedding": str(vecteur),
                        "modele": modeles,
                        "source_fichier": seg.source_fichier,
                    },
                )
                inseres += 1
            logger.info("ingestion.lot", debut=debut, taille=len(lot))

    return {"segments": inseres, "ignores": 0, "force": force}


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingestion RAG")
    parser.add_argument("--corpus-dir", default=CORPUS_DEFAULT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    configure_logging("seed.ingest_rag", get_settings().log_level, get_settings().log_format)
    corpus = Path(args.corpus_dir)
    if not corpus.exists():
        print(f"Corpus introuvable : {corpus}", file=sys.stderr)
        sys.exit(1)

    if args.apply and not args.dry_run:
        print(appliquer(corpus, force=args.force))
        return

    segments = collecter_segments(corpus)
    print(f"Segments detectes : {len(segments)}")
    if segments:
        print("Exemple :")
        print(asdict(segments[0]))


if __name__ == "__main__":
    main()
