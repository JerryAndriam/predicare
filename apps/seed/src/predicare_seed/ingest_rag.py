"""Ingestion du corpus de contrats PDF dans `core.document_vectorise`.

Phase 5.1 et 5.2 du plan d'action. Decoupe les PDF en segments, calcule
les embeddings et les indexe dans pgvector. Le module est idempotent :
relance sans `--force` ne fait rien si la table est deja peuplee.

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
TAILLE_CIBLE = 700  # caracteres approximatifs par segment


@dataclass
class Segment:
    contrat: str
    contrat_id: int | None
    article: str
    garantie: str
    texte: str
    page: int | None
    source: str


def _lire_pdf(chemin: Path) -> list[tuple[int, str]]:
    lecteur = PdfReader(str(chemin))
    pages: list[tuple[int, str]] = []
    for index, page in enumerate(lecteur.pages, start=1):
        texte = page.extract_text() or ""
        pages.append((index, texte.strip()))
    return pages


def _nettoyer(texte: str) -> str:
    texte = re.sub(r"\s+", " ", texte)
    return texte.strip()


def _formule_depuis_nom(nom: str) -> str:
    for formule in ("PREMIUM", "CONFORT", "ESSENTIEL"):
        if formule in nom.upper():
            return formule
    return "INCONNU"


def _segments_conditions_generales(chemin: Path, pages: list[tuple[int, str]]) -> list[Segment]:
    formule = _formule_depuis_nom(chemin.name)
    texte_complet = "\n".join(f"{t}" for _, t in pages)
    # Decoupage par article.
    morceaux = re.split(r"(?=Article\s+\d+\s*[–-])", texte_complet)
    segments: list[Segment] = []
    page_courante = 1
    for morceau in morceaux:
        morceau = morceau.strip()
        if not morceau or len(morceau) < 40:
            continue
        match = re.match(r"Article\s+(\d+)\s*[–-]\s*(.+?)(?:\n|$)", morceau)
        numero = match.group(1) if match else "?"
        titre = match.group(2).strip() if match else "Sans titre"
        article = f"Article {numero} - {titre}"[:128]
        # Garantie detectee dans le titre ou le debut du segment.
        garantie = "-"
        for cat in ("Consultation", "Pharmacie", "Laboratoire", "Imagerie",
                    "Hospitalisation", "Maternite", "Dentaire", "Optique",
                    "Kinesitherapie"):
            if cat.lower() in morceau.lower()[:200]:
                garantie = cat
                break
        segments.append(
            Segment(
                contrat=f"Conditions Generales {formule}",
                contrat_id=None,
                article=article,
                garantie=garantie,
                texte=_nettoyer(morceau)[:1200],
                page=page_courante,
                source=chemin.name,
            )
        )
    return segments


def _segments_conditions_particulieres(chemin: Path, pages: list[tuple[int, str]]) -> list[Segment]:
    texte = _nettoyer("\n".join(t for _, t in pages))
    # Numero de contrat dans le nom de fichier : CP_CTR-000048.pdf
    match = re.search(r"CTR-\d+", chemin.name)
    numero_contrat = match.group(0) if match else chemin.stem
    return [
        Segment(
            contrat=numero_contrat,
            contrat_id=None,
            article="Conditions particulieres",
            garantie="-",
            texte=texte[:1200],
            page=1,
            source=chemin.name,
        )
    ]


def _segments_generique(chemin: Path, pages: list[tuple[int, str]]) -> list[Segment]:
    morceaux: list[str] = []
    buffer = ""
    for _, texte in pages:
        for paragraphe in texte.split("\n"):
            paragraphe = paragraphe.strip()
            if not paragraphe:
                continue
            if len(buffer) + len(paragraphe) > TAILLE_CIBLE:
                if buffer:
                    morceaux.append(buffer.strip())
                buffer = paragraphe
            else:
                buffer = (buffer + " " + paragraphe).strip()
    if buffer:
        morceaux.append(buffer.strip())

    segments: list[Segment] = []
    for i, morceau in enumerate(morceaux, start=1):
        if len(morceau) < 40:
            continue
        segments.append(
            Segment(
                contrat=chemin.stem,
                contrat_id=None,
                article=f"Section {i}",
                garantie="-",
                texte=_nettoyer(morceau)[:1200],
                page=None,
                source=chemin.name,
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
                             embedding, modele_embedding)
                        VALUES
                            (:contrat_id, :contrat, :article, :garantie, :texte, :page,
                             :embedding, :modele)
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