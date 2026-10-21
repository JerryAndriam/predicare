#!/usr/bin/env python3
"""Emet un jeton de test pour un role, a partir du `.env`.

Le test d'intrusion a besoin de jetons REELS : un jeton fabrique a la main
ne prouverait rien, puisque c'est la signature que le serveur verifie. Ce
script signe donc avec la cle de l'environnement, comme le fait l'API.

Usage : scripts/jeton-test.py <assure|pro|gestionnaire|admin>
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent


def _secret(nom: str) -> str:
    for ligne in (RACINE / ".env").read_text(encoding="utf-8").splitlines():
        if ligne.startswith(f"{nom}="):
            return ligne.split("=", 1)[1].strip()
    return ""


def main() -> int:
    if len(sys.argv) < 2:
        print("usage : jeton-test.py <assure|pro|gestionnaire|admin>", file=sys.stderr)
        return 2
    role = sys.argv[1]
    if role not in {"assure", "pro", "gestionnaire", "admin"}:
        print(f"role inconnu : {role}", file=sys.stderr)
        return 2

    import jwt

    maintenant = datetime.now(UTC)
    charge = {
        "sub": "1",
        "role": {
            "assure": "assure",
            "pro": "professionnel_sante",
            "gestionnaire": "gestionnaire",
            "admin": "administrateur",
        }[role],
        "ins": "1" if role == "assure" else None,
        "iat": int(maintenant.timestamp()),
        "exp": int((maintenant + timedelta(minutes=30)).timestamp()),
        "jti": "test-intrusion",
        "token_use": "access",
    }
    print(
        jwt.encode(
            charge,
            _secret("JWT_SECRET_KEY") or "dev-only-change-me",
            algorithm="HS256",
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
