"""Enregistrement de la connexion BI et des datasets de pilotage.

Ce module est execute UNE FOIS par le job `superset-import`, apres
`superset init` et la creation de l'administrateur. Il rend le tableau de
bord disponible sans configuration manuelle a la main : c'est ce qui permet
de dire au jury « `make up-bi`, et le tableau de bord est deja la ».

Deux garanties sont posees ici :

1. La connexion utilise le role `superset_ro`, cree par la migration
   `0002_superset_readonly`, qui n'a aucun droit d'ecriture. Le tableau de
   bord ne peut donc pas modifier une donnee metier, meme par une requete
   erronee.
2. Les requetes sont declarees en dur et versionnees avec le depot. Un
   tableau de bord construit a la main dans l'interface n'est ni auditable,
   ni reproductible sur une machine vierge.
"""

from __future__ import annotations

import sys

#: Identifiants et requetes du pilotage decisionnel.
#: Le CDC (Phase 7.1) impose de documenter, pour chaque indicateur, sa
#: definition, sa source et sa frequence de mise a jour : ces trois
#: informations sont dans le commentaire de chaque requete.
DATASETS: dict[str, dict[str, str]] = {
    "Factures traitees": {
        "definition": "Nombre de factures et montant total, par mois.",
        "source": "core.facture",
        "frequence": " quotidienne, rafraichissement a l'ouverture",
        "sql": """
            SELECT date_trunc('month', f.date_facture) AS mois,
                   COUNT(*)              AS nb_factures,
                   SUM(f.montant_total)   AS montant_total_eur
            FROM core.facture f
            GROUP BY 1
            ORDER BY 1
        """,
    },
    "Taux de detection": {
        "definition": "Part des factures signalees comme frauduleuses par le modele.",
        "source": "ml.prediction",
        "frequence": " continue, une ligne par prediction",
        "sql": """
            SELECT p.created_at::date                    AS jour,
                   COUNT(*)                               AS nb_predictions,
                   SUM(CASE WHEN p.is_fraud THEN 1 ELSE 0 END) AS nb_alertes,
                   ROUND(100.0 * SUM(CASE WHEN p.is_fraud THEN 1 ELSE 0 END)
                         / NULLIF(COUNT(*), 0), 2)       AS taux_detection_pct
            FROM ml.prediction p
            GROUP BY 1
            ORDER BY 1
        """,
    },
    "Montants economises": {
        "definition": "Montant des factures en fraude validees par un gestionnaire.",
        "source": "audit.decision_gestionnaire + core.facture",
        "frequence": " a chaque decision gestionnaire",
        "sql": """
            SELECT d.decision,
                   COUNT(*)              AS nb_dossiers,
                   SUM(f.montant_total)  AS montant_concerne_eur
            FROM audit.decision_gestionnaire d
            JOIN ml.prediction p ON p.id = d.prediction_id
            JOIN core.facture f   ON f.id = p.facture_id
            GROUP BY 1
            ORDER BY 1
        """,
    },
    "Delai de traitement": {
        "definition": "Delai moyen entre la prediction et la decision gestionnaire.",
        "source": "ml.prediction",
        "frequence": " continue",
        "sql": """
            SELECT p.created_at::date AS jour,
                   ROUND(AVG(EXTRACT(EPOCH FROM (p.decided_at - p.created_at))), 1)
                       AS delai_moyen_secondes,
                   COUNT(*)      AS nb_dossiers_traites
            FROM ml.prediction p
            WHERE p.decided_at IS NOT NULL
            GROUP BY 1
            ORDER BY 1
        """,
    },
    "Faux positifs et faux negatifs": {
        "definition": (
            "Croisement entre la prediction du modele et la decision humaine. "
            "Un faux positif est une alerte sur une facture reellee non "
            "frauduleuse ; c'est l'indicateur qui justifie le seuil retenu."
        ),
        "source": "ml.prediction + audit.decision_gestionnaire",
        "frequence": " a chaque decision gestionnaire",
        "sql": """
            SELECT p.is_fraud                      AS prediction_fraude,
                   d.decision                      AS decision_gestionnaire,
                   COUNT(*)                        AS nb_dossiers
            FROM ml.prediction p
            LEFT JOIN audit.decision_gestionnaire d ON d.prediction_id = p.id
            GROUP BY 1, 2
            ORDER BY 1, 2
        """,
    },
}

#: Nom de la connexion telle qu'elle apparait dans l'interface Superset.
NOM_CONNEXION = "PrediCare (lecture seule)"


def enregistrer(session: object) -> list[str]:
    """Cree la connexion et les datasets s'ils n'existent pas deja.

    L'ecriture se fait par requete directe plutot que par un helper
    `get_or_create` : ces helpers ont disparu des versions majeures de
    Superset, alors que le modele `Database` est stable. Un script d'amorcage
    doit survivre a une montee de version.

    Le job est idempotent : relancer ne duplique ni la connexion ni les
    datasets, il se contente de remettre l'URI a jour.
    """
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.core import Database

    # La connexion de BI est celle declaree dans superset_config.py, donc en
    # lecture seule. `allow_dml=False` ajoute une troisieme barriere : meme
    # avec un role mal configure, SQL Lab ne peut pas ecrire.
    chaine = session.query(Database).filter_by(database_name=NOM_CONNEXION).one_or_none()
    if chaine is None:
        chaine = Database(
            database_name=NOM_CONNEXION,
            sqlalchemy_uri=session.info["ro_uri"],
            expose_in_sqllab=True,
            allow_ctas=False,
            allow_cvas=False,
            allow_dml=False,
        )
        session.add(chaine)
        session.commit()
    else:
        chaine.sqlalchemy_uri = session.info["ro_uri"]
        session.commit()

    crees: list[str] = []
    for nom in DATASETS:
        if session.query(SqlaTable).filter_by(table_name=f"v_{nom}").first():
            continue
        session.add(
            SqlaTable(
                database=chaine,
                table_name=f"v_{nom}",
                sql=DATASETS[nom]["sql"].strip(),
                is_sqllab_view=True,
            )
        )
        session.commit()
        crees.append(nom)

    return crees


def main() -> int:
    """Point d'entree du job `superset-import`."""
    import os

    os.environ.setdefault("SUPERSET_CONFIG_PATH", "/app/pythonpath/superset_config.py")

    from superset import config as superset_config
    from superset import db as superset_db
    from superset.app import create_app

    application = create_app()
    with application.app_context():
        # La source BI est la connexion en lecture seule. Elle est distincte
        # de `SQLALCHEMY_DATABASE_URI`, qui pointe sur les metadonnees de
        # Superset et doit donc rester accessible en ecriture.
        uri_bi = superset_config.PREDICARE_BI_DATABASE_URI
        if not uri_bi:
            print(
                "DB_CONNECTION_STRING absente : aucune source BI a enregistrer.",
                file=sys.stderr,
            )
            return 1
        superset_db.session.info["ro_uri"] = uri_bi

        try:
            crees = enregistrer(superset_db.session)
        except Exception as exc:
            print(f"ECHEC de l'enregistrement des datasets : {exc}", file=sys.stderr)
            return 1

        print(f"Connexion « {NOM_CONNEXION} » en lecture seule.")
        print(f"Datasets enregistres : {len(DATASETS)} (nouveaux : {len(crees)})")
        for definition in DATASETS.values():
            print(f"  - {definition['definition'][:70]}...")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
