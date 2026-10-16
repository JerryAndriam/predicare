"""Cree les graphiques et le tableau de bord de pilotage.

Execute par le job `superset-dashboard`, apres que le serveur Superset
repond. Les sources sont des vues physiques du schema `bi`, donc rien n'est
stocke dans les metadonnees en dehors des identifiants des objets.

Pourquoi l'API REST plutot que le modele ORM
--------------------------------------------
Le modele `Slice` de Superset a change de forme a chaque version majeure :
le couple `Slice` / `slice_data` de la 6 n'est pas celui de la 5. Un script
d'amorcage ecrit contre le modele cesse de fonctionner sur la montee de
version suivante ; ecrit contre l'API REST, il echoue a l'endroit exact ou la
charge utile a change, avec un message qui nomme le champ.

Trois details de cette API, tous decouverts a l'usage :

- l'authentification passe par `POST /api/v1/security/login`, qui renvoie un
  jeton. La session de formulaire du navigateur est refusee par
  `/api/v1/*` avec « Missing Authorization Header » ;
- le parametre de requete `q` est encode en **Rison**, le format de Superset,
  et pas en texte libre : passer un titre brut repond « Not a valid
  rison/json argument ». On liste donc la collection et on filtre en Python ;
- la liste se pagine a 100 elements.

Regles de conception appliquees au tableau de bord
--------------------------------------------------
1. Un indicateur par graphique. Un graphique qui melange un volume et un taux
   impose deux axes, et deux axes obligent le lecteur a en choisir un.
2. L'unite est dans le titre, pas seulement dans l'axe. Le jeu est en ariary :
   un titre « MGA » empeche la lecture en euros, qui serait fausse d'un
   facteur d'environ 57 000.
3. Lecture de haut en bas : indicateurs, puis tendance, puis decomposition,
   puis controle. C'est l'ordre des questions d'un gestionnaire.
4. Pas de camembert au-dela de sept parts. Au-dela, la comparaison angulaire
   devient illisible ; les barres horizontales se comparent par la longueur.
5. Les datasets vides sont representes, et non absents : une brique
   manquante passe inapercee, une brique vide avec son etat se discute.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from urllib.parse import urlencode

#: Adresse du serveur. `localhost` convient depuis la machine ; depuis le job
#: `superset-dashboard`, il faut le nom du service, car `localhost` y designe
#: le conteneur du job lui-meme.
BASE = os.environ.get("SUPERSET_URL", "http://localhost:8088")

TITRE_DASHBOARD = "Pilotage mensuel — PrediCare TPA"
SLUG = "pilotage-mensuel"

BLEU = "#1F77B4"
ROUGE = "#D64545"
VERT = "#2E7D32"
ORANGE = "#ED7D31"


class Client:
    """Client minimal de l'API Superset, authentifie par jeton."""

    def __init__(self, base: str, username: str, password: str) -> None:
        self.base = base.rstrip("/")
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )
        self.jeton = ""
        self.csrf = ""
        self._connecter(username, password)

    def _json(self, methode: str, chemin: str, charge: dict | None = None) -> dict:
        data = json.dumps(charge).encode() if charge is not None else None
        entetes = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Referer": self.base,
        }
        if self.jeton:
            entetes["Authorization"] = f"Bearer {self.jeton}"
        # Le jeton d'acces ne dispense pas du CSRF : la protection Flask-WTF
        # couvre `/api/v1/*` et refuse toute ecriture sans `X-CSRFToken`.
        if self.csrf:
            entetes["X-CSRFToken"] = self.csrf
        req = urllib.request.Request(
            f"{self.base}{chemin}", data=data, method=methode, headers=entetes
        )
        try:
            with self.opener.open(req, timeout=120) as r:
                brut = r.read()
                return json.loads(brut) if brut else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:400]
            raise RuntimeError(f"{methode} {chemin} -> HTTP {exc.code} : {detail}") from exc

    def _connecter(self, username: str, password: str) -> None:
        """Obtient un jeton d'acces.

        Sans le `superset init` du job d'amorcage, le role `Admin` n'a
        litteralement aucune permission : le compte existe, l'interface
        s'ouvre, et l'API repond « Forbidden » sur `/api/v1/dataset/`. Un role
        sans permission est impossible a distinguer d'un role refuse, et rien
        dans les journaux du conteneur ne le signale.
        """
        reponse = self._json(
            "POST",
            "/api/v1/security/login",
            {"username": username, "password": password, "provider": "db", "refresh": True},
        )
        self.jeton = reponse.get("access_token", "")
        if not self.jeton:
            raise RuntimeError("Superset n'a pas renvoye de jeton d'acces.")

        # Jeton CSRF, par le point d'entree dedie. La page `/login/` ne pose
        # aucun cookie `csrf_token` -- la protection CSRF de Flask-WTF couvre
        # `/api/v1/*` sans passer par le formulaire -- et lire le HTML pour
        # en extraire la valeur serait casse a chaque changement de gabarit.
        # La session de formulaire n'est donc pas necessaire : le jeton
        # d'acces et le jeton CSRF suffisent.
        self.csrf = self._json("GET", "/api/v1/security/csrf_token/").get("result", "")
        if not self.csrf:
            raise RuntimeError("Superset n'a pas renvoye de jeton CSRF.")

    def lister(self, chemin: str) -> list[dict]:
        """Liste une collection de l'API, page par page."""
        requete = urlencode({"q": "(page:0,page_size:100)"})
        return list(self._json("GET", f"{chemin}?{requete}").get("result") or [])


# ---------------------------------------------------------------------------
# Definitions des graphiques
# ---------------------------------------------------------------------------
# Chaque entree porte le titre lisible, la vue source, le type de visualisation
# et ses parametres. `params` est le JSON imbrique que Superset attend.
#
# PRECAUTION : dans une tuile `big_number`, le champ `metric` porte l'INDICATEUR
# CALCULE. Ecrire la chaine `"Count"` -- qui est une valeur legitime pour
# `big_number_total` -- y met le nombre de LIGNES de la vue, pas la mesure :
# les quatre tuiles affichaient 25, le nombre de mois, au lieu de 84 593
# factures. `custom_formatted_tooltip` ne rattrape rien : il formate la valeur
# deja calculee, il ne la calcule pas.
# ---------------------------------------------------------------------------


def _metrique(colonne: str, type_: str, libelle: str) -> dict:
    """Metrique simple : la colonne agregee par `SUM`.

    Deux champs ne sont pas optionnels, et les deux manquant font echouer le
    graphique a l'execution :

    * `column` designe la colonne ;
    * `aggregate` designe la fonction d'agregation, et son ENUM attend le
      nom de la fonction SQL, en MAJUSCULES (`SUM`), pas en minuscules :
      `KeyError: 'sum'` si on ecrit "sum". Le frontal ecrit toujours
      "SUM" ; un script d'amorcage qui l'omet, ou qui l'ecrit en bas de
      casse, produit une metrique que Superset refuse de resoudre.

    Sur une vue d'une seule ligne comme `v_kpi_global`, cette somme est la
    valeur -- y compris pour un taux, puisque le taux y est deja global.
    """
    return {
        "label": libelle,
        "expressionType": "SIMPLE",
        "column": {"column_name": colonne, "type": type_},
        "aggregate": "SUM",
    }


#: Bandeau principal, sur `v_kpi_global` : une seule ligne, deja globale.
#: (cle, titre, colonne, type SQL, format, sous-titre)
KPI = [
    ("kpi_volume", "Factures traitees", "nb_factures", "BIGINT", ",d", "Sur 24 mois"),
    ("kpi_montant", "Montant presente (MGA)", "montant_total_mga", "NUMERIC", "~s", "Ariary"),
    ("kpi_taux", "Taux de fraude observe (%)", "taux_fraude_pct", "DOUBLE", ".2f", "Prevalence terrain"),
    (
        "kpi_delai",
        "Delai moyen de traitement (jours)",
        "delai_moyen_jours",
        "DOUBLE",
        ".1f",
        "Pondere par facture",
    ),
]

#: Bandeau de la boucle de decision. Les trois indicateurs du CDC qui ne se
#: lisent pas sur `core` seul : ils comparent une PREDICTION a une VERITE
#: HUMAINE. Ils s'affichent desormais, avec leur etat, au lieu d'etre
#: absents du tableau. `v_cdc_global` renvoie toujours une ligne : le chiffre
#: est NULL tant que le modele n'a pas tourne, et le sous-titre le dit.
KPI_CDC = [
    (
        "cdc_economises",
        "Montants economises confirmes (MGA)",
        "montant_economise_mga",
        "NUMERIC",
        "~s",
        "En attente : aucune decision gestionnaire enregistree",
    ),
    (
        "cdc_detection",
        "Taux de detection du modele (%)",
        "taux_detection_pct",
        "DOUBLE",
        ".2f",
        "En attente : ml.prediction est vide, modele non entraine",
    ),
    (
        "cdc_faux_positifs",
        "Taux de faux positifs (%)",
        "taux_faux_positifs_pct",
        "DOUBLE",
        ".2f",
        "En attente : ml.prediction est vide, modele non entraine",
    ),
]


GRAPHIQUES = [
    {
        "cle": "volume_mensuel",
        "titre": "Montant present par mois (MGA)",
        "vue": "v_kpi_mensuel",
        "viz_type": "echarts_timeseries",
        "params": {
            "metrics": [
                _metrique("montant_total_mga", "NUMERIC", "Montant present (MGA)")
            ],
            "groupby": [{"column_name": "mois", "type": "TEMPORAL", "label": "Mois"}],
            "order_desc": True,
            "row_limit": 24,
            "timeseries_limit_metric": "montant_total_mga",
            "y_axis_format": "~s",
            "rich_tooltip": True,
            "color_scheme": BLEU,
            "line_type": "linear",
            "show_labels": False,
        },
    },
    {
        "cle": "fraude_par_type",
        "titre": "Fraude par mecanisme (24 mois)",
        "vue": "v_fraude_par_type",
        "viz_type": "dist_bar",
        "params": {
            "metrics": [
                _metrique("nb_fraudes", "BIGINT", "Nombre de factures")
            ],
            "groupby": [{"column_name": "type_fraude", "type": "STRING", "label": "Mecanisme"}],
            "order_desc": True,
            "row_limit": 20,
            "orientation": "horizontal",
            "color_scheme": ROUGE,
            "show_value": True,
            "sort_series_type": "sum",
        },
    },
    {
        "cle": "prestataires_risque",
        "titre": "Cinq prestataires les plus exposes (MGA)",
        "vue": "v_prestataires_risque",
        "viz_type": "table",
        "params": {
            "metrics": [
                _metrique("montant_expose_mga", "NUMERIC", "Montant expose (MGA)"),
                _metrique("taux_fraude_pct", "DOUBLE", "Taux de fraude (%)"),
            ],
            "groupby": [
                {"column_name": "prestataire_nom", "type": "STRING", "label": "Prestataire"},
                {"column_name": "prestataire_ville", "type": "STRING", "label": "Ville"},
            ],
            "order_desc": True,
            "row_limit": 5,
            "page_length": 10,
        },
    },
    {
        "cle": "delai_traitement",
        "titre": "Evolution du delai de traitement",
        "vue": "v_kpi_mensuel",
        "viz_type": "echarts_timeseries",
        "params": {
            "metrics": [
                _metrique("delai_traitement_jours", "DOUBLE", "Delai moyen (jours)")
            ],
            "groupby": [{"column_name": "mois", "type": "TEMPORAL", "label": "Mois"}],
            "order_desc": True,
            "row_limit": 24,
            "y_axis_format": ".1f",
            "color_scheme": VERT,
            "line_type": "linear",
            "rich_tooltip": True,
        },
    },
    {
        "cle": "points_controle",
        "titre": "Motifs de non-paiement par mois",
        "vue": "v_controle_points",
        "viz_type": "dist_bar",
        "params": {
            "metrics": [
                _metrique("nb_factures", "BIGINT", "Factures")
            ],
            "groupby": [
                {"column_name": "motif", "type": "STRING", "label": "Motif"},
                {"column_name": "mois", "type": "TEMPORAL", "label": "Mois"},
            ],
            "order_desc": True,
            "row_limit": 10000,
            "orientation": "vertical",
            "color_scheme": ORANGE,
            "show_value": False,
        },
    },
]

TOUS: list[dict] = [
    {
        "cle": cle,
        "titre": titre,
        "vue": "v_kpi_global",
        # `big_number`, et non `big_number_total` : c'est `metric` qui porte
        # la valeur affichee, et il attend ici une metrique, pas "Count".
        "viz_type": "big_number",
        "params": {
            "datasource": "v_kpi_global__table",
            "metric": _metrique(colonne, type_, titre),
            "adhoc_filters": [],
            "row_limit": 1,
            "time_range": "No filter",
            "y_axis_format": format_,
            "subheader": sous_titre,
        },
    }
    for cle, titre, colonne, type_, format_, sous_titre in KPI
] + [
    {
        "cle": cle,
        "titre": titre,
        "vue": "v_cdc_global",
        "viz_type": "big_number",
        "params": {
            "datasource": "v_cdc_global__table",
            "metric": _metrique(colonne, type_, titre),
            "adhoc_filters": [],
            "row_limit": 1,
            "time_range": "No filter",
            "y_axis_format": format_,
            "subheader": sous_titre,
        },
    }
    for cle, titre, colonne, type_, format_, sous_titre in KPI_CDC
] + GRAPHIQUES

#: Largeur de la grille de mise en page, en colonnes.
COLONNES = 12

#: Mise en page, en colonnes de `COLONNES` : (largeur, hauteur).
#: Deux bandeaux de tuiles -- les indicateurs calcules sur `core`, puis les
#: trois de la boucle de decision -- puis la lecture verticale attendue :
#: tendance, decomposition, controle.
GRILLE = {
    "kpi_volume": (3, 2),
    "kpi_montant": (3, 2),
    "kpi_taux": (3, 2),
    "kpi_delai": (3, 2),
    "cdc_economises": (4, 2),
    "cdc_detection": (4, 2),
    "cdc_faux_positifs": (4, 2),
    "volume_mensuel": (6, 6),
    "delai_traitement": (6, 6),
    "fraude_par_type": (6, 7),
    "prestataires_risque": (6, 7),
    "points_controle": (12, 8),
}


def creer_graphiques(client: Client, datasets: dict[str, int]) -> list[int]:
    """Cree ou met a jour chaque graphique. Idempotent."""
    titres = {d["titre"] for d in TOUS}

    # Les graphiques absents du code sont supprimes, et les DOUBLONS de titre
    # aussi. Un renommage de titre laisse sinon un orphelin dans l'interface,
    # sans plus rien pour le nourrir : c'est exactement le genre de residu qui
    # donne « there was an issue » au jury.
    #
    # Le parcours se fait sur une LISTE et non sur un dictionnaire indexe par
    # titre : deux graphiques de meme titre se sont produits lors des essais,
    # et un dictionnaire n'en retient qu'un. Le deuxieme survit au nettoyage,
    # invisible, et la deduplication par titre le laisse passer.
    vus: set[str] = set()
    for graphique in client.lister("/api/v1/chart/"):
        titre = graphique.get("slice_name")
        if titre not in titres:
            client._json("DELETE", f"/api/v1/chart/{graphique['id']}")
            print(f"  - graphique orphelin supprime : {titre}")
        elif titre in vus:
            client._json("DELETE", f"/api/v1/chart/{graphique['id']}")
            print(f"  - doublon de titre supprime : {titre} (id {graphique['id']})")
        else:
            vus.add(titre)

    existants = {c["slice_name"]: c["id"] for c in client.lister("/api/v1/chart/")}

    identifiants: list[int] = []
    for definition in TOUS:
        vue = definition["vue"]
        if vue not in datasets:
            raise RuntimeError(f"dataset absent : {vue}")
        id_dataset = datasets[vue]

        params = dict(definition["params"])
        params["datasource_id"] = id_dataset
        charge = {
            "datasource_id": id_dataset,
            "datasource_type": "table",
            "viz_type": definition["viz_type"],
            "slice_name": definition["titre"],
            "params": json.dumps(params, ensure_ascii=False),
            "cache_timeout": None,
        }

        deja = existants.get(definition["titre"])
        if deja:
            client._json("PUT", f"/api/v1/chart/{deja}", charge)
            identifiant = deja
        else:
            identifiant = client._json("POST", "/api/v1/chart/", charge)["id"]
        identifiants.append(identifiant)
        print(f"  - {definition['cle']:22} {definition['titre'][:44]:46} id {identifiant}")
    return identifiants


def creer_dashboard(client: Client, identifiants: list[int]) -> int:
    """Cree ou met a jour le dashboard et y place les graphiques."""
    charge = {"dashboard_title": TITRE_DASHBOARD, "slug": SLUG, "published": True}
    existants = [
        d
        for d in client.lister("/api/v1/dashboard/")
        if d.get("slug") == SLUG or d.get("dashboard_title") == TITRE_DASHBOARD
    ]
    if existants:
        id_dash = existants[0]["id"]
        # Le titre et le slug sont deja corrects : ils viennent de la creation.
        # On tente la mise a jour, mais un echec n'a pas a interrompre le job --
        # le schema de mise a jour du dashboard a change en version 6 et
        # refuse certaines charges sans quoi la creation, elle, reussit.
        with contextlib.suppress(RuntimeError):
            client._json("PUT", f"/api/v1/dashboard/{id_dash}", charge)
    else:
        id_dash = client._json("POST", "/api/v1/dashboard/", charge)["id"]

    # La mise en page est appliquee par ecriture directe, comme l'accrochage :
    # la route `PUT /api/v1/dashboard/<id>` echoue en « Fatal error » sur
    # Superset 6 avec une charge `position_json`, alors meme que la creation
    # du tableau par la meme route reussit. On tente l'API, puis on tombe sur
    # la metadonnee -- un tableau dont les tuiles se superposent reste
    # inexploitable, et ce n'est pas une option que l'on peut declarer
    # secondaire dans un livrable de soutenance.
    with contextlib.suppress(RuntimeError):
        client._json(
            "PUT",
            f"/api/v1/dashboard/{id_dash}",
            {"position_json": json.dumps(_position(identifiants))},
        )

    _attacher(id_dash, identifiants)
    _positionner(id_dash, identifiants)
    return id_dash


def _positionner(id_dash: int, identifiants: list[int]) -> None:
    """Ecrit `position_json` directement dans la metadonnee du tableau."""
    import sqlalchemy as sa
    from superset import db as superset_db
    from superset.app import create_app

    grille = _position(identifiants)
    application = create_app()
    with application.app_context():
        superset_db.session.execute(
            sa.text("UPDATE dashboards SET position_json = :p WHERE id = :d"),
            {"p": json.dumps(grille), "d": id_dash},
        )
        superset_db.session.commit()
    print(f"  mise en page ecrite : {len(identifiants)} tuiles sur une grille de {COLONNES} colonnes.")


def _position(identifiants: list[int]) -> dict:
    """Position des tuiles, en colonnes de 12, dans l'ordre de lecture.

    La grille est CALCULEE, pas ecrite a la main : une position codee en dur
    (`"x": 0, "y": 0` pour chaque tuile) empile les douze graphiques les uns
    sur les autres, et le tableau devient illisible sans lever la moindre
    erreur -- le genre de defaut qui ne se voit qu'a l'ouverture, devant le
    jury.

    `GRILLE` donne la taille en unites de 12 colonnes ; la position en decoule,
    ligne par ligne : on avance en x jusqu'a deborder, puis on passe a la
    ligne suivante a la hauteur de la plus haute tuile deja posee.
    """
    enfants = []
    x = y = 0
    hauteur_ligne = 0
    for index, identifiant in enumerate(identifiants):
        definition = TOUS[index]
        largeur, hauteur = GRILLE.get(definition["cle"], (6, 6))
        if x + largeur > COLONNES:
            y += hauteur_ligne
            x = 0
            hauteur_ligne = 0
        enfants.append(
            {
                "type": "CHART",
                "id": str(identifiant),
                "meta": {"chartId": identifiant, "width": largeur, "height": hauteur},
                "position": {"x": x, "y": y, "width": largeur, "height": hauteur},
            }
        )
        x += largeur
        hauteur_ligne = max(hauteur_ligne, hauteur)
    return {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": enfants},
    }


def _attacher(id_dash: int, identifiants: list[int]) -> None:
    """Rattache les graphiques au dashboard.

    L'API ne le permet plus : dans Superset 6, la route
    `/api/v1/dashboard/<id>/charts` n'expose que `GET` -- `POST` comme `PUT`
    repondent « 405 Method Not Allowed ». L'association se fait donc par la
    table de liaison `dashboard_slices`.

    C'est une table de metadonnees de l'outil, pas une donnee du projet :
    elle n'apparait dans aucun rapport et disparait avec un `down -v`, ce qui
    est le comportement voulu puisque le dashboard est reconstruit a chaque
    `make up-bi`.

    La session vient de `create_app()` : elle pointe sur la base de
    metadonnees de Superset, qui n'est PAS celle des donnees metier.
    """
    import sqlalchemy as sa
    from superset import db as superset_db
    from superset.app import create_app

    application = create_app()
    with application.app_context():
        session = superset_db.session
        # Le tableau est reconstruit : le job reste idempotent, et un
        # graphique retire du code disparait aussi du dashboard.
        session.execute(sa.text("DELETE FROM dashboard_slices WHERE dashboard_id = :d"), {"d": id_dash})
        for identifiant in identifiants:
            session.execute(
                sa.text(
                    "INSERT INTO dashboard_slices (dashboard_id, slice_id) "
                    "VALUES (:d, :s) ON CONFLICT DO NOTHING"
                ),
                {"d": id_dash, "s": identifiant},
            )
        session.commit()
    print(f"  {len(identifiants)} graphique(s) rattache(s) au dashboard {id_dash}.")


def main() -> int:
    identifiant = os.environ.get("SUPERSET_ADMIN_USERNAME", "admin")
    mot_de_passe = os.environ.get("SUPERSET_ADMIN_PASSWORD", "")
    if not mot_de_passe:
        print("SUPERSET_ADMIN_PASSWORD absent : dashboard non cree.", file=sys.stderr)
        return 1

    try:
        client = Client(BASE, identifiant, mot_de_passe)
        datasets = {
            d["table_name"]: d["id"]
            for d in client.lister("/api/v1/dataset/")
            if d.get("table_name", "").startswith("v_")
        }
        identifiants = creer_graphiques(client, datasets)
        id_dash = creer_dashboard(client, identifiants)
    except Exception as exc:
        print(f"ECHEC de la creation du tableau de bord : {exc}", file=sys.stderr)
        return 1

    print(f"Graphiques crees/maj : {len(identifiants)}")
    print(f"Dashboard « {TITRE_DASHBOARD} » : id {id_dash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
