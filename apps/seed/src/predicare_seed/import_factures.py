"""Import du lot de factures du jour J (CSV).

Le CDC prevoit un lot de 20 factures fourni par le jury : « traitement de
donnees inedites et rejet propre des factures invalides ». Ce module importe
un fichier au MEME schema que ``data/raw`` et applique les memes dix regles
que le chargement initial. Une facture invalide est rejetee avec son motif,
jamais corrigee ni completee par une valeur inventee.

Les factures importees entrent en base avec le statut ``recue``. Il reste a
les noter (``make score-factures``) pour alimenter la file du gestionnaire.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import text

from predicare.crypto import pseudonymize
from predicare.db import dispose_engine, session_scope
from predicare_seed.qualite_donnees import valider_factures

FACTURES = "factures.csv"
LIGNES = "lignes_facture.csv"

COLONNES_FACTURES = {
    "facture_id",
    "prestataire_id",
    "assure_id",
    "date_soin",
    "date_facture",
    "montant_total",
    "devise",
}
COLONNES_LIGNES = {"facture_id", "code", "quantite", "prix_unitaire", "montant"}


def _texte(valeur: Any) -> str:
    if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
        return ""
    return str(valeur).strip()


def _pseudonyme(valeur: Any) -> str:
    """Le CSV porte l'identifiant brut ``ASS-...`` ; la base, un pseudonyme.

    Le meme HMAC que la graine redonne le pseudonyme existant, sans jamais
    stocker l'identifiant brut. Un pseudonyme deja calcule est accepte tel
    quel (cas d'un export fait depuis l'API).
    """
    texte = _texte(valeur)
    if not texte or texte.startswith("assr_"):
        return texte
    return pseudonymize("assr", texte)


def _date(valeur: Any) -> datetime | None:
    if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
        return None
    texte = _texte(valeur)
    if not texte:
        return None
    return datetime.fromisoformat(texte[:19])


def _heure(valeur: Any) -> int:
    texte = _texte(valeur)
    for gabarit in ("%H:%M", "%H:%M:%S", "%Hh%M"):
        try:
            return datetime.strptime(texte, gabarit).hour
        except ValueError:
            continue
    return 0


def _date_acte(date_soin: datetime | None, heure_soin: Any, brut: Any) -> datetime:
    if date_soin is None:
        valeur = _date(brut)
        return valeur or datetime.now(UTC).replace(tzinfo=None)
    return date_soin.replace(hour=_heure(heure_soin), minute=0, second=0, microsecond=0)


def _charger(dossier: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    chemin_factures = dossier / FACTURES
    chemin_lignes = dossier / LIGNES
    if not chemin_factures.exists() or not chemin_lignes.exists():
        raise FileNotFoundError(
            f"{dossier} doit contenir {FACTURES} et {LIGNES} (schema de data/raw)."
        )
    factures = pd.read_csv(chemin_factures, dtype=str, low_memory=False)
    lignes = pd.read_csv(chemin_lignes, dtype=str, low_memory=False)
    manquantes = COLONNES_FACTURES - set(factures.columns)
    manquantes |= COLONNES_LIGNES - set(lignes.columns)
    if manquantes:
        raise ValueError(f"Colonnes absentes : {', '.join(sorted(manquantes))}")
    return factures, lignes


def _cartes(session: Any) -> dict[str, dict[str, int]]:
    def _carte(requete: str, cle: str = "code") -> dict[str, int]:
        return {row[0]: row[1] for row in session.execute(text(requete))}

    return {
        "assures": _carte("SELECT pseudonyme, id FROM core.assure", "pseudonyme"),
        "prestataires": _carte("SELECT code, id FROM core.prestataire"),
        "contrats": _carte("SELECT numero, id FROM core.contrat", "numero"),
        "ordonnances": _carte("SELECT reference, id FROM core.ordonnance", "reference"),
        "actes": _carte("SELECT code, id FROM core.acte"),
        "medicaments": _carte("SELECT code, id FROM core.medicament"),
    }


def _referentiels(session: Any) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    actes = pd.DataFrame(
        {"code_acte": [row[0] for row in session.execute(text("SELECT code FROM core.acte"))]}
    )
    medicaments = pd.DataFrame(
        {
            "code_medicament": [
                row[0] for row in session.execute(text("SELECT code FROM core.medicament"))
            ]
        }
    )
    assures = pd.DataFrame(
        {
            "assure_id": [
                row[0] for row in session.execute(text("SELECT pseudonyme FROM core.assure"))
            ]
        }
    )
    prestataires = pd.DataFrame(
        {
            "prestataire_id": [
                row[0] for row in session.execute(text("SELECT code FROM core.prestataire"))
            ]
        }
    )
    return actes, medicaments, assures, prestataires


def _importer(dossier: Path, *, date_reference: date | None) -> int:
    factures, lignes = _charger(dossier)

    # Pseudonymisation AVANT la validation : la regle ASSURE_INCONNU doit
    # comparer le pseudonyme au referentiel de la base, pas l'identifiant brut.
    factures["assure_id"] = factures["assure_id"].map(_pseudonyme)

    doublons = factures["facture_id"].duplicated(keep="first")
    rejets_doublons = factures.loc[doublons, ["facture_id"]].assign(motifs="DOUBLON")
    factures = factures.loc[~doublons].copy()
    lignes = lignes[lignes["facture_id"].isin(factures["facture_id"])].copy()

    with session_scope() as session:
        actes, medicaments, assures, prestataires = _referentiels(session)
        cartes = _cartes(session)
        valides, rejets = valider_factures(
            factures,
            lignes,
            actes,
            medicaments,
            assures,
            prestataires,
            date_reference=date_reference or date.today(),
        )
        rejets = pd.concat([rejets_doublons, rejets], ignore_index=True)

        existe = {
            row[0]
            for row in session.execute(
                text("SELECT reference FROM core.facture WHERE reference = ANY(:refs)"),
                {"refs": valides["facture_id"].tolist()},
            )
        }

        lignes_par_facture = dict(lignes.groupby("facture_id", sort=False))
        factures_inserees = 0
        lignes_inserees = 0
        deja_presentes = 0

        for row in valides.to_dict("records"):
            reference = _texte(row["facture_id"])
            if reference in existe:
                deja_presentes += 1
                continue

            date_soin = _date(row.get("date_soin"))
            date_facture = _date(row.get("date_facture")) or date_soin
            if date_facture is None:
                rejets = pd.concat(
                    [
                        rejets,
                        pd.DataFrame([{"facture_id": reference, "motifs": "DATE_IMPOSSIBLE"}]),
                    ],
                    ignore_index=True,
                )
                continue

            detail = lignes_par_facture.get(reference)
            if detail is None or detail.empty:
                rejets = pd.concat(
                    [
                        rejets,
                        pd.DataFrame([{"facture_id": reference, "motifs": "FACTURE_SANS_LIGNE"}]),
                    ],
                    ignore_index=True,
                )
                continue

            prestataire_id = cartes["prestataires"].get(_texte(row["prestataire_id"]))
            assure_id = cartes["assures"].get(_texte(row["assure_id"]))
            if prestataire_id is None or assure_id is None:
                rejets = pd.concat(
                    [
                        rejets,
                        pd.DataFrame([{"facture_id": reference, "motifs": "REFERENCE_INCONNUE"}]),
                    ],
                    ignore_index=True,
                )
                continue

            facture_db_id = session.execute(
                text(
                    """
                    INSERT INTO core.facture
                        (reference, numero_facture, assure_id, prestataire_id,
                         contrat_id, ordonnance_id, type_facture, date_soin,
                         heure_soin, date_facture, date_reception, canal_reception,
                         mode_reglement, attestation_pec_id, entente_prealable_id,
                         devise, nb_lignes, montant_total, montant_eligible,
                         montant_pris_en_charge, reste_a_charge, statut)
                    VALUES
                        (:reference, :numero_facture, :assure_id, :prestataire_id,
                         :contrat_id, :ordonnance_id, :type_facture, :date_soin,
                         :heure_soin, :date_facture, now(), 'IMPORT_CSV',
                         :mode_reglement, :attestation_pec_id, :entente_prealable_id,
                         :devise, :nb_lignes, :montant_total, :montant_eligible,
                         :montant_pris_en_charge, :reste_a_charge, 'recue')
                    RETURNING id
                    """
                ),
                {
                    "reference": reference,
                    "numero_facture": _texte(row.get("numero_facture")) or None,
                    "assure_id": assure_id,
                    "prestataire_id": prestataire_id,
                    "contrat_id": cartes["contrats"].get(_texte(row.get("contrat_id"))),
                    "ordonnance_id": cartes["ordonnances"].get(_texte(row.get("ordonnance_id"))),
                    "type_facture": _texte(row.get("type_facture")) or None,
                    "date_soin": date_soin,
                    "heure_soin": _texte(row.get("heure_soin")) or None,
                    "date_facture": date_facture,
                    "mode_reglement": _texte(row.get("mode_reglement")) or None,
                    "attestation_pec_id": _texte(row.get("attestation_pec_id")) or None,
                    "entente_prealable_id": _texte(row.get("entente_prealable_id")) or None,
                    "devise": _texte(row.get("devise")) or "MGA",
                    "nb_lignes": len(detail),
                    "montant_total": float(row["montant_total"]),
                    "montant_eligible": (
                        float(row["montant_eligible"])
                        if _texte(row.get("montant_eligible"))
                        else None
                    ),
                    "montant_pris_en_charge": (
                        float(row["montant_pris_en_charge"])
                        if _texte(row.get("montant_pris_en_charge"))
                        else None
                    ),
                    "reste_a_charge": (
                        float(row["reste_a_charge"]) if _texte(row.get("reste_a_charge")) else None
                    ),
                },
            ).scalar()
            factures_inserees += 1

            for num_ligne, ligne in enumerate(detail.to_dict("records"), start=1):
                code = _texte(ligne["code"])
                session.execute(
                    text(
                        """
                        INSERT INTO core.ligne_facture
                            (facture_id, acte_id, medicament_id, quantite,
                             montant_unitaire, date_acte, num_ligne, libelle)
                        VALUES
                            (:facture_id, :acte_id, :medicament_id, :quantite,
                             :montant_unitaire, :date_acte, :num_ligne, :libelle)
                        """
                    ),
                    {
                        "facture_id": facture_db_id,
                        "acte_id": cartes["actes"].get(code),
                        "medicament_id": cartes["medicaments"].get(code),
                        "quantite": int(float(ligne["quantite"])),
                        "montant_unitaire": float(ligne["prix_unitaire"]),
                        "date_acte": _date_acte(
                            date_soin, row.get("heure_soin"), ligne.get("date_acte")
                        ),
                        "num_ligne": int(float(ligne.get("num_ligne") or num_ligne)),
                        "libelle": _texte(ligne.get("libelle"))[:256] or None,
                    },
                )
                lignes_inserees += 1

    print(f"Factures lues          : {len(factures)}")
    print(f"Factures inserees      : {factures_inserees}")
    print(f"Factures deja presentes: {deja_presentes}")
    print(f"Lignes inserees        : {lignes_inserees}")
    print(f"Factures rejetees      : {len(rejets)}")
    for rejet in rejets.to_dict("records"):
        print(f"  - {rejet['facture_id']} : {rejet['motifs']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Importe le lot CSV du jour J.")
    parser.add_argument(
        "--dossier",
        type=Path,
        default=Path("/data/import"),
        help="Dossier contenant factures.csv et lignes_facture.csv.",
    )
    parser.add_argument(
        "--date-reference",
        type=date.fromisoformat,
        default=None,
        help="Date de reference pour la regle DATE_FUTURE (defaut : aujourd'hui).",
    )
    args = parser.parse_args(argv)
    try:
        return _importer(args.dossier, date_reference=args.date_reference)
    except FileNotFoundError as exc:
        print(f"ECHEC : {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"ECHEC : {exc}", file=sys.stderr)
        return 2
    finally:
        dispose_engine()


if __name__ == "__main__":
    raise SystemExit(main())
