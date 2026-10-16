"""Verifie que chaque graphique du dashboard RENDS une requete reussie.

Recette de la Phase 7 : « chaque graphique doit s'afficher sans erreur ».
Tant que cette verification n'existe pas, rien ne distingue un tableau qui
fonctionne d'un tableau dont les neuf tuiles affichent « there was an
issue » -- et c'est exactement ce qui s'etait produit.

Trois pieges de l'API `/api/v1/chart/data` de Superset 6, tous则以
l'execution :

  1. le parametre `q` des listes est en RISON, pas en texte libre ;
  2. le jeton CSRF est exige EN PLUS du jeton d'acces ;
  3. l'objet de requete est PLAT, et la colonne de regroupement s'appelle
     `columns`, pas `groupby` : `groupby` est la forme du `form_data`, que le
     frontal convertit. Envoyee telle quelle, elle n'est pas lue et Superset
     repond « Error: Empty query? ».

Ce fichier est une recette de recette, pas un test de CI : il demarre un
parcours d'identification a chaque execution.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = os.environ.get("SUPERSET_URL", "http://localhost:8088")


def _appel(methode, chemin, charge=None, jeton="", csrf=""):
    entetes = {"Content-Type": "application/json", "Accept": "application/json"}
    if jeton:
        entetes["Authorization"] = f"Bearer {jeton}"
    if csrf:
        entetes["X-CSRFToken"] = csrf
    requete = urllib.request.Request(
        f"{BASE}{chemin}",
        data=json.dumps(charge).encode() if charge is not None else None,
        method=methode,
        headers=entetes,
    )
    try:
        with urllib.request.urlopen(requete, timeout=90) as reponse:
            brut = reponse.read()
            return reponse.status, (json.loads(brut) if brut else {})
    except urllib.error.HTTPError as erreur:
        return erreur.code, {"_err": erreur.read().decode()[:400]}
    except OSError as erreur:
        return 0, {"_err": str(erreur)}


def _objet_requete(viz_type, params):
    """Traduit un `form_data` en objet de requeteAccepted par l'API."""
    series = viz_type == "echarts_timeseries"
    requete = {
        "filters": params.get("adhoc_filters") or [],
        "extras": params.get("applied_time_extras") or {},
        "row_limit": params.get("row_limit") or 10000,
        "row_offset": 0,
        "order_desc": bool(params.get("order_desc")),
        "is_timeseries": series,
    }
    # `metric` (tuile) ou `metrics` (graphe) : la requete n'a que `metrics`.
    if isinstance(params.get("metric"), dict):
        requete["metrics"] = [params["metric"]]
    else:
        requete["metrics"] = params.get("metrics") or []
    # Le regroupement s'appelle `columns` cote requete, `groupby` cote
    # `form_data`. C'est la confusion qui faisait echouer la recette.
    requete["columns"] = [
        colonne["column_name"] if isinstance(colonne, dict) else colonne
        for colonne in params.get("groupby") or []
    ]
    # Une serie temporelle a besoin de sa colonne de temps : le frontal la
    # deduit du regroupement, l'API ne le fait pas et refuse alors
    # « Datetime column not provided ».
    if series and requete["columns"]:
        requete["granularity"] = params.get("granularity_sqla") or requete["columns"][0]
    return requete


def main() -> int:
    mot_de_passe = ""
    for ligne in Path(".env").read_text(encoding="utf-8").splitlines():
        if ligne.startswith("SUPERSET_ADMIN_PASSWORD="):
            mot_de_passe = ligne.split("=", 1)[1].strip()
    if not mot_de_passe:
        print("  SUPERSET_ADMIN_PASSWORD introuvable dans .env")
        return 2

    statut, rep = _appel(
        "POST",
        "/api/v1/security/login",
        {"username": "admin", "password": mot_de_passe, "provider": "db"},
    )
    jeton = rep.get("access_token", "")
    if not jeton:
        print(f"  authentification impossible : HTTP {statut} {rep.get('_err', '')[:120]}")
        return 2
    _, rep = _appel("GET", "/api/v1/security/csrf_token/", None, jeton)
    csrf = rep.get("result", "")

    rison = urllib.parse.quote("(page:0,page_size:100)", safe="()")
    _, rep = _appel("GET", f"/api/v1/chart/?q={rison}", None, jeton)
    graphiques = rep.get("result") or []

    echecs = []
    print(f"  {len(graphiques)} graphiques verifies par execution reelle :")
    for graphique in graphiques:
        viz_type = graphique.get("viz_type")
        params = graphique.get("params")
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except json.JSONDecodeError:
                params = {}
        params = params or {}
        id_dataset = graphique.get("datasource_id")

        charge = {
            "datasource": {"id": id_dataset, "type": "table"},
            "queries": [
                {
                    "viz_type": viz_type,
                    "granularity": params.get("granularity_sqla"),
                    "granularity_sqla": params.get("granularity_sqla"),
                    "time_grain_sqla": params.get("time_grain_sqla") or "P1M",
                    "result_type": "full",
                    **_objet_requete(viz_type, params),
                }
            ],
            "form_data": params,
            "result_type": "full",
            "result_format": "json",
        }
        statut, rep = _appel("POST", "/api/v1/chart/data", charge, jeton, csrf)
        resultat = (rep.get("result") or [{}])[0]
        donnees = resultat.get("data") or []
        # `query` est le SQL emis, en chaine : c'est lui qui dit reellement
        # quelle agregation la base a appliquee, ce que le titre du graphique
        # ne garantit pas.
        requete_sql = resultat.get("query") or ""
        if not isinstance(requete_sql, str):
            requete_sql = str(requete_sql.get("sql", ""))

        if statut == 200:
            print(f"    {graphique['slice_name'][:44]:46} HTTP 200  {len(donnees):6d} ligne(s)")
        else:
            detail = (rep.get("_err") or rep.get("message") or "")[:110]
            echecs.append(graphique["slice_name"])
            print(f"    {graphique['slice_name'][:44]:46} HTTP {statut}  ECHEC {detail}")
            if requete_sql:
                print(f"      SQL : {requete_sql[:150]}")

    if echecs:
        print(f"\n  {len(echecs)} graphique(s) en erreur : {', '.join(echecs)}")
        return 1
    print("\n  Tous les graphiques rendent une requete reussie.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
