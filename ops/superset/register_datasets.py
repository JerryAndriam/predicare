"""Enregistrement de la connexion BI et des datasets de pilotage.

Ce module est execute UNE FOIS par le job `superset-import`, apres
`superset init` et la creation de l'administrateur. Il rend le tableau de
bord disponible sans configuration manuelle : c'est ce qui permet de dire au
jury « `make up`, et le tableau de bord est deja la ».

Trois garanties sont posees ici :

1. La connexion utilise le role `superset_ro`, cree par la migration `0002`,
   qui n'a aucun droit d'ecriture. Le tableau de bord ne peut donc pas
   modifier une donnee metier, meme par une requete erronee. `allow_dml`,
   `allow_ctas` et `allow_cvas` sont en plus mis a `False` : SQL Lab ne peut
   rien ecrire, meme si le role evoluait.

2. Les datasets pointent sur des VUES PHYSIQUES du schema `bi`, declarees
   dans `db/bi/views/*.sql`. La premiere version de ce script enregistrait
   des sources virtuelles (requetes SQL stockees dans les metadonnees de
   Superset). Cela posait trois problemes :
   - elles ne sont pas versionnees : le SQL vivait dans la base de
     metadonnees, hors du depot, et n'etait relisible par personne ;
   - `/dataset/list/` renvoie 404 sur Superset 6 pour une source virtuelle,
     ce qui donne l'impression d'une interface cassee ;
   - deux d'entre elles lisaient `audit.decision_gestionnaire`, schema
     volontairement interdit a `superset_ro` : elles echouaient en
     production avec « permission denied for schema audit ».

3. Le job est idempotent : relancer ne duplique rien. Les datasets dont le
   SQL a change sont mis a jour, pas recrees.
"""

from __future__ import annotations

import sys

#: Nom de la connexion telle qu'elle apparait dans l'interface Superset.
NOM_CONNEXION = "PrediCare (lecture seule)"

#: Datasets de pilotage : nom lisible -> nom de la vue physique dans `bi`.
#:
#: La definition, la source et la frequence sont reprises dans
#: `db/bi/README.md` : la documentation des indicateurs (Phase 7.3) doit
#: vivre dans le depot, pas dans un commentaire Python.
#:
#: `vide_jusqua` signale au script qu'un dataset sera vide tant qu'un certain
#: maillon de la chaine ne tournera pas. Le tableau de bord affiche alors un
#: etat, plutot que de laisser une absence passer pour un oubli.
DATASETS: dict[str, dict[str, str | None]] = {
    "Pilotage mensuel": {
        "vue": "v_kpi_mensuel",
        "definition": "Volume, montants, prevalence de la fraude et delai de traitement, par mois.",
        "vide_jusqua": None,
    },
    "Indicateurs globaux": {
        "vue": "v_kpi_global",
        "definition": (
            "Bandeau : une seule ligne. Taux de fraude RECALCULE et delai moyen PONDERE. "
            "Un taux ne se somme pas, une moyenne de moyennes n'est pas une moyenne."
        ),
        "vide_jusqua": None,
    },
    "Detail factures": {
        "vue": "v_factures_detail",
        "definition": "Une ligne par facture, avec dimensions denormalisees et verite terrain.",
        "vide_jusqua": None,
    },
    "Fraude par mecanisme": {
        "vue": "v_fraude_par_type",
        "definition": "Les mecanismes de fraude par mois, avec montant expose et part dans le volume.",
        "vide_jusqua": None,
    },
    "Prestataires a risque": {
        "vue": "v_prestataires_risque",
        "definition": "Prestataires classes par montant expose, avec taux de fraude et convention.",
        "vide_jusqua": None,
    },
    "Top 5 prestataires": {
        "vue": "v_top5_prestataires",
        "definition": "Les cinq prestataires les plus exposes par montant, pour le tableau de bord. La limite est structurelle (vue), pas un indice du frontal.",
        "vide_jusqua": None,
    },
    "Points de controle": {
        "vue": "v_controle_points",
        "definition": "Motifs de non-paiement : rejets metadataires et hors couverture.",
        "vide_jusqua": None,
    },
    "Detection du modele": {
        "vue": "v_detection_mensuel",
        "definition": "Volume de predictions et taux d'alerte du modele, par mois.",
        # `ml.prediction` est vide tant qu'aucun modele n'a ete execute.
        "vide_jusqua": "premiere execution du modele de detection",
    },
    "Delai de decision": {
        "vue": "v_delai_decision",
        "definition": "Delai entre alerte du modele et decision gestionnaire (moyenne, mediane, p90).",
        "vide_jusqua": "premiere decision gestionnaire enregistree",
    },
    "Montants economises": {
        "vue": "v_montants_economises",
        "definition": "Montant de fraude confirmee par un gestionnaire, par mois.",
        "vide_jusqua": "premiere decision gestionnaire enregistree",
    },
    "Faux positifs": {
        "vue": "v_faux_positifs",
        "definition": "Matrice de confusion metier : prediction du modele contre decision humaine.",
        "vide_jusqua": "premiere execution du modele et premiere decision gestionnaire",
    },
    "Performance du modele": {
        "vue": "v_modele_performance",
        "definition": (
            "Metriques de TEST de la version promue : rappel, faux positifs, precision, "
            "gain metier. Pas un rejeu in-sample de l'historique."
        ),
        "vide_jusqua": "promotion d'une version du modele",
    },
    "Boucle de decision": {
        "vue": "v_cdc_global",
        "definition": (
            "Alertes en attente, montant expose, decisions, montants confirmes et delai. "
            "Toujours une ligne, meme vide : une tuile « en attente » se voit, une absence non."
        ),
        "vide_jusqua": "premiere execution du modele et premiere decision gestionnaire",
    },
}


def synchroniser(table: object, session: object) -> None:
    """Remplit la liste de colonnes du dataset depuis la vue reelle.

    C'est l'etape la plus importante de cet enregistrement, et celle qu'un
    script d'amorcage oublie presque toujours.

    Ecrire la ligne `SqlaTable` en SQL direct cree bien le dataset, et
    l'interface l'affiche. Mais ses colonnes restent VIDE : `fetch_metadata`
    n'est appele par personne, puisque rien n'est passe par le formulaire
    « Add dataset » de Superset. Un graphique qui reference une colonne
    inexistante *pour Superset* echoue alors a l'execution avec
    « Columns missing in dataset » -- alors que la colonne est bel et bien
    dans la vue.

    C'est le pire des deux mondes : la vue est vraie, la colonne existe, et
    le graphique affiche « there was an issue ». Verifier que la colonne
    existe dans `information_schema` ne prouve donc RIEN : il faut verifier
    ce que Superset a, lui, dans `table_columns`.

    `fetch_metadata` fait autorité : il lit la vue et remplace la liste de
    colonnes. Le rappeler a chaque execution resynchronise un dataset dont la
    vue a gagne une colonne, ce qui arrive des que l'on ajoute un indicateur.

    La colonne de temps, ensuite
    ----------------------------
    Le controle « Time column » du frontal se remplit par defaut depuis
    `main_dttm_col`. Le laisser vide condamne toute requete de serie
    temporelle -- et `big_number` en construit toujours une, meme pour une
    valeur unique -- a un 400 « Datetime column not provided as part table
    configuration ». L'auto-detection de Superset a beau tomber juste sur la
    plupart des vues, elle n'est pas un contrat : on la rend explicite.
    """
    table.fetch_metadata()  # type: ignore[attr-defined]
    session.commit()  # type: ignore[attr-defined]
    nb = len(table.columns)  # type: ignore[attr-defined]
    if not nb:
        raise RuntimeError(
            f"la vue bi.{table.table_name} n'a pas de colonne exploitable "  # type: ignore[attr-defined]
            "par Superset : le dataset resterait inutilisable."
        )

    temps = [c.column_name for c in table.columns if c.is_dttm]  # type: ignore[attr-defined]
    if temps and table.main_dttm_col not in temps:  # type: ignore[attr-defined]
        # Deja valide : on ne remue pas un choix existant (`v_prestataires_risque`
        # date ses conventions par `date_fin_convention`, pas par sa premiere
        # colonne temporelle).
        table.main_dttm_col = temps[0]  # type: ignore[attr-defined]
        session.commit()  # type: ignore[attr-defined]
    print(  # type: ignore[attr-defined]
        f"    {table.table_name:24} {nb:3d} colonne(s)  temps={table.main_dttm_col or '(aucune)'}"  # type: ignore[attr-defined]
    )


def enregistrer(session: object) -> tuple[list[str], list[str]]:
    """Cree la connexion et enregistre les datasets sur les vues physiques.

    L'ecriture se fait par requete directe plutot que par un helper
    `get_or_create` : ces helpers ont disparu des versions majeures de
    Superset, alors que le modele `Database` est stable. Un script d'amorcage
    doit survivre a une montee de version.

    Retourne le couple (crees, supprimes) pour que le journal du job dise ce
    qui a reellement change.
    """
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.core import Database

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

    vues_attendues = {d["vue"] for d in DATASETS.values()}

    # Les datasets virtuels de la premiere version sont supprimes : deux
    # echouaient a l'execution, deux etaient vides, et le cinquieme portait un
    # libelle en euros sur des montants en ariary. Les laisser afficherait
    # des erreurs dans l'interface a cote des nouveaux.
    supprimes: list[str] = []
    for table in session.query(SqlaTable).filter_by(database_id=chaine.id).all():
        # Une source virtuelle porte un SQL ; une vue physique n'en porte pas
        # et se resout par `schema` + `table_name`.
        if table.sql or (
            (table.schema or "public") != "bi" or table.table_name not in vues_attendues
        ):
            supprimes.append(table.table_name)
            session.delete(table)
    if supprimes:
        session.commit()

    crees: list[str] = []
    for nom, spec in DATASETS.items():
        vue = spec["vue"]
        existant = session.query(SqlaTable).filter_by(database_id=chaine.id, table_name=vue).first()
        if existant is not None:
            # Un dataset physique porte `sql = None` et se resout par
            # `table_name`. Ne pas y remettre le SQL : il transformerait la
            # vue physique en source virtuelle, ce que cette migration
            # supprime justement.
            # Resynchronisation a CHAQUE execution, et non sur le seul dataset
            # vide : une vue qui gagne une colonne doit la voir arriver dans
            # `table_columns`. Ne resynchroniser que les datasets vides rendait
            # la nouvelle colonne invisible de Superset, et le graphique
            # echouait alors que la vue etait juste.
            synchroniser(existant, session)
            continue
        table = SqlaTable(
            database=chaine,
            table_name=vue,
            schema="bi",
            sql=None,
            is_sqllab_view=False,
        )
        session.add(table)
        session.commit()
        synchroniser(table, session)
        crees.append(nom)

    return crees, supprimes


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
            print("DB_CONNECTION_STRING absente : aucune source BI a enregistrer.", file=sys.stderr)
            return 1
        superset_db.session.info["ro_uri"] = uri_bi

        try:
            crees, supprimes = enregistrer(superset_db.session)
        except Exception as exc:
            print(f"ECHEC de l'enregistrement des datasets : {exc}", file=sys.stderr)
            return 1

        print(f"Connexion « {NOM_CONNEXION} » en lecture seule.")
        if supprimes:
            print(f"Datasets virtuels supprimes : {len(supprimes)}")
            for nom in supprimes:
                print(f"  - {nom}")
        print(f"Datasets enregistres : {len(DATASETS)} (nouveaux : {len(crees)})")
        for nom, spec in DATASETS.items():
            etat = f"[vide jusqu'a {spec['vide_jusqua']}]" if spec["vide_jusqua"] else "[peuple]"
            print(f"  - bi.{spec['vue']:28} {nom}  {etat}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
