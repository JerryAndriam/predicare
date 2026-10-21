"""Verifie que le tableau de bord s'affiche REELLEMENT dans le navigateur.

Trois controles, tous faits sur l'etat VIVANT :

1. **le type de graphique existe** : un `viz_type` absent du registre de
   Superset 6 n'a aucun plugin, et le navigateur affiche « Data error: Empty
   query » sans jamais envoyer de requete ;
2. **la requete aboutit** : la charge envoyee est celle que le navigateur
   construirait -- meme forme de colonnes, meme colonne de temps, meme
   conversion des filtres. Le serveur fait alors ses propres controles
   (libelles dupliques, requete vide) ;
3. **le tableau est celui du depot** : les `form_data` des tuiles, la mise en
   page et les metadonnees sont compares a l'archive versionnee.

La version precedente de ce verificateur construisait la requete A LA MAIN :
elle envoyait `columns = groupby` alors que le frontal de Superset 6 envoie
`columns = [X-Axis] + groupby`, avec la colonne temporelle transformee en
colonne adhoc `BASE_AXIS`. Elle validait donc 200 des tuiles que le
navigateur recevait en 400. Une verification qui verifie autre chose que ce
que fait le navigateur ne verifie rien.

Pieges de l'API, tous constates a l'execution : le parametre `q` des
listes est en RISON ; le jeton CSRF est exige en plus du jeton d'acces ;
et le resultat de `/chart/data` porte `query` en CHAINE, pas en objet.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dashboard_etat import VIZ_TYPES_V6, requete_navigateur

BASE = os.environ.get("SUPERSET_URL", "http://localhost:8088")
TABLEAU = os.environ.get("SUPERSET_DASHBOARD", "pilotage-mensuel")
#: L'archive est dans le depot quand le verificateur tourne sur l'hote, et
#: dans l'image quand il tourne dans le conteneur.
DOSSIER_ETAT = os.environ.get(
    "SUPERSET_ETAT_DIR", str(Path(__file__).resolve().parent / "dashboards")
)


def _appel(
    methode: str, chemin: str, charge: dict | None = None, jeton: str = "", csrf: str = ""
) -> tuple[int, Any]:
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


def _verifier_mise_en_page(position: dict) -> list[str]:
    """Controle structurel : les enfants doivent etre des identifiants.

    Un arbre imbrique -- l'erreur commise -- ne leve aucune erreur a
    l'enregistrement. Le frontal, lui, cherche `position[enfant]` et ne trouve
    rien : le tableau s'ouvre vide.
    """
    problemes: list[str] = []
    if position.get("DASHBOARD_VERSION_KEY") != "v2":
        problemes.append("DASHBOARD_VERSION_KEY devrait valoir 'v2'")
    if "ROOT_ID" not in position:
        problemes.append("ROOT_ID absent")

    graphiques = 0
    for cle, noeud in position.items():
        if cle == "DASHBOARD_VERSION_KEY":
            continue
        if not isinstance(noeud, dict):
            problemes.append(f"{cle} n'est pas un noeud")
            continue
        for enfant in noeud.get("children") or []:
            if not isinstance(enfant, str):
                problemes.append(
                    f"{cle} contient un enfant {type(enfant).__name__}, pas un identifiant"
                )
            elif enfant not in position:
                problemes.append(f"{cle} reference {enfant}, absent de la carte")
        if noeud.get("type") == "CHART":
            graphiques += 1
            if not (noeud.get("meta") or {}).get("chartId"):
                problemes.append(f"{cle} n'a pas de chartId")
    if not graphiques:
        problemes.append("aucune tuile CHART dans la mise en page")
    print(
        f"    mise en page : {len(position)} noeuds, {graphiques} tuiles, "
        f"version {position.get('DASHBOARD_VERSION_KEY')}"
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

    # 0. L'archive : la reference du tableau.
    chemin = Path(DOSSIER_ETAT) / f"{TABLEAU}.json"
    if not chemin.exists():
        print(f"  archive introuvable : {chemin}")
        return 2
    archive = json.loads(chemin.read_text(encoding="utf-8"))
    tuiles = archive.get("tuiles") or []

    # 1. La page du tableau charge ses sources.
    statut, rep = _appel("GET", f"/api/v1/dashboard/{TABLEAU}/datasets", None, jeton)
    if statut == 200:
        print(f"    datasets du dashboard : HTTP 200, {len(rep.get('result') or [])} source(s)")
    else:
        echecs.append("datasets du dashboard")
        print(f"    datasets du dashboard : HTTP {statut} {(rep.get('_err') or '')[:140]}")

    # 2. Le tableau vivant, compare a l'archive.
    statut, rep = _appel("GET", f"/api/v1/dashboard/{TABLEAU}", None, jeton)
    if statut != 200:
        print(f"  tableau illisible : HTTP {statut}")
        return 2
    vivant = rep.get("result") or {}
    position = vivant.get("position_json") or "{}"
    position = json.loads(position) if isinstance(position, str) else position
    for probleme in _verifier_mise_en_page(position):
        echecs.append(probleme)
        print(f"    mise en page : {probleme}")

    position_archivee = archive.get("position_json") or {}
    if set(position) != set(position_archivee):
        echecs.append("mise en page : le tableau vivant differe de l'archive")
        print("    mise en page : derive par rapport a l'archive")
    metadonnees = vivant.get("json_metadata") or {}
    if isinstance(metadonnees, str):
        metadonnees = json.loads(metadonnees or "{}")
    for cle, valeur in (archive.get("json_metadata") or {}).items():
        if metadonnees.get(cle) != valeur:
            echecs.append(f"metadonnee « {cle} » : derive par rapport a l'archive")
            print(f"    metadonnee « {cle} » : derive par rapport a l'archive")

    # 3. Chaque tuile : type connu, requete navigateur, etats a jour.
    rison = urllib.parse.quote("(page:0,page_size:100)", safe="()")
    _, rep = _appel("GET", f"/api/v1/chart/?q={rison}", None, jeton)
    graphiques = {g.get("slice_name"): g for g in (rep.get("result") or [])}
    _, rep = _appel("GET", f"/api/v1/dataset/?q={rison}", None, jeton)
    datasets = {d.get("table_name"): d for d in (rep.get("result") or [])}

    print(f"\n    {len(tuiles)} tuile(s) de l'archive, requete reelle de chacune :")
    for tuile in tuiles:
        nom = tuile["titre"]
        viz_type = tuile["viz_type"]
        params = tuile.get("params") or {}

        if viz_type not in VIZ_TYPES_V6:
            echecs.append(f"{nom} : type de graphique « {viz_type} » inexistant en Superset 6")
            print(f"    {nom[:44]:46} ECHEC  type « {viz_type} » inexistant (Empty query)")
            continue

        vivant_ici = graphiques.get(nom)
        if vivant_ici is None:
            echecs.append(f"{nom} : absente du tableau")
            print(f"    {nom[:44]:46} ECHEC  absente du tableau")
            continue
        params_vivants = vivant_ici.get("params")
        if isinstance(params_vivants, str):
            params_vivants = json.loads(params_vivants or "{}")
        if (params_vivants or {}) != params:
            echecs.append(f"{nom} : les parametres ont derive de l'archive")
            print(f"    {nom[:44]:46} ECHEC  parametres divergents de l'archive")
            continue
        if vivant_ici.get("viz_type") != viz_type:
            echecs.append(f"{nom} : type de graphique divergente de l'archive")
            print(f"    {nom[:44]:46} ECHEC  type divergent de l'archive")
            continue

        dataset = datasets.get(tuile.get("vue"))
        if dataset is None:
            echecs.append(f"{nom} : dataset « {tuile.get('vue')} » introuvable")
            print(f"    {nom[:44]:46} ECHEC  dataset introuvable")
            continue

        requete = requete_navigateur(viz_type, params)
        charge = {
            "datasource": {"id": int(dataset["id"]), "type": "table"},
            "queries": [requete],
            "form_data": params,
            "result_type": "full",
            "result_format": "json",
        }
        form_data = urllib.parse.quote(json.dumps({"slice_id": vivant_ici["id"]}))
        statut, rep = _appel(
            "POST",
            f"/api/v1/chart/data?form_data={form_data}",
            charge,
            jeton,
            csrf,
        )
        resultat = (rep.get("result") or [{}])[0] if isinstance(rep.get("result"), list) else {}
        donnees = resultat.get("data") or []
        if statut == 200:
            valeur = ""
            if len(donnees) == 1:
                colonnes = [
                    v
                    for k, v in donnees[0].items()
                    if k not in ("__timestamp",) and not k.startswith("_")
                ]
                valeur = f"  ->  {colonnes[0]}" if colonnes else ""
            print(f"    {nom[:44]:46} HTTP 200  {len(donnees):6d} ligne(s){valeur}")
        else:
            detail = (rep.get("_err") or rep.get("message") or "")[:150]
            echecs.append(f"{nom} : {detail}")
            print(f"    {nom[:44]:46} HTTP {statut}  ECHEC {detail}")

    if echecs:
        print(f"\n  {len(echecs)} probleme(s) : {', '.join(echecs[:6])}")
        return 1
    print("\n  Le tableau de bord s'affiche : requetes navigateur, sources et mise en page.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
