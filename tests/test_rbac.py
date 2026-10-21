"""Controle d'acces : les quatre roles du CDC et leurs permissions.

La matrice de permissions est un element du dossier de cadrage : elle
decrit ce que chaque role peut faire, et le jury peut la confronter au
controle d'acces reellement applique par l'API.

Ces tests la verrouillent. Une permission ajoutee par erreur ouvrirait un
acces que personne n'a autorise.
"""

from __future__ import annotations

import pytest

from predicare.dependencies import require_permission, require_role
from predicare.errors import ForbiddenError
from predicare.rbac import PERMISSIONS, Role, ensure_permission, ensure_role, has_role

TOUS_LES_ROLES = list(Role)


# --------------------------------------------------------------- hierarchie


def test_quatre_roles_declares() -> None:
    """Le CDC impose exactement quatre roles."""
    assert {str(role) for role in TOUS_LES_ROLES} == {
        "assure",
        "professionnel_sante",
        "gestionnaire",
        "administrateur",
    }


def test_administrateur_herite_de_tous() -> None:
    for role in TOUS_LES_ROLES:
        assert has_role(Role.ADMINISTRATEUR, role), f"administrateur devrait heriter de {role}"


@pytest.mark.parametrize(
    "role,interdit",
    [
        (Role.ASSURE, Role.GESTIONNAIRE),
        (Role.ASSURE, Role.PROFESSIONNEL_SANTE),
        (Role.ASSURE, Role.ADMINISTRATEUR),
        (Role.PROFESSIONNEL_SANTE, Role.ASSURE),
        (Role.GESTIONNAIRE, Role.ADMINISTRATEUR),
        (Role.GESTIONNAIRE, Role.PROFESSIONNEL_SANTE),
    ],
)
def test_roles_sans_heritage_croise(role: Role, interdit: Role) -> None:
    """Pas de privilege horizontal.

    Un gestionnaire n'est pas administrateur : c'est la separation des
    pouvoirs que le dossier de conformite doit pouvoir montrer.
    """
    assert not has_role(role, interdit)


# --------------------------------------------------------------- permissions


def test_matrice_exhaustive() -> None:
    """Chaque permission declaree doit nommer au moins un role.

    Une permission vide serait soit inutilisable, soit un trou : dans les
    deux cas, c'est une erreur de la matrice.
    """
    vides = [nom for nom, roles in PERMISSIONS.items() if not roles]
    assert not vides, f"permissions sans role : {vides}"


def test_tout_role_est_reconnu() -> None:
    """Aucun role cite dans la matrice ne doit etre inconnu du code.

    Une faute de frappe dans un nom de role donnerait un acces
    impossible a granted, sans que rien ne le signale.
    """
    for nom, roles in PERMISSIONS.items():
        for role in roles:
            assert role in TOUS_LES_ROLES, f"permission {nom} cite le role inconnu {role}"


def test_seul_administrateur_change_le_seuil() -> None:
    """Le seuil de detection conditionne le volume d'alertes.

    Seul l'administrateur peut le changer, et c'est une exigence directe
    du CDC (configuration sans toucher au code).
    """
    assert PERMISSIONS["seuil:modifier"] == {Role.ADMINISTRATEUR}
    assert PERMISSIONS["modele:bascule"] == {Role.ADMINISTRATEUR}
    assert PERMISSIONS["secret:modifier"] == {Role.ADMINISTRATEUR}


def test_gestionnaire_peut_decider_sans_administrer() -> None:
    """Un gestionnaire tranche sur les alertes, sans pouvoir reconfigurer
    la plateforme.

    La separation se verifie vers le bas, pas vers le haut : c'est
    l'administrateur qui herite de tout, jamais l'inverse.
    """
    assert Role.GESTIONNAIRE in PERMISSIONS["alerte:decider"]
    assert Role.GESTIONNAIRE not in PERMISSIONS["seuil:modifier"]
    assert Role.GESTIONNAIRE not in PERMISSIONS["secret:modifier"]
    assert Role.GESTIONNAIRE not in PERMISSIONS["modele:bascule"]


def test_assure_accede_au_rag_mais_pas_aux_alertes() -> None:
    assert Role.ASSURE in PERMISSIONS["rag:interroger"]
    assert Role.ASSURE not in PERMISSIONS["alerte:lire"]


def test_pilotage_ouvert_au_gestionnaire_et_a_l_administrateur() -> None:
    """Le tableau de bord est partage par les deux roles qui suivent l'activite."""
    assert PERMISSIONS["pilotage:consulter"] == {
        Role.GESTIONNAIRE,
        Role.ADMINISTRATEUR,
    }


def test_professionnel_soumet_mais_ne_decide_pas() -> None:
    assert Role.PROFESSIONNEL_SANTE in PERMISSIONS["facture:soumettre"]
    assert Role.PROFESSIONNEL_SANTE not in PERMISSIONS["alerte:decider"]


# --------------------------------------------------------------- application


def test_role_autorise_accede() -> None:
    ensure_role(Role.ADMINISTRATEUR, Role.ASSURE)
    ensure_permission(Role.ADMINISTRATEUR, "seuil:modifier")


def test_role_refuse_leve_une_erreur() -> None:
    with pytest.raises(ForbiddenError) as erreur:
        ensure_role(Role.ASSURE, Role.ADMINISTRATEUR)

    assert erreur.value.code == "forbidden"
    assert erreur.value.http_status == 403


def test_permission_refusee_leve_une_erreur() -> None:
    with pytest.raises(ForbiddenError):
        ensure_permission(Role.ASSURE, "alerte:decider")


def test_permission_inconnue_refusee() -> None:
    """Une permission non declaree doit etre refusee, pas accordee.

    L'oubli d'une ligne dans la matrice ne doit jamais produire un acces
    par defaut.
    """
    with pytest.raises(ForbiddenError) as erreur:
        ensure_permission(Role.ADMINISTRATEUR, "permission:inventee")

    assert "permission:inventee" in str(erreur.value)


# --------------------------------------------------------------- dependances


def test_dependance_de_role_laisse_passer_les_roles_autorises() -> None:
    dependance = require_role(Role.GESTIONNAIRE)

    jeton = type("Jeton", (), {"role": Role.GESTIONNAIRE})()

    assert dependance(jeton).role is Role.GESTIONNAIRE


def test_dependance_de_role_bloque_les_autres() -> None:
    dependance = require_role(Role.GESTIONNAIRE)
    jeton = type("Jeton", (), {"role": Role.ASSURE})()

    with pytest.raises(ForbiddenError):
        dependance(jeton)


def test_dependance_de_permission_bloque() -> None:
    dependance = require_permission("seuil:modifier")
    jeton = type("Jeton", (), {"role": Role.GESTIONNAIRE})()

    with pytest.raises(ForbiddenError):
        dependance(jeton)


def test_dependance_de_permission_accepte() -> None:
    dependance = require_permission("seuil:modifier")
    jeton = type("Jeton", (), {"role": Role.ADMINISTRATEUR})()

    assert dependance(jeton).role is Role.ADMINISTRATEUR
