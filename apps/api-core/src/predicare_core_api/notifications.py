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

from predicare.config import get_settings
from predicare.logging_config import get_logger

logger = get_logger("api-core.notifications")

#: Court volontairement : la notification est un effet de bord du depot.
#: Au-dela, le depot lui-meme paraitrait bloque.
DELAI_SECONDES = 3.0


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

    if score < settings.n8n_seuil_notification:
        return ResultatNotification(
            envoye=False,
            motif=(
                f"Score {score:.3f} sous le seuil de notification "
                f"({settings.n8n_seuil_notification:.2f}) : la facture reste "
                "dans la file du gestionnaire, sans notification instantanee."
            ),
        )

    charge: dict[str, object] = {
        "facture_id": facture_id,
        "score_fraude": score,
        "seuil_applique": seuil,
        "seuil_notification": settings.n8n_seuil_notification,
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
