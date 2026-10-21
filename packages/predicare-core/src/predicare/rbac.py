"""Roles et controle d'acces.

Quatre roles imposes par le CDC. Le controle est applique COTE SERVEUR dans
la dependance FastAPI : un role absent donne 403 avant meme d'atteindre le
code metier, donc avant toute requete base ou tout appel LLM.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    """Les quatre roles de la plateforme."""

    ASSURE = "assure"
    PROFESSIONNEL_SANTE = "professionnel_sante"
    GESTIONNAIRE = "gestionnaire"
    ADMINISTRATEUR = "administrateur"


#: Un gestionnaire herite des droits d'un assure sur son propre dossier.
_ROLE_HIERARCHY: dict[Role, frozenset[Role]] = {
    Role.ASSURE: frozenset({Role.ASSURE}),
    Role.PROFESSIONNEL_SANTE: frozenset({Role.PROFESSIONNEL_SANTE}),
    Role.GESTIONNAIRE: frozenset({Role.GESTIONNAIRE}),
    Role.ADMINISTRATEUR: frozenset(Role),
}


def has_role(actual: Role, required: Role) -> bool:
    """Un role autorise-t-il l'acces demande ?"""
    return required in _ROLE_HIERARCHY.get(actual, frozenset())


def ensure_role(actual: Role, required: Role) -> None:
    """Lever une ForbiddenError si l'acces est refuse.

    Le message ne doit jamais reveler l'existence de la ressource : un
    assure qui teste un identifiant d'autrui apprendrait qu'il existe.
    """
    from predicare.errors import ForbiddenError

    if not has_role(actual, required):
        raise ForbiddenError(
            "Acces refuse : role insuffisant pour cette operation.",
            details={"required_role": str(required)},
        )


#: Contrat de roles par ressource, aligne sur le CDC section 1.
PERMISSIONS: dict[str, frozenset[Role]] = {
    "facture:soumettre": frozenset({Role.PROFESSIONNEL_SANTE, Role.ADMINISTRATEUR}),
    "facture:lire": frozenset(
        {Role.ASSURE, Role.PROFESSIONNEL_SANTE, Role.GESTIONNAIRE, Role.ADMINISTRATEUR}
    ),
    "alerte:lire": frozenset({Role.GESTIONNAIRE, Role.ADMINISTRATEUR}),
    "alerte:decider": frozenset({Role.GESTIONNAIRE, Role.ADMINISTRATEUR}),
    "seuil:modifier": frozenset({Role.ADMINISTRATEUR}),
    "secret:modifier": frozenset({Role.ADMINISTRATEUR}),
    "modele:bascule": frozenset({Role.ADMINISTRATEUR}),
    # Re-controler un stock de factures : c'est un long traitement, mais il
    # n'ecrit que des predictions. Reserve a l'administrateur.
    "modele:recontroler": frozenset({Role.ADMINISTRATEUR}),
    # Droits des personnes : export, rectification, opposition, effacement.
    # Ces operations sont IRREVERSIBLES : elles sont reservees a
    # l'administrateur, et chacune est journalisee.
    "rgpd:administrer": frozenset({Role.ADMINISTRATEUR}),
    "audit:lire": frozenset({Role.GESTIONNAIRE, Role.ADMINISTRATEUR}),
    "rag:interroger": frozenset({Role.ASSURE, Role.GESTIONNAIRE, Role.ADMINISTRATEUR}),
    "metriques:lire": frozenset({Role.ADMINISTRATEUR, Role.GESTIONNAIRE}),
    # Le pilotage decisionnel est un ecran de lecture partage par les deux
    # roles qui suivent l'activite. Il ne donne aucun droit d'ecriture.
    "pilotage:consulter": frozenset({Role.GESTIONNAIRE, Role.ADMINISTRATEUR}),
}


def ensure_permission(actual: Role, permission: str) -> None:
    """Verifier une permission fine. `permission` provient de PERMISSIONS."""
    from predicare.errors import ForbiddenError

    allowed = PERMISSIONS.get(permission)
    if allowed is None:
        raise ForbiddenError(f"Permission inconnue : {permission}")
    if actual not in allowed:
        raise ForbiddenError(
            "Acces refuse : permission insuffisante.",
            details={"permission": permission},
        )
