"""Journaux structures et exploitation des erreurs.

Contrainte "Supervisable" du jury : journaux lisibles par une machine. On
ecrit du JSON sur stdout, Docker s'occupe de la collecte, Prometheus recupere
les metriques exposees par `metrics.py`.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def configure_logging(service_name: str, level: str = "INFO", fmt: str = "json") -> None:
    """Configure structlog + logging standard pour un service donne."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level)
    for noisy in ("uvicorn.access", "sqlalchemy.engine.Engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    processors.append(
        structlog.processors.JSONRenderer()
        if fmt == "json"
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    get_logger(service_name).info("service.demarrage", service=service_name, log_format=fmt)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Logger structure. Le nom du service est lie au contexte."""
    return structlog.get_logger(name) if name else structlog.get_logger()
