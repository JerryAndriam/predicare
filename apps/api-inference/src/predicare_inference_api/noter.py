"""Notation en lot de l'historique (peuplement de `ml.prediction`).

Pourquoi ce job existe
----------------------
Le chargement initial ecrit 84 000 factures dans `core.facture`, mais aucune
prediction. Le service d'inference ne note que ce qu'on lui soumet : il n'a
jamais vu l'historique. Sans notation, la file d'alertes du gestionnaire reste
vide, la boucle de decision n'a aucune cle a laquelle s'accrocher et les
indicateurs de detection du tableau de bord n'ont pas de source.

Ce job rejoue l'historique en process, avec le MEME modele et la MEME fonction
de featurisation (`predicare.features.calculer_features`) que l'entrainement.

Pourquoi pas un appel HTTP a `/predire`
---------------------------------------
La payload de soumission (`InvoiceSubmission`) ne transporte ni l'ordonnance
liee ni l'heure du soin : le service les resout par une HEURISTIQUE (ordonnance
la plus recente du couple assure/prestataire, heure a 00:00). Sur une facture
stockee, ces deux informations sont connues exactement (`ordonnance_id`,
`heure_soin`). Les ignorer produit un score faux, sans erreur visible :
`FAC-00063774` passe de 0,06 a 0,998 parce que l'heuristique invente une
ordonnance de medicaments que la facture ne reference pas.

Le job lit donc les lignes stockees et construit la facture exactement comme
`apps/ml-training/.../dataset.py`. La parite est verifiee par
`tests/test_features_parite.py`.

Ce qu'il ne fait pas
--------------------
Il ne remplace pas les soumissions temps reel. Par defaut il marque ses
predictions `statut = 'archive'` : elles mesurent la qualite du modele sur
l'historique, mais n'entrent pas dans la file de travail du gestionnaire.
Sans cette distinction, des milliers d'alertes retrospectives non decidees
feraient afficher 100 % de faux positifs et un delai de decision de plusieurs
annees. `--statut nouvelle` force l'entree en file pour une demonstration.

Usage
-----
    python -m predicare_inference_api.noter --limite 500 --dry-run
    python -m predicare_inference_api.noter --limite 500
    python -m predicare_inference_api.noter --reference FAC-00001234 --rescorer
    python -m predicare_inference_api.noter --limite 200 --statut nouvelle
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from predicare.config import get_settings
from predicare.db import session_scope
from predicare.features import (
    Contrat,
    FactureBrute,
    LigneFacture,
    Ordonnance,
    Prestataire,
    Referentiels,
    calculer_features,
)
from predicare.logging_config import configure_logging, get_logger
from predicare.persistance_ml import (
    STATUTS_PREDICTION,
    lire_seuil_effectif,
    stocker_prediction,
)
from predicare_inference_api.registry import ModelBundle, ModelRegistry
from predicare_inference_api.scoring import Scorer

logger = get_logger("api-inference.noter")

#: Fenetre de selection par defaut. Les factures plus anciennes restent en
#: base : elles ne sont simplement pas dans le lot courant.
FENETRE_VALIDATION_JOURS = 730

#: Une transaction par paquet : assez pour amortir les commits, assez peu pour
#: qu'une interruption ne perde pas une heure de notation. Le job reste
#: reprenable : il ne selectionne que les factures sans prediction.
LOT_COMMIT = 200

PROGRESSION_TOUS_LES = 200


@dataclass
class Resultat:
    """Compteurs d'un run, separes parce qu'ils n'ont pas la meme gravite.

    `ignores` est un etat de la donnee (pas de date de soin, pas de ligne) :
    la facture ne peut pas etre featurisee, ce n'est pas une panne.
    `echecs` est une panne de persistance : le run doit sortir en erreur.
    """

    notes: int = 0
    ignores: int = 0
    echecs: int = 0
    duree_s: float = 0.0
    details_ignores: list[str] = field(default_factory=list)
    details_echecs: list[str] = field(default_factory=list)
    apercu: list[tuple[str, float]] = field(default_factory=list)

    @property
    def debit(self) -> float:
        return self.notes / self.duree_s if self.duree_s > 0 else 0.0


def heure_depuis(texte: str | None) -> int:
    """`'10:35'` -> 10. Meme lecture que `dataset._heure`, defaut 0.

    La base stocke l'heure du soin en texte (`varchar(8)`), heritee du CSV.
    Le modele, lui, attend un entier dans `date_acte`.
    """
    if not texte:
        return 0
    for gabarit in ("%H:%M", "%H:%M:%S", "%Hh%M"):
        try:
            return datetime.strptime(str(texte), gabarit).hour
        except ValueError:
            continue
    return 0


def construire_facture(
    *,
    montant_total: float,
    date_facture: date,
    date_soin: date,
    heure_soin: str | None,
    lignes: list[tuple[str, int, float]],
    ordonnance: Ordonnance | None,
    contrat: Contrat | None,
    prestataire: Prestataire | None,
    prestataire_id: str,
    assure_annee_naissance: int | None,
    assure_sexe: str,
) -> FactureBrute:
    """Assemble la facture EXACTEMENT comme `dataset.py`.

    Les deux pieges corriges ici :

    - `date_acte` porte l'heure du soin. Sans elle, un soin a 10:35 est vu a
      00:00, donc « hors horaire », et le score monte ;
    - l'ordonnance est celle que la facture reference (`ordonnance_id`), ou
      aucune. La resolution heuristique du service choisit une ordonnance que
      la facture ne reference pas, et `taux_lignes_non_prescrites` passe a 1.
    """
    heure = heure_depuis(heure_soin)
    date_acte = datetime(date_soin.year, date_soin.month, date_soin.day, heure)
    return FactureBrute(
        montant_total=float(montant_total),
        date_facture=date_facture,
        lignes=tuple(
            LigneFacture(
                code=code,
                quantite=quantite,
                montant_unitaire=montant,
                date_acte=date_acte,
            )
            for code, quantite, montant in lignes
        ),
        ordonnance=ordonnance,
        contrat=contrat,
        prestataire=prestataire,
        assure_annee_naissance=assure_annee_naissance,
        assure_sexe=assure_sexe,
        prestataire_id=prestataire_id,
    )


def _depuis(valeur: str | None, *, maintenant: datetime | None = None) -> datetime:
    if valeur:
        date_lue = datetime.fromisoformat(valeur)
        return date_lue.replace(tzinfo=UTC) if date_lue.tzinfo is None else date_lue.astimezone(UTC)
    return (maintenant or datetime.now(UTC)) - timedelta(days=FENETRE_VALIDATION_JOURS)


def selectionner_factures(
    session: Session,
    *,
    limite: int,
    depuis: datetime,
    reference: str | None,
    rescorer: bool,
) -> list[dict[str, Any]]:
    """Factures candidates, avec tout leur contexte en une requete.

    `NOT EXISTS` rend le job idempotent : relancer ne renote pas ce qui l'a
    deja ete. `--rescorer` leve ce filtre pour diagnostiquer une facture
    preciser (la prediction existante est alors mise a jour).
    """
    lignes = (
        session.execute(
            text(
                """
                SELECT f.id,
                       f.reference,
                       f.montant_total,
                       f.date_facture,
                       f.date_soin,
                       f.heure_soin,
                       f.ordonnance_id,
                       c.numero       AS contrat_numero,
                       p.code         AS prestataire_code,
                       a.annee_naissance,
                       a.sexe
                FROM core.facture f
                JOIN core.assure a      ON a.id = f.assure_id
                JOIN core.prestataire p ON p.id = f.prestataire_id
                LEFT JOIN core.contrat c ON c.id = f.contrat_id
                WHERE f.date_facture >= :depuis
                  AND (CAST(:reference AS text) IS NULL OR f.reference = :reference)
                  AND (
                      :rescorer
                      OR NOT EXISTS (
                          SELECT 1 FROM ml.prediction mp WHERE mp.facture_id = f.id
                      )
                  )
                ORDER BY f.date_facture DESC, f.id DESC
                LIMIT :limite
                """
            ),
            {
                "depuis": depuis,
                "reference": reference,
                "rescorer": rescorer,
                "limite": limite,
            },
        )
        .mappings()
        .all()
    )
    return [dict(ligne) for ligne in lignes]


def charger_lignes(
    session: Session, facture_ids: list[int]
) -> dict[int, list[tuple[str, int, float]]]:
    """`(code, quantite, montant_unitaire)` par facture.

    Le code vient de l'acte OU du medicament : `COALESCE` rend celui qui est
    porte. Un identifiant technique a la place du code ferait noter la facture
    avec des variables neutres, sans aucune erreur visible.
    """
    if not facture_ids:
        return {}
    lignes = (
        session.execute(
            text(
                """
                SELECT l.facture_id,
                       COALESCE(ac.code, m.code) AS code,
                       l.quantite,
                       l.montant_unitaire
                FROM core.ligne_facture l
                LEFT JOIN core.acte ac      ON ac.id = l.acte_id
                LEFT JOIN core.medicament m ON m.id = l.medicament_id
                WHERE l.facture_id = ANY(:ids)
                ORDER BY l.facture_id, COALESCE(l.num_ligne, 32767), l.id
                """
            ),
            {"ids": facture_ids},
        )
        .mappings()
        .all()
    )
    par_facture: dict[int, list[tuple[str, int, float]]] = {}
    for ligne in lignes:
        par_facture.setdefault(ligne["facture_id"], []).append(
            (str(ligne["code"] or ""), int(ligne["quantite"]), float(ligne["montant_unitaire"]))
        )
    return par_facture


def charger_ordonnances(session: Session, ordonnance_ids: list[int]) -> dict[int, Ordonnance]:
    """Ordonnances referencees par les factures, avec leurs codes prescrits."""
    if not ordonnance_ids:
        return {}

    entetes = (
        session.execute(
            text(
                """
                SELECT o.id, o.date_ordonnance, o.validite_jours,
                       p.code AS prescripteur_code
                FROM core.ordonnance o
                JOIN core.prestataire p ON p.id = o.prestataire_id
                WHERE o.id = ANY(:ids)
                """
            ),
            {"ids": ordonnance_ids},
        )
        .mappings()
        .all()
    )
    lignes = (
        session.execute(
            text(
                """
                SELECT ol.ordonnance_id,
                       COALESCE(a.code, m.code) AS code
                FROM core.ordonnance_ligne ol
                LEFT JOIN core.acte a       ON a.id = ol.acte_id
                LEFT JOIN core.medicament m ON m.id = ol.medicament_id
                WHERE ol.ordonnance_id = ANY(:ids)
                """
            ),
            {"ids": ordonnance_ids},
        )
        .mappings()
        .all()
    )

    codes: dict[int, set[str]] = {}
    for ligne in lignes:
        if ligne["code"]:
            codes.setdefault(ligne["ordonnance_id"], set()).add(str(ligne["code"]))

    return {
        entete["id"]: Ordonnance(
            prescripteur_id=str(entete["prescripteur_code"] or ""),
            date_prescription=(
                entete["date_ordonnance"].date() if entete["date_ordonnance"] else None
            ),
            validite_jours=int(entete["validite_jours"] or 0),
            codes_prescrits=frozenset(codes.get(entete["id"], ())),
        )
        for entete in entetes
    }


def noter_lot(
    session: Session,
    factures: list[dict[str, Any]],
    *,
    lignes_par_facture: dict[int, list[tuple[str, int, float]]],
    ordonnances: dict[int, Ordonnance],
    referentiels: Referentiels,
    bundle: ModelBundle,
    seuil: float,
    statut: str,
    dry_run: bool,
    resultat: Resultat,
) -> None:
    """Note les factures du lot et persiste les predictions."""
    scorer = Scorer(bundle, seuil=seuil)

    for rang, facture in enumerate(factures, start=1):
        reference = str(facture["reference"])
        if facture["date_soin"] is None:
            resultat.ignores += 1
            resultat.details_ignores.append(f"{reference} : pas de date de soin")
            continue

        lignes = lignes_par_facture.get(facture["id"], [])
        if not lignes:
            resultat.ignores += 1
            resultat.details_ignores.append(f"{reference} : aucune ligne")
            continue

        brut = construire_facture(
            montant_total=float(facture["montant_total"]),
            date_facture=facture["date_facture"].date(),
            date_soin=facture["date_soin"].date(),
            heure_soin=facture["heure_soin"],
            lignes=lignes,
            ordonnance=ordonnances.get(facture["ordonnance_id"])
            if facture["ordonnance_id"]
            else None,
            contrat=referentiels.contrats.get(str(facture["contrat_numero"] or "")),
            prestataire=referentiels.prestataires.get(str(facture["prestataire_code"] or "")),
            prestataire_id=str(facture["prestataire_code"] or ""),
            assure_annee_naissance=facture["annee_naissance"],
            assure_sexe=str(facture["sexe"] or ""),
        )
        valeurs = calculer_features(brut, referentiels)
        row = [float(valeurs.get(nom, 0.0)) for nom in bundle.feature_names]
        notation = scorer.score(row)

        if dry_run:
            resultat.notes += 1
            resultat.apercu.append((reference, notation.score))
            continue

        try:
            # Savepoint par facture : une ecriture en echec n'annule pas les
            # precedentes du meme paquet.
            with session.begin_nested():
                stocker_prediction(
                    session,
                    reference=reference,
                    model_version=bundle.version,
                    score=notation.score,
                    seuil=notation.seuil,
                    is_fraud=notation.is_fraud,
                    contributions=notation.contributions,
                    statut=statut,
                )
        except Exception as exc:
            resultat.echecs += 1
            resultat.details_echecs.append(f"{reference} : {exc}")
            logger.warning("notation.non_persistee", facture=reference, erreur=str(exc))
            continue

        resultat.notes += 1
        if rang % LOT_COMMIT == 0:
            session.commit()
        if rang % PROGRESSION_TOUS_LES == 0:
            logger.info(
                "notation.progression",
                traitees=rang,
                total=len(factures),
                notes=resultat.notes,
                ignores=resultat.ignores,
                echecs=resultat.echecs,
            )


def _afficher_bilan(resultat: Resultat, statut: str, dry_run: bool) -> None:
    print("")
    print("Notation en lot - bilan" + (" (a blanc)" if dry_run else ""))
    print("-----------------------")
    print(f"  Factures notees      : {resultat.notes}")
    print(f"  Factures ignorees    : {resultat.ignores}")
    print(f"  Echecs de persist.   : {resultat.echecs}")
    if not dry_run:
        print(f"  Statut pose          : {statut}")
    print(f"  Duree                : {resultat.duree_s:.1f} s")
    print(f"  Debit                : {resultat.debit:.2f} facture(s)/s")
    for reference, score in resultat.apercu[:10]:
        print(f"  {reference} : score {score:.4f}")
    if len(resultat.apercu) > 10:
        print(f"  ... {len(resultat.apercu) - 10} autre(s)")
    for detail in resultat.details_ignores[:5]:
        print(f"  ignore : {detail}")
    for detail in resultat.details_echecs[:5]:
        print(f"  echec  : {detail[:220]}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Note en lot des factures historiques pour peupler ml.prediction."
    )
    parser.add_argument(
        "--limite", type=int, default=500, help="Nombre maximum de factures (defaut : 500)."
    )
    parser.add_argument(
        "--depuis",
        default=None,
        help="Date ISO minimale sur date_facture (defaut : il y a 730 jours).",
    )
    parser.add_argument(
        "--reference", default=None, help="Noter une seule facture, par sa reference (FAC-...)."
    )
    parser.add_argument(
        "--statut",
        choices=STATUTS_PREDICTION,
        default="archive",
        help=(
            "`archive` (defaut) = notation retrospective hors file de travail ; "
            "`nouvelle` = entre dans la file du gestionnaire."
        ),
    )
    parser.add_argument(
        "--rescorer",
        action="store_true",
        help="Renoter des factures deja notees (diagnostic, mise a jour de la prediction).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Calcule les scores et affiche un apercu, sans rien ecrire.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging("api-inference.noter", settings.log_level, settings.log_format)

    if args.limite < 1:
        print("--limite doit etre superieur ou egal a 1.", file=sys.stderr)
        return 2

    registry = ModelRegistry(
        model_dir=Path(os.getenv("MODEL_DIR", settings.model_dir)),
        threshold=settings.fraud_alert_threshold,
    )
    bundle = registry.load_version(
        os.getenv("MODEL_ACTIVE_VERSION", str(settings.model_active_version))
    )
    enregistre = lire_seuil_effectif()
    if enregistre is not None:
        registry.set_threshold(enregistre)
    seuil = registry.threshold

    referentiels = bundle.referentiels
    if not isinstance(referentiels, Referentiels):
        print(
            "Le modele charge n'embarque pas ses referentiels : notation impossible.",
            file=sys.stderr,
        )
        return 2

    depuis = _depuis(args.depuis)
    resultat = Resultat()
    debut = time.perf_counter()

    with session_scope() as session:
        factures = selectionner_factures(
            session,
            limite=args.limite,
            depuis=depuis,
            reference=args.reference,
            rescorer=args.rescorer,
        )
        if not factures:
            print("Aucune facture a noter : tout est deja note dans cette fenetre.")
            return 0

        print(
            f"{len(factures)} facture(s) a noter "
            f"(depuis le {depuis.date().isoformat()}, modele v{bundle.version}, "
            f"statut cible : {args.statut})."
        )

        lignes = charger_lignes(session, [facture["id"] for facture in factures])
        ordonnances = charger_ordonnances(
            session,
            [
                int(facture["ordonnance_id"])
                for facture in factures
                if facture["ordonnance_id"] is not None
            ],
        )
        noter_lot(
            session,
            factures,
            lignes_par_facture=lignes,
            ordonnances=ordonnances,
            referentiels=referentiels,
            bundle=bundle,
            seuil=seuil,
            statut=args.statut,
            dry_run=args.dry_run,
            resultat=resultat,
        )

    resultat.duree_s = time.perf_counter() - debut
    _afficher_bilan(resultat, args.statut, args.dry_run)
    return 1 if resultat.echecs else 0


if __name__ == "__main__":
    sys.exit(main())
