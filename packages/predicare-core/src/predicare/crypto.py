"""Chiffrement des identifiants et utilitaires cryptographiques.

Regle RGPD du projet : les noms et coordonnees n'existent QUE dans une table
chiffree isolee. Partout ailleurs on manipule un pseudonyme non reversible.
La cle vit dans l'environnement, jamais en base ni dans le code.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.fernet import Fernet, InvalidToken


def generate_encryption_key() -> str:
    """Genere une cle Fernet (32 octets en base64) pour `make secrets`."""
    return Fernet.generate_key().decode()


def get_fernet(key: str | None = None) -> Fernet:
    """Construit le jeu de cle a partir de l'environnement."""
    from predicare.config import get_settings

    raw = key or get_settings().identity_encryption_key
    if not raw or "CHANGER_MOI" in raw:
        raise RuntimeError(
            "IDENTITY_ENCRYPTION_KEY absente ou non configuree. "
            "Executez `make secrets` avant de demarrer la plateforme."
        )
    return Fernet(raw)


def encrypt_value(plaintext: str, fernet: Fernet | None = None) -> str:
    """Chiffre une valeur de la table d'identites."""
    return (fernet or get_fernet()).encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str, fernet: Fernet | None = None) -> str:
    """Dechiffre une valeur. Le contenu reste en memoire uniquement."""
    try:
        return (fernet or get_fernet()).decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError(
            "Dechiffrement impossible : la cle ne correspond pas a celle utilisee au chargement."
        ) from exc


# --------------------------------------------------------------------------
# Pseudonymisation
# --------------------------------------------------------------------------
def pseudonymize(namespace: str, raw_identifier: str) -> str:
    """Pseudonyme stable et irreversible pour un identifiant.

    Le meme assure donne toujours le meme pseudonyme : indispensable pour
    relier une facture a un dossier sans jamais stocker l'identite. HMAC et
    non MD5/SHA nu : un secret de l'application rend le resultat non
    rejouable par un tiers qui aurait la liste des identifiants.
    """
    from predicare.config import get_settings

    secret = get_settings().app_secret_key.encode()
    digest = hmac.new(secret, f"{namespace}:{raw_identifier}".encode(), hashlib.sha256).digest()
    return f"{namespace[:4]}_{base64.urlsafe_b64encode(digest).decode().rstrip('=')[:22]}"


def generate_opaque_id(prefix: str) -> str:
    """Identifiant non devinable pour une ligne sans identite metier."""
    return f"{prefix}_{base64.urlsafe_b64encode(os.urandom(9)).decode().rstrip('=')}"
