"""Les secrets de la plateforme : ecrits en base, chiffres, priorite a la base.

Le CDC exige que les canaux et les secrets soient modifiables sans code et
sans redemarrage. Un secret dans l'environnement ne l'est pas : le changer
demande un redemarrage de conteneur, donc un deploiement.

Ce module apporte la piece qui manquait :

* `INVENTAIRE` : la liste des secrets geres, avec la variable
  d'environnement correspondante et l'effet de son absence ;
* `ecrire_secret` / `lire_secret` : la valeur est CHIFFREE (Fernet, la cle
  maitresse reste dans l'environnement) ;
* `appliquer_secrets` : la base prime sur l'environnement, et la fonction
  dit ce qu'elle a surcharge, pour que le demarrage le dise dans ses logs.

Une ecriture est un acte d'administration : elle est journalisee.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from predicare.crypto import decrypt_value, encrypt_value


@dataclass(frozen=True, slots=True)
class SecretAttendu:
    """Un secret que la plateforme sait nommer."""

    nom: str
    variable: str
    effet: str


#: L'inventaire. Le nom est celui utilise partout (ecran, API, base) ; la
#: variable est celle de l'environnement, qui reste la valeur de depart.
INVENTAIRE: tuple[SecretAttendu, ...] = (
    SecretAttendu(
        nom="Cle LLM",
        variable="LLM_API_KEY",
        effet="Sans elle, l'assistant repond en mode degrade (extraits, sans redaction).",
    ),
    SecretAttendu(
        nom="Cle d'embedding",
        variable="EMBEDDING_API_KEY",
        effet="Sans elle, la recherche reste lexicale (empreinte locale).",
    ),
    SecretAttendu(
        nom="Webhook Slack",
        variable="SLACK_WEBHOOK_URL",
        effet="Sans lui, l'alerte n'atteint pas Slack ; l'e-mail prend le relais.",
    ),
    SecretAttendu(
        nom="Expediteur e-mail",
        variable="SMTP_FROM",
        effet="Sans lui, l'alerte e-mail n'est pas envoyee.",
    ),
    SecretAttendu(
        nom="Webhook d'alerte",
        variable="N8N_ALERTE_WEBHOOK_URL",
        effet="Sans lui, le parcours web ne declenche aucune notification.",
    ),
)

PAR_NOM: dict[str, SecretAttendu] = {secret.nom: secret for secret in INVENTAIRE}
PAR_VARIABLE: dict[str, SecretAttendu] = {secret.variable: secret for secret in INVENTAIRE}


def _valeur_chiffree(valeur: str) -> str:
    return encrypt_value(valeur)


def ecrire_secret(session: Any, nom: str, valeur: str, auteur: str) -> None:
    """Ecrit (ou remplace) un secret, chiffre, et journalise l'ecriture."""
    from sqlalchemy import text

    if nom not in PAR_NOM:
        raise ValueError(f"Secret inconnu : {nom!r}.")
    session.execute(
        text(
            """
            INSERT INTO core.secret (nom, valeur, modifie_par, modifie_at)
            VALUES (:nom, :valeur, :auteur, now())
            ON CONFLICT (nom) DO UPDATE
            SET valeur = EXCLUDED.valeur,
                modifie_par = EXCLUDED.modifie_par,
                modifie_at = now()
            """
        ),
        {"nom": nom, "valeur": _valeur_chiffree(valeur), "auteur": auteur},
    )
    session.commit()


def lire_secret(session: Any, nom: str) -> str | None:
    """La valeur en clair d'un secret ecrit en base, ou None."""
    from sqlalchemy import text

    ligne = session.execute(
        text("SELECT valeur FROM core.secret WHERE nom = :nom"), {"nom": nom}
    ).scalar()
    if ligne is None:
        return None
    try:
        return decrypt_value(str(ligne))
    except Exception:
        # Une valeur chiffree avec une autre cle (cle maîtresse changee) ne
        # se dechiffre pas : elle est traitee comme absente, pas comme une
        # panne silencieuse.
        return None


def secrets_presents(session: Any) -> dict[str, bool]:
    """Quels secrets sont ecrits en base."""
    from sqlalchemy import text

    lignes = session.execute(text("SELECT nom FROM core.secret")).fetchall()
    return {secret.nom: any(ligne[0] == secret.nom for ligne in lignes) for secret in INVENTAIRE}


def appliquer_secrets(settings: Any, session: Any) -> list[str]:
    """Surcharge les secrets d'environnement par ceux de la base.

    Rend la liste des secrets surchargees, pour que le service l'annonce au
    demarrage : un secret vient soit de l'environnement, soit de la base, et
    l'exploitant doit pouvoir le savoir.
    """
    surcharge: list[str] = []
    for secret in INVENTAIRE:
        valeur = lire_secret(session, secret.nom)
        if valeur is None:
            continue
        # La configuration expose des attributs en minuscules (`llm_api_key`),
        # pas les noms d'environnement. Le passage de l'un a l'autre est la
        # convention du module de configuration : on ne la devine pas.
        attribut = secret.variable.lower()
        if not hasattr(settings, attribut):
            continue
        setattr(settings, attribut, valeur)
        surcharge.append(secret.nom)
    return surcharge


def est_configure(valeur: str | None) -> bool:
    """Vrai si la valeur ressemble a une vraie cle, pas a un gabarit."""
    if not valeur or not valeur.strip():
        return False
    marqueurs = ("change-me", "changer", "changeme", "not-configured", "votre-cle")
    return not any(marqueur in valeur.lower() for marqueur in marqueurs)


def masquer(valeur: str | None) -> str:
    """Une valeur affichee sans la divulguer : quatre premiers caracteres."""
    if not valeur:
        return ""
    if len(valeur) <= 8:
        return "*" * len(valeur)
    return f"{valeur[:4]}{'*' * (len(valeur) - 4)}"
