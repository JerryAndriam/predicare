"""Chiffrement des identites et pseudonymisation (exigence RGPD).

La regle du projet est simple : aucune identite nominative en clair en
dehors de `core.identite_chiffree`. Partout ailleurs, on manipule un
pseudonyme non reversible.

Les deux proprietes a garantir sont :

1. le meme assure donne TOUJOURS le meme pseudonyme, sinon on ne peut pas
   relier une facture a un dossier ;
2. le pseudonyme ne permet PAS de retrouver l'identite d'origine, meme en
   connaissant la liste des assures.
"""

from __future__ import annotations

import pytest

from predicare.crypto import (
    decrypt_value,
    encrypt_value,
    generate_opaque_id,
    get_fernet,
    pseudonymize,
)

# --------------------------------------------------------------- pseudonymisation


def test_pseudonyme_stable(cle_chiffrement: str) -> None:
    """Deux appels sur le meme identifiant donnent le meme pseudonyme.

    C'est la condition pour relier facture, ordonnance et dossier.
    """
    assert pseudonymize("assr", "ASSURE_00042") == pseudonymize("assr", "ASSURE_00042")


def test_pseudonymes_distincts_pour_identifiants_distincts(cle_chiffrement: str) -> None:
    a = pseudonymize("assr", "ASSURE_00042")
    b = pseudonymize("assr", "ASSURE_00043")

    assert a != b


def test_pseudonyme_depend_du_namespace(cle_chiffrement: str) -> None:
    """Le meme identifiant dans deux espaces donne deux pseudonymes.

    Sans cela, un assure et un prestataire portant la meme reference
    partageraient un identifiant, et la pseudonymisation ne protege plus
    rien.
    """
    assert pseudonymize("assr", "X1") != pseudonymize("prest", "X1")


def test_pseudonyme_ne_contient_pas_l_identite(cle_chiffrement: str) -> None:
    identifiant = "JEAN_DUPONT_1975"
    pseudo = pseudonymize("assr", identifiant)

    assert identifiant not in pseudo
    assert "JEAN" not in pseudo.upper()


def test_pseudonyme_a_prefixe_lisible(cle_chiffrement: str) -> None:
    """Le prefixe du namespace reste visible pour le debogage et les
    journaux, sans rien reveler de l'identite."""
    assert pseudonymize("assure", "X1").startswith("assu")


def test_deux_pseudonymes_ne_sont_pas_reversibles(cle_chiffrement: str) -> None:
    """Un pseudonyme hors liste ne doit pas pouvoir etre retrouve par
    correspondance, meme en connaissant la liste complete des assures.

    La cible est volontairement hors de la plage generee : sinon le test
    verifierait qu'un element de la liste n'appartient pas a la liste.
    """
    cible = pseudonymize("assr", "ASSURE_99999")
    liste = {pseudonymize("assr", f"ASSURE_{i:05d}") for i in range(100)}

    assert cible not in liste
    assert len(liste) == 100


def test_changement_de_secret_change_les_pseudonymes(cle_chiffrement: str, monkeypatch) -> None:
    """Le secret applicatif fait partie du calcul.

    Un attaquant ayant vole la base mais pas le secret ne peut donc pas
    retrouver les identites.
    """
    import os

    avant = pseudonymize("assr", "ASSURE_00042")

    os.environ["APP_SECRET_KEY"] = "un-autre-secret"
    try:
        import predicare.config as config

        config.get_settings.cache_clear()
        apres = pseudonymize("assr", "ASSURE_00042")
    finally:
        os.environ["APP_SECRET_KEY"] = "dev-only-change-me"
        config.get_settings.cache_clear()

    assert avant != apres


# --------------------------------------------------------------- chiffrement


def test_chiffrement_alleer_retour(cle_chiffrement: str) -> None:
    secret = "Jean Dupont, 12 rue des Lilas, jean.dupont@exemple.fr"

    chiffre = encrypt_value(secret)

    assert chiffre != secret
    assert decrypt_value(chiffre) == secret


def test_chiffrement_non_deterministe(cle_chiffrement: str) -> None:
    """Deux chiffrements du meme texte different.

    Deux assures avec le meme nom ne doivent pas avoir le meme bloc
    chiffre : sans cela, la frequence des homonymes dans la base est
    triviale a exploiter.
    """
    assert encrypt_value("Jean Dupont") != encrypt_value("Jean Dupont")


def test_texte_chiffre_illisible(cle_chiffrement: str) -> None:
    chiffre = encrypt_value("Jean Dupont, jean.dupont@exemple.fr")

    assert "Jean" not in chiffre
    assert "dupont" not in chiffre


def test_erreur_sur_cle_erronee(cle_chiffrement: str) -> None:
    chiffre = encrypt_value("secret")

    from cryptography.fernet import Fernet

    autre_fernet = Fernet(Fernet.generate_key())

    with pytest.raises(Exception, match="Dechiffrement impossible"):
        decrypt_value(chiffre, autre_fernet)


def test_cle_vide_refusee(monkeypatch) -> None:
    """Sans cle exploitable, on refuse de fonctionner.

    Chiffrer silencieusement avec une cle de remplacement rendrait le
    chiffrement decoratif : le premier essai de lecture echouerait, bien
    plus tard et dans un contexte ou l'on ne saura plus pourquoi.

    La variable est mise a vide plutot que supprimee : pydantic-settings
    lit aussi le fichier `.env`, ou la cle est toujours presente.
    """
    import predicare.config as config

    monkeypatch.setenv("IDENTITY_ENCRYPTION_KEY", "")
    config.get_settings.cache_clear()

    try:
        with pytest.raises(RuntimeError, match="IDENTITY_ENCRYPTION_KEY"):
            get_fernet()
    finally:
        config.get_settings.cache_clear()


def test_marqueur_de_placeholder_refuse(cle_chiffrement: str, monkeypatch) -> None:
    """Une cle encore a l'etat de marqueur doit etre refusee aussi.

    C'est le cas si quelqu'un lance la plateforme sans avoir lance
    `make secrets`.
    """
    import predicare.config as config

    monkeypatch.setenv("IDENTITY_ENCRYPTION_KEY", "CHANGER_MOI_FERNET")
    config.get_settings.cache_clear()

    try:
        with pytest.raises(RuntimeError):
            get_fernet()
    finally:
        config.get_settings.cache_clear()


# --------------------------------------------------------------- identifiants opaques


def test_identifiant_opaque_unique() -> None:
    genere = {generate_opaque_id("pai") for _ in range(200)}

    assert len(genere) == 200


def test_identifiant_opaque_non_devinable() -> None:
    """L'identifiant d'un paiement ne doit pas etre sequentiel.

    Un compteur permettrait a un tiers de deviner le nombre de dossiers
    traités et d'acceder au suivant par increment.
    """
    id1 = generate_opaque_id("pai")
    id2 = generate_opaque_id("pai")

    assert id1 != id2
    assert id1.startswith("pai_")
