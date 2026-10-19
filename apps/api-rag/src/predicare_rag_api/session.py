"""Memoire de session de l'assistant (Phase C).

L'agent reste sans etat entre deux requetes : sans ce module, une question
de suivi comme « Et pour la pharmacie ? » n'a aucun sens pour le modele.
La memoire est volontairement courte (6 tours par defaut) et bornee au
`scope` de l'assure connecte : une session ne doit jamais franchir la
frontiere d'un dossier.

Deux implementations derriere le meme protocole :

- `RedisSessionStore` : partage entre processus, avec expiration (TTL) ;
- `InMemorySessionStore` : repli si Redis est indisponible, et support des
  tests hors infrastructure.

Une panne de Redis ne doit jamais empecher l'assistant de repondre : toutes
les operations degradent vers « pas d'historique » en journalisant l'erreur.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Protocol

import redis

from predicare.logging_config import get_logger

logger = get_logger("api-rag.session")

#: Prefixe de cle. Le `scope` (identifiant assure) fait partie de la cle :
#: deux assures qui choisissent le meme `session_id` restent isoles.
SESSION_KEY_PREFIX = "rag:session"


class SessionStore(Protocol):
    """Contrat minimal d'un stockage de tours de conversation."""

    def get(self, scope: str, session_id: str) -> list[dict]: ...

    def append(self, scope: str, session_id: str, turn: dict) -> None: ...

    def clear(self, scope: str, session_id: str) -> None: ...


def _cle(scope: str, session_id: str) -> str:
    """Cle Redis/InMemory. Le scope est toujours present, meme vide."""
    return f"{SESSION_KEY_PREFIX}:{scope}:{session_id}"


class RedisSessionStore:
    """Historique de session dans Redis, avec TTL et taille bornee.

    `RPUSH` + `LTRIM(-max_turns, -1)` conserve les derniers tours dans
    l'ordre chronologique : l'index 0 est le plus ancien, ce que l'agent
    attend pour reconstruire la conversation.
    """

    def __init__(
        self,
        redis_url: str,
        *,
        ttl_seconds: int = 3600,
        max_turns: int = 6,
        client: Any | None = None,
    ) -> None:
        self._client = client or redis.Redis.from_url(redis_url, decode_responses=True)
        self._ttl_seconds = ttl_seconds
        self._max_turns = max(1, max_turns)

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    @property
    def max_turns(self) -> int:
        return self._max_turns

    def ping(self) -> bool:
        """Verifie la disponibilite de Redis sans lever d'exception."""
        try:
            return bool(self._client.ping())
        except Exception as exc:
            logger.warning("session.redis_indisponible", erreur=str(exc))
            return False

    def get(self, scope: str, session_id: str) -> list[dict]:
        """Tours du plus ancien au plus recent ; liste vide si Redis echoue."""
        try:
            bruts = self._client.lrange(_cle(scope, session_id), 0, -1)
        except Exception as exc:
            logger.warning("session.redis_get_erreur", erreur=str(exc))
            return []

        tours: list[dict] = []
        for brut in bruts:
            try:
                tour = json.loads(brut)
            except (TypeError, ValueError):
                # Une entree corrompue ne doit pas invalider tout l'historique.
                logger.warning("session.tour_illisible")
                continue
            if isinstance(tour, dict):
                tours.append(tour)
        return tours

    def append(self, scope: str, session_id: str, turn: dict) -> None:
        """Ajoute un tour et ne conserve que les `max_turns` plus recents."""
        cle = _cle(scope, session_id)
        try:
            self._client.rpush(cle, json.dumps(turn, ensure_ascii=False))
            self._client.ltrim(cle, -self._max_turns, -1)
            self._client.expire(cle, self._ttl_seconds)
        except Exception as exc:
            logger.warning("session.redis_append_erreur", erreur=str(exc))

    def clear(self, scope: str, session_id: str) -> None:
        try:
            self._client.delete(_cle(scope, session_id))
        except Exception as exc:
            logger.warning("session.redis_clear_erreur", erreur=str(exc))


class InMemorySessionStore:
    """Repli local : suffisant pour les tests et pour un Redis absent.

    La duree de vie est appliquee a la lecture : une session inutilisee
    depuis `ttl_seconds` est oubliee, comme dans Redis.
    """

    def __init__(self, *, ttl_seconds: int = 3600, max_turns: int = 6) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_turns = max(1, max_turns)
        self._tours: dict[str, list[dict]] = {}
        self._expire_at: dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def max_turns(self) -> int:
        return self._max_turns

    def get(self, scope: str, session_id: str) -> list[dict]:
        cle = _cle(scope, session_id)
        with self._lock:
            if self._expiree(cle):
                return []
            return [dict(tour) for tour in self._tours.get(cle, [])]

    def append(self, scope: str, session_id: str, turn: dict) -> None:
        cle = _cle(scope, session_id)
        with self._lock:
            if self._expiree(cle):
                self._tours.pop(cle, None)
            tours = self._tours.setdefault(cle, [])
            tours.append(dict(turn))
            if len(tours) > self._max_turns:
                del tours[: len(tours) - self._max_turns]
            self._expire_at[cle] = time.time() + self._ttl_seconds

    def clear(self, scope: str, session_id: str) -> None:
        cle = _cle(scope, session_id)
        with self._lock:
            self._tours.pop(cle, None)
            self._expire_at.pop(cle, None)

    def _expiree(self, cle: str) -> bool:
        limite = self._expire_at.get(cle)
        if limite is None or limite > time.time():
            return False
        self._tours.pop(cle, None)
        self._expire_at.pop(cle, None)
        return True
