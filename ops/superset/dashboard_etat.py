"""Etat du tableau de bord Superset : archive, restauration, requete navigateur.

Le modele
---------
Jusqu'ici, les douze tuiles du tableau etaient decrites en Python, et chaque
description etait un bug en attente : une fois sur deux, la forme des
`form_data` ne correspondait pas a ce que le plugin v6 attend, et le
navigateur affichait « Data error » la ou la verification annoncait 200.

Le modele change : **l'interface ecrit, le depot archive, le code restaure**.

* l'interface Superset est l'outil de creation : on y fait les tuiles, avec
  les reglages de l'interface, qui sont coerents par construction ;
* `make bi-export` capture l'etat vivant -- les `form_data` des tuiles, la
  mise en page, les filtres natifs -- dans un fichier JSON versionne ;
* `make bi-dashboard` rejoue cet etat : le tableau est reconstruit a partir
  du depot, quel que soit ce qui a ete fait dans l'interface entre-temps ;
* `verifier_graphiques.py` compare le vivant a l'archive, et interroge chaque
  tuile avec la requete que le NAVIGATEUR construirait.

Ce module porte les trois briques communes : le client HTTP, le constructeur
de requete, et l'archive.

La requete navigateur
---------------------
C'est la piece qui manquait. Un verificateur qui construit la requete a la
main verifie une fiction : il envoie `columns = groupby` alors que le plugin
v6 envoie `columns = [X-Axis] + groupby`, avec la colonne temporelle
transformee en colonne adhoc `BASE_AXIS` (le grain de temps s'y applique).
Les deux formes ne sont pas la meme requete, et seule la seconde est celle
du navigateur.

Trois regles du frontal, lues dans le code de Superset 6.1 :

1. `groupby` est un ALIAS de `columns` (`extractQueryFields`) ;
2. quand `x_axis` est pose, la colonne temporelle devient une colonne adhoc
   `BASE_AXIS` portant le grain (`normalizeTimeColumn`) ;
3. quand `x_axis` est ABSENT, le frontal travaille en « serie temporelle »
   (`is_timeseries: true`) : la colonne de temps s'ajoute alors aux colonnes,
   et une colonne temporelle deja presente dans `groupby` donne deux colonnes
   du meme nom -- refus par le serveur : « Duplicate column/metric labels ».
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

BASE = os.environ.get("SUPERSET_URL", "http://localhost:8088")
NOM_CONNEXION = "PrediCare (lecture seule)"

#: Les types de graphique enregistres dans Superset 6.1 (`VizType.ts`).
#:
#: Un type absent de cette liste n'a aucun plugin : le navigateur ne
#: construit aucune requete et affiche « Data error: Empty query ». C'est ce
#: qui est arrive aux deux graphiques en barres `dist_bar`, type supprime en
#: Superset 6 au profit de `echarts_timeseries_bar`.
VIZ_TYPES_V6: frozenset[str] = frozenset(
    {
        "echarts_area",
        "echarts_timeseries",
        "echarts_timeseries_bar",
        "echarts_timeseries_line",
        "echarts_timeseries_scatter",
        "echarts_timeseries_smooth",
        "echarts_timeseries_step",
        "big_number",
        "big_number_total",
        "pop_kpi",
        "box_plot",
        "bubble_v2",
        "bullet",
        "cal_heatmap",
        "cartodiagram",
        "chord",
        "compare",
        "country_map",
        "funnel",
        "gantt_chart",
        "gauge_chart",
        "graph_chart",
        "handlebars",
        "heatmap_v2",
        "histogram_v2",
        "horizon",
        "bubble",
        "mixed_timeseries",
        "paired_ttest",
        "para",
        "partition",
        "pie",
        "pivot_table_v2",
        "radar",
        "rose",
        "sankey_v2",
        "table",
        "ag-grid-table",
        "time_pivot",
        "time_table",
        "tree_chart",
        "treemap_v2",
        "waterfall",
        "word_cloud",
        "world_map",
    }
)


class Client:
    """Client minimal de l'API Superset, authentifie par jeton."""

    def __init__(self, base: str, username: str, password: str) -> None:
        self.base = base.rstrip("/")
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
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
            detail = exc.read().decode(errors="replace")[:300]
            raise RuntimeError(f"{methode} {chemin} -> HTTP {exc.code} : {detail}") from exc

    def _connecter(self, username: str, password: str) -> None:
        reponse = self._json(
            "POST",
            "/api/v1/security/login",
            {"username": username, "password": password, "provider": "db", "refresh": True},
        )
        self.jeton = reponse.get("access_token", "")
        if not self.jeton:
            raise RuntimeError("Superset n'a pas renvoye de jeton d'acces.")
        self.csrf = self._json("GET", "/api/v1/security/csrf_token/").get("result", "")
        if not self.csrf:
            raise RuntimeError("Superset n'a pas renvoye de jeton CSRF.")

    def lister(self, chemin: str) -> list[dict]:
        """Liste une collection de l'API, page par page."""
        requete = urlencode({"q": "(page:0,page_size:100)"})
        return list(self._json("GET", f"{chemin}?{requete}").get("result") or [])


# ---------------------------------------------------------------------------
# Requete navigateur
# ---------------------------------------------------------------------------
def _metriques(params: dict) -> list[dict]:
    metriques = list(params.get("metrics") or [])
    if isinstance(params.get("metric"), dict):
        metriques = [params["metric"]]
    return metriques


def _filtres(params: dict) -> list[dict]:
    """Convertit les filtres adhoc en filtres de requete.

    Le frontal envoie `{col, op, val}` ; le serveur refuse la forme
    `{clause, subject, operator, comparator}` (« Missing data for required
    field »). C'est la forme que le navigateur produit.
    """
    filtres: list[dict] = []
    for filtre in params.get("adhoc_filters") or []:
        if not isinstance(filtre, dict) or "subject" not in filtre:
            continue
        filtres.append(
            {
                "col": filtre.get("subject"),
                "op": filtre.get("operator"),
                "val": filtre.get("comparator"),
            }
        )
    return filtres


def requete_navigateur(viz_type: str, params: dict) -> dict:
    """Construit la requete que le navigateur construirait pour cette tuile.

    Les regles viennent du frontal de Superset 6.1, lues dans le code :
    `extractQueryFields` (alias `groupby` -> `columns`), le `buildQuery` de
    chaque plugin, et `normalizeTimeColumn` (colonne temporelle en
    `BASE_AXIS` quand X-Axis est pose).
    """
    params = dict(params or {})
    groupby = list(params.get("groupby") or [])
    metriques = _metriques(params)
    x_axis = params.get("x_axis")
    grain = params.get("time_grain_sqla")

    colonnes: list[Any] = []
    serie_temporelle = False

    if viz_type.startswith("echarts_timeseries"):
        if x_axis:
            # X-Axis pose : la colonne temporelle devient une colonne adhoc
            # BASE_AXIS, c'est elle qui porte le grain de temps.
            colonnes.append(
                {
                    "timeGrain": grain,
                    "columnType": "BASE_AXIS",
                    "sqlExpression": x_axis,
                    "label": x_axis,
                    "expressionType": "SQL",
                    "isColumnReference": True,
                }
            )
            colonnes += [g for g in groupby if g != x_axis]
        else:
            # Pas de X-Axis : le frontal travaille en serie temporelle et la
            # colonne de temps S'AJOUTE aux colonnes. Une colonne temporelle
            # deja dans `groupby` donne alors deux colonnes du meme nom, et le
            # serveur refuse. On reproduit ce comportement fidelement : c'est
            # lui qui doit etre detecte.
            colonnes = list(groupby)
            if params.get("granularity_sqla"):
                colonnes.append(params["granularity_sqla"])
            serie_temporelle = True
    else:
        colonnes = list(groupby)

    requete: dict[str, Any] = {
        "metrics": metriques,
        "columns": colonnes,
        "filters": _filtres(params),
        "row_limit": params.get("row_limit") if params.get("row_limit") is not None else 10000,
        "row_offset": 0,
        "order_desc": bool(params.get("order_desc")),
        "time_range": params.get("time_range") or "No filter",
        "result_type": "full",
    }
    if serie_temporelle:
        requete["is_timeseries"] = True
        if params.get("granularity_sqla"):
            requete["granularity"] = params["granularity_sqla"]
        if grain:
            requete["time_grain_sqla"] = grain

    # Le tri : la table classe sur la metrique de tri, sinon sur la premiere.
    # Le serveur attend un LIBELLE, pas un objet metrique.
    limite = params.get("timeseries_limit_metric")
    ascendant = not bool(params.get("order_desc"))
    if isinstance(limite, dict) and metriques:
        requete["orderby"] = [[limite.get("label"), ascendant]]
    elif metriques and viz_type == "table":
        requete["orderby"] = [[_libelle(metriques[0]), ascendant]]
    return requete


def _libelle(metrique: Any) -> str:
    if isinstance(metrique, dict):
        return str(metrique.get("label") or "")
    return str(metrique)


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------
def chemin_archive(slug: str) -> Path:
    """Chemin du fichier d'archive, dans le depot."""
    base = os.environ.get("SUPERSET_ETAT_DIR", "/app/dashboards")
    return Path(base) / f"{slug}.json"


def _datasets(client: Client) -> dict[int, str]:
    """Table dataset id -> nom de vue (le nom est stable, l'identifiant non)."""
    return {
        int(dataset["id"]): dataset.get("table_name") or ""
        for dataset in client.lister("/api/v1/dataset/")
    }


def exporter(client: Client, chemin: Path, slug: str) -> dict:
    """Capture l'etat vivant du tableau et l'ecrit dans l'archive."""
    tableau = client._json("GET", f"/api/v1/dashboard/{slug}").get("result") or {}
    if not tableau:
        raise RuntimeError(f"tableau « {slug} » introuvable dans Superset.")

    position = tableau.get("position_json") or "{}"
    position = json.loads(position) if isinstance(position, str) else position
    metadonnees = tableau.get("json_metadata") or {}
    if isinstance(metadonnees, str):
        metadonnees = json.loads(metadonnees or "{}")

    noms = _datasets(client)
    graphiques = {g["id"]: g for g in client.lister("/api/v1/chart/")}

    # L'ordre de lecture est celui de la mise en page : les noeuds ROW
    # portent les tuiles, dans l'ordre ou elles se lisent.
    tuiles: list[dict] = []
    for _cle, noeud in position.items():
        if not isinstance(noeud, dict) or noeud.get("type") != "CHART":
            continue
        identifiant = int((noeud.get("meta") or {}).get("chartId") or 0)
        graphique = graphiques.get(identifiant)
        if graphique is None:
            continue
        params = graphique.get("params")
        if isinstance(params, str):
            params = json.loads(params or "{}")
        tuiles.append(
            {
                "id": identifiant,
                "titre": graphique.get("slice_name"),
                "viz_type": graphique.get("viz_type"),
                "vue": noms.get(int(graphique.get("datasource_id") or 0), ""),
                "params": params or {},
                "cache_timeout": graphique.get("cache_timeout"),
            }
        )

    etat = {
        "version": 1,
        "slug": slug,
        "titre": tableau.get("dashboard_title"),
        "exporte_le": None,
        "tuiles": tuiles,
        "position_json": position,
        "json_metadata": metadonnees,
    }
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(etat, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return etat


def remapper_position(position: dict, correspondance: dict[int, int]) -> dict:
    """Reecrit la mise en page avec les NOUVEAUX identifiants de tuiles.

    Les noeuds sont nommes `CHART-<id>` : si une tuile est recree, son
    identifiant change et la mise en page pointerait sur une tuile qui
    n'existe plus. Le remappage se fait sur le titre, seul identifiant stable.
    """
    par_ancien = dict(correspondance.items())
    nouveau: dict[str, Any] = {}
    for cle, noeud in position.items():
        if not isinstance(noeud, dict):
            nouveau[cle] = noeud
            continue
        if cle.startswith("CHART-") and noeud.get("type") == "CHART":
            ancien = int(cle.split("-", 1)[1])
            cible = par_ancien.get(ancien)
            if cible is None:
                continue
            copie = json.loads(json.dumps(noeud))
            copie["id"] = f"CHART-{cible}"
            copie["meta"] = {**(copie.get("meta") or {}), "chartId": cible}
            nouveau[f"CHART-{cible}"] = copie
            continue
        copie = json.loads(json.dumps(noeud))
        for cle_enfant, valeur in (
            ("children", copie.get("children")),
            ("parents", copie.get("parents")),
        ):
            if isinstance(valeur, list):
                copie[cle_enfant] = [
                    f"CHART-{par_ancien[int(v.split('-', 1)[1])]}"
                    if v.startswith("CHART-") and int(v.split("-", 1)[1]) in par_ancien
                    else v
                    for v in valeur
                ]
        nouveau[cle] = copie
    return nouveau


def appliquer(client: Client, chemin: Path, slug: str) -> list[int]:
    """Rejoue l'etat archive : tuiles, puis mise en page, puis metadonnees.

    Rend les identifiants des tuiles appliquees, dans l'ordre de l'archive.
    """
    if not chemin.exists():
        raise RuntimeError(f"Aucune archive ({chemin}) : rien a reappliquer.")
    etat = json.loads(chemin.read_text(encoding="utf-8"))

    datasets = {
        dataset.get("table_name"): int(dataset["id"])
        for dataset in client.lister("/api/v1/dataset/")
    }
    existants = {g.get("slice_name"): g for g in client.lister("/api/v1/chart/")}

    correspondance: dict[int, int] = {}
    for tuile in etat.get("tuiles") or []:
        id_dataset = datasets.get(tuile.get("vue"))
        if id_dataset is None:
            raise RuntimeError(f"dataset « {tuile.get('vue')} » introuvable dans Superset.")
        charge = {
            "datasource_id": id_dataset,
            "datasource_type": "table",
            "viz_type": tuile["viz_type"],
            "slice_name": tuile["titre"],
            "params": json.dumps(tuile.get("params") or {}, ensure_ascii=False),
            "cache_timeout": tuile.get("cache_timeout"),
        }
        deja = existants.get(tuile["titre"])
        if deja is not None:
            client._json("PUT", f"/api/v1/chart/{deja['id']}", charge)
            correspondance[tuile["id"]] = int(deja["id"])
        else:
            cree = client._json("POST", "/api/v1/chart/", charge)
            correspondance[tuile["id"]] = int(cree["id"])
        print(f"  - {tuile['titre'][:48]:50} {tuile['viz_type']}")

    tableau = client._json("GET", f"/api/v1/dashboard/{slug}").get("result") or {}
    id_tableau = tableau.get("id")
    if id_tableau is None:
        raise RuntimeError(f"tableau « {slug} » introuvable dans Superset.")

    position = remapper_position(etat.get("position_json") or {}, correspondance)
    client._json(
        "PUT",
        f"/api/v1/dashboard/{id_tableau}",
        {"position_json": json.dumps(position, ensure_ascii=False)},
    )
    metadonnees = etat.get("json_metadata") or {}
    if metadonnees:
        client._json(
            "PUT",
            f"/api/v1/dashboard/{id_tableau}",
            {"json_metadata": json.dumps(metadonnees, ensure_ascii=False)},
        )
    return list(correspondance.values())
