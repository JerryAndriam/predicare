"""Cree les quatre comptes de demonstration, un par role du CDC.

La table `core.utilisateur` est volontairement vide apres les migrations :
aucun mot de passe n'est code en dur dans le depot. Ce script est donc
l'etape explicite qui rend l'interface utilisable.

Le mot de passe vient de `DEMO_PASSWORD` (au moins 12 caracteres, Argon2id).
S'il est absent, un mot de passe aleatoire est genere et affiche UNE fois :
il n'est jamais ecrit dans un fichier versionne.

Le script est idempotent : le relancer met a jour le mot de passe et le role
au lieu de creer un doublon.

Usage :
    docker compose -f docker-compose.yml run --rm seed \\
        python -m predicare_seed.creer_comptes
"""

from __future__ import annotations

import os
import secrets
import string

from sqlalchemy import text

from predicare.auth import hash_password
from predicare.db import session_scope
from predicare.logging_config import get_logger
from predicare.rbac import Role

logger = get_logger("seed.comptes")

#: (email, role, nom affiche, rattache a un dossier assure).
COMPTES: tuple[tuple[str, Role, str, bool], ...] = (
    ("assure@predicare.local", Role.ASSURE, "Assure de demonstration", True),
    ("pro@predicare.local", Role.PROFESSIONNEL_SANTE, "Dr Aina - professionnel", False),
    ("gestionnaire@predicare.local", Role.GESTIONNAIRE, "Ravo - gestionnaire", False),
    ("admin@predicare.local", Role.ADMINISTRATEUR, "Administrateur PrediCare", False),
)

#: Longueur minimale imposee par `predicare.auth.hash_password`.
LONGUEUR_MINIMALE = 12


def mot_de_passe_demo() -> str:
    """Mot de passe impose par `DEMO_PASSWORD`, sinon genere et affiche."""
    impose = os.getenv("DEMO_PASSWORD", "").strip()
    if impose:
        if len(impose) < LONGUEUR_MINIMALE:
            raise SystemExit(
                f"DEMO_PASSWORD doit contenir au moins {LONGUEUR_MINIMALE} caracteres."
            )
        return impose

    alphabet = string.ascii_letters + string.digits + "!@#%&*+-"
    return "".join(secrets.choice(alphabet) for _ in range(24))


def creer_comptes(mot_de_passe: str) -> list[tuple[str, str]]:
    """Ecrit les quatre comptes. Rend (email, role) pour l'affichage."""
    hache = hash_password(mot_de_passe)
    resultat: list[tuple[str, str]] = []

    with session_scope() as session:
        # Le compte assure doit pointer vers un dossier reel : c'est ce lien
        # qui limite l'historique a SES factures. Sans donnees chargees, le
        # compte est cree sans dossier et le signaler vaut mieux que le
        # laisser echouer silencieusement a la premiere connexion.
        assure_id = session.execute(text("SELECT id FROM core.assure ORDER BY id LIMIT 1")).scalar()

        # Le compte professionnel est rattache a un prestataire reel : sans ce
        # lien, l'API lui refuse l'acces (403) plutot que de lui montrer les
        # factures de tous les etablissements.
        prestataire_id = session.execute(
            text("SELECT id FROM core.prestataire ORDER BY id LIMIT 1")
        ).scalar()

        if prestataire_id is None:
            logger.warning(
                "comptes.aucun_prestataire",
                message="Chargez les donnees avant le compte professionnel.",
            )
            print(
                "ATTENTION : aucune ligne dans core.prestataire. "
                "Le compte professionnel sera cree sans perimetre et devra etre "
                "rattache par un administrateur."
            )

        if assure_id is None:
            logger.warning(
                "comptes.aucun_assure", message="Chargez les donnees avant le compte assure."
            )
            print(
                "ATTENTION : aucune ligne dans core.assure. "
                "Lancez d'abord `docker compose -f docker-compose.yml run --rm seed`, "
                "puis relancez ce script pour rattacher le compte assure."
            )

        for email, role, nom, rattache in COMPTES:
            session.execute(
                text(
                    """
                    INSERT INTO core.utilisateur
                        (email, password_hash, role, assured_id, prestataire_id,
                         display_name, is_active)
                    VALUES (:email, :hache, :role, :assured_id, :prestataire_id,
                            :nom, true)
                    ON CONFLICT (email) DO UPDATE
                    SET password_hash = EXCLUDED.password_hash,
                        role = EXCLUDED.role,
                        assured_id = EXCLUDED.assured_id,
                        prestataire_id = EXCLUDED.prestataire_id,
                        display_name = EXCLUDED.display_name,
                        is_active = true
                    """
                ),
                {
                    "email": email,
                    "hache": hache,
                    "role": str(role),
                    "assured_id": assure_id if rattache else None,
                    "prestataire_id": (
                        prestataire_id if role is Role.PROFESSIONNEL_SANTE else None
                    ),
                    "nom": nom,
                },
            )
            resultat.append((email, str(role)))

    return resultat


def main() -> None:
    mot_de_passe = mot_de_passe_demo()
    comptes = creer_comptes(mot_de_passe)

    print()
    print("Comptes de demonstration prets :")
    print(f"  {'email':34} {'role':22} mot de passe")
    for email, role in comptes:
        print(f"  {email:34} {role:22} {mot_de_passe}")
    print()
    if not os.getenv("DEMO_PASSWORD", "").strip():
        print("Mot de passe genere. Notez-le : il n'est pas enregistre dans le depot.")
        print("Pour le fixer : ajoutez DEMO_PASSWORD=... dans .env, puis relancez ce script.")


if __name__ == "__main__":
    main()
