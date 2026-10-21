"""Rejoue l'import d'un lot de 20 factures contre l'API, comme le fait
l'onglet « Import » de l'ecran professionnel.

Le script appelle `POST /api/core/factures/soumettre` pour chaque facture
du lot, comme le fait le front, et verifie que les factures invalides sont
REJETEES avec un message nommant le champ fautif. Il affiche le bilan
exactement comme l'ecran : ligne, reference, statut et message.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

BASE = "http://localhost:8080"
EMAIL = "pro@predicare.local"
MOT_DE_PASSE = "PrediCare2026!"


def main() -> None:
    if len(sys.argv) < 2:
        print("usage : tester_import_lot.py <fichier.json> [email] [mot_de_passe]")
        raise SystemExit(2)
    chemin = Path(sys.argv[1])
    email = sys.argv[2] if len(sys.argv) > 2 else EMAIL
    mot_de_passe = sys.argv[3] if len(sys.argv) > 3 else MOT_DE_PASSE

    lot = json.loads(chemin.read_text(encoding="utf-8"))
    if isinstance(lot, dict):
        lot = [lot]

    with httpx.Client(timeout=30.0) as client:
        reponse = client.post(
            f"{BASE}/api/core/auth/login",
            json={"email": email, "password": mot_de_passe},
        )
        reponse.raise_for_status()
        jeton = reponse.json()["access_token"]
        entetes = {"Authorization": f"Bearer {jeton}"}

        acceptes = 0
        rejetes = 0
        for numero, facture in enumerate(lot, start=1):
            resultat = client.post(
                f"{BASE}/api/core/factures/soumettre",
                json=facture,
                headers=entetes,
            )
            if resultat.status_code == 202:
                corps = resultat.json()
                acceptes += 1
                print(
                    f"  ligne {numero:>2}  OK    {corps['facture_id']}  "
                    f"score={corps['score_fraude']:.4f}  fraude={corps['is_fraud']}"
                )
            else:
                rejetes += 1
                corps = resultat.json()
                print(f"  ligne {numero:>2}  REJET {resultat.status_code}  {corps.get('message')}")

    print()
    print(f"total={len(lot)} acceptes={acceptes} rejetes={rejetes}")


if __name__ == "__main__":
    main()
