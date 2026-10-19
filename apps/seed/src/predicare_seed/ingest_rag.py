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
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import text

from predicare.config import get_settings
from predicare.db import session_scope
from predicare.logging_config import configure_logging, get_logger

logger = get_logger("seed.ingest_rag")

CORPUS_DEFAULT = os.getenv("RAG_CORPUS_DIR", "/data/rag_corpus")
BATCH_SIZE = 64
TAILLE_CIBLE = 450  # caracteres approximatifs par segment generique
TAILLE_ARTICLE = 800  # plafond demande pour les articles des CG
CHEVAUCHEMENT = 50

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
}


@dataclass
class Segment:
    contrat: str
    contrat_id: int | None
    article: str
    garantie: str
    texte: str
    page: int | None
    source_fichier: str


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
    """Nettoyage complet : boilerplate, tirets, espaces et accents."""
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


def _decouper_texte(texte: str, cible: int = TAILLE_CIBLE, chevauchement: int = CHEVAUCHEMENT) -> list[str]:
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


def _articles_avec_pages(
    pages: list[tuple[int, str]],
) -> list[dict[str, object]]:
    """Regroupe les lignes des Conditions Generales par article."""
    articles: list[dict[str, object]] = []
    courant: dict[str, object] | None = None
    for page, ligne in _lignes_avec_pages(pages):
        correspondance = re.match(r"Article\s+(\d+)\s*-\s*(.+)$", ligne, flags=re.IGNORECASE)
        if correspondance:
            if courant is not None:
                articles.append(courant)
            courant = {
                "numero": int(correspondance.group(1)),
                "titre": correspondance.group(2).strip(),
                "page": page,
                "lignes": [(page, ligne)],
            }
        elif courant is not None:
            courant["lignes"].append((page, ligne))  # type: ignore[union-attr]
    if courant is not None:
        articles.append(courant)
    return articles


def _segments_article_5(
    chemin: Path,
    formule: str,
    article: dict[str, object],
) -> list[Segment]:
    lignes: list[tuple[int, str]] = article["lignes"]  # type: ignore[assignment]
    texte_entier = _bloc([ligne for _, ligne in lignes])
    plafond_global = re.search(
        r"Plafond annuel global par bénéficiaire\s*:\s*([\d\s]+Ar)", texte_entier
    )
    plafond = plafond_global.group(1).strip() if plafond_global else "non precise"

    premiere_categorie = next(
        (
            index
            for index, (_, ligne) in enumerate(lignes)
            if ligne.strip() in CATEGORIES_ARTICLE_5
        ),
        len(lignes),
    )
    intro = _nettoyer(" ".join(ligne for _, ligne in lignes[1:premiere_categorie]))
    if "Plafond annuel global" not in intro:
        intro = f"{intro} Plafond annuel global par bénéficiaire : {plafond}.".strip()

    segments: list[Segment] = [
        Segment(
            contrat=f"Conditions Generales {formule}",
            contrat_id=None,
            article="Article 5 - Tableau des garanties (vue globale)",
            garantie="Global",
            texte=_bloc(
                [
                    "Article 5 – Tableau des garanties (vue globale)",
                    intro,
                ]
            ),
            page=int(article["page"]),  # type: ignore[arg-type]
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
                f"Carence : {carence}. Plafond annuel global par bénéficiaire : {plafond}.",
            ]
        )
        segments.append(
            Segment(
                contrat=f"Conditions Generales {formule}",
                contrat_id=None,
                article="Article 5 - Tableau des garanties",
                garantie=categorie,
                texte=texte,
                page=page,
                source_fichier=chemin.name,
            )
        )
    return segments


def _segments_conditions_generales(
    chemin: Path, pages: list[tuple[int, str]]
) -> list[Segment]:
    formule = _formule_depuis_nom(chemin.name)
    segments: list[Segment] = []
    for article in _articles_avec_pages(pages):
        if int(article["numero"]) == 5:  # type: ignore[arg-type]
            segments.extend(_segments_article_5(chemin, formule, article))
            continue

        lignes: list[tuple[int, str]] = article["lignes"]  # type: ignore[assignment]
        titre = f"Article {article['numero']} - {article['titre']}"[:128]
        corps = _bloc([ligne for _, ligne in lignes[1:]])
        texte_complet = _bloc([titre, corps])
        if len(texte_complet) <= TAILLE_ARTICLE:
            morceaux = [texte_complet]
        else:
            cible = max(200, TAILLE_ARTICLE - len(titre) - 1)
            morceaux = [f"{titre}\n{morceau}" for morceau in _decouper_texte(corps, cible)]

        for morceau in morceaux:
            if len(morceau) < 40:
                continue
            segments.append(
                Segment(
                    contrat=f"Conditions Generales {formule}",
                    contrat_id=None,
                    article=titre,
                    garantie="-",
                    texte=morceau,
                    page=int(article["page"]),  # type: ignore[arg-type]
                    source_fichier=chemin.name,
                )
            )
    return segments


def _extraire(regex: str, texte: str, defaut: str = "non precise") -> str:
    correspondance = re.search(regex, texte, flags=re.IGNORECASE)
    return correspondance.group(1).strip() if correspondance else defaut


def _segments_conditions_particulieres(
    chemin: Path, pages: list[tuple[int, str]]
) -> list[Segment]:
    texte = _nettoyer("\n".join(contenu for _, contenu in pages))
    numero_contrat = _extraire(r"Contrat\s+(CTR-\d+)", texte, chemin.stem)
    police = _extraire(r"Police\s+([A-Z0-9-]+)", texte)
    formule = _extraire(r"Formule\s+([A-Z]+)", texte)
    souscripteur = _extraire(r"Souscripteur\s*:\s*(.+?)\s+Date d'effet", texte)
    date_police = _extraire(r"Date d'effet de la police\s*:\s*([0-9-]+)", texte)
    date_contrat = _extraire(r"Date d'effet du contrat\s*:\s*([0-9-]+)", texte)
    fin = _extraire(r"Fin\s*:\s*(.+?)\s+-\s+Statut", texte, "tacite reconduction")
    statut = _extraire(r"Statut\s*:\s*([A-Z]+)", texte)
    prime = _extraire(r"Prime annuelle\s*:\s*(.+?\.)", texte)
    plafond = _extraire(
        r"Plafond annuel global par bénéficiaire\s*:\s*([\d\s]+Ar)", texte
    )

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
            f"Conditions Generales de la formule {formule}.",
        ]
    )

    lignes = [ligne for _, contenu in pages for ligne in _nettoyer_lignes(contenu).splitlines()]
    beneficiaires: list[str] = []
    index = 0
    while index < len(lignes):
        ligne = lignes[index]
        if re.fullmatch(r"ASS-[A-Z0-9]+", ligne):
            champs = lignes[index + 1 : index + 6]
            if len(champs) == 5:
                rang, sexe, annee, adhesion, radiation = champs
                beneficiaires.append(
                    f"{ligne} | Rang : {rang} | Sexe : {sexe} | "
                    f"Année naiss. : {annee} | Adhésion : {adhesion} | "
                    f"Radiation : {radiation}"
                )
                index += 6
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
    motif_code = re.compile(
        r"^(?:(?:CONS|IMG|LAB|KINE|DENT|OPT|HOSP|ACC|MED)-[A-Z0-9]+|DIALYSE)$"
    )
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
    sections: list[dict[str, object]] = []
    courante: dict[str, object] | None = None
    for page, ligne in _lignes_avec_pages(pages):
        cle = _cle_normalisee(ligne)
        if cle in SECTIONS_GUIDE:
            titre = SECTIONS_GUIDE[cle]
            if courante is not None and courante["cle"] == cle:
                # Titre repete apres un saut de page : la section continue.
                continue
            courante = {
                "cle": cle,
                "titre": titre,
                "page": page,
                "lignes": [],
            }
            sections.append(courante)
        elif courante is not None:
            courante["lignes"].append((page, ligne))  # type: ignore[union-attr]

    segments: list[Segment] = []
    for section in sections:
        titre = str(section["titre"])
        contenu: list[tuple[int, str]] = section["lignes"]  # type: ignore[assignment]
        lignes = [ligne for _, ligne in contenu]
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
                    page=int(section["page"]),  # type: ignore[arg-type]
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
        return _segments_conditions_generales(chemin, pages)
    if nom.startswith("CP_") or "conditions_particulieres" in str(chemin):
        return _segments_conditions_particulieres(chemin, pages)
    if nom.startswith("Bareme_Reference"):
        return _segments_bareme(chemin, pages)
    if nom.startswith("Guide_Reseau"):
        return _segments_guide(chemin, pages)
    return _segments_generique(chemin, pages)


def _resoudre_contrat_id(session, numero: str) -> int | None:
    if not numero.startswith("CTR-"):
        return None
    row = session.execute(
        text("SELECT id FROM core.contrat WHERE numero = :numero LIMIT 1"),
        {"numero": numero},
    ).scalar()
    return int(row) if row is not None else None


def _embedder():
    from langchain_openai import OpenAIEmbeddings

    settings = get_settings()
    return OpenAIEmbeddings(
        base_url=settings.embedding_api_base or None,
        api_key=settings.embedding_api_key or "not-configured",
        model=settings.embedding_model,
    )


def collecter_segments(corpus_dir: Path) -> list[Segment]:
    segments: list[Segment] = []
    for chemin in sorted(corpus_dir.rglob("*.pdf")):
        try:
            segs = _segments_pour_fichier(chemin)
            for seg in segs:
                seg.contrat_id = None
            segments.extend(segs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pdf.erreur", fichier=str(chemin), erreur=str(exc))
    # Resolution des contrat_id.
    with session_scope() as session:
        for seg in segments:
            if seg.contrat.startswith("CTR-"):
                seg.contrat_id = _resoudre_contrat_id(session, seg.contrat)
    return segments


def appliquer(corpus_dir: Path, force: bool = False) -> dict:
    segments = collecter_segments(corpus_dir)
    logger.info("ingestion.segments", nombre=len(segments))

    with session_scope() as session:
        existants = session.execute(
            text("SELECT count(*) FROM core.document_vectorise")
        ).scalar() or 0
        if existants and not force:
            logger.info("ingestion.ignoree", existants=existants)
            return {"segments": 0, "ignores": existants, "force": force}

        if force and existants:
            session.execute(text("TRUNCATE core.document_vectorise RESTART IDENTITY"))
            session.commit()

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
            session.commit()
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

    segments = collecter_segments(corpus)
    print(f"Segments detectes : {len(segments)}")
    if segments:
        print("Exemple :")
        print(segments[0].__dict__)

    if args.dry_run or not args.apply:
        return

    resultat = appliquer(corpus, force=args.force)
    print(resultat)


if __name__ == "__main__":
    main()
