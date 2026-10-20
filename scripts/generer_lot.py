"""Fabrique un lot de 20 factures pour repeter l'import du jour J.

Le CDC demande de soumettre 20 factures inedites, dont des factures
invalides, et de verifier que les invalides sont REJETEES nommage un
champ fautif. Ce script produit un JSON au format accepte par l'onglet
« Import » de l'ecran professionnel : 17 factures valides et 3 invalides
(montant d'un acte inconnu, quantite nulle, assure absent).

Usage :
    python scripts/generer_lot.py <assure> <prestataire> <acte> [prix] [sortie]
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path


def facture(
    *,
    assure: str,
    prestataire: str,
    acte: str,
    prix: float,
    quantite: int = 1,
) -> dict:
    date = datetime.now(UTC)
    return {
        "assure_pseudonyme": assure,
        "prestataire_id": prestataire,
        "date_facture": date.isoformat(),
        "montant_total": round(prix * quantite, 2),
        "lignes": [
            {
                "code_acte": acte,
                "quantite": quantite,
                "montant_unitaire": prix,
                "date_acte": date.isoformat(),
            }
        ],
    }


def main() -> None:
    if len(sys.argv) < 4:
        print(
            "usage : generer_lot.py <assure> <prestataire> <acte> [prix] [sortie]",
            file=sys.stderr,
        )
        raise SystemExit(2)
    assure, prestataire, acte = sys.argv[1], sys.argv[2], sys.argv[3]
    prix = float(sys.argv[4]) if len(sys.argv) > 4 else 25000.0
    sortie = Path(sys.argv[5]) if len(sys.argv) > 5 else Path("lot_factures_20.json")

    lot = [
        facture(assure=assure, prestataire=prestataire, acte=acte, prix=prix) for _ in range(17)
    ]

    # Trois cas invalides, volontairement distincts : le message d'erreur
    # doit nommer un champ different a chaque fois.
    lot.append(facture(assure=assure, prestataire=prestataire, acte="ACTE-INCONNU", prix=prix))
    lot.append(facture(assure=assure, prestataire=prestataire, acte=acte, prix=prix, quantite=0))
    lot.append(facture(assure="", prestataire=prestataire, acte=acte, prix=prix))

    sortie.write_text(json.dumps(lot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(lot)} factures ecrites dans {sortie}")


if __name__ == "__main__":
    main()
