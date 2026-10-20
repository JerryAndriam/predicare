"""Factures et ordonnances : depot, consultation, historique.

Le depot d'une facture est un enchainement, pas un simple proxy :

1. valider la charge utile avec le MEME schema que le service d'inference
   (`InvoiceSubmission`) : le front et le back refusent donc les memes
   documents, avec le meme vocabulaire ;
2. verifier que l'assure, le prestataire et les actes existent ;
3. faire noter la facture par le Flux 1 (XGBoost + SHAP) ;
4. seulement alors, ecrire la facture en base.

L'ordre est delibere. Noter avant d'ecrire garantit qu'une facture invalide
ne laisse AUCUNE trace, et que la base ne contient jamais un document que le
modele n'a pas vu. La prediction est ensuite persistee depuis api-core, parce
que la facture n'existait pas encore au moment de l'appel d'inference.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from predicare.audit import journaliser
from predicare.auth import TokenPayload
from predicare.db import session_scope
from predicare.dependencies import get_threshold, require_permission
from predicare.errors import (
    ConflictError,
    ForbiddenError,
    InvalidInvoiceError,
    ModelNotReadyError,
    NotFoundError,
    PrediCareError,
)
from predicare.logging_config import get_logger
from predicare.persistance_ml import persister_prediction
from predicare.rbac import Role
from predicare.schemas import InvoiceSubmission, ShapContribution
from predicare_core_api.notifications import notifier_alerte

router = APIRouter(prefix="/factures", tags=["facturation"])
logger = get_logger("api-core.billing")

#: Le controle d'acces est applique AVANT le corps de la route, donc avant
#: toute lecture ou ecriture en base. Le front ne fait que refleter la regle ;
#: la verite est ici (CDC, Phase 6.1).
SubmitUser = Annotated[TokenPayload, Depends(require_permission("facture:soumettre"))]
ReadUser = Annotated[TokenPayload, Depends(require_permission("facture:lire"))]


class InvoiceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facture_id: str
    assure_pseudonyme: str
    prestataire_id: str
    date_facture: datetime
    montant_total: float
    montant_eligible: float | None = None
    montant_pris_en_charge: float | None = None
    reste_a_charge: float | None = None
    statut: str
    score_fraude: float | None = None
    is_fraud: bool | None = None


class Page(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[InvoiceSummary]
    total: int
    limit: int
    offset: int


class SubmitAccepted(BaseModel):
    """Reponse du service d'inference, retransmise telle quelle.

    `extra="allow"` est volontaire : le score, les contributions SHAP et le
    rapport lisible sont ajoutes par le Flux 1. Les figer ici obligerait a
    modifier api-core a chaque evolution de l'explicabilite.
    """

    model_config = ConfigDict(extra="allow")

    facture_id: str
    score_fraude: float
    is_fraud: bool
    seuil_applique: float
    model_version: str | None = None


@router.post("/soumettre", response_model=SubmitAccepted, status_code=202)
def submit_invoice(payload: dict, request: Request, user: SubmitUser) -> SubmitAccepted:
    """Valide, note via le Flux 1, puis enregistre la facture."""
    try:
        invoice = InvoiceSubmission.model_validate(payload)
    except ValidationError as exc:
        raise InvalidInvoiceError(f"Facture invalide - {_field_error(exc)}") from exc

    # L'identifiant metier est la `reference` en base : c'est lui que le
    # service d'inference renvoie, et lui qui rattache la prediction.
    reference = invoice.facture_id or f"FAC-{uuid4().hex[:12].upper()}"

    _verifier_references(invoice, user)
    resultat = _appeler_inference(request, {**payload, "facture_id": reference})
    _enregistrer_facture(invoice, reference)

    contributions = [ShapContribution(**contribution) for contribution in resultat.get("shap", [])]
    persister_prediction(
        reference=reference,
        model_version=str(resultat.get("model_version", "inconnu")),
        score=float(resultat["score_fraude"]),
        seuil=float(resultat["seuil_applique"]),
        is_fraud=bool(resultat["is_fraud"]),
        contributions=contributions,
    )

    logger.info(
        "facture.soumise",
        reference=reference,
        score=resultat["score_fraude"],
        acteur=user.subject,
    )

    # Flux 1 du CDC : au-dessus du seuil de NOTIFICATION, la chaine d'alerte
    # est declenchee (webhook n8n -> Slack + e-mail au gestionnaire).
    # L'appel est tolerent aux pannes : une panne de notification ne doit
    # pas faire perdre la facture, qui est deja notee et enregistree.
    #
    # L'etat de la notification est RENVOYE au front : un depot qui n'a
    # prevenu personne doit le dire, sinon l'utilisateur croit avoir
    # declenche une alerte alors que personne n'a ete prevenu.
    notification = notifier_alerte(
        facture_id=reference,
        score=float(resultat["score_fraude"]),
        seuil=float(resultat["seuil_applique"]),
        rapport_shap=str(resultat.get("rapport_shap", "")),
        model_version=str(resultat.get("model_version", "")),
        assure_pseudonyme=invoice.assure_pseudonyme,
        montant_total=invoice.montant_total,
    )
    resultat["notification"] = {
        "envoye": notification.envoye,
        "message": notification.motif,
    }

    return SubmitAccepted(**resultat)


def _field_error(exc: ValidationError) -> str:
    """Message nommant le champ fautif, comme dans le service d'inference."""
    return " ; ".join(
        f"{'.'.join(str(partie) for partie in erreur['loc']) or 'racine'} : {erreur['msg']}"
        for erreur in exc.errors()
    )


def _exiger(session: Session, table: str, colonne: str, valeur: str, champ: str) -> int:
    """Resout un identifiant technique, ou rejette la facture en nommant le champ.

    `table` et `colonne` sont des litteraux du code, jamais des valeurs
    utilisateur : l'interpolation est donc sans risque d'injection.
    """
    identifiant = session.execute(
        text(f"SELECT id FROM {table} WHERE {colonne} = :valeur"),
        {"valeur": valeur},
    ).scalar()
    if identifiant is None:
        raise InvalidInvoiceError(
            f"Facture invalide - {champ} : valeur inconnue ({valeur})",
            details={"champ": champ, "valeur": valeur},
        )
    return int(identifiant)


def _verifier_references(invoice: InvoiceSubmission, user: TokenPayload) -> None:
    """Verifie les references AVANT de noter : rien n'est ecrit si elles manquent.

    Un professionnel de sante ne depose que pour SON prestataire : le controle
    est fait ici, sur l'identifiant du compte, et pas seulement dans le
    formulaire. Changer le code envoye dans la requete ne suffit donc pas a
    facturer pour un autre etablissement.
    """
    with session_scope() as session:
        _exiger(
            session, "core.assure", "pseudonyme", invoice.assure_pseudonyme, "assure_pseudonyme"
        )
        prestataire_id = _exiger(
            session, "core.prestataire", "code", invoice.prestataire_id, "prestataire_id"
        )
        for index, ligne in enumerate(invoice.lignes):
            _exiger(session, "core.acte", "code", ligne.code_acte, f"lignes.{index}.code_acte")

        if user.role is Role.PROFESSIONNEL_SANTE:
            propre = _prestataire_du_compte(session, user)
            if propre != prestataire_id:
                raise ForbiddenError(
                    "Un professionnel ne peut deposer que pour son propre prestataire.",
                    details={"champ": "prestataire_id"},
                )


def _prestataire_du_compte(session: Session, user: TokenPayload) -> int:
    """Prestataire rattache au compte professionnel, ou 403 explicite.

    Sans ce rattachement, le compte verrait toutes les factures de la
    plateforme : c'est le trou de perimetre que la revue a identifie.
    """
    if not str(user.subject).isdigit():
        raise ForbiddenError("Compte professionnel sans identifiant exploitable.")
    propre = session.execute(
        text("SELECT prestataire_id FROM core.utilisateur WHERE id = :user_id"),
        {"user_id": int(user.subject)},
    ).scalar()
    if propre is None:
        raise ForbiddenError(
            "Ce compte professionnel n'est rattache a aucun prestataire. "
            "Un administrateur doit le configurer."
        )
    return int(propre)


def _appeler_inference(request: Request, payload: dict) -> dict:
    """Appelle le Flux 1 et traduit ses erreurs en erreurs metier d'api-core.

    Sans cette traduction, un modele absent remonterait en 500 : le
    gestionnaire verrait une panne technique la ou il faut lui dire
    exactement ce qui manque.
    """
    url = str(request.app.state.inference_api_url).rstrip("/")
    try:
        response = httpx.post(f"{url}/predire", json=payload, timeout=15.0)
    except httpx.HTTPError as exc:
        raise ModelNotReadyError(
            "Service d'inference injoignable : verifiez le conteneur api-inference."
        ) from exc

    if response.status_code == 422:
        corps = _corps_json(response)
        raise InvalidInvoiceError(
            str(corps.get("message", "Facture invalide.")),
            details=corps.get("details") or {},
        )
    if response.status_code == 503:
        raise ModelNotReadyError(
            "Aucun modele actif : lancez `make train`, puis `make model-promote`."
        )
    if response.status_code >= 400:
        raise PrediCareError(
            "Le service d'inference a refuse la facture.",
            details={"status": response.status_code, **_corps_json(response)},
        )
    return response.json()


def _corps_json(response: httpx.Response) -> dict:
    """Corps JSON tolerant : une passerelle peut renvoyer du HTML."""
    try:
        corps = response.json()
    except ValueError:
        return {"message": response.text[:500]}
    return corps if isinstance(corps, dict) else {"message": str(corps)[:500]}


def _ordonnance_liee(
    session: Session,
    *,
    assure_id: int,
    prestataire_id: int,
    date_facture: datetime,
    codes_actes: list[str],
) -> int | None:
    """Ordonnance qui couvre l'un des actes de la facture, si elle existe.

    Le modele d'inference resout deja l'ordonnance par date, mais laisser
    `facture.ordonnance_id` vide prive la base du lien explicite demande par
    le CDC. On ne cree pas de lien approximatif : il faut le meme assure, le
    meme prestataire, un acte present dans les lignes et une ordonnance encore
    valide a la date du soin.
    """
    if not codes_actes:
        return None
    identifiant = session.execute(
        text(
            """
            SELECT o.id
            FROM core.ordonnance o
            JOIN core.ordonnance_ligne ol ON ol.ordonnance_id = o.id
            JOIN core.acte a ON a.id = ol.acte_id
            WHERE o.assure_id = :assure_id
              AND o.prestataire_id = :prestataire_id
              AND a.code IN :codes
              AND o.date_ordonnance <= :date_facture
              AND o.date_ordonnance
                  + make_interval(days => COALESCE(o.validite_jours, 0))
                  >= :date_facture
            ORDER BY o.date_ordonnance DESC
            LIMIT 1
            """
        ).bindparams(bindparam("codes", expanding=True)),
        {
            "assure_id": assure_id,
            "prestataire_id": prestataire_id,
            "date_facture": date_facture,
            "codes": codes_actes,
        },
    ).scalar()
    return int(identifiant) if identifiant is not None else None


def _enregistrer_facture(invoice: InvoiceSubmission, reference: str) -> None:
    """Ecrit la facture et ses lignes. Idempotent sur `reference`."""
    with session_scope() as session:
        existante = session.execute(
            text("SELECT id FROM core.facture WHERE reference = :reference"),
            {"reference": reference},
        ).scalar()
        if existante is not None:
            return

        assure_id = _exiger(
            session, "core.assure", "pseudonyme", invoice.assure_pseudonyme, "assure_pseudonyme"
        )
        prestataire_id = _exiger(
            session, "core.prestataire", "code", invoice.prestataire_id, "prestataire_id"
        )
        ordonnance_id = _ordonnance_liee(
            session,
            assure_id=assure_id,
            prestataire_id=prestataire_id,
            date_facture=invoice.date_facture,
            codes_actes=[ligne.code_acte for ligne in invoice.lignes],
        )
        facture_id = session.execute(
            text(
                """
                INSERT INTO core.facture
                    (reference, assure_id, prestataire_id, ordonnance_id,
                     date_facture, montant_total, statut)
                VALUES (:reference, :assure_id, :prestataire_id, :ordonnance_id,
                        :date_facture, :montant_total, 'recue')
                RETURNING id
                """
            ),
            {
                "reference": reference,
                "assure_id": assure_id,
                "prestataire_id": prestataire_id,
                "ordonnance_id": ordonnance_id,
                "date_facture": invoice.date_facture,
                "montant_total": invoice.montant_total,
            },
        ).scalar()

        for index, ligne in enumerate(invoice.lignes):
            acte_id = _exiger(
                session, "core.acte", "code", ligne.code_acte, f"lignes.{index}.code_acte"
            )
            session.execute(
                text(
                    """
                    INSERT INTO core.ligne_facture
                        (facture_id, acte_id, quantite, montant_unitaire, date_acte)
                    VALUES (:facture_id, :acte_id, :quantite, :montant_unitaire, :date_acte)
                    """
                ),
                {
                    "facture_id": facture_id,
                    "acte_id": acte_id,
                    "quantite": ligne.quantite,
                    "montant_unitaire": ligne.montant_unitaire,
                    "date_acte": ligne.date_acte,
                },
            )


@router.get("", response_model=Page)
def list_invoices(
    user: ReadUser,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    statut: str | None = Query(default=None, max_length=32),
    prestataire: str | None = Query(default=None, max_length=64),
) -> Page:
    """Historique des factures.

    Un assure ne voit QUE ses propres factures : le filtre est applique
    dans la requete SQL a partir du pseudonyme du jeton, jamais renvoye au
    client pour qu'il filtre lui-meme.

    `statut` et `prestataire` sont des filtres de lecture, appliques COTE
    SERVEUR : ils servent a retrouver un dossier precis dans une base qui
    compte plus de 80 000 factures, pas a contourner le perimetre du role.
    """
    where = ""
    params: dict[str, object] = {}
    if user.role is Role.ASSURE:
        if not user.insured_id:
            raise InvalidInvoiceError(
                "Aucun dossier assure rattache a ce compte.",
                details={"champ": "assured_id"},
            )
        where = "AND f.assure_id = :assure_id"
        params["assure_id"] = user.insured_id
    elif user.role is Role.PROFESSIONNEL_SANTE:
        # Perimetre du professionnel : ses propres depots uniquement. Le
        # rattachement vit en base, pas dans le jeton, pour qu'un changement
        # de prestataire s'applique sans reconnecter l'utilisateur.
        with session_scope() as session:
            propre = _prestataire_du_compte(session, user)
        where = "AND f.prestataire_id = :prestataire_id"
        params["prestataire_id"] = propre

    # Filtres de lecture, toujours en plus du perimetre du role.
    if statut is not None and statut.strip():
        # La base melange les historique (PAYEE, EN_COURS) et les statuts
        # crees par le front (recue, fraude_confirmee) : la comparaison se
        # fait donc sans distinction de casse.
        where += " AND upper(f.statut) = :statut"
        params["statut"] = statut.strip().upper()
    if prestataire is not None and prestataire.strip():
        where += " AND pr.code = :prestataire_code"
        params["prestataire_code"] = prestataire.strip()

    with session_scope() as session:
        total = int(
            session.execute(
                text(
                    f"""
                SELECT count(*)
                FROM core.facture f
                JOIN core.prestataire pr ON pr.id = f.prestataire_id
                WHERE true {where}
                """
                ),
                params,
            ).scalar_one()
        )
        rows = (
            session.execute(
                text(
                    f"""
                SELECT f.id::text AS facture_id, a.pseudonyme AS assure_pseudonyme,
                       pr.code AS prestataire_id, f.date_facture, f.montant_total,
                       f.montant_eligible, f.montant_pris_en_charge, f.reste_a_charge,
                       f.statut, p.score_fraude, p.is_fraud
                FROM core.facture f
                JOIN core.assure a ON a.id = f.assure_id
                JOIN core.prestataire pr ON pr.id = f.prestataire_id
                LEFT JOIN ml.prediction p ON p.facture_id = f.id
                WHERE true {where}
                ORDER BY f.date_facture DESC
                LIMIT :limit OFFSET :offset
                """
                ),
                {**params, "limit": limit, "offset": offset},
            )
            .mappings()
            .all()
        )

    return Page(
        items=[InvoiceSummary(**row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/seuil-actuel")
def current_threshold() -> dict[str, float]:
    """Seuil d'alerte en vigueur, affiche dans l'ecran d'administration."""
    return {"seuil": get_threshold()}




class ReferenceAssure(BaseModel):
    pseudonyme: str


class ReferencePrestataire(BaseModel):
    code: str
    nom: str
    specialite: str


class ReferenceActe(BaseModel):
    code: str
    libelle: str
    prix_unitaire: float


class References(BaseModel):
    """Referentiels necessaires au formulaire de depot.

    Sans eux, un professionnel devrait connaitre par coeur les codes d'acte
    et les pseudonymes : l'interface serait inutilisable en demonstration.
    Seules des valeurs de reference sont exposees, jamais une identite.
    """

    model_config = ConfigDict(extra="forbid")

    assures: list[ReferenceAssure]
    prestataires: list[ReferencePrestataire]
    actes: list[ReferenceActe]
    prestataire_du_compte: str | None = None


@router.get("/references", response_model=References)
def references(user: SubmitUser) -> References:
    """Valeurs de reference pour pre-remplir le formulaire de depot.

    Un professionnel ne recoit QUE son prestataire : le formulaire ne peut donc
    pas proposer un etablissement qui lui vaudrait un 403 a la soumission.
    """
    propre: str | None = None
    with session_scope() as session:
        assures = (
            session.execute(text("SELECT pseudonyme FROM core.assure ORDER BY id LIMIT 50"))
            .mappings()
            .all()
        )
        if user.role is Role.PROFESSIONNEL_SANTE:
            prestataire_id = _prestataire_du_compte(session, user)
            prestataires = (
                session.execute(
                    text(
                        "SELECT code, nom, specialite FROM core.prestataire "
                        "WHERE id = :prestataire_id ORDER BY code"
                    ),
                    {"prestataire_id": prestataire_id},
                )
                .mappings()
                .all()
            )
            propre = prestataires[0]["code"] if prestataires else None
        else:
            prestataires = (
                session.execute(
                    text(
                        "SELECT code, nom, specialite FROM core.prestataire "
                        "ORDER BY code LIMIT 100"
                    )
                )
                .mappings()
                .all()
            )
        actes = (
            session.execute(
                text(
                    "SELECT code, libelle, prix_unitaire FROM core.acte "
                    "WHERE actif ORDER BY code LIMIT 200"
                )
            )
            .mappings()
            .all()
        )
    return References(
        assures=[ReferenceAssure(**row) for row in assures],
        prestataires=[ReferencePrestataire(**row) for row in prestataires],
        actes=[ReferenceActe(**row) for row in actes],
        prestataire_du_compte=propre,
    )


class Ordonnance(BaseModel):
    """Depot d'ordonnance par un professionnel de sante.

    Les champs `reference`, `diagnostic` et `validite_jours` alimentent les
    variables de prescription du Flux 1 (`delai_prescription_jours`,
    `ordonnance_expiree`, `taux_lignes_non_prescrites`). Les laisser vides
    rendait ces variables neutres pour toute ordonnance creee depuis l'IHM.
    """

    model_config = ConfigDict(extra="forbid")

    assure_pseudonyme: str = Field(min_length=4, max_length=64)
    prestataire_id: str = Field(min_length=2, max_length=64)
    code_acte: str = Field(min_length=2, max_length=20)
    date_ordonnance: datetime
    quantite: int = Field(default=1, ge=1, le=999)
    reference: str | None = Field(default=None, max_length=64)
    diagnostic: str | None = Field(default=None, max_length=256)
    validite_jours: int = Field(default=30, ge=1, le=730)


@router.post("/ordonnances", status_code=201)
def submit_prescription(payload: Ordonnance, user: SubmitUser) -> dict[str, str]:
    """Enregistre une ordonnance et detecte le doublon evident.

    Le CDC demande la detection des doublons de prescription. Le controle
    porte sur le triplet (assure, acte, jour) : deux prescriptions identiques
    le meme jour sont refusees avec un 409 explicite, au lieu d'etre empilees
    silencieusement. Le reste des anomalies (inadequation diagnostic) est
    laisse au modele, qui recoit desormais le diagnostic et la duree.
    """
    with session_scope() as session:
        assure_id = _exiger(
            session, "core.assure", "pseudonyme", payload.assure_pseudonyme, "assure_pseudonyme"
        )
        prestataire_id = _exiger(
            session, "core.prestataire", "code", payload.prestataire_id, "prestataire_id"
        )
        if user.role is Role.PROFESSIONNEL_SANTE:
            propre = _prestataire_du_compte(session, user)
            if propre != prestataire_id:
                raise ForbiddenError(
                    "Un professionnel ne peut prescrire que pour son propre prestataire.",
                    details={"champ": "prestataire_id"},
                )
        acte_id = _exiger(session, "core.acte", "code", payload.code_acte, "code_acte")

        doublon = session.execute(
            text(
                """
                SELECT COALESCE(o.reference, 'sans reference')
                FROM core.ordonnance o
                WHERE o.assure_id = :assure_id
                  AND (
                        o.acte_id = :acte_id
                        OR EXISTS (
                            SELECT 1
                            FROM core.ordonnance_ligne ol
                            WHERE ol.ordonnance_id = o.id AND ol.acte_id = :acte_id
                        )
                      )
                  AND CAST(o.date_ordonnance AS date) = CAST(:date_ordonnance AS date)
                LIMIT 1
                """
            ),
            {
                "assure_id": assure_id,
                "acte_id": acte_id,
                "date_ordonnance": payload.date_ordonnance,
            },
        ).scalar()
        if doublon is not None:
            raise ConflictError(
                f"Ordonnance en doublon : {doublon} existe deja pour ce dossier, "
                "cet acte et ce jour.",
                details={"type": "doublon_ordonnance", "reference": str(doublon)},
            )

        reference = (payload.reference or f"ORD-{uuid4().hex[:10].upper()}").strip()
        deja_utilisee = session.execute(
            text("SELECT 1 FROM core.ordonnance WHERE reference = :reference LIMIT 1"),
            {"reference": reference},
        ).scalar()
        if deja_utilisee is not None:
            raise ConflictError(
                f"La reference d ordonnance {reference} est deja utilisee.",
                details={"type": "reference_ordonnance", "reference": reference},
            )
        ordonnance_id = session.execute(
            text(
                """
                INSERT INTO core.ordonnance
                    (assure_id, prestataire_id, acte_id, date_ordonnance, quantite,
                     reference, validite_jours, diagnostic)
                VALUES (:assure_id, :prestataire_id, :acte_id, :date_ordonnance,
                        :quantite, :reference, :validite_jours, :diagnostic)
                RETURNING id
                """
            ),
            {
                "assure_id": assure_id,
                "prestataire_id": prestataire_id,
                "acte_id": acte_id,
                "date_ordonnance": payload.date_ordonnance,
                "quantite": payload.quantite,
                "reference": reference,
                "validite_jours": payload.validite_jours,
                "diagnostic": payload.diagnostic,
            },
        ).scalar_one()

        # L'en-tete seul ne suffit pas au modele : `taux_lignes_non_prescrites`
        # est calcule a partir des codes presents dans `ordonnance_ligne`.
        session.execute(
            text(
                """
                INSERT INTO core.ordonnance_ligne
                    (ordonnance_id, num_ligne, acte_id, quantite)
                VALUES (:ordonnance_id, 1, :acte_id, :quantite)
                """
            ),
            {
                "ordonnance_id": int(ordonnance_id),
                "acte_id": acte_id,
                "quantite": payload.quantite,
            },
        )
        journaliser(
            session,
            acteur=user.subject,
            role=str(user.role),
            action="ordonnance_deposee",
            cible=f"ordonnance:{ordonnance_id}",
            details={
                "reference": reference,
                "assure_pseudonyme": payload.assure_pseudonyme,
                "code_acte": payload.code_acte,
                "diagnostic": payload.diagnostic,
                "validite_jours": payload.validite_jours,
            },
        )

    logger.info(
        "ordonnance.deposee",
        acteur=user.subject,
        acte=payload.code_acte,
        reference=reference,
    )
    return {
        "status": "accepted",
        "assure_pseudonyme": payload.assure_pseudonyme,
        "reference": reference,
    }


# ---------------------------------------------------------------------------
# DETAIL D'UNE FACTURE
# ---------------------------------------------------------------------------
# Cette route est declaree EN DERNIER : /{facture_id} capterait sinon
# les routes statiques (/references, /seuil-actuel, ...) qui doivent
# etre declarees avant.
class FactureLigne(BaseModel):
    """Une ligne de facture, avec l'acte qui la porte."""

    model_config = ConfigDict(extra="forbid")

    code_acte: str
    libelle: str
    quantite: int
    montant_unitaire: float
    montant_total: float
    date_acte: datetime


class FactureDetail(BaseModel):
    """Facture complete : lignes, actes, notation et decisions.

    C'est l'ecran qui manquait pour que l'assure, le professionnel et le
    gestionnaire puissent TOUS consulter la meme facture. Le perimetre reste
    celui du role : un assure ne voit que ses factures, un professionnel
    que les siennes.
    """

    model_config = ConfigDict(extra="forbid")

    facture_id: str
    assure_pseudonyme: str
    prestataire_id: str
    date_facture: datetime
    montant_total: float
    montant_eligible: float | None = None
    montant_pris_en_charge: float | None = None
    reste_a_charge: float | None = None
    statut: str
    lignes: list[FactureLigne] = []
    score_fraude: float | None = None
    is_fraud: bool | None = None
    seuil_applique: float | None = None
    model_version: str | None = None
    predictions: list[dict] = []
    decisions: list[dict] = []


@router.get("/{facture_id}", response_model=FactureDetail)
def detail_facture(facture_id: str, user: ReadUser) -> FactureDetail:
    """Detail d'une facture : lignes, actes, notation et historique.

    Le perimetre est applique comme dans la liste : un assure qui demande
    la facture d'un autre dossier recoit un 404, pas une 403 qui revelerait
    l'existence du dossier.
    """
    if not facture_id.isdigit():
        raise NotFoundError("Facture introuvable.")

    with session_scope() as session:
        entete = (
            session.execute(
                text(
                    """
                SELECT f.id::text AS facture_id, a.pseudonyme AS assure_pseudonyme,
                       pr.code AS prestataire_id, f.date_facture, f.montant_total,
                       f.montant_eligible, f.montant_pris_en_charge, f.reste_a_charge,
                       f.statut, p.score_fraude, p.is_fraud, p.seuil_applique,
                       p.model_version
                FROM core.facture f
                JOIN core.assure a ON a.id = f.assure_id
                JOIN core.prestataire pr ON pr.id = f.prestataire_id
                LEFT JOIN ml.prediction p ON p.facture_id = f.id
                WHERE f.id = :facture_id
                """
                ),
                {"facture_id": int(facture_id)},
            )
            .mappings()
            .first()
        )
        if entete is None:
            raise NotFoundError("Facture introuvable.")

        # Meme regle de perimetre que la liste : on ne revele pas l'existence
        # d'une facture qui n'appartient pas au role.
        if user.role is Role.ASSURE:
            if not user.insured_id:
                raise NotFoundError("Facture introuvable.")
            possesseur = session.execute(
                text("SELECT assure_id FROM core.facture WHERE id = :facture_id"),
                {"facture_id": int(facture_id)},
            ).scalar()
            if int(possesseur) != int(user.insured_id):
                raise NotFoundError("Facture introuvable.")
        elif user.role is Role.PROFESSIONNEL_SANTE:
            propre = _prestataire_du_compte(session, user)
            prestataire = session.execute(
                text("SELECT prestataire_id FROM core.facture WHERE id = :facture_id"),
                {"facture_id": int(facture_id)},
            ).scalar()
            if int(prestataire) != propre:
                raise NotFoundError("Facture introuvable.")

        lignes = (
            session.execute(
                text(
                    """
                    SELECT a.code AS code_acte, a.libelle, l.quantite,
                           l.montant_unitaire,
                           (l.quantite * l.montant_unitaire) AS montant_total,
                           l.date_acte
                    FROM core.ligne_facture l
                    JOIN core.acte a ON a.id = l.acte_id
                    WHERE l.facture_id = :facture_id
                    ORDER BY l.id
                    """
                ),
                {"facture_id": int(facture_id)},
            )
            .mappings()
            .all()
        )

        predictions = (
            session.execute(
                text(
                    """
                    SELECT id::text AS prediction_id, score_fraude, is_fraud,
                           seuil_applique, model_version, statut, created_at
                    FROM ml.prediction
                    WHERE facture_id = :facture_id
                    ORDER BY created_at DESC
                    """
                ),
                {"facture_id": int(facture_id)},
            )
            .mappings()
            .all()
        )

        decisions = (
            session.execute(
                text(
                    """
                    SELECT d.decision, d.commentaire, d.decided_by, d.decided_at
                    FROM audit.decision_gestionnaire d
                    JOIN ml.prediction p ON p.id = d.prediction_id
                    WHERE p.facture_id = :facture_id
                    ORDER BY d.decided_at DESC
                    """
                ),
                {"facture_id": int(facture_id)},
            )
            .mappings()
            .all()
        )

    return FactureDetail(
        **entete,
        lignes=[FactureLigne(**ligne) for ligne in lignes],
        predictions=[dict(row) for row in predictions],
        decisions=[dict(row) for row in decisions],
    )
