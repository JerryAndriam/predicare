"""Resolution du contexte d'une facture soumise.

La featurisation (`predicare.features`) est pure : elle ne lit jamais la base.
Elle a besoin de quatre informations qu'une facture soumise ne porte pas :

- l'ordonnance liee (validite, codes prescrits) ;
- le contrat (formule, periode de couverture) ;
- le prestataire (statut, convention, horaires) ;
- le profil de l'assure (annee de naissance, sexe).

Ce module va les chercher. Il est tolerant par construction : toute erreur de
resolution donne un contexte vide, donc des variables neutres, donc une facture
QUI EST MALGRES TOUT NOTEE. Un pseudonyme inconnu ou une table indisponible
ne doit pas faire repondre 500 au jury le jour J.

Les referentiels statiques (actes, grille tarifaire, garanties, contrats) ne
sont PAS lus ici : ils sont versionnes avec le modele et charges en memoire au
demarrage (`registry.load_version`). Seules les donnees VOLATILES
(ordonnances, assures) necessitent une lecture.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text

from predicare.db import session_scope
from predicare.features import Contrat, Ordonnance, Prestataire, Referentiels
from predicare.logging_config import get_logger
from predicare.schemas import InvoiceSubmission

logger = get_logger("api-inference.context")


#: Felzenszwalb & Huttenlocher : une facture ne peut pas concerner une
#: ordonnance de plus de 730 jours, c'est la duree maximale de conservation
#: retenue par `api-inference/validation.py`. Sans borne, un jour de soin
#: aberrant (0001-01-01) rapperait le premier jour dusiecle.
PERIODE_MAX_ORDONNANCE_JOURS = 730


def _date(valeur: object) -> date | None:
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    return None


def _resoudre_ordonnance(session: Any, facture: InvoiceSubmission) -> Ordonnance | None:
    """Charge l'ordonnance validee a la date du soin.

    Une facture peut porter plusieurs ordonnances candidates. On retient celle
    qui est validee a la date du soin et la plus recente : c'est la regle
    metier, et c'est celle qui rend `ordonnance_expiree` signifiant.
    """
    pseudonyme = facture.assure_pseudonyme
    prestataire = facture.prestataire_id
    date_facture = _date(facture.date_facture)
    if date_facture is None:
        return None
    borne_bas = date_facture - timedelta(days=PERIODE_MAX_ORDONNANCE_JOURS)

    # Les cles etrangeres de `core.*` sont des ID TECHNIQUES (entiers), alors
    # que la payload porte des pseudonymes et des codes metier. Sans cette
    # traduction, chaque requete echoue sur un `invalid input syntax for type
    # integer` et le contexte retombe silencieusement a vide.
    id_assure = session.execute(
        text("SELECT id FROM core.assure WHERE pseudonyme = :p"),
        {"p": pseudonyme},
    ).scalar()
    if id_assure is None:
        logger.info("assure.inconnu", pseudonyme=pseudonyme)
        return None

    # La facture porte le CODE metier du prestataire, la base stocke un ID
    # technique : la traduction se fait une fois, en amont. Sans elle, le
    # filtre ne retournerait jamais de ligne et toutes les variables de
    # prescription retomberaient a leur valeur neutre.
    id_prestataire = session.execute(
        text("SELECT id FROM core.prestataire WHERE code = :code"),
        {"code": prestataire},
    ).scalar()
    if id_prestataire is None:
        logger.info("prestataire.inconnu", code=prestataire)
        return None

    lignes = session.execute(
        text(
            """
            SELECT o.id, o.date_ordonnance, o.validite_jours, o.prestataire_id
            FROM core.ordonnance o
            WHERE o.assure_id = :assure
              AND o.prestataire_id = :prestataire_id
              AND o.date_ordonnance BETWEEN :borne_bas AND :date_facture
            ORDER BY o.date_ordonnance DESC
            LIMIT 10
            """
        ),
        {
            "assure": id_assure,
            "prestataire_id": id_prestataire,
            "borne_bas": borne_bas,
            "date_facture": date_facture,
        },
    ).fetchall()
    if not lignes:
        return None

    # `o.prestataire_id` est un id technique : on le convertit en code metier
    # pour que la comparaison avec `prestataire_id` de la facture fonctionne
    # des deux cotes.
    correspondance = session.execute(
        text("SELECT id, code FROM core.prestataire WHERE id = ANY(:ids)"),
        {"ids": [ligne.prestataire_id for ligne in lignes]},
    ).fetchall()
    codes = {row.id: row.code for row in correspondance}

    choisi = None
    for ligne in lignes:
        prescription = _date(ligne.date_ordonnance)
        validite = int(ligne.validite_jours or 0)
        if prescription is None or date_facture is None:
            continue
        if prescription <= date_facture <= prescription + timedelta(days=validite):
            choisi = (ligne.id, ligne.date_ordonnance, validite, ligne.prestataire_id)
            break

    if choisi is None:
        # Aucune ordonnance valide : on retient la plus recente malgre tout,
        # pour que `ordonnance_expiree` vaille 1 et que le gestionnaire voie
        # pourquoi la facture est signalee.
        ligne = lignes[0]
        choisi = (
            ligne.id,
            ligne.date_ordonnance,
            int(ligne.validite_jours or 0),
            ligne.prestataire_id,
        )
        logger.info("ordonnance.expiree", facture_id=facture.facture_id, ordonnance=str(choisi[0]))

    ordonnance_id, prescription, validite, id_prescripteur = choisi

    # `core.ordonnance_ligne` ne stocke PAS de code : elle reference l'acte
    # ou le medicament par ID technique. Il faut donc rejoindre les deux
    # referentiels pour retrouver les CODES, sans quoi
    # `taux_lignes_non_prescrites` serait toujours a 1 (aucun code trouve)
    # et le modele crierait a la fraude sur toute facture ordonnee.
    codes_prescrits = {
        row.code
        for row in session.execute(
            text(
                """
                SELECT a.code AS code FROM core.ordonnance_ligne ol
                JOIN core.acte a ON a.id = ol.acte_id
                WHERE ol.ordonnance_id = :id AND ol.acte_id IS NOT NULL
                UNION
                SELECT m.code AS code FROM core.ordonnance_ligne ol
                JOIN core.medicament m ON m.id = ol.medicament_id
                WHERE ol.ordonnance_id = :id AND ol.medicament_id IS NOT NULL
                """
            ),
            {"id": ordonnance_id},
        )
    }
    return Ordonnance(
        prescripteur_id=codes.get(id_prescripteur, ""),
        date_prescription=_date(prescription),
        validite_jours=validite,
        codes_prescrits=frozenset(codes_prescrits),
    )


def _resoudre_contrat(session: Any, facture: InvoiceSubmission) -> Contrat | None:
    """Contrat actif de l'assure a la date du soin.

    Les contrats sont statiques et figurent dans les referentiels du modele ;
    cette lecture ne sert donc qu'a identifier lequel s'applique. Si la base
    est indisponible, le referentiel fourni au featheur couvre l'essentiel.
    """
    date_facture = _date(facture.date_facture)
    if date_facture is None:
        return None
    # `cb.assure_id` est l'ID technique, pas le pseudonyme de la payload.
    row = session.execute(
        text(
            """
            SELECT c.numero, c.date_debut, c.date_fin, c.niveau
            FROM core.contrat_beneficiaire cb
            JOIN core.contrat c ON c.id = cb.contrat_id
            JOIN core.assure a ON a.id = cb.assure_id
            WHERE a.pseudonyme = :pseudonyme
              AND (c.date_debut IS NULL OR c.date_debut <= :date_facture)
              AND (c.date_fin IS NULL OR c.date_fin >= :date_facture)
            ORDER BY c.date_debut DESC
            LIMIT 1
            """
        ),
        {"pseudonyme": facture.assure_pseudonyme, "date_facture": date_facture},
    ).fetchone()
    if row is None:
        return None
    return Contrat(
        date_effet=_date(row.date_debut),
        date_fin=_date(row.date_fin),
        formule=(row.niveau or "").upper(),
    )


def _resoudre_assure(session: Any, facture: InvoiceSubmission) -> tuple[int | None, str]:
    """Annee de naissance et sexe de l'assure, pour la coherence profil.

    Ce sont les DEUX seuls attributs personnes lus ici. Le nom, la date de
    naissance exacte et les coordonnees restent dans `core.identite_chiffree`,
    chiffre et isole : le modele n'en a pas besoin, donc il ne les demande pas.
    """
    row = session.execute(
        text("SELECT annee_naissance, sexe FROM core.assure WHERE pseudonyme = :p"),
        {"p": facture.assure_pseudonyme},
    ).fetchone()
    if row is None:
        logger.info("assure.inconnu", pseudonyme=facture.assure_pseudonyme)
        return None, ""
    return row.annee_naissance, (row.sexe or "")


def resolve_context(
    facture: InvoiceSubmission,
    referentiels: Referentiels | None = None,
) -> dict[str, Any]:
    """Rend le contexte de `build_features`, ou un contexte neutre.

    Toute exception est absorbee et journalisee : le retour est alors un
    dictionnaire vide, donc des variables neutres, donc une facture notee.
    Preference aux referentiels du modele pour le prestataire, qui est une
    donnee statique : la base n'est interrogee que si le referentiel ne le
    contient pas.
    """
    contexte: dict[str, Any] = {}

    prestataire: Prestataire | None = None
    if referentiels is not None:
        prestataire = referentiels.prestataires.get(facture.prestataire_id)
    if prestataire is not None:
        contexte["prestataire"] = prestataire

    try:
        with session_scope() as session:
            ordonnance = _resoudre_ordonnance(session, facture)
            if ordonnance is not None:
                contexte["ordonnance"] = ordonnance
            contrat = _resoudre_contrat(session, facture)
            if contrat is not None:
                contexte["contrat"] = contrat
            annee, sexe = _resoudre_assure(session, facture)
            if annee is not None or sexe:
                contexte["assure_annee_naissance"] = annee
                contexte["assure_sexe"] = sexe
    except Exception as exc:
        # La base est un confort, pas une condition de notation.
        logger.warning(
            "contexte.resolution.echouee", erreur=str(exc), facture_id=facture.facture_id
        )

    return contexte
