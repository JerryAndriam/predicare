"""Persistance des predictions, des rapports SHAP et du registre de modeles.

Flux 1 du CDC : « Inference -> SHAP -> Stockage de la transaction -> n8n ».
Le stockage manquait : le service d'inference renvoyait le score et ses
contributions sans rien ecrire, si bien que la file d'alertes du gestionnaire
restait vide et que la boucle de decision (taux de detection, faux positifs,
montants economises) restait a NULL dans le tableau de bord.

Trois ecritures, dans cet ordre d'importance :

- `ml.prediction` : une ligne par facture notee. Une facture deja en attente de
  decision est RE-NOTEE (UPDATE) au lieu d'etre dupliquee : deux lignes pour la
  meme facture feraient deux alertes dans la file du gestionnaire.
- `ml.shap_explication` : les contributions du rapport, numerotees comme dans
  la notification envoyee au gestionnaire.
- `ml.modele_version` : le registre des modeles de la plateforme (candidat puis
  promu), qui porte la condition « Maintenable » du jury.

Regle structurante : une panne d'ecriture ne doit JAMAIS faire echouer une
inference. Une facture notee mais non stockee reste une facture notee ;
l'inverse ferait perdre une alerte a cause d'un disque plein. Les fonctions
`stocker_*` levent (elles sont testables et transactionnelles), les fonctions
`persister_*` les enveloppent et avalent l'erreur en la journalisant.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from predicare.db import session_scope
from predicare.logging_config import get_logger

logger = get_logger("persistance-ml")

#: Seuil applique quand ni l'environnement ni le modele n'en proposent.
SEUIL_PAR_DEFAUT = 0.80

#: Nombre de contributions SHAP conservees par prediction. Le rapport envoye
#: au gestionnaire en compte 5 (`shap_to_contributions`) : en stocker moins
#: priverait l'ecran de decision de ce qu'il a lu, en stocker plus alourdirait
#: la table sans rien ajouter a la justification.
CONTRIBUTIONS_CONSERVEES = 5

#: Statuts qu'un calcul de score peut poser. Les autres valeurs de
#: `ml.prediction.statut` viennent des decisions du gestionnaire (`valider`,
#: `rejeter`, `piece`) et ne sont jamais ecrites par l'inference.
STATUTS_PREDICTION = ("nouvelle", "archive")

#: Cle du seuil d'alerte dans `audit.parametre`. L'ecran d'administration
#: ecrit cette cle ; la file du gestionnaire la relit. Une seule verite pour
#: tout le monde, ce qui evite qu'api-core filtre a 0.8 des alertes emises a
#: 0.29.
CLE_SEUIL_ALERTE = "seuil_alerte"


def _id_facture(session: Session, reference: str) -> int | None:
    """`core.facture.reference` porte l'identifiant metier (`FAC-...`).

    Le service d'inference recoit cet identifiant dans sa payload ; la cle
    etrangere de `ml.prediction` attend l'identifiant technique.
    """
    return session.execute(
        text("SELECT id FROM core.facture WHERE reference = :reference"),
        {"reference": reference},
    ).scalar()


def _prediction_en_attente(
    session: Session, facture_id: int, statut: str = "nouvelle"
) -> int | None:
    """Prediction de cette facture encore dans le statut donne, s'il y en a."""
    return session.execute(
        text(
            """
            SELECT id FROM ml.prediction
            WHERE facture_id = :facture_id AND statut = :statut
            ORDER BY id DESC
            LIMIT 1
            """
        ),
        {"facture_id": facture_id, "statut": statut},
    ).scalar()


def stocker_prediction(
    session: Session,
    *,
    reference: str,
    model_version: str,
    score: float,
    seuil: float,
    is_fraud: bool,
    contributions: Iterable[Any],
    statut: str = "nouvelle",
) -> int | None:
    """Ecrit `ml.prediction` et `ml.shap_explication`. Rend l'id, ou None.

    `statut` distingue deux usages :

    - `nouvelle` (defaut) : soumission temps reel, la facture entre dans la
      file de travail du gestionnaire ;
    - `archive` : notation RETROSPECTIVE (job `make noter`). Le score est
      conserve et mesure la qualite du modele, mais la facture n'a jamais ete
      soumise a un gestionnaire : la compter comme alerte non confirmee
      ferait afficher 100 % de faux positifs sur l'historique.

    None signifie « ignoree, et c'est normal » : la facture n'appartient pas a
    l'historique de la plateforme. Un identifiant inconnu n'est pas une panne,
    c'est une facture d'un autre systeme ; la journaliser en erreur noierait
    les vraies pannes.
    """
    if statut not in STATUTS_PREDICTION:
        raise ValueError(
            f"Statut de prediction inconnu : {statut!r}. Attendu : {STATUTS_PREDICTION}."
        )

    facture_id = _id_facture(session, reference)
    if facture_id is None:
        logger.info("prediction.facture_inconnue", reference=reference)
        return None

    valeurs = {
        "facture_id": facture_id,
        "version": model_version,
        "score": score,
        "seuil": seuil,
        "is_fraud": is_fraud,
    }

    prediction_id = _prediction_en_attente(session, facture_id, statut)
    if prediction_id is None:
        prediction_id = session.execute(
            text(
                """
                INSERT INTO ml.prediction
                    (facture_id, model_version, score_fraude, seuil_applique,
                     is_fraud, statut)
                VALUES (:facture_id, :version, :score, :seuil, :is_fraud, :statut)
                RETURNING id
                """
            ),
            {**valeurs, "statut": statut},
        ).scalar()
    else:
        # Re-notation : le score precedent n'a plus de sens, et la date doit
        # suivre le score courant sinon le delai de decision mesure une
        # ancienne alerte. Les explications sont remplacees plus bas.
        session.execute(
            text(
                """
                UPDATE ml.prediction
                SET model_version = :version, score_fraude = :score,
                    seuil_applique = :seuil, is_fraud = :is_fraud,
                    created_at = now()
                WHERE id = :prediction_id
                """
            ),
            {**valeurs, "prediction_id": prediction_id},
        )
        session.execute(
            text("DELETE FROM ml.shap_explication WHERE prediction_id = :prediction_id"),
            {"prediction_id": prediction_id},
        )

    for rang, contribution in enumerate(contributions, start=1):
        if rang > CONTRIBUTIONS_CONSERVEES:
            break
        session.execute(
            text(
                """
                INSERT INTO ml.shap_explication
                    (prediction_id, rang, feature, valeur, shap_value,
                     base_value, direction, libelle)
                VALUES (:prediction_id, :rang, :feature, :valeur, :shap_value,
                        :base_value, :direction, :libelle)
                """
            ),
            {
                "prediction_id": prediction_id,
                "rang": rang,
                "feature": contribution.feature,
                "valeur": float(contribution.value),
                "shap_value": float(contribution.shap_value),
                "base_value": (
                    float(contribution.base_value) if contribution.base_value is not None else None
                ),
                "direction": contribution.direction,
                "libelle": contribution.human_readable,
            },
        )
    return prediction_id


def persister_prediction(**champs: Any) -> int | None:
    """`stocker_prediction` en version « ne leve jamais », pour l'inference."""
    try:
        with session_scope() as session:
            return stocker_prediction(session, **champs)
    except Exception as exc:
        logger.warning(
            "prediction.non_persistee",
            erreur=str(exc),
            reference=champs.get("reference"),
        )
        return None


def enregistrer_version(
    session: Session,
    *,
    version: str,
    artefact_path: str,
    empreinte_donnees: str,
    metriques: dict[str, Any],
) -> None:
    """Inscrit la version au registre `ml.modele_version`, en statut candidat.

    Reentrainer une version deja connue la RAMENE a candidat : l'artefact a
    change, il n'a plus ete valide. C'est la seule facon d'eviter qu'un modele
    fraichement entraine et jamais evalue soit presente comme promu.
    """
    session.execute(
        text(
            """
            INSERT INTO ml.modele_version
                (version, statut, artefact_path, empreinte_donnees, metriques)
            VALUES (:version, 'candidat', :artefact_path, :empreinte,
                    CAST(:metriques AS jsonb))
            ON CONFLICT (version) DO UPDATE
            SET statut = 'candidat',
                promu_le = NULL,
                artefact_path = EXCLUDED.artefact_path,
                empreinte_donnees = EXCLUDED.empreinte_donnees,
                metriques = EXCLUDED.metriques,
                cree_le = now()
            """
        ),
        {
            "version": version,
            "artefact_path": artefact_path,
            "empreinte": empreinte_donnees,
            "metriques": json.dumps(metriques, ensure_ascii=False),
        },
    )


def declarer_version(**champs: Any) -> bool:
    """`enregistrer_version` en version « ne leve jamais », pour le job `train`.

    Un entrainement doit aboutir meme si la base est injoignable : les
    artefacts sur le volume suffisent au service. Le registre est un confort
    d'exploitation, pas une dependance de l'entrainement.
    """
    try:
        with session_scope() as session:
            enregistrer_version(session, **champs)
        return True
    except Exception as exc:
        logger.warning("version.non_enregistree", erreur=str(exc), version=champs.get("version"))
        return False


def marquer_version_active(session: Session, version: str) -> None:
    """Passe une version en `promu` et archive celle qu'elle remplace.

    `promu_le` n'est pose qu'une fois : repromouvoir la meme version (retour
    arriere vers une version deja promue) ne doit pas reecrire la date de sa
    premiere mise en service.
    """
    session.execute(
        text(
            """
            UPDATE ml.modele_version
            SET statut = 'archive'
            WHERE version <> :version AND statut = 'promu'
            """
        ),
        {"version": version},
    )
    session.execute(
        text(
            """
            UPDATE ml.modele_version
            SET statut = 'promu', promu_le = COALESCE(promu_le, now())
            WHERE version = :version
            """
        ),
        {"version": version},
    )


def activer_version(version: str) -> bool:
    """`marquer_version_active` en version « ne leve jamais », pour la bascule."""
    try:
        with session_scope() as session:
            marquer_version_active(session, version)
        return True
    except Exception as exc:
        logger.warning("version.statut_non_mis_a_jour", erreur=str(exc), version=version)
        return False


def lire_seuil_alerte(session: Session) -> float | None:
    """Seuil choisi par un administrateur, tel que persiste dans `audit.parametre`."""
    valeur = session.execute(
        text("SELECT valeur FROM audit.parametre WHERE cle = :cle"),
        {"cle": CLE_SEUIL_ALERTE},
    ).scalar()
    if valeur is None:
        return None
    try:
        seuil = float(valeur)
    except (TypeError, ValueError):
        logger.warning("seuil.illisible", valeur=str(valeur))
        return None
    return seuil if 0.0 <= seuil <= 1.0 else None


def amorcer_seuil_alerte(session: Session, valeur: float) -> bool:
    """Inscrit le seuil du modele s'il n'existe AUCUN seuil enregistre.

    `DO NOTHING` volontaire : le seuil arbitre par un administrateur, ou par
    l'exploitation via `FRAUD_ALERT_THRESHOLD`, ne doit jamais etre ecrase par
    le modele charge. Ce n'est qu'une amorce : la plateforme doit afficher un
    seuil des le premier demarrage, celui du modele, au lieu d'un 0.8 herite
    que le modele n'utilise plus.
    """
    resultat = session.execute(
        text(
            """
            INSERT INTO audit.parametre (cle, valeur, modifie_par, modifie_at)
            VALUES (:cle, :valeur, 'api-inference', now())
            ON CONFLICT (cle) DO NOTHING
            """
        ),
        {"cle": CLE_SEUIL_ALERTE, "valeur": str(valeur)},
    )
    # `rowcount` n'existe que sur un `CursorResult` : `getattr` evite un cast
    # qui mentirait sur le type rendu par `execute`.
    return bool(getattr(resultat, "rowcount", 0))


def lire_seuil_effectif() -> float | None:
    """`lire_seuil_alerte` en version « ne leve jamais », pour les services."""
    try:
        with session_scope() as session:
            return lire_seuil_alerte(session)
    except Exception as exc:
        logger.warning("seuil.base_injoignable", erreur=str(exc))
        return None


def amorcer_seuil_effectif(valeur: float) -> bool:
    """`amorcer_seuil_alerte` en version « ne leve jamais », pour le demarrage."""
    try:
        with session_scope() as session:
            return amorcer_seuil_alerte(session, valeur)
    except Exception as exc:
        logger.warning("seuil.non_amorce", erreur=str(exc))
        return False
