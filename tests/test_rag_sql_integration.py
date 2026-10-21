"""Integration SQL du RAG : les modeles de requetes sur la vraie base.

Ces tests ne tournent que si `PREDICARE_DB_RO_URL` est fourni (par exemple
dans le conteneur api-rag). Sans cette variable, ils sont ignores : la CI
pure reste executable sans Docker.
"""

from __future__ import annotations

import os

import pytest

from predicare_rag_api.sql_tool import TEMPLATES_REQUETES, InsuredHistoryTool

URL_RO = os.getenv("PREDICARE_DB_RO_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not URL_RO,
        reason="PREDICARE_DB_RO_URL absent : integration SQL non executee",
    ),
]


@pytest.fixture(scope="module")
def outil() -> InsuredHistoryTool:
    return InsuredHistoryTool(URL_RO, max_rows=100)


def test_total_rembourse_assure_1(outil: InsuredHistoryTool) -> None:
    lignes = outil.run(TEMPLATES_REQUETES["total_rembourse"], assure_id="1")

    assert len(lignes) == 1
    assert float(next(iter(lignes[0].values()))) == pytest.approx(616060.00)


def test_dernieres_factures_assure_1(outil: InsuredHistoryTool) -> None:
    lignes = outil.run(TEMPLATES_REQUETES["dernieres_factures"], assure_id="1")

    assert len(lignes) == 10
    dates = [ligne["date_facture"] for ligne in lignes]
    assert dates == sorted(dates, reverse=True)


def test_factures_rejetees_assure_1(outil: InsuredHistoryTool) -> None:
    lignes = outil.run(TEMPLATES_REQUETES["factures_rejetees"], assure_id="1")

    assert len(lignes) == 1
    assert lignes[0]["motif_rejet"] == "ORDONNANCE_PERIMEE"


def test_filtre_assure_isole_les_dossiers(outil: InsuredHistoryTool) -> None:
    """Une requete pour l'assure 2 ne doit jamais ramener les lignes de l'assure 1."""
    requete = "SELECT id, assure_id FROM core.facture WHERE 1=1 AND assure_id = :assure_id"

    lignes_1 = outil.run(requete, assure_id="1")
    lignes_2 = outil.run(requete, assure_id="2")

    ids_1 = {ligne["id"] for ligne in lignes_1}
    ids_2 = {ligne["id"] for ligne in lignes_2}

    assert ids_1
    assert all(int(ligne["assure_id"]) == 2 for ligne in lignes_2)
    assert ids_1.isdisjoint(ids_2)
