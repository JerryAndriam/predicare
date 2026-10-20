"""Les droits des personnes : export, rectification, opposition, effacement.

Le CDC renvoie a la conformite, et le dossier de cadrage est explicite :
« l'effacement est le point le plus delicat : supprimer la ligne d'identite
rend le pseudonyme non re-identifiable, mais les factures et predictions
restent ».

La regle retenue ici est explicite, et c'est celle d'un dossier d'assurance :

* l'**effacement** supprime les donnees METIER de la personne (identite
  chiffree, factures, lignes, ordonnances, predictions, explanations SHAP,
  contrats) ;
* le **journal d'audit** est conserve, mais ANONYMISE : l'action et
  l'horodatage restent (l'obligation de tracabilite prime), le pseudonyme
  part ;
* un evenement « effacement » est journalise SANS pseudonyme : on peut prouver
  qu'un effacement a eu lieu, sans pouvoir dire de qui.

C'est une decision, pas une evidence : elle doit etre ecrite, lisible et
stable.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from predicare.audit import journaliser
from predicare.auth import TokenPayload
from predicare.crypto import decrypt_value, encrypt_value
from predicare.db import session_scope
from predicare.dependencies import require_permission
from predicare.errors import ForbiddenError, NotFoundError
from predicare.logging_config import get_logger
from predicare.rbac import Role

router = APIRouter(prefix="/rgpd", tags=["rgpd"])
logger = get_logger("api-core.rgpd")

#: Les operations RGPD sont reservees a l'administrateur : elles sont
#: irreversibles (effacement) ou portent sur des identites reelles.
AdminRGPD = Annotated[TokenPayload, Depends(require_permission("rgpd:administrer"))]


class IdentiteCorrigee(BaseModel):
    """L'identite reelle, en clair : c'est la donnee que la personne veut corriger."""

    model_config = ConfigDict(extra="forbid")

    nom: str | None = None
    coordonnees: str | None = None
    date_naissance: str | None = None


def _pseudonyme_du_dossier(session: Any, pseudonyme: str) -> int:
    identifiant = session.execute(
        text("SELECT id FROM core.assure WHERE pseudonyme = :pseudonyme"),
        {"pseudonyme": pseudonyme},
    ).scalar()
    if identifiant is None:
        raise NotFoundError("Dossier introuvable.")
    return int(identifiant)


def _opposition(session: Any, assure_id: int) -> bool:
    valeur = session.execute(
        text("SELECT opposition FROM core.assure WHERE id = :assure_id"),
        {"assure_id": assure_id},
    ).scalar()
    return bool(valeur)


def _identite(session: Any, pseudonyme: str) -> dict[str, Any]:
    """L'identite chiffree, dechiffree.

    Le dechiffrement se fait a la volee : la valeur n'est jamais ecrite en
    clair ailleurs que dans la reponse a la personne concernee.
    """
    ligne = (
        session.execute(
            text(
                """
            SELECT reference_brute_chiffree, nom_chiffre, coordonnees_chiffrees,
                   date_naissance_chiffree
            FROM core.identite_chiffree WHERE pseudonyme = :pseudonyme
            """
            ),
            {"pseudonyme": pseudonyme},
        )
        .mappings()
        .one_or_none()
    )
    if ligne is None:
        return {}

    def dechiffrer(valeur: bytes | None) -> str | None:
        if not valeur:
            return None
        return decrypt_value(bytes(valeur).decode("ascii"))

    return {
        "reference_brute": dechiffrer(ligne["reference_brute_chiffree"]),
        "nom": dechiffrer(ligne["nom_chiffre"]),
        "coordonnees": dechiffrer(ligne["coordonnees_chiffrees"]),
        "date_naissance": dechiffrer(ligne["date_naissance_chiffree"]),
    }


def _exporter(pseudonyme: str) -> dict[str, Any]:
    """L'export complet du dossier d'une personne.

    C'est le droit d'ACCES et de PORTABILITE : la personne recupere ses
    donnees, en clair, dans un format exploitable. La reponse est un objet
    JSON ; le front la sert avec un en-tete de telechargement, ce qui donne
    un fichier sans avoir a maintained un second format.
    """
    with session_scope() as session:
        assure_id = _pseudonyme_du_dossier(session, pseudonyme)
        factures = [
            dict(ligne)
            for ligne in session.execute(
                text(
                    """
                    SELECT reference, date_facture, montant_total, montant_pris_en_charge,
                           reste_a_charge, statut
                    FROM core.facture WHERE assure_id = :assure_id
                    ORDER BY date_facture
                    """
                ),
                {"assure_id": assure_id},
            ).mappings()
        ]
        ordonnances = [
            dict(ligne)
            for ligne in session.execute(
                text(
                    """
                    SELECT o.reference, o.date_ordonnance, o.quantite, o.diagnostic,
                           o.validite_jours, a.code AS code_acte
                    FROM core.ordonnance o
                    LEFT JOIN core.acte a ON a.id = o.acte_id
                    WHERE o.assure_id = :assure_id
                    ORDER BY o.date_ordonnance
                    """
                ),
                {"assure_id": assure_id},
            ).mappings()
        ]
        predictions = [
            dict(ligne)
            for ligne in session.execute(
                text(
                    """
                    SELECT p.model_version, p.score_fraude, p.seuil_applique, p.is_fraud,
                           p.statut, p.created_at
                    FROM ml.prediction p
                    JOIN core.facture f ON f.id = p.facture_id
                    WHERE f.assure_id = :assure_id
                    ORDER BY p.created_at
                    """
                ),
                {"assure_id": assure_id},
            ).mappings()
        ]
        identite = _identite(session, pseudonyme)
        opposition = _opposition(session, assure_id)

    return {
        "pseudonyme": pseudonyme,
        "identite": identite,
        "opposition": opposition,
        "factures": factures,
        "ordonnances": ordonnances,
        "predictions": predictions,
        "genere_le": None,
    }


@router.get("/assures/{pseudonyme}/export")
def exporter(pseudonyme: str, _admin: AdminRGPD) -> dict[str, Any]:
    """L'export complet du dossier d'une personne (droit d'acces)."""
    return _exporter(pseudonyme)


@router.get("/moi/export")
def exporter_moi(request: Request) -> dict[str, Any]:
    """L'export du dossier de l'assure connecte.

    Le pseudonyme vient du JETON, jamais de la requete : un assure ne peut
    pas exporter le dossier d'un autre en changeant l'URL.
    """
    payload: TokenPayload = request.state.user
    if payload.role is not Role.ASSURE or not payload.insured_id:
        raise ForbiddenError("Seul un dossier assure peut etre exporte ainsi.")
    with session_scope() as session:
        pseudonyme = session.execute(
            text("SELECT pseudonyme FROM core.assure WHERE id = :assure_id"),
            {"assure_id": int(payload.insured_id)},
        ).scalar()
    if not pseudonyme:
        raise NotFoundError("Dossier introuvable.")
    return _exporter(str(pseudonyme))


@router.put("/assures/{pseudonyme}/identite")
def rectifier(pseudonyme: str, identite: IdentiteCorrigee, _admin: AdminRGPD) -> dict[str, Any]:
    """Rectifie l'identite chiffree d'une personne.

    La valeur est rechiffree immediatement : l'identite n'est jamais
    stockee en clair, meme temporairement.
    """
    with session_scope() as session:
        _pseudonyme_du_dossier(session, pseudonyme)
        if identite.nom is not None:
            session.execute(
                text(
                    """
                    UPDATE core.identite_chiffree SET nom_chiffre = :valeur
                    WHERE pseudonyme = :pseudonyme
                    """
                ),
                {
                    "valeur": encrypt_value(identite.nom),
                    "pseudonyme": pseudonyme,
                },
            )
        if identite.coordonnees is not None:
            session.execute(
                text(
                    """
                    UPDATE core.identite_chiffree SET coordonnees_chiffrees = :valeur
                    WHERE pseudonyme = :pseudonyme
                    """
                ),
                {
                    "valeur": encrypt_value(identite.coordonnees),
                    "pseudonyme": pseudonyme,
                },
            )
        if identite.date_naissance is not None:
            session.execute(
                text(
                    """
                    UPDATE core.identite_chiffree SET date_naissance_chiffre = :valeur
                    WHERE pseudonyme = :pseudonyme
                    """
                ),
                {
                    "valeur": encrypt_value(identite.date_naissance),
                    "pseudonyme": pseudonyme,
                },
            )
        journaliser(
            session,
            acteur="rgpd",
            role="administrateur",
            action="identite_rectifiee",
            cible="dossier:anonyme",
        )
    return {"rectifie": True}


@router.post("/assures/{pseudonyme}/opposition")
def opposer(pseudonyme: str, _admin: AdminRGPD) -> dict[str, Any]:
    """Enregistre l'opposition d'une personne au traitement de ses donnees.

    L'opposition ne supprime rien : elle arrete la SERVITION. L'effacement
    reste une decision separee, et l'une n'impose pas l'autre.
    """
    with session_scope() as session:
        assure_id = _pseudonyme_du_dossier(session, pseudonyme)
        session.execute(
            text("UPDATE core.assure SET opposition = true WHERE id = :assure_id"),
            {"assure_id": assure_id},
        )
        journaliser(
            session,
            acteur="rgpd",
            role="administrateur",
            action="opposition_enregistree",
            cible="dossier:anonyme",
        )
    return {"opposition": True}


@router.delete("/assures/{pseudonyme}")
def effacer(pseudonyme: str, _admin: AdminRGPD) -> dict[str, Any]:
    """Efface le dossier d'une personne, et trace l'effacement.

    Ce que l'effacement supprime : l'identite chiffree, les factures et leurs
    lignes, les ordonnances et les leurs, les predictions et les explications
    SHAP, les contrats, le lien entre le compte et le dossier.

    Ce qu'il conserve : le journal d'audit, dont les lignes citant le
    pseudonyme sont ANONYMISEES. Une trace reste -- sans la personne.
    """
    supprimees: dict[str, int] = {}
    with session_scope() as session:
        assure_id = _pseudonyme_du_dossier(session, pseudonyme)

        # Le journal : on retire le pseudonyme AVANT de supprimer le dossier,
        # car c'est lui qui donne le nom a effacer.
        session.execute(
            text(
                """
                UPDATE audit.journal
                SET details = replace(details::text, :pseudonyme, '[EFFACE]')::jsonb,
                    cible = replace(cible, :pseudonyme, '[EFFACE]')
                WHERE details::text LIKE :motif OR cible LIKE :motif
                """
            ),
            {"pseudonyme": pseudonyme, "motif": f"%{pseudonyme}%"},
        )

        for requete, cle in (
            (
                "DELETE FROM ml.shap_explication WHERE prediction_id IN "
                "(SELECT p.id FROM ml.prediction p JOIN core.facture f ON f.id = p.facture_id "
                "WHERE f.assure_id = :assure_id)",
                "explications_shap",
            ),
            (
                "DELETE FROM ml.prediction WHERE facture_id IN "
                "(SELECT id FROM core.facture WHERE assure_id = :assure_id)",
                "predictions",
            ),
            (
                # Les etiquettes d'entrainement referencent les factures :
                # sans cette suppression, la contrainte de cle etrangere
                # refuse l'effacement.
                "DELETE FROM ml.label_fraude WHERE facture_id IN "
                "(SELECT id FROM core.facture WHERE assure_id = :assure_id)",
                "etiquettes_fraude",
            ),
            (
                "DELETE FROM core.ligne_facture WHERE facture_id IN "
                "(SELECT id FROM core.facture WHERE assure_id = :assure_id)",
                "lignes_facture",
            ),
            (
                "DELETE FROM core.facture WHERE assure_id = :assure_id",
                "factures",
            ),
            (
                "DELETE FROM core.ordonnance_ligne WHERE ordonnance_id IN "
                "(SELECT id FROM core.ordonnance WHERE assure_id = :assure_id)",
                "lignes_ordonnance",
            ),
            (
                "DELETE FROM core.ordonnance WHERE assure_id = :assure_id",
                "ordonnances",
            ),
            (
                "DELETE FROM core.contrat_beneficiaire WHERE contrat_id IN "
                "(SELECT id FROM core.contrat WHERE assure_id = :assure_id)",
                "beneficiaires",
            ),
            (
                "DELETE FROM core.garantie WHERE contrat_id IN "
                "(SELECT id FROM core.contrat WHERE assure_id = :assure_id)",
                "garanties",
            ),
            (
                "DELETE FROM core.contrat WHERE assure_id = :assure_id",
                "contrats",
            ),
            (
                "DELETE FROM core.contrat_beneficiaire WHERE assure_id = :assure_id",
                "beneficiaires_directs",
            ),
            (
                "DELETE FROM core.identite_chiffree WHERE pseudonyme = :pseudonyme",
                "identites",
            ),
        ):
            resultat = session.execute(
                text(requete), {"assure_id": assure_id, "pseudonyme": pseudonyme}
            )
            supprimees[cle] = int(getattr(resultat, "rowcount", 0) or 0)

        session.execute(
            text("UPDATE core.utilisateur SET assured_id = NULL WHERE assured_id = :assure_id"),
            {"assure_id": assure_id},
        )
        session.execute(
            text("DELETE FROM core.assure WHERE id = :assure_id"), {"assure_id": assure_id}
        )
        journaliser(
            session,
            acteur="rgpd",
            role="administrateur",
            action="dossier_efface",
            cible="dossier:anonyme",
            details={"lignes_supprimees": json.dumps(supprimees)},
        )
    return {"efface": True, "lignes_supprimees": supprimees}
