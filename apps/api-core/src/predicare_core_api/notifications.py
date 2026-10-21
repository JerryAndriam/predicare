"""Notification n8n des alertes de fraude (Flux 1 du CDC).

Le CDC demande que le depot d'une facture au-dessus du seuil declenche une
alerte au gestionnaire, avec le rapport d'explicabilite. La chaine de
notification est portee par n8n : api-core appelle son webhook, n8n notifie
Slack puis l'e-mail.

Ce module repond a la question « une fraude deposee depuis l'interface
previent-elle quelqu'un ? ». La reponse doit etre VISIBLE, pas seulement
vraie : c'est pourquoi l'appel rend un etat (`envoye`, `motif`) que l'API
retransmet au front, qui l'affiche.

Contrat : ne leve jamais. Une notification perdue ne doit pas transformer un
depot reussi en erreur 500, ni faire perdre la facture, deja notee et
enregistree. C'est la meme doctrine que `notifier_bascule` du Flux 1.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from sqlalchemy import text

from predicare.config import get_settings
from predicare.db import session_scope
from predicare.dependencies import get_threshold
from predicare.logging_config import get_logger

logger = get_logger("api-core.notifications")

#: Court volontairement : la notification est un effet de bord du depot.
#: Au-dela, le depot lui-meme paraitrait bloque.
DELAI_SECONDES = 3.0

#: Cle de la table `audit.parametre` qui porte le seuil de NOTIFICATION.
#: Elle est distincte de `seuil_alerte` (seuil de DETECTION) : une alerte
#: Slack est une interruption humaine, le CDC la reserve aux cas tres nets.
CLE_SEUIL_NOTIFICATION = "seuil_notification"

#: Le seuil de repli (0,8) est la valeur litterale du CDC (Flux 1 :
#: « Si Score > 0,8 -> Notification Slack »). Il reste porte par
#: `N8N_SEUIL_NOTIFICATION` dans `predicare.config`, pour ne pas dupliquer
#: la valeur dans deux modules.


@dataclass(frozen=True, slots=True)
class ResultatNotification:
    """Ce qu'il est advenu de la notification.

    `envoye` dit si la chaine d'alerte a ete declenchee. `motif` est
    affichable tel quel a l'utilisateur : c'est lui qui explique au
    gestionnaire pourquoi il n'a pas recu d'alerte.
    """

    envoye: bool
    motif: str


def webhook_configure() -> bool:
    """Vrai si une chaine d'alerte est configuree sur cette machine."""
    adresse = get_settings().n8n_alerte_webhook_url.strip()
    return adresse != "" and not adresse.lower().startswith("changer")


def _lire_seuil_notification_base() -> float | None:
    """Seuil de notification enregistre dans `audit.parametre`, ou None.

    Lire la base a chaque notification est volontaire : un changement fait
    par l'exploitation s'applique sans redemarrage, comme pour le seuil de
    detection. Ne leve jamais : une base injoignable ne doit pas empecher
    une notification de partir avec la valeur de l'environnement.
    """
    try:
        with session_scope() as session:
            valeur = session.execute(
                text("SELECT valeur FROM audit.parametre WHERE cle = :cle"),
                {"cle": CLE_SEUIL_NOTIFICATION},
            ).scalar()
    except Exception as exc:
        logger.warning("alerte.seuil_base_illisible", erreur=str(exc))
        return None

    if valeur is None:
        return None
    try:
        seuil = float(valeur)
    except (TypeError, ValueError):
        logger.warning("alerte.seuil_illisible", valeur=str(valeur))
        return None
    return seuil if 0.0 <= seuil <= 1.0 else None


def seuil_notification_effectif() -> float:
    """Seuil de NOTIFICATION applique par api-core, en une seule source.

    Hierarchie :

    1. `audit.parametre.seuil_notification` : reglage d'exploitation, relu a
       chaque alerte (meme doctrine que le seuil de detection).
    2. `N8N_SEUIL_NOTIFICATION` : configuration de la machine, lue au
       demarrage. C'est le repli quand la base n'a pas de reglage.
    3. 0,8 : valeur litterale du CDC.

    Le resultat ne descend jamais sous le seuil de DETECTION effectif
    (`get_threshold`, lui aussi alimente par `audit.parametre`) : on ne peut
    pas interrompre un humain pour une facture que le modele n'a meme pas
    retenue. Avec les valeurs du depot (detection 0,2876, notification 0,8),
    le comportement reste celui du CDC ; si l'exploitation releve le seuil
    de detection au-dessus de 0,8, la notification suit au lieu de diverger.
    """
    configure = _lire_seuil_notification_base()
    if configure is None:
        configure = get_settings().n8n_seuil_notification
    try:
        detection = get_threshold()
    except Exception as exc:  # get_threshold ne leve pas ; double filet.
        logger.warning("alerte.seuil_detection_illisible", erreur=str(exc))
        detection = 0.0
    return max(configure, detection, 0.0)


def notifier_alerte(
    *,
    facture_id: str,
    score: float,
    seuil: float,
    rapport_shap: str,
    model_version: str = "",
    assure_pseudonyme: str = "",
    montant_total: float | None = None,
) -> ResultatNotification:
    """Declenche l'alerte. Rend l'etat de la notification.

    L'appel n'a lieu que si l'adresse du webhook est configuree ET si le
    score franchit le seuil de NOTIFICATION. Ce seuil est distinct du seuil
    de DETECTION : toute detection reste dans la file du gestionnaire, mais
    seules les fraudes tres nettes interrompent un humain par Slack.
    """
    settings = get_settings()
    if not webhook_configure():
        return ResultatNotification(
            envoye=False,
            motif=(
                "Aucune chaine d'alerte configuree sur cette machine "
                "(N8N_ALERTE_WEBHOOK_URL). La fraude est bien notee et "
                "visible dans la file du gestionnaire."
            ),
        )

    seuil_notification = seuil_notification_effectif()
    if score < seuil_notification:
        return ResultatNotification(
            envoye=False,
            motif=(
                f"Score {score:.3f} sous le seuil de notification "
                f"({seuil_notification:.2f}) : la facture reste "
                "dans la file du gestionnaire, sans notification instantanee."
            ),
        )

    charge: dict[str, object] = {
        "facture_id": facture_id,
        "score_fraude": score,
        "seuil_applique": seuil,
        "seuil_notification": seuil_notification,
        "rapport_shap": rapport_shap,
        "model_version": model_version,
        "assure_pseudonyme": assure_pseudonyme,
    }
    if montant_total is not None:
        charge["montant_total"] = montant_total

    try:
        reponse = httpx.post(
            settings.n8n_alerte_webhook_url,
            json=charge,
            timeout=DELAI_SECONDES,
        )
        reponse.raise_for_status()
    except (httpx.HTTPError, ValueError) as exc:
        # La facture reste enregistree : l'alerte est perdue, pas la facture.
        logger.warning("alerte.notification_echouee", facture_id=facture_id, erreur=str(exc))
        return ResultatNotification(
            envoye=False,
            motif=f"Alerte non transmise au canal de notification ({exc}).",
        )

    logger.info("alerte.notification_envoyee", facture_id=facture_id, score=score)
    return ResultatNotification(
        envoye=True,
        motif="Alerte transmise au canal de notification (Slack / e-mail).",
    )
