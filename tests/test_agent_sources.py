"""Sources remontees par les outils et historique de session.

Deux regressions sont couvertes ici, sans appeler de LLM :

1. une source demandee par l'outil `rechercher_contrats` doit apparaitre
   dans `RagAnswer.sources` (sinon le modele cite un passage que l'API ne
   renvoie pas - echec de citation Q30) ;
2. l'historique de session est reinjecte en paires Human/AI, sans les
   sources precedentes.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from predicare_rag_api.agent import RagAgent, _merge_sources
from predicare_rag_api.finops import estimer_cout
from predicare_rag_api.retriever import Source
from predicare_rag_api.sql_tool import InsuredHistoryTool

URL_FACTICE = "postgresql+psycopg://predicare_ro:x@localhost:5432/predicare"


class RetrieverFictif:
    """Premiere recherche : source initiale. Suivante : source « guide »."""

    def __init__(self) -> None:
        self.appels = 0

    def search(self, question: str) -> list[Source]:
        self.appels += 1
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

    def bind_tools(self, tools: object) -> LlmFictif:
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


def _agent(llm: LlmFictif) -> RagAgent:
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


def test_l_historique_est_rejoue_sans_les_sources() -> None:
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

    contenus = [message.content for message in llm.messages]
    assert "Quel est le taux de la consultation ?" in contenus
    assert "Le taux est de 80 %." in contenus
    assert any(isinstance(message, HumanMessage) for message in llm.messages)
    assert any(isinstance(message, AIMessage) for message in llm.messages)
    # Les anciennes sources ne sont pas rejouees : elles pourraient faire
    # citer un passage hors sujet.
    assert not any("TRESOR-ANCIENNE-SOURCE" in str(contenu) for contenu in contenus)


def test_historique_borne_a_six_tours() -> None:
    llm = LlmFictif()
    agent = _agent(llm)
    history = [{"question": f"Q{index}", "answer": f"R{index}"} for index in range(10)]

    agent.ask("Question courante", assure_id="assure-A", history=history)

    contenus = [message.content for message in llm.messages]
    assert "Q3" not in contenus
    assert "Q4" in contenus
    assert "Q9" in contenus


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
