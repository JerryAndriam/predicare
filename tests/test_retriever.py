"""Recherche pgvector : sources citees, tri, seuil.

Le store est remplace par un faux objet : aucun conteneur n'est necessaire.
"""

from __future__ import annotations

from predicare_rag_api.retriever import ContractRetriever, Source


class _StoreFaux:
    def __init__(self, resultats):
        self._resultats = resultats

    def similarity_search(self, query, *, k, score_threshold):  # noqa: ARG002 - signature imposee par le protocole
        return self._resultats[:k]


def test_search_retourne_sources_triees():
    store = _StoreFaux(
        [
            ({"contrat": "C1", "article": "Art 1", "garantie": "G", "texte": "t1"}, 0.9),
            ({"contrat": "C2", "article": "Art 2", "garantie": "G", "texte": "t2"}, 0.75),
        ]
    )
    retriever = ContractRetriever(store, top_k=5, threshold=0.7)
    sources = retriever.search("question")
    assert len(sources) == 2
    assert sources[0].score >= sources[1].score
    assert all(isinstance(s, Source) for s in sources)


def test_search_vide_si_aucun_resultat():
    store = _StoreFaux([])
    retriever = ContractRetriever(store, top_k=5, threshold=0.7)
    assert retriever.search("question") == []


def test_format_sources_cite_contrat_et_article():
    store = _StoreFaux([])
    retriever = ContractRetriever(store)
    source = Source(
        contrat="PREMIUM",
        article="Art 5",
        garantie="Consultation",
        extrait="taux 100%",
        score=0.9,
        source_fichier="Conditions_Generales_PREMIUM.pdf",
    )
    bloc = retriever.format_sources([source])
    assert "PREMIUM" in bloc
    assert "Art 5" in bloc
    assert "Conditions_Generales_PREMIUM.pdf" in bloc
    assert source.to_dict()["source_fichier"] == "Conditions_Generales_PREMIUM.pdf"
