"""Scoring en lot des factures deja presentes en base.

Deux usages, volontairement separes :

* ``historique`` : rejoue les factures etiquetees du jeu de depart. Les scores
  portent le statut ``historique`` et la date de la facture ; ils alimentent
  les graphiques mensuels sans jamais envahir la file d'alertes. Le rejeu est
  idempotent (``WHERE NOT EXISTS``).
* ``nouvelles`` : note les factures importees le jour J. Les scores portent le
  statut ``nouvelle`` et entrent dans la file du gestionnaire.

Le lot utilise le meme modele, les memes referentiels et la meme
featurisation que ``POST /api/inference/predire``. Le contexte (ordonnance,
contrat, profil assure) est precharge une fois : sur 84 000 factures, sept
requetes par facture transformeraient le backfill en dizaines de minutes.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import cast

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from predicare.config import get_settings
from predicare.db import dispose_engine, session_scope
from predicare.features import Contrat, Ordonnance, Referentiels
from predicare.persistance_ml import (
    lire_seuil_effectif,
    stocker_prediction,
    stocker_prediction_historique,
)
from predicare.schemas import InvoiceLine, InvoiceSubmission
from predicare_inference_api.explainability import shap_to_contributions
from predicare_inference_api.features import build_features
from predicare_inference_api.registry import ModelRegistry

PERIODE_MAX_ORDONNANCE_JOURS = 730
TAILLE_LOT_SCORING = 2048
TAILLE_LOT_SHAP = 512
GARDE_NOUVELLES = 200


@dataclass(slots=True)
class FactureANoter:
    id: int
    reference: str
    pseudonyme: str
    prestataire_code: str
    assure_id: int
    prestataire_db_id: int
    date_facture: datetime
    montant_total: float
    date_soin: datetime | None = None
    heure_soin: str | None = None
    ordonnance_db_id: int | None = None
    contrat_numero: str | None = None
    lignes: list[InvoiceLine] = field(default_factory=list)


@dataclass(slots=True)
class ContextePrecharge:
    profils: dict[int, tuple[int | None, str]] = field(default_factory=dict)
    contrats: dict[int, list[tuple[date, date | None, str]]] = field(default_factory=dict)
    ordonnances: dict[tuple[int, int], list[tuple[int, date, int, int]]] = field(
        default_factory=dict
    )
    ordonnances_par_id: dict[int, Ordonnance] = field(default_factory=dict)
    codes: dict[int, frozenset[str]] = field(default_factory=dict)
    prestataires: dict[int, str] = field(default_factory=dict)


def _heure(valeur: object) -> int | None:
    """Heure d'une colonne `HH:MM`, comme le chargeur d'entrainement."""
    texte = str(valeur or "").strip()
    for gabarit in ("%H:%M", "%H:%M:%S", "%Hh%M"):
        try:
            return datetime.strptime(texte, gabarit).hour
        except ValueError:
            continue
    return None


def _date_acte(facture: FactureANoter, brut: datetime) -> datetime:
    """Horodatage du soin, comme `dataset.py` le construit a l'entrainement.

    La graine stocke `date_acte` a minuit et garde l'heure dans
    `core.facture.heure_soin` : sans cette recomposition, la variable
    `soin_hors_horaire` divergeait de l'entrainement et le backfill alertait
    six fois trop.
    """
    if facture.date_soin is None:
        return brut
    jour = facture.date_soin.date()
    return datetime(jour.year, jour.month, jour.day, _heure(facture.heure_soin) or 0)


def _compter_a_noter(session: Session, *, historiques: bool) -> int:
    condition = (
        "EXISTS (SELECT 1 FROM ml.label_fraude l WHERE l.facture_id = f.id)"
        if historiques
        else "TRUE"
    )
    return int(
        session.execute(
            text(
                f"""
                SELECT count(*)
                FROM core.facture f
                WHERE {condition}
                  AND NOT EXISTS (
                      SELECT 1 FROM ml.prediction p WHERE p.facture_id = f.id
                  )
                """
            )
        ).scalar_one()
    )


def _charger_ids(session: Session, *, historiques: bool, limite: int | None) -> list[int]:
    condition = (
        "EXISTS (SELECT 1 FROM ml.label_fraude l WHERE l.facture_id = f.id)"
        if historiques
        else "TRUE"
    )
    clause_limite = f"LIMIT {int(limite)}" if limite else ""
    return [
        row.id
        for row in session.execute(
            text(
                f"""
                SELECT f.id
                FROM core.facture f
                WHERE {condition}
                  AND NOT EXISTS (
                      SELECT 1 FROM ml.prediction p WHERE p.facture_id = f.id
                  )
                ORDER BY f.id
                {clause_limite}
                """
            )
        )
    ]


def _charger_factures(session: Session, ids: list[int]) -> list[FactureANoter]:
    if not ids:
        return []
    rows = session.execute(
        text(
            """
            SELECT f.id, f.reference, a.pseudonyme, p.code AS prestataire_code,
                   f.assure_id, f.prestataire_id AS prestataire_db_id,
                   f.date_facture, f.date_soin, f.heure_soin,
                   f.montant_total, f.ordonnance_id, c.numero AS contrat_numero,
                   COALESCE(ac.code, me.code) AS code,
                   lf.quantite, lf.montant_unitaire, lf.date_acte
            FROM core.facture f
            JOIN core.assure a ON a.id = f.assure_id
            JOIN core.prestataire p ON p.id = f.prestataire_id
            JOIN core.ligne_facture lf ON lf.facture_id = f.id
            LEFT JOIN core.acte ac ON ac.id = lf.acte_id
            LEFT JOIN core.medicament me ON me.id = lf.medicament_id
            LEFT JOIN core.contrat c ON c.id = f.contrat_id
            WHERE f.id = ANY(:ids)
            ORDER BY f.id, lf.num_ligne NULLS LAST, lf.id
            """
        ),
        {"ids": ids},
    ).fetchall()

    factures: dict[int, FactureANoter] = {}
    for row in rows:
        facture = factures.get(row.id)
        if facture is None:
            facture = FactureANoter(
                id=row.id,
                reference=row.reference,
                pseudonyme=row.pseudonyme,
                prestataire_code=row.prestataire_code,
                assure_id=row.assure_id,
                prestataire_db_id=row.prestataire_db_id,
                date_facture=row.date_facture,
                montant_total=float(row.montant_total),
                date_soin=row.date_soin,
                heure_soin=row.heure_soin,
                ordonnance_db_id=row.ordonnance_id,
                contrat_numero=row.contrat_numero,
            )
            factures[row.id] = facture
        facture.lignes.append(
            InvoiceLine(
                code_acte=row.code,
                quantite=row.quantite,
                montant_unitaire=float(row.montant_unitaire),
                date_acte=_date_acte(facture, row.date_acte),
            )
        )
    return list(factures.values())


def _charger_contexte(session: Session) -> ContextePrecharge:
    contexte = ContextePrecharge()

    for row in session.execute(text("SELECT id, annee_naissance, sexe FROM core.assure")):
        contexte.profils[row.id] = (row.annee_naissance, row.sexe or "")

    for row in session.execute(
        text(
            """
            SELECT cb.assure_id, c.date_debut, c.date_fin, c.niveau
            FROM core.contrat_beneficiaire cb
            JOIN core.contrat c ON c.id = cb.contrat_id
            ORDER BY cb.assure_id, c.date_debut DESC
            """
        )
    ):
        contexte.contrats.setdefault(row.assure_id, []).append(
            (row.date_debut, row.date_fin, row.niveau or "")
        )

    for row in session.execute(
        text(
            """
            SELECT id, assure_id, prestataire_id, date_ordonnance, validite_jours
            FROM core.ordonnance
            ORDER BY assure_id, prestataire_id, date_ordonnance DESC
            """
        )
    ):
        contexte.ordonnances.setdefault((row.assure_id, row.prestataire_id), []).append(
            (
                row.id,
                row.date_ordonnance.date(),
                int(row.validite_jours or 0),
                row.prestataire_id,
            )
        )

    codes: dict[int, set[str]] = {}
    for row in session.execute(
        text(
            """
            SELECT ol.ordonnance_id, COALESCE(a.code, m.code) AS code
            FROM core.ordonnance_ligne ol
            LEFT JOIN core.acte a ON a.id = ol.acte_id
            LEFT JOIN core.medicament m ON m.id = ol.medicament_id
            WHERE COALESCE(a.code, m.code) IS NOT NULL
            """
        )
    ):
        codes.setdefault(row.ordonnance_id, set()).add(row.code)
    contexte.codes = {k: frozenset(v) for k, v in codes.items()}

    for row in session.execute(text("SELECT id, code FROM core.prestataire")):
        contexte.prestataires[row.id] = row.code

    # Ordonnance par identifiant technique : c'est celle que la facture
    # reference explicitement. La resolution par assure + prestataire + date
    # reste le chemin des factures SANS lien (celles du jour J).
    for row in session.execute(
        text(
            """
            SELECT id, date_ordonnance, validite_jours, prestataire_id
            FROM core.ordonnance
            """
        )
    ):
        contexte.ordonnances_par_id[row.id] = Ordonnance(
            prescripteur_id=contexte.prestataires.get(row.prestataire_id, ""),
            date_prescription=row.date_ordonnance.date(),
            validite_jours=int(row.validite_jours or 0),
            codes_prescrits=contexte.codes.get(row.id, frozenset()),
        )

    return contexte


def _resoudre_ordonnance(
    contexte: ContextePrecharge,
    assure_id: int,
    prestataire_id: int,
    jour: date,
) -> Ordonnance | None:
    borne_bas = jour - timedelta(days=PERIODE_MAX_ORDONNANCE_JOURS)
    candidates = [
        ligne
        for ligne in contexte.ordonnances.get((assure_id, prestataire_id), [])
        if borne_bas <= ligne[1] <= jour
    ][:10]
    if not candidates:
        return None

    choisi = None
    for ligne in candidates:
        if ligne[1] <= jour <= ligne[1] + timedelta(days=ligne[2]):
            choisi = ligne
            break
    if choisi is None:
        choisi = candidates[0]

    ordonnance_id, prescription, validite, prescripteur_id = choisi
    return Ordonnance(
        prescripteur_id=contexte.prestataires.get(prescripteur_id, ""),
        date_prescription=prescription,
        validite_jours=validite,
        codes_prescrits=contexte.codes.get(ordonnance_id, frozenset()),
    )


def _resoudre_contrat(contexte: ContextePrecharge, assure_id: int, jour: date) -> Contrat | None:
    for date_debut, date_fin, niveau in contexte.contrats.get(assure_id, []):
        if (date_debut is None or date_debut <= jour) and (date_fin is None or date_fin >= jour):
            return Contrat(
                date_effet=date_debut,
                date_fin=date_fin,
                formule=niveau.upper(),
            )
    return None


def _construire_invoice(
    facture: FactureANoter,
    contexte: ContextePrecharge,
    referentiels: Referentiels | None,
    *,
    historiques: bool,
) -> tuple[InvoiceSubmission, Ordonnance | None, Contrat | None, int | None, str]:
    jour = facture.date_facture.date()

    # Une facture du jeu de depart porte ses liens (ou leur absence) : les
    # suivre donne EXACTEMENT la featurisation de l'entrainement. La
    # resolution par date ne sert qu'aux factures du jour J, qui n'en ont pas.
    if facture.ordonnance_db_id is not None:
        ordonnance = contexte.ordonnances_par_id.get(facture.ordonnance_db_id)
    elif historiques:
        ordonnance = None
    else:
        ordonnance = _resoudre_ordonnance(
            contexte, facture.assure_id, facture.prestataire_db_id, jour
        )

    contrat = None
    if facture.contrat_numero:
        contrats = getattr(referentiels, "contrats", {}) or {}
        contrat = contrats.get(facture.contrat_numero)
    if contrat is None and not historiques:
        contrat = _resoudre_contrat(contexte, facture.assure_id, jour)

    annee, sexe = contexte.profils.get(facture.assure_id, (None, ""))
    invoice = InvoiceSubmission(
        facture_id=facture.reference,
        assure_pseudonyme=facture.pseudonyme,
        prestataire_id=facture.prestataire_code,
        date_facture=facture.date_facture,
        montant_total=facture.montant_total,
        lignes=facture.lignes,
    )
    return invoice, ordonnance, contrat, annee, sexe


def _scorer(estimator: object, lignes: list[list[float]]) -> list[float]:
    scores: list[float] = []
    for debut in range(0, len(lignes), TAILLE_LOT_SCORING):
        lot = np.asarray(lignes[debut : debut + TAILLE_LOT_SCORING], dtype=float)
        scores.extend(float(s) for s in estimator.predict_proba(lot)[:, 1])  # type: ignore[attr-defined]
    return scores


def _shap_alertes(
    estimator: object,
    lignes: list[list[float]],
    scores: list[float],
    seuil: float,
    feature_names: list[str],
    base_value: float,
) -> dict[int, list]:
    import shap

    indices = [index for index, score in enumerate(scores) if score >= seuil]
    if not indices:
        return {}

    explainer = shap.TreeExplainer(estimator)
    contributions: dict[int, list] = {}
    for debut in range(0, len(indices), TAILLE_LOT_SHAP):
        lot_indices = indices[debut : debut + TAILLE_LOT_SHAP]
        lot = np.asarray([lignes[index] for index in lot_indices], dtype=float)
        valeurs = explainer.shap_values(lot)
        if isinstance(valeurs, list):
            valeurs = valeurs[-1]
        valeurs = np.asarray(valeurs)
        if valeurs.ndim == 3:
            valeurs = valeurs[:, :, -1]
        for position, index in enumerate(lot_indices):
            contributions[index] = shap_to_contributions(
                feature_names, valeurs[position], base_value
            )
    return contributions


def _executer(
    *,
    historiques: bool,
    limite: int | None,
    dry_run: bool,
    force: bool,
    remplacer: bool = False,
) -> int:
    settings = get_settings()

    with session_scope() as session:
        if historiques and remplacer:
            session.execute(
                text(
                    """
                    DELETE FROM ml.shap_explication
                    WHERE prediction_id IN (
                        SELECT id FROM ml.prediction WHERE statut = 'historique'
                    )
                    """
                )
            )
            resultat = session.execute(
                text("DELETE FROM ml.prediction WHERE statut = 'historique'")
            )
            supprimees = getattr(resultat, "rowcount", 0)
            print(f"{supprimees} prediction(s) historique(s) remplacee(s).", flush=True)
        nombre = _compter_a_noter(session, historiques=historiques)
        if not historiques and not force and nombre > GARDE_NOUVELLES:
            print(
                f"{nombre} factures sans prediction : au-dela de {GARDE_NOUVELLES}, "
                "lancez d'abord `make score-historique` (ou ajoutez --force).",
                file=sys.stderr,
            )
            return 2
        ids = _charger_ids(session, historiques=historiques, limite=limite)
        print(
            f"{len(ids)} facture(s) a noter ({'historique' if historiques else 'nouvelle'}).",
            flush=True,
        )
        factures = _charger_factures(session, ids)
        if len(factures) < len(ids):
            print(
                f"  {len(ids) - len(factures)} facture(s) sans ligne : ignoree(s).",
                flush=True,
            )
        contexte = _charger_contexte(session)

    registry = ModelRegistry(Path(settings.model_dir), settings.fraud_alert_threshold)
    registry.load_version(str(settings.model_active_version))
    seuil_effectif = lire_seuil_effectif()
    if registry.seuil_impose is None and seuil_effectif is not None:
        registry.set_threshold(seuil_effectif)
    bundle = registry.active
    seuil = registry.threshold
    referentiels = cast(Referentiels | None, bundle.referentiels)

    lignes: list[list[float]] = []
    for index, facture in enumerate(factures, start=1):
        invoice, ordonnance, contrat, annee, sexe = _construire_invoice(
            facture, contexte, referentiels, historiques=historiques
        )
        features = build_features(
            invoice,
            referentiels,
            ordonnance=ordonnance,
            contrat=contrat,
            assure_annee_naissance=annee,
            assure_sexe=sexe,
        )
        lignes.append(features.as_row(bundle.feature_names))
        if index % 10000 == 0:
            print(f"  featurisation : {index}/{len(factures)}", flush=True)

    print(
        f"  modele {bundle.version}, seuil {seuil:.6f} ; scoring...",
        flush=True,
    )
    scores = _scorer(bundle.estimator, lignes)
    alertes = sum(1 for score in scores if score >= seuil)
    print(
        f"  scores : {len(scores)} ; alertes (score >= seuil) : {alertes}",
        flush=True,
    )

    if dry_run:
        return 0

    contributions = _shap_alertes(
        bundle.estimator,
        lignes,
        scores,
        seuil,
        bundle.feature_names,
        bundle.shap_base_value,
    )

    ecrites = 0
    with session_scope() as session:
        for index, (facture, score) in enumerate(zip(factures, scores, strict=True), start=1):
            is_fraud = score >= seuil
            shap = contributions.get(index - 1, [])
            if historiques:
                prediction_id = stocker_prediction_historique(
                    session,
                    facture_id=facture.id,
                    model_version=bundle.version,
                    score=score,
                    seuil=seuil,
                    is_fraud=is_fraud,
                    created_at=facture.date_facture,
                    contributions=shap,
                )
            else:
                prediction_id = stocker_prediction(
                    session,
                    reference=facture.reference,
                    model_version=bundle.version,
                    score=score,
                    seuil=seuil,
                    is_fraud=is_fraud,
                    contributions=shap,
                )
            if prediction_id is not None:
                ecrites += 1
            if index % 10000 == 0:
                print(f"  ecriture : {index}/{len(factures)}", flush=True)

    print(f"  predictions ecrites : {ecrites}", flush=True)
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scoring en lot des factures PrediCare.")
    sous = parser.add_subparsers(dest="mode", required=True)

    historique = sous.add_parser("historique", help="Rejoue le jeu etiquete (statut historique).")
    historique.add_argument("--limite", type=int, default=None)
    historique.add_argument("--dry-run", action="store_true")
    historique.add_argument(
        "--remplacer",
        action="store_true",
        help="Supprime les predictions 'historique' avant de rejouer.",
    )

    nouvelles = sous.add_parser(
        "nouvelles", help="Note les factures sans prediction (statut nouvelle)."
    )
    nouvelles.add_argument("--limite", type=int, default=None)
    nouvelles.add_argument("--force", action="store_true")
    nouvelles.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return _executer(
            historiques=args.mode == "historique",
            limite=args.limite,
            dry_run=args.dry_run,
            force=getattr(args, "force", False),
            remplacer=getattr(args, "remplacer", False),
        )
    finally:
        dispose_engine()


if __name__ == "__main__":
    raise SystemExit(main())
