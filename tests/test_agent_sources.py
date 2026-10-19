"""Sources remontees par les outils, historique de session et degradations.

Trois regressions sont couvertes ici, sans appeler de LLM :

1. une source demandee par l'outil `rechercher_contrats` doit apparaitre
   dans `RagAnswer.sources` (sinon le modele cite un passage que l'API ne
   renvoie pas - echec de citation Q30) ;
2. l'historique de session est reinjecte comme une DONNEE NON FIABLE, dans
   un bloc balise, et jamais comme des messages Human/AI bruts ;
3. un appel LLM en echec, vide ou sans repli produit `succes=False`, pour
   que la route ne le mette ni en cache ni dans l'historique.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from predicare import metrics
from predicare.config import Settings
from predicare_rag_api.agent import RagAgent, _merge_sources
from predicare_rag_api.finops import estimer_cout
from predicare_rag_api.retriever import Source
from predicare_rag_api.sql_tool import InsuredHistoryTool

URL_FACTICE = "postgresql+psycopg://predicare_ro:x@localhost:5432/predicare"


class RetrieverFictif:
    """Premiere recherche : source initiale. Suivante : source « guide »."""

    def __init__(self) -> None:
        self.appels = 0
        self.requetes: list[str] = []

    def search(self, question: str) -> list[Source]:
        self.appels += 1
        self.requetes.append(question)
        if self.appels == 1:
            return [
                Source(
                    contrat="Conditions Generales PREMIUM",
                    article="Article 5",
                    garantie="Optique",
                    extrait="Monture remboursee selon la formule.",
                    score=0.88,
                    source_fichier="premium.pdf",
                )
            ]
        return [
            Source(
                contrat="Guide des garanties PREMIUM",
                article="Article 7",
                garantie="Optique",
                extrait="Pieces justificatives : ordonnance et facture.",
                score=0.81,
                source_fichier="guide.pdf",
            )
        ]

    def format_sources(self, sources: list[Source]) -> str:
        return "<sources>" + "".join(source.extrait for source in sources) + "</sources>"


class LlmFictif:
    """Un appel d'outil, puis une reponse finale."""

    def __init__(self) -> None:
        self.appels = 0
        self.messages: list = []

    def bind_tools(self, _tools: object) -> LlmFictif:
        return self

    def invoke(self, messages: list) -> AIMessage:
        self.messages = list(messages)
        self.appels += 1
        if self.appels == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "rechercher_contrats",
                        "args": {"question": "pieces justificatives optique"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
                usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
            )
        return AIMessage(
            content="Il faut une ordonnance et la facture (Article 7).",
            usage_metadata={"input_tokens": 120, "output_tokens": 30, "total_tokens": 150},
        )


class LlmQuiLeve:
    """Tout appel echoue : simulation d'un fournisseur indisponible."""

    def bind_tools(self, _tools: object) -> LlmQuiLeve:
        return self

    def invoke(self, _messages: list) -> AIMessage:
        raise RuntimeError("LLM indisponible")


class LlmVide:
    """Le LLM repond sans texte : ce n'est pas une reponse exploitable."""

    def bind_tools(self, _tools: object) -> LlmVide:
        return self

    def invoke(self, _messages: list) -> AIMessage:
        return AIMessage(content="", usage_metadata={})


class LlmToujoursOutil:
    """Boucle sur un appel d'outil, puis echoue au repli sans outils."""

    def __init__(self) -> None:
        self.appels = 0

    def bind_tools(self, _tools: object) -> LlmToujoursOutil:
        return self

    def invoke(self, _messages: list) -> AIMessage:
        self.appels += 1
        if self.appels == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "rechercher_contrats",
                        "args": {"question": "optique"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
                usage_metadata={},
            )
        raise RuntimeError("LLM indisponible au repli")


def _agent(llm: object) -> RagAgent:
    agent = RagAgent(RetrieverFictif(), InsuredHistoryTool(URL_FACTICE), model="modele-test")
    agent._llm = llm  # type: ignore[assignment]
    return agent


def test_les_sources_de_l_outil_apparaissent_dans_la_reponse() -> None:
    agent = _agent(LlmFictif())

    reponse = agent.ask("Quelles pieces pour l'optique ?", assure_id="assure-A")

    contrats = {source["contrat"] for source in reponse.sources}
    assert "Conditions Generales PREMIUM" in contrats
    assert "Guide des garanties PREMIUM" in contrats
    assert reponse.succes is True
    assert reponse.to_dict()["succes"] is True


def test_les_sources_sont_dedupliquees() -> None:
    source = Source("C", "A", "G", "meme extrait", 0.9)

    fusion = _merge_sources([source], [source])

    assert len(fusion) == 1


def test_l_historique_est_rejoue_comme_donnee_non_fiable() -> None:
    llm = LlmFictif()
    agent = _agent(llm)

    agent.ask(
        "Et pour la pharmacie ?",
        assure_id="assure-A",
        history=[
            {
                "question": "Quel est le taux de la consultation ?",
                "answer": "Le taux est de 80 %.",
                "sources": [{"extrait": "TRESOR-ANCIENNE-SOURCE"}],
                "timestamp": 1.0,
            }
        ],
    )

    contenus = "\n".join(str(message.content) for message in llm.messages)
    assert "Quel est le taux de la consultation ?" in contenus
    assert "Le taux est de 80 %." in contenus
    assert "<historique_session>" in contenus
    assert "DONNEE NON FIABLE" in contenus
    # Le tour precedent n'est pas un HumanMessage brut : il reste dans la
    # zone de donnees et ne peut pas passer pour une instruction.
    assert not any(
        isinstance(message, HumanMessage)
        and "Quel est le taux de la consultation ?" in str(message.content)
        for message in llm.messages
    )
    # Les anciennes sources ne sont pas rejouees : elles pourraient faire
    # citer un passage hors sujet.
    assert "TRESOR-ANCIENNE-SOURCE" not in contenus


def test_historique_borne_a_six_tours_par_defaut() -> None:
    llm = LlmFictif()
    agent = _agent(llm)
    history = [{"question": f"Q{index}", "answer": f"R{index}"} for index in range(10)]

    agent.ask("Question courante", assure_id="assure-A", history=history)

    contenus = "\n".join(str(message.content) for message in llm.messages)
    assert "Q3" not in contenus
    assert "Q4" in contenus
    assert "Q9" in contenus


def test_historique_suit_session_max_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    """La borne vient de la configuration, pas d'une constante en dur."""
    import predicare_rag_api.agent as module

    monkeypatch.setattr(
        module, "get_settings", lambda: Settings(_env_file=None, session_max_turns=2)
    )
    llm = LlmFictif()
    agent = RagAgent(RetrieverFictif(), InsuredHistoryTool(URL_FACTICE), model="modele-test")
    agent._llm = llm  # type: ignore[assignment]
    history = [{"question": f"Q{index}", "answer": f"R{index}"} for index in range(6)]

    agent.ask("Question courante", assure_id="assure-A", history=history)

    contenus = "\n".join(str(message.content) for message in llm.messages)
    assert "Q3" not in contenus
    assert "Q4" in contenus
    assert "Q5" in contenus


def test_un_tour_invalide_ne_consomme_pas_un_emplacement() -> None:
    """Les tours corrompus sont filtres avant la coupe des N derniers."""
    llm = LlmFictif()
    agent = _agent(llm)
    history = [
        {"question": "Q1", "answer": "R1"},
        {"question": "Q2", "answer": None},
        {"question": "Q3", "answer": "R3"},
    ]

    agent.ask("Question courante", assure_id="assure-A", history=history)

    contenus = "\n".join(str(message.content) for message in llm.messages)
    assert "Q1" in contenus
    assert "R1" in contenus
    assert "Q3" in contenus
    assert "Q2" not in contenus


def test_un_suivi_cherche_avec_la_question_precedente() -> None:
    """« Et pour la pharmacie ? » seul n'a aucun mot-cle exploitable."""
    retriever = RetrieverFictif()
    agent = RagAgent(retriever, InsuredHistoryTool(URL_FACTICE), model="modele-test")
    agent._llm = LlmFictif()  # type: ignore[assignment]

    agent.ask(
        "Et pour la pharmacie ?",
        assure_id="assure-A",
        history=[{"question": "Quel est le taux de la consultation ?", "answer": "80 %"}],
    )

    assert retriever.requetes[0] == ("Quel est le taux de la consultation ? Et pour la pharmacie ?")


def test_le_cout_est_calcule_sur_les_tokens_des_deux_sens() -> None:
    agent = _agent(LlmFictif())

    reponse = agent.ask("Quelles pieces pour l'optique ?", assure_id="assure-A")

    attendu = estimer_cout(
        220,
        40,
        prix_entree_par_million_usd=agent._settings.llm_input_cost_per_million_usd,
        prix_sortie_par_million_usd=agent._settings.llm_output_cost_per_million_usd,
        taux_usd_eur=agent._settings.taux_usd_eur,
    )
    assert reponse.tokens_entree == 220
    assert reponse.tokens_sortie == 40
    assert reponse.cout_estime_usd == attendu["cout_total_usd"]
    assert reponse.cout_estime_eur == attendu["cout_total_eur"]


def test_les_compteurs_de_cout_et_de_tokens_incrementent() -> None:
    """Le dossier FinOps repose sur des compteurs reellement alimentes."""
    agent = _agent(LlmFictif())
    modele = agent._model_name
    cout_avant = metrics.LLM_COST_USD.labels("api-rag", modele)._value.get()
    prompt_avant = metrics.LLM_TOKENS.labels("api-rag", modele, "prompt")._value.get()
    completion_avant = metrics.LLM_TOKENS.labels("api-rag", modele, "completion")._value.get()

    reponse = agent.ask("Quelles pieces pour l'optique ?", assure_id="assure-A")

    attendu = estimer_cout(
        reponse.tokens_entree,
        reponse.tokens_sortie,
        prix_entree_par_million_usd=agent._settings.llm_input_cost_per_million_usd,
        prix_sortie_par_million_usd=agent._settings.llm_output_cost_per_million_usd,
        taux_usd_eur=agent._settings.taux_usd_eur,
    )
    assert metrics.LLM_COST_USD.labels("api-rag", modele)._value.get() - cout_avant == (
        pytest.approx(attendu["cout_total_usd_brut"])
    )
    assert (
        metrics.LLM_TOKENS.labels("api-rag", modele, "prompt")._value.get() - prompt_avant
        == reponse.tokens_entree
    )
    assert (
        metrics.LLM_TOKENS.labels("api-rag", modele, "completion")._value.get() - completion_avant
        == reponse.tokens_sortie
    )


def test_le_llm_qui_leve_produit_une_degradation() -> None:
    reponse = _agent(LlmQuiLeve()).ask("Question ?", assure_id="assure-A")

    assert reponse.succes is False
    assert reponse.to_dict()["succes"] is False


def test_une_reponse_vide_est_une_degradation() -> None:
    reponse = _agent(LlmVide()).ask("Question ?", assure_id="assure-A")

    assert reponse.succes is False


def test_l_echec_du_repli_sans_outils_est_une_degradation() -> None:
    agent = _agent(LlmToujoursOutil())
    agent._max_steps = 1

    reponse = agent.ask("Question ?", assure_id="assure-A")

    assert reponse.succes is False
