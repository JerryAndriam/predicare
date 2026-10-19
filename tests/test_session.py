"""Memoire de session : ordre, borne, TTL et cloisonnement par assure.

La memoire de session est une fonctionnalite de confort, mais son
cloisonnement est une exigence de securite : deux assures ne doivent jamais
partager un historique, meme s'ils choisissent le meme `session_id`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from predicare.config import Settings
from predicare_rag_api.agent import RagAnswer
from predicare_rag_api.main import AskRequest, _creer_session_store, ask
from predicare_rag_api.semantic_cache import CacheHit, SemanticCache
from predicare_rag_api.session import (
    SESSION_KEY_PREFIX,
    InMemorySessionStore,
    RedisSessionStore,
)


class EmbedderFictif:
    """Embeddings deterministes, sans appel reseau (cf. test_semantic_cache)."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        import hashlib

        vecteurs: list[list[float]] = []
        for texte in texts:
            dimensions = [0.0] * 16
            for mot in texte.lower().split():
                brut = int(hashlib.sha256(mot.encode()).hexdigest(), 16)
                dimensions[brut % 16] += 1.0
            if not any(dimensions):
                dimensions[0] = 1.0
            vecteurs.append(dimensions)
        return vecteurs


class FakeRedis:
    """Client Redis minimal, suffisant pour les commandes utilisees.

    `fakeredis` n'est pas une dependance du projet : ce faux client garde
    les tests hors ligne et evite d'ajouter un paquet pour trois commandes.
    """

    def __init__(self) -> None:
        self.data: dict[str, list[str]] = {}
        self.expirations: dict[str, int] = {}
        self.ping_ok = True

    def ping(self) -> bool:
        return self.ping_ok

    def rpush(self, key: str, value: str) -> int:
        self.data.setdefault(key, []).append(value)
        return len(self.data[key])

    def ltrim(self, key: str, start: int, end: int) -> bool:
        valeurs = self.data.get(key, [])
        taille = len(valeurs)
        debut = start if start >= 0 else max(taille + start, 0)
        fin = end if end >= 0 else taille + end
        self.data[key] = valeurs[debut : fin + 1]
        return True

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        valeurs = self.data.get(key, [])
        taille = len(valeurs)
        debut = start if start >= 0 else max(taille + start, 0)
        fin = end if end >= 0 else taille + end
        return valeurs[debut : fin + 1]

    def expire(self, key: str, seconds: int) -> bool:
        self.expirations[key] = seconds
        return True

    def delete(self, key: str) -> int:
        return 1 if self.data.pop(key, None) is not None else 0


class RedisEnPanne:
    """Client qui echoue sur toutes les commandes."""

    def ping(self) -> bool:
        raise ConnectionError("redis indisponible")

    def rpush(self, *args: object, **kwargs: object) -> None:
        raise ConnectionError("redis indisponible")

    def ltrim(self, *args: object, **kwargs: object) -> None:
        raise ConnectionError("redis indisponible")

    def expire(self, *args: object, **kwargs: object) -> None:
        raise ConnectionError("redis indisponible")

    def lrange(self, *args: object, **kwargs: object) -> list[str]:
        raise ConnectionError("redis indisponible")

    def delete(self, *args: object, **kwargs: object) -> None:
        raise ConnectionError("redis indisponible")


def _tour(question: str, answer: str = "reponse") -> dict:
    return {
        "question": question,
        "answer": answer,
        "sources": [],
        "timestamp": 1_700_000_000.0,
    }


# --------------------------------------------------------------- memoire locale


def test_append_puis_get_conserve_l_ordre_chronologique() -> None:
    store = InMemorySessionStore()

    store.append("assure-A", "s1", _tour("Q1", "R1"))
    store.append("assure-A", "s1", _tour("Q2", "R2"))

    assert [tour["question"] for tour in store.get("assure-A", "s1")] == ["Q1", "Q2"]


def test_max_turns_ne_conserve_que_les_plus_recents() -> None:
    store = InMemorySessionStore(max_turns=3)

    for index in range(5):
        store.append("assure-A", "s1", _tour(f"Q{index}"))

    questions = [tour["question"] for tour in store.get("assure-A", "s1")]

    assert questions == ["Q2", "Q3", "Q4"]


def test_session_vide_rend_une_liste_vide() -> None:
    assert InMemorySessionStore().get("assure-A", "inconnue") == []


def test_clear_efface_la_session() -> None:
    store = InMemorySessionStore()
    store.append("assure-A", "s1", _tour("Q1"))

    store.clear("assure-A", "s1")

    assert store.get("assure-A", "s1") == []


def test_meme_session_id_est_isolee_par_scope() -> None:
    """Le point de securite : le scope fait partie de la cle."""
    store = InMemorySessionStore()
    store.append("assure-A", "partagee", _tour("Question de A"))

    assert store.get("assure-B", "partagee") == []
    assert store.get("assure-A", "partagee") != []


def test_expiration_locale() -> None:
    store = InMemorySessionStore(ttl_seconds=10)
    store.append("assure-A", "s1", _tour("Q1"))

    # Une session inutilisee depuis plus de 10 s est oubliee.
    for cle in store._expire_at:
        store._expire_at[cle] -= 11

    assert store.get("assure-A", "s1") == []


# --------------------------------------------------------------- Redis


def test_redis_append_puis_get() -> None:
    client = FakeRedis()
    store = RedisSessionStore("redis://inutile", client=client)

    store.append("assure-A", "s1", _tour("Q1", "R1"))
    store.append("assure-A", "s1", _tour("Q2", "R2"))

    assert [tour["question"] for tour in store.get("assure-A", "s1")] == ["Q1", "Q2"]
    assert f"{SESSION_KEY_PREFIX}:assure-A:s1" in client.data


def test_redis_max_turns_et_ttl() -> None:
    client = FakeRedis()
    store = RedisSessionStore("redis://inutile", ttl_seconds=120, max_turns=2, client=client)

    for index in range(4):
        store.append("assure-A", "s1", _tour(f"Q{index}"))

    assert [tour["question"] for tour in store.get("assure-A", "s1")] == ["Q2", "Q3"]
    assert client.expirations[f"{SESSION_KEY_PREFIX}:assure-A:s1"] == 120


def test_redis_isole_par_scope() -> None:
    client = FakeRedis()
    store = RedisSessionStore("redis://inutile", client=client)
    store.append("assure-A", "partagee", _tour("Question de A"))

    assert store.get("assure-B", "partagee") == []


def test_redis_ignore_une_entree_corrompue() -> None:
    client = FakeRedis()
    store = RedisSessionStore("redis://inutile", client=client)
    cle = f"{SESSION_KEY_PREFIX}:assure-A:s1"
    client.data[cle] = ["pas du json", '{"question": "Q1", "answer": "R1"}']

    tours = store.get("assure-A", "s1")

    assert [tour["question"] for tour in tours] == ["Q1"]


def test_redis_panne_ne_leve_jamais() -> None:
    store = RedisSessionStore("redis://inutile", client=RedisEnPanne())

    assert store.ping() is False
    store.append("assure-A", "s1", _tour("Q1"))
    store.clear("assure-A", "s1")
    assert store.get("assure-A", "s1") == []


# --------------------------------------------------------------- cablage route


class AgentFictif:
    def __init__(self) -> None:
        self.historiques: list[list[dict] | None] = []

    def ask(
        self,
        question: str,
        *,
        assure_id: str | None,
        history: list[dict] | None = None,
    ) -> RagAnswer:
        self.historiques.append(history)
        return RagAnswer(
            answer=f"Reponse a : {question}",
            sources=[{"contrat": "C-001", "article": "Article 1"}],
            steps=[],
            latency_ms=12.5,
            tokens=30,
            cached=False,
            tokens_entree=20,
            tokens_sortie=10,
            cout_estime_usd=0.000009,
            cout_estime_eur=0.000008,
        )


class CacheVide:
    def get(self, *args: object, **kwargs: object) -> None:
        return None

    def put(self, *args: object, **kwargs: object) -> None:
        return None


class CacheAvecSucces:
    def get(self, *args: object, **kwargs: object) -> CacheHit:
        return CacheHit(
            question="Question ?",
            answer="Reponse du cache",
            sources=[{"contrat": "C-002"}],
            similarity=1.0,
        )

    def put(self, *args: object, **kwargs: object) -> None:
        return None


def _requete(agent: AgentFictif, cache: object, sessions: InMemorySessionStore) -> object:
    state = SimpleNamespace(agent=agent, cache=cache, sessions=sessions)
    return SimpleNamespace(app=SimpleNamespace(state=state))


def test_route_transmet_l_historique_au_deuxieme_tour() -> None:
    agent = AgentFictif()
    sessions = InMemorySessionStore()
    request = _requete(agent, CacheVide(), sessions)

    ask(
        AskRequest(question="Quel est le taux de la consultation ?", session_id="s1"),
        request,  # type: ignore[arg-type]
        assure_id="assure-A",
        x_rag_no_cache=True,
    )
    ask(
        AskRequest(question="Et pour la pharmacie ?", session_id="s1"),
        request,  # type: ignore[arg-type]
        assure_id="assure-A",
        x_rag_no_cache=True,
    )

    assert agent.historiques[0] == []
    assert agent.historiques[1] is not None
    assert agent.historiques[1][0]["question"] == "Quel est le taux de la consultation ?"
    assert len(sessions.get("assure-A", "s1")) == 2


def test_route_ajoute_le_cout_et_les_tokens() -> None:
    request = _requete(AgentFictif(), CacheVide(), InMemorySessionStore())

    reponse = ask(
        AskRequest(question="Question ?", session_id=None),
        request,  # type: ignore[arg-type]
        assure_id="assure-A",
        x_rag_no_cache=True,
    )

    assert reponse.tokens_entree == 20
    assert reponse.tokens_sortie == 10
    assert reponse.cout_estime_usd == pytest.approx(0.000009)
    assert reponse.cout_estime_eur == pytest.approx(0.000008)


def test_route_memorise_un_succes_de_cache_avec_cout_nul() -> None:
    sessions = InMemorySessionStore()
    request = _requete(AgentFictif(), CacheAvecSucces(), sessions)

    reponse = ask(
        AskRequest(question="Question ?", session_id="s1"),
        request,  # type: ignore[arg-type]
        assure_id="assure-A",
        x_rag_no_cache=False,
    )

    assert reponse.tokens == 0
    assert reponse.cout_estime_usd == 0.0
    assert reponse.cout_estime_eur == 0.0
    assert sessions.get("assure-A", "s1")[0]["answer"] == "Reponse du cache"


def test_route_ne_franchit_pas_la_frontiere_des_assures() -> None:
    """Meme `session_id`, deux jetons : le second ne voit pas le premier."""
    agent = AgentFictif()
    sessions = InMemorySessionStore()
    request = _requete(agent, CacheVide(), sessions)

    ask(
        AskRequest(question="Question de A", session_id="partagee"),
        request,  # type: ignore[arg-type]
        assure_id="assure-A",
        x_rag_no_cache=True,
    )
    ask(
        AskRequest(question="Question de B", session_id="partagee"),
        request,  # type: ignore[arg-type]
        assure_id="assure-B",
        x_rag_no_cache=True,
    )

    assert agent.historiques[1] == []
    assert sessions.get("assure-A", "partagee")[0]["question"] == "Question de A"
    assert sessions.get("assure-B", "partagee")[0]["question"] == "Question de B"


# --------------------------------------------- cache et reponses contextuelles


def test_une_reponse_de_suivi_ne_pollue_pas_le_cache() -> None:
    """Une reponse construite avec l'historique ne doit jamais etre stockee
    sous la cle du seul assure, ni servie a une autre session.

    On produit d'abord un tour de suivi en session A, puis on repose la meme
    question en session B, sans historique : B ne doit pas obtenir un succes
    de cache.
    """
    agent = AgentFictif()
    cache = SemanticCache(EmbedderFictif(), threshold=0.95)
    sessions = InMemorySessionStore()
    request = _requete(agent, cache, sessions)

    # Tour 1 de A : premiere question, cache autorise.
    ask(
        AskRequest(question="Quel est le taux de la consultation ?", session_id="A"),
        request,  # type: ignore[arg-type]
        assure_id="assure-A",
        x_rag_no_cache=False,
    )
    # Tour 2 de A : question de suivi, le cache doit etre contourne.
    ask(
        AskRequest(question="Et pour la pharmacie ?", session_id="A"),
        request,  # type: ignore[arg-type]
        assure_id="assure-A",
        x_rag_no_cache=False,
    )
    # Session B, premiere question : contexte different, pas de cache.
    reponse_b = ask(
        AskRequest(question="Et pour la pharmacie ?", session_id="B"),
        request,  # type: ignore[arg-type]
        assure_id="assure-A",
        x_rag_no_cache=False,
    )

    assert reponse_b.cache_semantique is False
    # La reponse contextuelle de A n'a pas ete ecrite : le cache ne contient
    # que la premiere question de A et la premiere question de B.
    assert cache.stats()["entrees"] == 2
    assert agent.historiques[2] == []


def test_succes_de_cache_appende_quand_meme_le_tour() -> None:
    """Un succes de cache reste une reponse valide : il alimente la session."""
    agent = AgentFictif()
    cache = SemanticCache(EmbedderFictif(), threshold=0.95)
    sessions = InMemorySessionStore()
    request = _requete(agent, cache, sessions)

    # Sans session : la premiere question remplit le cache.
    ask(
        AskRequest(question="Quel est mon plafond ?"),
        request,  # type: ignore[arg-type]
        assure_id="assure-A",
        x_rag_no_cache=False,
    )
    reponse = ask(
        AskRequest(question="Quel est mon plafond ?", session_id="s1"),
        request,  # type: ignore[arg-type]
        assure_id="assure-A",
        x_rag_no_cache=False,
    )

    assert reponse.cache_semantique is True
    assert sessions.get("assure-A", "s1")[0]["question"] == "Quel est mon plafond ?"


class AgentEnEchec:
    """Agent dont le LLM est indisponible : reponse de degradation."""

    def ask(
        self,
        question: str,
        *,
        assure_id: str | None,
        history: list[dict] | None = None,
    ) -> RagAnswer:
        return RagAnswer(
            answer="Le service de reponse est temporairement indisponible.",
            sources=[],
            steps=[],
            latency_ms=0.0,
            tokens=0,
            cached=False,
            succes=False,
        )


def test_une_reponse_en_echec_n_entre_pas_dans_l_historique() -> None:
    sessions = InMemorySessionStore()
    request = _requete(AgentEnEchec(), CacheVide(), sessions)  # type: ignore[arg-type]

    reponse = ask(
        AskRequest(question="Question ?", session_id="s1"),
        request,  # type: ignore[arg-type]
        assure_id="assure-A",
        x_rag_no_cache=True,
    )

    assert reponse.succes is False
    assert sessions.get("assure-A", "s1") == []


# ------------------------------------------------------ selection du store


def test_creer_session_store_repli_memoire(monkeypatch: pytest.MonkeyPatch) -> None:
    import predicare_rag_api.main as module

    monkeypatch.setattr(module.RedisSessionStore, "ping", lambda self: False)
    store = _creer_session_store(Settings(_env_file=None))

    assert isinstance(store, InMemorySessionStore)


def test_creer_session_store_utilise_redis_si_disponible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import predicare_rag_api.main as module

    monkeypatch.setattr(module.RedisSessionStore, "ping", lambda self: True)
    store = _creer_session_store(Settings(_env_file=None))

    assert isinstance(store, RedisSessionStore)
