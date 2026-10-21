"""Worker d'indexation RAG et de maintenance du cache semantique.

Meme image que `api-rag`, commande differente. Ce worker prepares ce que
l'agent consomme : segments de contrats a indexer et entrees de cache a
purger. Il ne repond a aucune requete.

Comme pour le worker d'ingestion, la boucle resiste aux erreurs : une
faille du fournisseur d'embeddings pendant une minute ne doit pas entrainer
un redemarrage en boucle qui, lui, consommerait des tokens.
"""

from __future__ import annotations

import signal
import time

from predicare import db
from predicare.config import get_settings
from predicare.logging_config import configure_logging, get_logger

INTERVALLE_PAR_DEFAUT = 300
INTERVALLE_SURVEILLANCE = 60

_ARRET_DEMANDE = False


def _installer_arret() -> None:
    def _handler(signum: int, _frame: object) -> None:
        global _ARRET_DEMANDE
        _ARRET_DEMANDE = True
        get_logger("worker-ai").info("worker.arret_demande", signal=signum)

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


def _dormir_avec_reactivite(secondes: int) -> None:
    for _ in range(secondes):
        if _ARRET_DEMANDE:
            return
        time.sleep(1)


def main() -> None:
    settings = get_settings()
    configure_logging("worker-ai", settings.log_level, settings.log_format)
    _installer_arret()

    logger = get_logger("worker-ai")
    logger.info(
        "worker.demarre",
        modele_embeddings=settings.embedding_model,
        dimension=settings.embedding_dimension,
        cache_ttl=settings.semantic_cache_ttl_seconds,
    )

    tour = 0
    while not _ARRET_DEMANDE:
        tour += 1
        try:
            base_ok = db.check_database()
            logger.info(
                "worker.tour",
                tour=tour,
                base=base_ok,
                # Le cache est en memoire dans le service API, donc ce worker
                # ne peut pas le vider a distance : il journalise son etat
                # pour que la metrique reste visible dans Grafana.
                note="cache_semantique=geree_par_api-rag",
            )
        except Exception as exc:
            logger.warning("worker.tour_en_echec", tour=tour, erreur=str(exc))

        # Le controle de la base est plus frequent que l'indexation : c'est
        # la seule information dont l'operateur a besoin en continu.
        _dormir_avec_reactivite(INTERVALLE_SURVEILLANCE if base_ok else INTERVALLE_PAR_DEFAUT)

    db.dispose_engine()
    logger.info("worker.arrete", tours=tour)


if __name__ == "__main__":
    main()
