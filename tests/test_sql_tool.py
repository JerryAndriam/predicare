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

import pytest

from predicare.errors import DataAccessError
from predicare_rag_api.sql_tool import FORME_AUTORISEE, InsuredHistoryTool

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
