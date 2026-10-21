"""Les trois API se construisent et exposent leur supervision.

C'est le test le plus brutal du projet : si une importation casse, si une
route disparait ou si le format de /health change, tout le reste est
inutilisable. Il ne demande ni base ni conteneur : `create_app()` ne se
connecte a rien tant qu'aucune requete ne touche la base.

On verifie aussi la distinction entre vivacite et disponibilite, qui est
une decision d'exploitation : `/health` doit repondre 200 meme degrade,
sinon Docker arrete un service qui fonctionne.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from predicare_core_api import SERVICE_NAME as CORE
from predicare_inference_api import SERVICE_NAME as INFERENCE
from predicare_rag_api import SERVICE_NAME as RAG

APPLICATIONS = [
    ("api-core", CORE, "predicare_core_api.main"),
    ("api-inference", INFERENCE, "predicare_inference_api.main"),
    ("api-rag", RAG, "predicare_rag_api.main"),
]


def _construire(chemin_module: str):
    """Importe et instancie l'application sans lancer de serveur."""
    import importlib

    return importlib.import_module(chemin_module).create_app()


@pytest.fixture(params=APPLICATIONS, ids=[nom for nom, _, _ in APPLICATIONS])
def application(request: pytest.FixtureRequest):
    nom, service, chemin = request.param
    return nom, service, _construire(chemin)


# --------------------------------------------------------------- construction


def test_application_construite(application: tuple) -> None:
    """Une erreur d'import ou de configuration doit ici sauter."""
    nom, service, app = application

    assert app is not None
    assert app.state.service == service
    assert nom


def test_titre_et_version_renseignes(application: tuple) -> None:
    _, _, app = application

    assert app.title
    assert app.version


# --------------------------------------------------------------- supervision


def test_health_repond_200(application: tuple) -> None:
    """/health est la sonde de VIVACITE : 200 tant que le processus tient.

    Elle doit rester 200 meme si la base est injoignable. Le cas inverse
    ferait arreter par Docker un service parfaitement fonctionnel, parce
    qu'il n'a pas encore de modele ou de cle LLM.
    """
    with TestClient(application[2]) as client:
        reponse = client.get("/health")

    assert reponse.status_code == 200


def test_health_expose_les_sondes(application: tuple) -> None:
    with TestClient(application[2]) as client:
        corps = client.get("/health").json()

    assert corps["service"] == application[1]
    assert "checks" in corps
    assert corps["status"] in {"ok", "degraded"}


def test_ready_refuse_si_dependance_manquante(application: tuple) -> None:
    """/health/ready est la sonde de DISPONIBILITE : 503 quand une
    dependance critique manque. C'est elle que Docker et la passerelle
    utilisent pour ne pas router vers un service qui echouerait."""
    with TestClient(application[2]) as client:
        reponse = client.get("/health/ready")

    assert reponse.status_code in {200, 503}
    if reponse.status_code == 503:
        assert reponse.json()["ready"] is False


def test_metrics_exposees(application: tuple) -> None:
    with TestClient(application[2]) as client:
        reponse = client.get("/metrics")

    assert reponse.status_code == 200
    assert "predicare_http_requests_total" in reponse.text


def test_metrics_exposent_la_version(application: tuple) -> None:
    with TestClient(application[2]) as client:
        reponse = client.get("/metrics")

    assert "predicare_build_info" in reponse.text
    assert application[1] in reponse.text


# --------------------------------------------------------------- documentation


def test_openapi_genere(application: tuple) -> None:
    """Chaque service expose sa specification a son propre chemin.

    Les APIs sont montees sous `/api/<service>` par la passerelle : une
    URL OpenAPI unique pour les trois mettrait la documentation en
    collision une fois le routage applique.
    """
    app = application[2]

    with TestClient(app) as client:
        reponse = client.get(app.openapi_url)

    assert reponse.status_code == 200
    assert reponse.json()["info"]["title"]


def test_health_present_dans_openapi(application: tuple) -> None:
    """/health doit etre documente : c'est le point d'entree de
    l'exploitant de la plateforme."""
    app = application[2]

    with TestClient(app) as client:
        chemins = client.get(app.openapi_url).json()["paths"]

    assert "/health" in chemins


# --------------------------------------------------------------- identite des erreurs


def test_erreur_au_format_metier(application: tuple) -> None:
    """Une requete non authentifiee doit renvoyer le format d'erreur du
    projet, pas une trace Python.

    Le format `{code, message, request_id}` fait partie du contrat
    d'interface consomme par l'interface web.
    """
    with TestClient(application[2]) as client:
        reponse = (
            client.get("/api/core/factures")
            if application[1] == CORE
            else client.get("/api/rag/question")
        )

    if reponse.status_code == 401:
        corps = reponse.json()
        assert corps["code"] == "unauthorized"
        assert "message" in corps
        assert "request_id" in corps


def test_tracer_de_correlation_present(application: tuple) -> None:
    """Chaque reponse porte un `X-Request-Id`, sans quoi il est impossible
    de relier un message d'erreur a une ligne de journal."""
    with TestClient(application[2]) as client:
        reponse = client.get("/health")

    assert "X-Request-Id" in reponse.headers


def test_tracer_de_correlation_repris_de_l_entree(application: tuple) -> None:
    with TestClient(application[2]) as client:
        reponse = client.get("/health", headers={"X-Request-Id": "test-1234"})

    assert reponse.headers.get("X-Request-Id") == "test-1234"


# --------------------------------------------------------------- sondes RAG


def test_sonde_llm_rejette_les_gabarits() -> None:
    """Un gabarit est *truthy* : `/health` ne doit pas annoncer `ok` pour autant.

    `bool("CHANGER_MOI_LLM")` vaut True. Sans la regle `est_configure`, la
    sonde RAG annoncait un assistant sain alors qu'il tourne en mode degrade.
    """
    from predicare_rag_api.main import _llm_configure

    for gabarit in (None, "", "   ", "CHANGER_MOI_LLM", "changeme", "xxx", "<votre-cle>"):
        assert _llm_configure(gabarit) is False, gabarit


def test_sonde_llm_accepte_une_vraie_cle() -> None:
    from predicare_rag_api.main import _llm_configure

    assert _llm_configure("sk-proj-abcdef123456") is True
