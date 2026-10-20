"""Worker d'ingestion et de suivi de derive.

Meme image que `api-inference`, commande differente : le service sert les
requeteles, ce worker tourne en arriere-plan. Aucun code n'est duplique.

Le traitement par lots (ingestion des 24 mois, featurisation, entrainement,
rapport de derive) sera branche ici ; en attendant, le worker tient une boucle
de controle qui verifie la base, publie un heartbeat et journalise l'etat. Un
worker qui sort silencieusement serait pire qu'absent : Docker le relancerait
en boucle sans qu'on comprenne pourquoi.
"""

from __future__ import annotations

import signal
import time
from collections.abc import Callable

from predicare import db
from predicare.config import get_settings
from predicare.logging_config import configure_logging, get_logger
from predicare_inference_api.derive import calculer_et_persister_derive

INTERVALLE_PAR_DEFAUT = 60

#: Drapeau d'arret, positionne par SIGTERM puis relu par la boucle.
_ARRET_DEMANDE = False


def _installer_arret() -> None:
    """SIGTERM doit arreter proprement : Docker envoie ce signal a l'arret."""

    def _handler(signum: int, _frame: object) -> None:
        global _ARRET_DEMANDE
        _ARRET_DEMANDE = True
        get_logger("worker-ingest").info("worker.arret_demande", signal=signum)

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


def boucle(
    nom: str,
    taches: list[tuple[str, Callable[[], None]]],
    *,
    intervalle: int = INTERVALLE_PAR_DEFAUT,
) -> None:
    """Boucle de fond : execute chaque tache, journalise, resistee aux erreurs.

    Une tache qui echoue ne doit pas tuer le worker : une migration en cours
    ferait echouer l'ingestion pendant quelques secondes, et le redemarrage
    en boucle amplifierait la panne au lieu de la tolerer.
    """
    logger = get_logger(nom)
    logger.info(
        "worker.demarre", taches=[nom_tache for nom_tache, _ in taches], intervalle=intervalle
    )

    while not _ARRET_DEMANDE:
        debut = time.perf_counter()
        for nom_tache, tache in taches:
            if _ARRET_DEMANDE:
                break
            try:
                tache()
            except Exception as exc:
                logger.warning("worker.tache_en_echec", tache=nom_tache, erreur=str(exc))
        duree = time.perf_counter() - debut
        logger.info("worker.tour", duree_s=round(duree, 3))

        # Decoupe le sommeil en tranches courtes pour repondre au SIGTERM
        # sans attendre la fin de l'intervalle.
        for _ in range(intervalle):
            if _ARRET_DEMANDE:
                break
            time.sleep(1)

    db.dispose_engine()
    logger.info("worker.arrete")


def _verifier_base() -> None:
    if not db.check_database():
        raise RuntimeError("Base de donnees injoignable")


def main() -> None:
    settings = get_settings()
    configure_logging("worker-ingest", settings.log_level, settings.log_format)
    _installer_arret()

    logger = get_logger("worker-ingest")
    logger.info(
        "worker.contexte",
        model_dir=settings.model_dir,
        modele_actif=settings.model_active_version,
        fenetre_derive=settings.drift_window_days,
    )

    # Le calcul ecrit dans `ml.rapport_derive` ; l'API relit la derniere ligne.
    # Le garde-fou horaire est dans `derive.py`, pas dans la boucle : la tache
    # peut donc etre appelee a chaque tour sans faire grossir la table.
    def _calculer_derive() -> None:
        calculer_et_persister_derive()

    boucle("worker-ingest", [("verifier_base", _verifier_base), ("derive", _calculer_derive)])


if __name__ == "__main__":
    main()
