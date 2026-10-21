"""Acces base de donnees.

Regle structurante (CDC section 5) : une seule instance PostgreSQL porte les
donnees metier, les vecteurs et l'audit. Les services se distinguent par le
SCHEMA qu'ils utilisent, pas par des bases separees : une sauvegarde unique
reste alors coherente (condition "Persistante" du jury).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from predicare.config import get_settings

# Les trois schemas applicatifs. Le schema `audit` est en lecture seule pour
# l'agent RAG : il ne doit jamais pouvoir modifier un journal.
SCHEMA_CORE = "core"
SCHEMA_ML = "ml"
SCHEMA_AUDIT = "audit"

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine(url: str | None = None) -> Engine:
    """Moteur SQLAlchemy paresseux, partage dans le processus."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            url or settings.db_url,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            future=True,
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Session transactionnelle : commit automatique, rollback sur exception."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_database() -> bool:
    """Sonde utilisee par /health : la base repond-elle ?"""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
