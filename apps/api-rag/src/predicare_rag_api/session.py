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
from urllib.parse import urlsplit

import redis

from predicare.logging_config import get_logger

logger = get_logger("api-rag.session")

#: Prefixe de cle. Le `scope` (identifiant assure) fait partie de la cle :
#: deux assures qui choisissent le meme `session_id` restent isoles.
SESSION_KEY_PREFIX = "rag:session"

#: Bornes de connexion Redis. Sans elles, un Redis suspendu peut bloquer le
#: `ping()` du demarrage ou la route d'ask, qui sont synchrones.
REDIS_CONNECT_TIMEOUT_SECONDS = 1.0
REDIS_READ_TIMEOUT_SECONDS = 1.0
REDIS_HEALTH_CHECK_INTERVAL_SECONDS = 30


def adresse_redis(redis_url: str) -> str:
    """Decrit Redis pour les logs sans jamais exposer l'identifiant.

    `redis_url` peut porter un mot de passe (`redis://user:secret@host`).
    Un journal est lisible par l'exploitant et finit souvent dans un
    agregateur : on ne conserve que l'hote, le port et le numero de base.
    """
    try:
        parties = urlsplit(redis_url)
        hote = parties.hostname or "redis"
        port = parties.port or 6379
        base = (parties.path or "/0").lstrip("/") or "0"
    except ValueError:
        # `urlsplit` et la lecture du port levent tous deux `ValueError` sur
        # une URL malformee : un journal de demarrage ne doit pas faire
        # echouer le service.
        return "redis"
    return f"{hote}:{port}/{base}"


class SessionStore(Protocol):
    """Contrat minimal d'un stockage de tours de conversation.

    Un tour ne contient que `question`, `answer` et `timestamp` : les sources
    ne sont pas requises pour rejouer la conversation et ne sont donc pas
    persistees (minimisation des donnees, RGPD).
    """

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
        self._client = client or redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=REDIS_CONNECT_TIMEOUT_SECONDS,
            socket_timeout=REDIS_READ_TIMEOUT_SECONDS,
            health_check_interval=REDIS_HEALTH_CHECK_INTERVAL_SECONDS,
        )
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
    depuis `ttl_seconds` est oubliee, comme dans Redis. Comme rien ne relit
    une session abandonnee, un balayage des entrees expirees est fait a
    chaque ecriture et la taille totale est bornee par `max_sessions` : sans
    cette borne, un repli de longue duree accumulerait sans fin des sessions
    mortes.
    """

    def __init__(
        self,
        *,
        ttl_seconds: int = 3600,
        max_turns: int = 6,
        max_sessions: int = 1000,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_turns = max(1, max_turns)
        self._max_sessions = max(1, max_sessions)
        self._tours: dict[str, list[dict]] = {}
        self._expire_at: dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def max_turns(self) -> int:
        return self._max_turns

    @property
    def nombre_sessions(self) -> int:
        with self._lock:
            return len(self._tours)

    def get(self, scope: str, session_id: str) -> list[dict]:
        cle = _cle(scope, session_id)
        with self._lock:
            if self._expiree(cle):
                return []
            return [dict(tour) for tour in self._tours.get(cle, [])]

    def append(self, scope: str, session_id: str, turn: dict) -> None:
        cle = _cle(scope, session_id)
        with self._lock:
            # `_expiree` retire deja la cle perimee : ne pas la retirer ici en
            # double, ce serait un `pop` inutile sur un dictionnaire vide.
            self._expiree(cle)
            tours = self._tours.setdefault(cle, [])
            tours.append(dict(turn))
            if len(tours) > self._max_turns:
                del tours[: len(tours) - self._max_turns]
            self._expire_at[cle] = time.time() + self._ttl_seconds
            self._borner_taille()

    def clear(self, scope: str, session_id: str) -> None:
        cle = _cle(scope, session_id)
        with self._lock:
            self._tours.pop(cle, None)
            self._expire_at.pop(cle, None)

    def _borner_taille(self) -> None:
        """Evince les sessions les plus anciennes au-dela de `max_sessions`.

        Les sessions expirees partent en premier ; s'il en reste trop, on
        retire dans l'ordre d'insertion (les dictionnaires Python le
        conservent), ce qui revient a une politique FIFO suffisante pour un
        repli de secours.
        """
        expirees = [cle for cle, limite in self._expire_at.items() if limite <= time.time()]
        for cle in expirees:
            self._tours.pop(cle, None)
            self._expire_at.pop(cle, None)
        while len(self._tours) > self._max_sessions:
            plus_ancienne = next(iter(self._tours))
            self._tours.pop(plus_ancienne, None)
            self._expire_at.pop(plus_ancienne, None)

    def _expiree(self, cle: str) -> bool:
        limite = self._expire_at.get(cle)
        if limite is None or limite > time.time():
            return False
        self._tours.pop(cle, None)
        self._expire_at.pop(cle, None)
        return True
