"""Verifie que le tableau de bord s'affiche REELLEMENT dans le navigateur.

Recette de la Phase 7 : « chaque graphique doit s'afficher sans erreur ».

Ce script interroge Superset comme le fait le navigateur, et non comme il est
commode de le faire depuis un script. La difference a coute trois allers-retours
et un tableau entier qui n'affichait rien.

Ce qu'une version precedente faisait de travers
-----------------------------------------------
Elle construisait la charge de requete a partir des parametres du graphique,
et CONVERTISSait au passage les colonnes de regroupement en chaines. Les
parametres stockes, eux, contenaient des dictionnaires.

Elle validait donc une charge transformee, et non celle que le navigateur
lit. Elle annoncait « 12/12 » sur douze graphiques qui affichaient tous
« there was an issue ». Une verification qui normalise ce qu'elle verifie ne
verifie rien.

Trois controles, dont deux que l'ancienne version ne faisait pas :

  1. le parcours du navigateur, a l'identique :
     `POST /api/v1/chart/data?form_data={"slice_id": N}` ;
  2. `GET /api/v1/dashboard/<slug>/datasets`, qui repondait 422
     « unhashable type: 'dict' » et cassait la page entiere ;
  3. la structure de la mise en page, ou un enfant imbrique au lieu d'un
     identifiant rend le tableau vide sans lever d'erreur.

Pieges de l'API, tous constates a l'execution : le parametre `q` des listes
est en RISON ; le jeton CSRF est exige en plus du jeton d'acces ; et le
resultat de `/chart/data` porte `query` en CHAINE, pas en objet.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = os.environ.get("SUPERSET_URL", "http://localhost:8088")
TABLEAU = os.environ.get("SUPERSET_DASHBOARD", "pilotage-mensuel")


def _appel(methode, chemin, charge=None, jeton="", csrf="", brut=False):
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
        with urllib.request.urlopen(requete, timeout=120) as reponse:
            corps = reponse.read()
            return reponse.status, (json.loads(corps) if corps else {})
    except urllib.error.HTTPError as erreur:
        return erreur.code, {"_err": erreur.read().decode()[:400]}
    except OSError as erreur:
        return 0, {"_err": str(erreur)}


def _corps_requete(viz_type: str, params: dict, id_dataset: int) -> dict:
    """Corps de requete, construit SANS transformer les valeurs.

    `groupby` (forme du form_data) devient `columns` (forme de la requete) :
    c'est un renommage structurel, celui que fait le frontal. Les VALEURS, en
    revanche, sont recopiees telles quelles.

    C'est precisement ce que faisait de travers la version precedente : elle
    convertissait les colonnes en chaines, et validait donc une charge que le
    navigateur n'envoie jamais. Une verification qui normalise ce qu'elle
    verifie ne verifie rien.
    """
    serie = viz_type == "echarts_timeseries"
    colonnes = list(params.get("groupby") or [])
    metriques = params.get("metrics") or []
    if isinstance(params.get("metric"), dict):
        metriques = [params["metric"]]

    # La granularite est un NOM de colonne : le frontal l'extrait du
    # regroupement. Ce champ n'est pas celui que l'on veut tester -- le
    # regroupement lui-meme reste intact dans `columns`.
    premiere = colonnes[0] if colonnes else None
    nom = premiere.get("column_name") if isinstance(premiere, dict) else premiere

    requete = {
        "metrics": metriques,
        "columns": colonnes,
        "filters": params.get("adhoc_filters") or [],
        "extras": params.get("applied_time_extras") or {},
        "row_limit": params.get("row_limit") or 10000,
        "row_offset": 0,
        "order_desc": bool(params.get("order_desc")),
        "is_timeseries": serie,
        "result_type": "full",
    }
    if serie and nom:
        requete["granularity"] = nom
    return {
        "datasource": {"id": id_dataset, "type": "table"},
        "queries": [requete],
        "form_data": params,
        "result_type": "full",
        "result_format": "json",
    }


def _verifier_mise_en_page(jeton: str) -> list[str]:
    """Controle structurel : les enfants doivent etre des identifiants.

    Un arbre imbrique -- l'erreur commise -- ne leve aucune erreur a
    l'enregistrement. Le frontal, lui, cherche `position[enfant]` et ne trouve
    rien : le tableau s'ouvre vide.
    """
    statut, rep = _appel("GET", f"/api/v1/dashboard/{TABLEAU}", None, jeton)
    if statut != 200:
        return [f"dashboard illisible : HTTP {statut} {(rep.get('_err') or '')[:120]}"]
    resultat = rep.get("result") or {}
    brut = resultat.get("position_json") or "{}"
    plan = json.loads(brut) if isinstance(brut, str) else brut
    if not isinstance(plan, dict) or not plan:
        return ["mise en page absente : le tableau s'ouvrira sans tuiles"]

    problemes: list[str] = []
    if plan.get("DASHBOARD_VERSION_KEY") != "v2":
        problemes.append("DASHBOARD_VERSION_KEY devrait valoir 'v2'")
    if "ROOT_ID" not in plan:
        problemes.append("ROOT_ID absent")

    graphiques = 0
    for cle, noeud in plan.items():
        if cle == "DASHBOARD_VERSION_KEY":
            continue
        if not isinstance(noeud, dict):
            problemes.append(f"{cle} n'est pas un noeud")
            continue
        for enfant in noeud.get("children") or []:
            if not isinstance(enfant, str):
                # C'est LA faute : un enfant imbrique au lieu d'un identifiant.
                problemes.append(
                    f"{cle} contient un enfant {type(enfant).__name__}, pas un identifiant"
                )
            elif enfant not in plan:
                problemes.append(f"{cle} reference {enfant}, absent de la carte")
        if noeud.get("type") == "CHART":
            graphiques += 1
            if not (noeud.get("meta") or {}).get("chartId"):
                problemes.append(f"{cle} n'a pas de chartId")
    if not graphiques:
        problemes.append("aucune tuile CHART dans la mise en page")
    print(
        f"    mise en page : {len(plan)} noeuds, {graphiques} tuiles, version {plan.get('DASHBOARD_VERSION_KEY')}"
    )
    return problemes


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
        print(f"  authentification impossible : HTTP {statut} {(rep.get('_err') or '')[:120]}")
        return 2
    _, rep = _appel("GET", "/api/v1/security/csrf_token/", None, jeton)
    csrf = rep.get("result", "")

    echecs: list[str] = []

    # 1. La page du tableau charge ses sources : c'est cet appel qui repondait
    #    422 et cassait l'affichage entier.
    statut, rep = _appel("GET", f"/api/v1/dashboard/{TABLEAU}/datasets", None, jeton)
    if statut == 200:
        print(f"    datasets du dashboard : HTTP 200, {len(rep.get('result') or [])} source(s)")
    else:
        echecs.append("datasets du dashboard")
        print(f"    datasets du dashboard : HTTP {statut} {(rep.get('_err') or '')[:140]}")

    # 2. La mise en page.
    for probleme in _verifier_mise_en_page(jeton):
        echecs.append(probleme)
        print(f"    mise en page : {probleme}")

    # 3. Chaque graphique, par le parcours du navigateur.
    rison = urllib.parse.quote("(page:0,page_size:100)", safe="()")
    _, rep = _appel("GET", f"/api/v1/chart/?q={rison}", None, jeton)
    graphiques = rep.get("result") or []
    print(f"\n    {len(graphiques)} graphiques, requete reelle de chacun :")
    for graphique in graphiques:
        identifiant = graphique["id"]
        # Le parametre d'URL `form_data` est celui du navigateur -- il sert a
        # la journalisation et a la cle de cache. Le corps, lui, porte la
        # requete, et ses valeurs viennent des parametres STOCKES, recopiees
        # sans transformation.
        params = graphique.get("params")
        if isinstance(params, str):
            params = json.loads(params or "{}")
        params = params or {}
        form_data = urllib.parse.quote(json.dumps({"slice_id": identifiant}))
        corps = _corps_requete(graphique.get("viz_type") or "", params, graphique["datasource_id"])
        statut, rep = _appel(
            "POST", f"/api/v1/chart/data?form_data={form_data}", corps, jeton, csrf
        )
        resultat = (rep.get("result") or [{}])[0] if isinstance(rep.get("result"), list) else {}
        donnees = resultat.get("data") or []
        nom = graphique["slice_name"][:44]
        if statut == 200:
            valeur = ""
            if len(donnees) == 1:
                ligne = donnees[0]
                colonnes = [
                    v
                    for k, v in ligne.items()
                    if k not in ("__timestamp",) and not k.startswith("_")
                ]
                valeur = f"  ->  {colonnes[0]}" if colonnes else ""
            print(f"    {nom:46} HTTP 200  {len(donnees):6d} ligne(s){valeur}")
        else:
            detail = (rep.get("_err") or rep.get("message") or "")[:150]
            echecs.append(graphique["slice_name"])
            print(f"    {nom:46} HTTP {statut}  ECHEC {detail}")

    if echecs:
        print(f"\n  {len(echecs)} probleme(s) : {', '.join(echecs[:6])}")
        return 1
    print("\n  Le tableau de bord s'affiche : requetes, sources et mise en page.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
