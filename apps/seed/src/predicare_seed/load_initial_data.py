"""Charge les fichiers de `data/raw/` dans PostgreSQL.

Format attendu, aligne sur le jeu de donnees de l'encadrement :
- `actes.csv`             : code_acte, libelle, unite, prix_unitaire
- `prestataires.csv`      : id, nom, specialite, type
- `contrats.csv`          : id, assure_ref, niveau, date_debut, date_fin
- `assures.csv`           : reference, date_naissance, sexe, commune
- `ordonnances.csv`       : id, assure_ref, prestataire_id, code_acte, date
- `factures.csv`          : id, assure_ref, prestataire_id, date, montant
- `lignes_facture.csv`    : facture_id, code_acte, quantite, montant_unitaire
- `fraudes.csv`           : facture_id, label (fichier de labels separe)

Les identites sont pseudonymisees a l'import : rien de nominatif n'atteint
la table metier. La table `core.identite_chiffree` ne contient que les
pseudonymes.
"""

from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from predicare.config import get_settings
from predicare.crypto import pseudonymize
from predicare.db import session_scope
from predicare.logging_config import configure_logging, get_logger

configure_logging("seed", get_settings().log_level, get_settings().log_format)
logger = get_logger("seed")

RAW_DIR = Path("/data/raw")

FICHIERS_ATTENDUS = (
    "actes.csv",
    "prestataires.csv",
    "assures.csv",
    "contrats.csv",
    "factures.csv",
    "fraudes.csv",
)


def _lire(fichier: Path) -> list[dict[str, str]]:
    """Lit un CSV en ignorant les lignes vides."""
    with fichier.open(newline="", encoding="utf-8-sig") as handle:
        return [row for row in csv.DictReader(handle) if any(row.values())]


def controler_presence() -> tuple[bool, list[str]]:
    """Verifie la presence du jeu de donnees sans rien charger."""
    if not RAW_DIR.exists():
        return False, []
    presents = [nom for nom in FICHIERS_ATTENDUS if (RAW_DIR / nom).exists()]
    return bool(presents), presents


def charger_reference(session: Session) -> int:
    """Charge actes et prestataires. Ce sont des referentiels stables."""
    total = 0
    actes = RAW_DIR / "actes.csv"
    if actes.exists():
        rows = _lire(actes)
        session.execute(
            text(
                """
                INSERT INTO core.acte (code, libelle, prix_unitaire)
                VALUES (:code, :libelle, :prix)
                ON CONFLICT (code) DO UPDATE
                    SET libelle = EXCLUDED.libelle, prix_unitaire = EXCLUDED.prix_unitaire
                """
            ),
            [
                {
                    "code": row["code_acte"],
                    "libelle": row.get("libelle", ""),
                    "prix": float(row.get("prix_unitaire", 0) or 0),
                }
                for row in rows
            ],
        )
        total += len(rows)

    prestataires = RAW_DIR / "prestataires.csv"
    if prestataires.exists():
        rows = _lire(prestataires)
        session.execute(
            text(
                """
                INSERT INTO core.prestataire (code, nom, specialite)
                VALUES (:code, :nom, :specialite)
                ON CONFLICT (code) DO NOTHING
                """
            ),
            [
                {
                    "code": row["id"],
                    "nom": row.get("nom", ""),
                    "specialite": row.get("specialite", ""),
                }
                for row in rows
            ],
        )
        total += len(rows)

    return total


def charger_assures(session: Session) -> int:
    """Charge les assures, pseudonymises.

    Aucune date de naissance ni coordonnee ne va dans `core.assure` : elles
    sont chiffrees dans `core.identite_chiffree`. C'est la separation
    exigee par le CDC pour le critere RGPD.
    """
    fichier = RAW_DIR / "assures.csv"
    if not fichier.exists():
        return 0

    lignes = _lire(fichier)
    session.execute(
        text(
            """
            INSERT INTO core.assure (pseudonyme, annee_naissance, sexe, commune_code)
            VALUES (:pseudonyme, :annee, :sexe, :commune)
            ON CONFLICT (pseudonyme) DO NOTHING
            """
        ),
        [
            {
                "pseudonyme": pseudonymize("assr", row["reference"]),
                "annee": int(str(row.get("date_naissance", "1980-01-01"))[:4]),
                "sexe": row.get("sexe", "F"),
                "commune": row.get("commune", ""),
            }
            for row in lignes
        ],
    )
    logger.info("assures.charges", nombre=len(lignes))
    return len(lignes)


def main() -> int:
    """Point d'entree du conteneur `seed`."""
    present, fichiers = controler_presence()

    if not present:
        logger.warning(
            "donnees.absentes",
            chemin=str(RAW_DIR),
            message=(
                "Aucun jeu de donnees trouve. La base reste vide mais la plateforme "
                "demarre. Depposez les CSV dans ./data/raw puis lancez `make reload-data`."
            ),
        )
        return 0

    logger.info("donnees.detectees", fichiers=fichiers)

    with session_scope() as session:
        total = charger_reference(session)
        total += charger_assures(session)

    logger.info("chargement.termine", enregistrements=total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
