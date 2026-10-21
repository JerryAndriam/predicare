"""Securite de l'outil SQL utilise par l'agent.

C'est la barriere la plus serieuse du projet : elle ne repose pas sur une
instruction donnee au LLM, mais sur trois contraintes structurelles.

1. La connexion pointe vers un role PostgreSQL en lecture seule.
2. Les requetes passent par une liste blanche de formes.
3. Le filtre sur l'assure connecte est injecte par le code.

Ce module verifie les points 2 et 3, qui sont testables sans base. Le
point 1 est verifie par la migration `0002_superset_readonly` et par le
controle de fuite de la CI.
"""

from __future__ import annotations

import json
import re

import pytest

from predicare.errors import DataAccessError
from predicare_rag_api.sql_tool import (
    FORME_AUTORISEE,
    TEMPLATES_REQUETES,
    InsuredHistoryTool,
)

# URL de connexion factice : `create_engine` n'ouvre pas de connexion tant
# qu'on ne l'utilise pas, donc aucun conteneur n'est necessaire.
URL_FACTICE = "postgresql+psycopg://predicare_ro:x@localhost:5432/predicare"


@pytest.fixture
def outil() -> InsuredHistoryTool:
    return InsuredHistoryTool(URL_FACTICE)


# --------------------------------------------------------------- formes acceptees


def test_select_simple_accepte(outil: InsuredHistoryTool) -> None:
    requete = "SELECT * FROM core.facture"

    assert outil._validate(requete) == requete


def test_select_avec_filtre_assure_accepte(outil: InsuredHistoryTool) -> None:
    requete = "SELECT id, montant_total FROM core.facture WHERE 1=1 AND assure_id = :assure_id"

    assert outil._validate(requete) == requete


def test_select_filtre_limite_accepte(outil: InsuredHistoryTool) -> None:
    requete = "SELECT * FROM core.facture WHERE 1=1 AND assure_id = :assure_id LIMIT 10"

    assert outil._validate(requete) == requete


def test_casse_ignoree(outil: InsuredHistoryTool) -> None:
    requete = "select ID from CORE.FACTURE"

    assert outil._validate(requete) == requete


def test_point_virgule_final_accepte(outil: InsuredHistoryTool) -> None:
    """Un `;` final est courant et sans danger : une seule instruction.

    Le moteur du modele ajoute souvent ce point-virgule ; le refuser ferait
    echouer la requete exacte des modeles de reference.
    """
    requete = TEMPLATES_REQUETES["total_rembourse"] + " ;"

    assert outil._validate(requete) == requete


def test_filtre_sans_1_egal_1_accepte(outil: InsuredHistoryTool) -> None:
    """Le modele peut omettre `1=1` : le filtre reste exige et verifie."""
    requete = (
        "SELECT statut FROM core.facture WHERE assure_id = :assure_id "
        "ORDER BY date_facture DESC LIMIT 1"
    )

    assert outil._validate(requete) == requete


def test_where_sans_filtre_assure_refuse(outil: InsuredHistoryTool) -> None:
    """Un WHERE qui ne filtre pas sur l'assure connecte est rejete."""
    with pytest.raises(DataAccessError) as erreur:
        outil._validate("SELECT * FROM core.facture WHERE statut = 'PAYEE'")

    assert erreur.value.details["type_erreur"] == "forme_refusee"


# --------------------------------------------------------------- formes refusees

#: Chaque entree doit etre rejetee. La nature du refus est verifiee
#: separement : une requete malformee et une requete d'ecriture
# n'appellent pas le meme message a l'utilisateur.
REQUETES_ECRITURE = [
    "DELETE FROM core.facture",
    "UPDATE core.facture SET montant_total = 0",
    "INSERT INTO core.facture (id) VALUES (1)",
    "DROP TABLE core.facture",
    "ALTER TABLE core.facture ADD COLUMN x int",
    "TRUNCATE core.facture",
    "CREATE TABLE pirate (id int)",
    "GRANT ALL ON core.facture TO predicare_ro",
]


@pytest.mark.parametrize("requete", REQUETES_ECRITURE)
def test_requetes_ecriture_refusees(outil: InsuredHistoryTool, requete: str) -> None:
    with pytest.raises(DataAccessError) as erreur:
        outil._validate(requete)

    assert erreur.value.code == "data_access_denied"


INJECTIONS_CLASSIQUES = [
    "SELECT * FROM core.facture; DROP TABLE core.assure",
    "SELECT * FROM core.facture UNION SELECT email FROM core.utilisateur",
    "SELECT * FROM core.facture -- et ensuite DROP TABLE",
    "SELECT * FROM core.facture /* commentaire */",
    "SELECT pg_sleep(10)",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM core.facture WHERE 1=1 UNION SELECT username FROM ab_user",
]


@pytest.mark.parametrize("requete", INJECTIONS_CLASSIQUES)
def test_injections_sql_refusees(outil: InsuredHistoryTool, requete: str) -> None:
    with pytest.raises(DataAccessError):
        outil._validate(requete)


REQUETES_HORS_PERIMETRE = [
    "SELECT * FROM core.assure",
    "SELECT * FROM core.utilisateur",
    "SELECT * FROM audit.journal",
    "SELECT * FROM pg_tables",
    "SELECT * FROM core.identite_chiffree",
]


@pytest.mark.parametrize("requete", REQUETES_HORS_PERIMETRE)
def test_tables_hors_perimetre_refusees(outil: InsuredHistoryTool, requete: str) -> None:
    """Seules `core.facture` et `core.remboursement` sont lisibles.

    `core.identite_chiffree` est hors de portee par construction : meme en
    lecture seule, l'agent n'a pas a avoir acces aux identites chiffrees.
    """
    with pytest.raises(DataAccessError):
        outil._validate(requete)


def test_requete_vide_refusee(outil: InsuredHistoryTool) -> None:
    with pytest.raises(DataAccessError):
        outil._validate("")


# --------------------------------------------------------------- filtre assure


def test_execution_sans_assure_refusee(outil: InsuredHistoryTool) -> None:
    """Sans pseudonyme de session, l'outil refuse de s'executer.

    C'est ce qui rend impossible a l'agent de repondre a la place d'un
    autre : l'identifiant n'est pas un argument, il vient du jeton.
    """
    with pytest.raises(DataAccessError) as erreur:
        outil.run("SELECT * FROM core.facture", assure_id="")

    assert "dossier assure" in str(erreur.value)


def test_requete_valide_but_sans_session_refusee(outil: InsuredHistoryTool) -> None:
    with pytest.raises(DataAccessError):
        outil.run("SELECT * FROM core.facture", assure_id="")


# --------------------------------------------------------------- construction


def test_url_vide_refusee_a_la_construction() -> None:
    """Pas d'URL en lecture seule = pas d'outil du tout.

    Mieux vaut un assistant sans historique qu'un assistant dont
    l'historique serait lu par un compte disposant de droits d'ecriture.
    """
    with pytest.raises(DataAccessError):
        InsuredHistoryTool("")


def test_description_declare_une_portee_etroite(outil: InsuredHistoryTool) -> None:
    """La description est ce que le LLM lit pour choisir un outil.

    Elle doit dire explicitement que la portee est limitee a l'assure
    connecte : une description vague ouvre la porte a une requete
    disproportionnee.
    """
    assert "assure connecte" in outil.description
    assert "autre assure" in outil.description


def test_nom_de_l_outil_stable(outil: InsuredHistoryTool) -> None:
    """Le nom de l'outil fait partie du contrat du systeme : le changer
    casserait silencieusement les references dans le prompt."""
    assert outil.name == "consulter_historique_assure"


def test_liste_blanche_bloque_les_jointures_complexes(outil: InsuredHistoryTool) -> None:
    """Une jointure entre trois tables n'est pas dans la liste blanche.

    Elle est refusee : la forme la plus simple a autoriser est aussi la
    moins dangereuse a maintenir.
    """
    requete = (
        "SELECT * FROM core.facture f JOIN core.assure a ON a.id = f.assure_id "
        "WHERE 1=1 AND assure_id = :assure_id"
    )

    with pytest.raises(DataAccessError):
        outil._validate(requete)


def test_liste_blanche_est_ancree_sur_core() -> None:
    """La liste blanche ne peut cibler que `core.facture` ou
    `core.remboursement`. Verifie directement sur le motif, pour qu'une
    modification de la liste ne passe pas inapercue."""
    assert "core" in FORME_AUTORISEE.pattern
    assert "assure_id" in FORME_AUTORISEE.pattern


# ------------------------------------------------------- agregats et modeles


def test_agregat_sum_accepte(outil: InsuredHistoryTool) -> None:
    """SUM est un besoin metier : un total ne se calcule pas a la main."""
    requete = TEMPLATES_REQUETES["total_rembourse"]

    assert outil._validate(requete) == requete


def test_templates_de_requetes_disponibles(outil: InsuredHistoryTool) -> None:
    assert set(TEMPLATES_REQUETES) == {
        "total_rembourse",
        "dernieres_factures",
        "factures_rejetees",
    }
    for requete in TEMPLATES_REQUETES.values():
        assert outil._validate(requete) == requete


def test_description_expose_les_templates(outil: InsuredHistoryTool) -> None:
    """Le LLM choisit ses arguments en lisant la description de l'outil."""
    for requete in TEMPLATES_REQUETES.values():
        assert requete in outil.description


# ------------------------------------------------------- erreurs structurees


def test_erreur_motif_refuse_structuree(outil: InsuredHistoryTool) -> None:
    with pytest.raises(DataAccessError) as erreur:
        outil._validate("DELETE FROM core.facture")

    details = erreur.value.details
    assert details["type_erreur"] == "motif_refuse"
    assert details["forme_attendue"]
    assert details["exemple"]


def test_assure_id_numerique_refuse(outil: InsuredHistoryTool) -> None:
    """Une valeur en dur lirait le dossier d'un autre assure."""
    with pytest.raises(DataAccessError) as erreur:
        outil._validate("SELECT * FROM core.facture WHERE 1=1 AND assure_id = 2")

    assert erreur.value.details["type_erreur"] == "motif_refuse"


def test_erreur_table_refusee_structuree(outil: InsuredHistoryTool) -> None:
    with pytest.raises(DataAccessError) as erreur:
        outil._validate("SELECT * FROM core.assure")

    details = erreur.value.details
    assert details["type_erreur"] == "table_refusee"
    assert ":assure_id" in details["forme_attendue"]


def test_erreur_forme_refusee_structuree(outil: InsuredHistoryTool) -> None:
    with pytest.raises(DataAccessError) as erreur:
        outil._validate("SELECT * FROM core.facture WHERE 1=1 AND assure_id = :assure_id OR 1=1")

    details = erreur.value.details
    assert details["type_erreur"] == "forme_refusee"
    assert details["exemple"].startswith("SELECT")


# --------------------------------------------------------------- run_agent


def test_run_agent_succes(monkeypatch: pytest.MonkeyPatch, outil: InsuredHistoryTool) -> None:
    def _run(requete: str, *, assure_id: str) -> list[dict]:
        assert "assure_id" in requete
        return [{"total": 616060.0}]

    monkeypatch.setattr(outil, "run", _run)

    payload = json.loads(outil.run_agent(TEMPLATES_REQUETES["total_rembourse"], assure_id="1"))

    assert payload == {"ok": True, "lignes": [{"total": 616060.0}]}


def test_run_agent_erreur_structuree(outil: InsuredHistoryTool) -> None:
    payload = json.loads(outil.run_agent("DELETE FROM core.facture", assure_id="1"))

    assert payload["ok"] is False
    assert payload["type_erreur"] == "motif_refuse"
    assert payload["forme_attendue"]
    assert payload["exemple"]
    assert payload["erreur"]


def test_run_agent_sans_assure_refuse(outil: InsuredHistoryTool) -> None:
    payload = json.loads(outil.run_agent(TEMPLATES_REQUETES["total_rembourse"], assure_id=""))

    assert payload["ok"] is False
    assert payload["type_erreur"] in {"forme_refusee", "motif_refuse"}
    assert "dossier assure" in payload["erreur"]


def test_run_agent_indisponible_ne_conseille_pas_de_recorriger(
    monkeypatch: pytest.MonkeyPatch, outil: InsuredHistoryTool
) -> None:
    """Une panne n'est pas une requete mal formee : le conseil differe.

    Inviter le modele a reecrire sa requete sur une erreur d'infrastructure
    l'engage dans une boucle de correction inutile.
    """

    def _run(requete: str, *, assure_id: str) -> list[dict]:
        raise DataAccessError(
            "Lecture de l'historique indisponible pour le moment.",
            details={"type_erreur": "indisponible"},
        )

    monkeypatch.setattr(outil, "run", _run)

    payload = json.loads(outil.run_agent("SELECT * FROM core.facture", assure_id="1"))

    assert payload["type_erreur"] == "indisponible"
    assert "reessaie pas" in payload["conseil"].lower()
    assert "forme_attendue" not in payload


def test_execution_indisponible_ne_fuit_pas_le_message_du_pilote(
    outil: InsuredHistoryTool,
) -> None:
    """Le message du pilote reste dans les journaux, jamais dans l'erreur."""

    class _MoteurEnPanne:
        def connect(self) -> object:
            raise RuntimeError("FATAL: password authentication failed for user predicare_ro")

    outil._engine = _MoteurEnPanne()  # type: ignore[assignment]

    with pytest.raises(DataAccessError) as erreur:
        outil.run(
            "SELECT * FROM core.facture WHERE 1=1 AND assure_id = :assure_id",
            assure_id="1",
        )

    assert erreur.value.details["type_erreur"] == "indisponible"
    assert "password" not in erreur.value.message


# --------------------------------------------------------------- injection du filtre


def _contient_filtre_assure(requete: str) -> bool:
    return re.search(r"\bassure_id\s*=\s*:assure_id\b", requete) is not None


def test_injection_sans_clause_where(outil: InsuredHistoryTool) -> None:
    requete = outil._injecter_filtre("SELECT * FROM core.facture")

    assert requete == "SELECT * FROM core.facture WHERE 1=1 AND assure_id = :assure_id"
    assert _contient_filtre_assure(requete)


def test_injection_avant_order_by(outil: InsuredHistoryTool) -> None:
    requete = outil._injecter_filtre(
        "SELECT date_facture FROM core.facture ORDER BY date_facture DESC"
    )

    assert requete == (
        "SELECT date_facture FROM core.facture WHERE 1=1 AND assure_id = :assure_id "
        "ORDER BY date_facture DESC"
    )
    assert _contient_filtre_assure(requete)


def test_injection_avant_limit(outil: InsuredHistoryTool) -> None:
    requete = outil._injecter_filtre("SELECT * FROM core.facture LIMIT 10")

    assert requete == "SELECT * FROM core.facture WHERE 1=1 AND assure_id = :assure_id LIMIT 10"
    assert _contient_filtre_assure(requete)


def test_injection_point_virgule_final_conserve(outil: InsuredHistoryTool) -> None:
    """Le `;` doit rester terminal : la clause ne s'ecrit pas apres lui."""
    requete = outil._injecter_filtre("SELECT * FROM core.facture;")

    assert requete == "SELECT * FROM core.facture WHERE 1=1 AND assure_id = :assure_id;"
    assert requete.endswith(";")


def test_injection_ignore_un_litteral_contenant_assure_id(outil: InsuredHistoryTool) -> None:
    """Un `:assure_id` dans une chaine ne doit pas faire croire au filtre."""
    requete = outil._injecter_filtre(
        "SELECT montant_total FROM core.facture WHERE motif_rejet = ':assure_id'"
    )

    assert _contient_filtre_assure(requete)
    assert requete != "SELECT montant_total FROM core.facture WHERE motif_rejet = ':assure_id'"
    assert requete.endswith("AND assure_id = :assure_id")


def test_injection_ne_duplique_pas_un_filtre_present(outil: InsuredHistoryTool) -> None:
    requete = "SELECT * FROM core.facture WHERE 1=1 AND assure_id = :assure_id"

    assert outil._injecter_filtre(requete) == requete


def test_requete_injectee_valide(outil: InsuredHistoryTool) -> None:
    """La requete finale est re-validee : l'injection ne contourne pas la liste blanche."""
    injectee = outil._injecter_filtre(
        "SELECT * FROM core.facture ORDER BY date_facture DESC LIMIT 5"
    )

    assert outil._validate(injectee) == injectee


# --------------------------------------------------------------- evasions nouvelles


def test_assure_id_dans_un_litteral_ne_vaut_pas_filtre(outil: InsuredHistoryTool) -> None:
    """Un WHERE dont le seul `:assure_id` est dans une chaine est refuse."""
    with pytest.raises(DataAccessError) as erreur:
        outil._validate("SELECT statut FROM core.facture WHERE statut = ':assure_id'")

    assert erreur.value.details["type_erreur"] == "forme_refusee"


def test_sous_requete_scalaire_refusee(outil: InsuredHistoryTool) -> None:
    """`SELECT (SELECT ...)` est une lecture hors perimetre potentielle."""
    with pytest.raises(DataAccessError):
        outil._validate(
            "SELECT (SELECT count(*) FROM core.remboursement) FROM core.facture "
            "WHERE 1=1 AND assure_id = :assure_id"
        )


def test_agregat_sum_toujours_accepte_apres_refus_des_sous_requetes(
    outil: InsuredHistoryTool,
) -> None:
    requete = TEMPLATES_REQUETES["total_rembourse"]

    assert outil._validate(requete) == requete
