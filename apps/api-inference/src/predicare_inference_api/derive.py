"""Calcul et persistance du rapport de derive (Phase 3.4).

Le worker ne peut pas tenir le rapport en memoire : il tourne dans un
processus distinct de l'API, qui repondrait toujours `non_calcule`. Le calcul
ecrit donc dans `ml.rapport_derive`, et `GET /api/inference/derive` relit la
derniere ligne. C'est aussi ce qui rend le rapport consultable apres un
redemarrage.

Faute de feature store, la comparaison porte sur ce que `ml.prediction`
conserve reellement : le score, le montant de la facture et deux agregats de
lignes. Ce n'est pas la derive des 32 variables du modele ; c'est un signal
honnete et peu couteux, suffisant pour declencher une investigation. Le jour
ou les features seront stockees, `charger_fenetres_derive` suffira a les
ajouter au DataFrame.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from predicare.config import get_settings
from predicare.db import session_scope
from predicare.logging_config import get_logger
from predicare.persistance_ml import (
    lire_version_promue,
    persister_rapport_derive,
)
from predicare_inference_api.drift import detect_drift

logger = get_logger("worker-ingest")

#: Le calcul est peu couteux, mais un rapport par minute n'apporterait rien :
#: la derive est un phenomene lent. Une heure laisse le temps aux lots de
#: factures d'arriver et evite d'ecrire 1 440 lignes par jour.
INTERVALLE_RAPPORT_DERIVE = 3600

#: Variables comparees entre la population de reference (notations
#: retrospectives `archive`) et la fenetre courante. Les noms sont ceux du
#: DataFrame, pas ceux du modele : le rapport reste lisible sans le booster.
SQL_REFERENCE = """
    SELECT
        p.score_fraude,
        f.montant_total::float8 AS montant_total,
        count(l.id)::float8 AS nb_lignes,
        COALESCE(avg(l.montant_unitaire * l.quantite), 0)::float8 AS montant_moyen_ligne
    FROM ml.prediction p
    JOIN core.facture f ON f.id = p.facture_id
    LEFT JOIN core.ligne_facture l ON l.facture_id = f.id
    WHERE p.statut = 'archive'
      AND p.model_version = :version
    GROUP BY p.id, p.score_fraude, f.montant_total
"""

SQL_COURANTE = """
    SELECT
        p.score_fraude,
        f.montant_total::float8 AS montant_total,
        count(l.id)::float8 AS nb_lignes,
        COALESCE(avg(l.montant_unitaire * l.quantite), 0)::float8 AS montant_moyen_ligne
    FROM ml.prediction p
    JOIN core.facture f ON f.id = p.facture_id
    LEFT JOIN core.ligne_facture l ON l.facture_id = f.id
    WHERE p.statut <> 'archive'
      AND p.model_version = :version
      AND p.created_at >= now() - make_interval(days => :jours)
    GROUP BY p.id, p.score_fraude, f.montant_total
"""


def charger_fenetres_derive(
    session: Session, *, window_days: int, version: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Deux DataFrames comparables : reference retrospective et fenetre courante.

    La reference est la notation retrospective (`statut = 'archive'`) : elle
    represente la population sur laquelle le modele a ete mesure. La fenetre
    courante exclut ces archives, sinon le rapport comparerait l'historique a
    lui-meme et afficherait toujours une derive nulle.
    """
    if window_days < 1:
        raise ValueError(f"Fenetre de derive invalide : {window_days}")

    connexion = session.connection()
    reference = pd.read_sql_query(
        text(SQL_REFERENCE),
        connexion,
        params={"version": version},
    )
    courante = pd.read_sql_query(
        text(SQL_COURANTE),
        connexion,
        params={"version": version, "jours": window_days},
    )
    return reference, courante


def _dernier_rapport_recent(session: Session, *, max_age_s: int) -> bool:
    """Vrai si un rapport a deja ete ecrit dans la fenetre de fraicheur."""
    age = session.execute(
        text(
            """
            SELECT EXTRACT(EPOCH FROM (now() - calcule_le))
            FROM ml.rapport_derive
            ORDER BY calcule_le DESC NULLS LAST, id DESC
            LIMIT 1
            """
        )
    ).scalar()
    return age is not None and float(age) < max_age_s


def calculer_et_persister_derive(*, force: bool = False) -> int | None:
    """Calcule le rapport et l'ecrit dans `ml.rapport_derive`.

    `force=True` ignore le garde-fou horaire : utilise par les tests et par un
    operateur qui veut un rapport immediat. Rend l'id cree, ou None si aucun
    rapport n'a ete ecrit (deja recent, ou pas assez de donnees).
    """
    settings = get_settings()
    with session_scope() as session:
        if not force and _dernier_rapport_recent(session, max_age_s=INTERVALLE_RAPPORT_DERIVE):
            logger.debug("derive.deja_recente", intervalle_s=INTERVALLE_RAPPORT_DERIVE)
            return None

        version = lire_version_promue(session) or str(settings.model_active_version)
        reference, courante = charger_fenetres_derive(
            session,
            window_days=settings.drift_window_days,
            version=version,
        )

    if reference.empty or courante.empty:
        logger.info(
            "derive.donnees_insuffisantes",
            reference=len(reference),
            courante=len(courante),
            version=version,
        )
        return None

    rapport = detect_drift(
        reference,
        courante,
        window_days=settings.drift_window_days,
    )
    identifiant = persister_rapport_derive(
        fenetre_jours=rapport.window_days,
        psi_global=rapport.psi_global,
        variables_concernees={
            "concernees": rapport.drifted_features,
            "psi_par_variable": rapport.feature_scores,
            "observations_reference": len(reference),
            "observations_courantes": len(courante),
            "version_modele": version,
        },
        score_moyen_reference=rapport.score_mean_reference,
        score_moyen_courant=rapport.score_mean_current,
        alerte=rapport.alert,
    )
    if identifiant is None:
        return None

    logger.info(
        "derive.enregistree",
        rapport_id=identifiant,
        alerte=rapport.alert,
        psi_global=round(rapport.psi_global, 4),
        variables=rapport.drifted_features,
        observations_reference=len(reference),
        observations_courantes=len(courante),
        version=version,
    )
    return identifiant
