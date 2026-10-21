"""Comportement de l'agent face a l'outil SQL.

Deux garanties sont verifiees ici, sans appeler de LLM :

1. le plafond de deux appels SQL par question, qui evite qu'un modele
   insiste sur une requete refusee jusqu'a epuiser ses etapes ;
2. la description de l'outil, seule source d'information du modele pour
   construire une requete valide.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from predicare_rag_api.agent import (
    CONSIGNE_SYNTHESE,
    MAX_APPELS_SQL,
    _sql_attempt_allowed,
    _usage,
)
from predicare_rag_api.guardrails import SYSTEM_PROMPT
from predicare_rag_api.sql_tool import TEMPLATES_REQUETES, InsuredHistoryTool

URL_FACTICE = "postgresql+psycopg://predicare_ro:x@localhost:5432/predicare"


@pytest.fixture
def outil() -> InsuredHistoryTool:
    return InsuredHistoryTool(URL_FACTICE)


def test_premiers_appels_sql_autorises() -> None:
    assert _sql_attempt_allowed(0) is True
    assert _sql_attempt_allowed(1) is True


def test_troisieme_appel_sql_refuse() -> None:
    assert _sql_attempt_allowed(MAX_APPELS_SQL) is False
    assert _sql_attempt_allowed(MAX_APPELS_SQL + 1) is False


def test_limite_sql_est_de_deux() -> None:
    assert MAX_APPELS_SQL == 2


def test_description_contient_les_templates(outil: InsuredHistoryTool) -> None:
    for requete in TEMPLATES_REQUETES.values():
        assert requete in outil.description


def test_description_exige_le_parametre_assure_id(outil: InsuredHistoryTool) -> None:
    assert ":assure_id" in outil.description
    assert "jamais" in outil.description.lower()


def test_description_consigne_l_agregation(outil: InsuredHistoryTool) -> None:
    """Une question de montant doit produire un agregat, pas une enumeration."""
    description = outil.description.lower()

    for agregat in ("sum(", "count(", "avg(", "min(", "max("):
        assert agregat in description, agregat
    assert "5 lignes" in description


def test_prompt_consigne_la_synthese() -> None:
    """Le prompt demande un total, et borne les lignes brutes a cinq."""
    consigne = CONSIGNE_SYNTHESE.lower()

    for agregat in ("sum(", "count(", "avg(", "min(", "max("):
        assert agregat in consigne, agregat
    assert "5 lignes" in consigne


def test_prompt_ne_relache_aucun_garde_fou() -> None:
    """La consigne de synthese s'ajoute au prompt : elle ne le remplace pas."""
    prompt = f"{SYSTEM_PROMPT}\n{CONSIGNE_SYNTHESE}".lower()

    assert "regle absolue" in prompt
    assert "regle de citation" in prompt
    assert "donnees non fiables" in prompt
    assert "tu ne dois jamais" in prompt
    assert "autre assure" in prompt


# --------------------------------------------------------------- cout en tokens


def test_usage_separe_entree_et_sortie() -> None:
    """Le cout se calcule sur les deux sens : la completion seule sous-estime."""
    message = AIMessage(
        content="reponse",
        usage_metadata={"input_tokens": 120, "output_tokens": 30, "total_tokens": 150},
    )

    assert _usage(message) == (120, 30)


def test_usage_repli_sur_la_longueur_de_la_completion() -> None:
    """Sans metadonnees, on estime la sortie et l'entree reste inconnue."""
    message = AIMessage(content="a" * 40)

    entree, sortie = _usage(message)

    assert entree == 0
    assert sortie == 10
