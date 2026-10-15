"""Fixtures partagees par la suite de tests.

Aucun test de ce dossier ne demarre de conteneur ni ne touche PostgreSQL :
tout porte sur des fonctions pures. C'est un choix, pas une commodite.

La CI doit rester rapide et able de tourner sur une pull request sans
Docker. Et surtout : le jour J, le jury soumet 20 factures inedites. Ce que
l'on doit proteger en priorite, c'est le rejet propre d'une facture
invalide et l'etranglement du RAG. Ce sont des fonctions pures, donc
testables en quelques millisecondes, sans infrastructure.
"""

from __future__ import annotations

import pytest

#: Facture valide de reference. Les tests partent de ce dictionnaire et le
#: modifient pour declencher un rejet precis : ecrire un jeu de donnees par
#: cas rendait les tests incomprehensibles des qu'un champ changeait.
FACTURE_VALIDE: dict = {
    "assure_pseudonyme": "assr_a1b2c3d4e5f6",
    "prestataire_id": "PREST_001",
    "date_facture": "2026-06-15T10:00:00+00:00",
    "montant_total": 120.0,
    "lignes": [
        {
            "code_acte": "CONS_001",
            "quantite": 2,
            "montant_unitaire": 60.0,
            "date_acte": "2026-06-14T09:00:00+00:00",
        }
    ],
}


@pytest.fixture
def facture_valide() -> dict:
    """Copie neuve du jeu de reference, modifiable par chaque test."""
    import copy

    return copy.deepcopy(FACTURE_VALIDE)


@pytest.fixture
def cle_chiffrement() -> str:
    """Cle Fernet de test, injectee dans la configuration applicative.

    `predicare.crypto` lit la cle dans l'environnement et leve une
    exception si elle manque : sans cette fixture, tous les tests de
    chiffrement echoueraient avant meme d'arriver au code teste.
    """
    import os

    from cryptography.fernet import Fernet

    cle = Fernet.generate_key().decode()
    os.environ["IDENTITY_ENCRYPTION_KEY"] = cle
    yield cle
    os.environ.pop("IDENTITY_ENCRYPTION_KEY", None)
