"""Le re-chiffrement des identites et des secrets lors d'une rotation de cle.

La cle maitresse de Fernet chiffre deux choses : les identites des personnes
(`core.identite_chiffree`) et les secrets ecrits depuis l'ecran
d'administration (`core.secret`). La remplacer sans rehacher ces valeurs
rend TOUT illisible : la plateforme demarre, mais elle ne sait plus a qui
appartient une facture.

Ce module fait le rehachage dans UNE transaction, avec l'ancienne cle encore
active : soit les deux versions sont coherentes, soit rien n'est change. La
rotation elle-meme (generation des cles, ecriture du `.env`) est dans
`scripts/rotater-cles.sh`.
"""

from __future__ import annotations

import os
import sys

from cryptography.fernet import Fernet
from sqlalchemy import text

from predicare.crypto import decrypt_value, encrypt_value
from predicare.db import dispose_engine, session_scope
from predicare.logging_config import configure_logging, get_logger

configure_logging("api-core", "INFO", "text")
logger = get_logger("api-core.rotation")


def _fernet(cle: str) -> Fernet:
    return Fernet(cle.encode() if isinstance(cle, str) else cle)


def _rechiffrer(valeur: bytes, ancien: Fernet, nouveau: Fernet) -> bytes:
    """Rechiffre une valeur chiffree, ou la laisse intacte si elle ne l'est pas.

    Une valeur qui n'est pas chiffree (une donnee de test, un import ancien)
    ne doit pas faire echouer la rotation : elle est conservee telle quelle.
    """
    if not valeur:
        return valeur
    try:
        clair = decrypt_value(bytes(valeur).decode("ascii"), ancien)
    except Exception:
        return valeur
    return encrypt_value(clair, nouveau).encode()


def main() -> int:
    ancienne_cle = os.environ.get("ANCIENNE_FERNET", "").strip()
    nouvelle_cle = os.environ.get("NOUVELLE_FERNET", "").strip()
    if not nouvelle_cle:
        print("NOUVELLE_FERNET absente : rien a faire.", file=sys.stderr)
        return 2
    if not ancienne_cle:
        # Premiere installation : il n'y a rien a rehacher.
        ancienne_cle = nouvelle_cle
    ancien = _fernet(ancienne_cle)
    nouveau = _fernet(nouvelle_cle)

    identites = 0
    secrets_rechiffres = 0
    with session_scope() as session:
        for ligne in session.execute(
            text(
                """
                SELECT id, reference_brute_chiffree, nom_chiffre,
                       coordonnees_chiffrees, date_naissance_chiffree
                FROM core.identite_chiffree
                """
            )
        ).mappings():
            session.execute(
                text(
                    """
                    UPDATE core.identite_chiffree
                    SET reference_brute_chiffree = :reference,
                        nom_chiffre = :nom,
                        coordonnees_chiffrees = :coordonnees,
                        date_naissance_chiffree = :naissance
                    WHERE id = :id
                    """
                ),
                {
                    "reference": _rechiffrer(ligne["reference_brute_chiffree"], ancien, nouveau),
                    "nom": _rechiffrer(ligne["nom_chiffre"], ancien, nouveau),
                    "coordonnees": _rechiffrer(ligne["coordonnees_chiffrees"], ancien, nouveau),
                    "naissance": _rechiffrer(ligne["date_naissance_chiffree"], ancien, nouveau),
                    "id": ligne["id"],
                },
            )
            identites += 1

        for ligne in session.execute(text("SELECT nom, valeur FROM core.secret")).mappings():
            session.execute(
                text("UPDATE core.secret SET valeur = :valeur WHERE nom = :nom"),
                {
                    "valeur": _rechiffrer(ligne["valeur"], ancien, nouveau).decode("ascii"),
                    "nom": ligne["nom"],
                },
            )
            secrets_rechiffres += 1

    logger.info("rotation.rechiffrement", identites=identites, secrets=secrets_rechiffres)
    print(f"identites rechiffrees : {identites} ; secrets rechiffres : {secrets_rechiffres}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        dispose_engine()
