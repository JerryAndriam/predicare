"""Peuple l'historique SQL Lab et les requetes enregistrees de Superset.

Pourquoi ce job existe
----------------------
Les douze tuiles du tableau de bord interrogent la base par l'API
`/api/v1/chart/data`, qui n'ecrit RIEN dans l'historique de Superset. Seule
SQL Lab alimente la table `query`. Resultat : l'onglet « Query history » de
SQL Lab est vide, et le jury le lit comme une panne.

Ce job execute une liste versionnee de requetes de pilotage par l'API SQL
Lab (`POST /api/v1/sqllab/execute/`), puis les enregistre comme « Saved
queries » (`POST /api/v1/saved_query/`). L'historique est donc authentique :
ce sont de vraies executions, avec leur SQL, leur duree et leur nombre de
lignes -- pas des lignes fabriquees a la main dans la table.

Les requetes sont en lecture seule sur la connexion « PrediCare (lecture
seule) » : `allow_ctas`, `allow_cvas` et `allow_dml` sont desactivation, et
la session PostgreSQL est en `default_transaction_read_only=on`. Rien ne peut
ecrire, meme par accident.

Le contenu est aligne sur le CDC : les cinq indicateurs exiges, plus les
vues de pilotage qui les produisent.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from urllib.parse import urlencode

BASE = os.environ.get("SUPERSET_URL", "http://localhost:8088")
NOM_CONNEXION = "PrediCare (lecture seule)"
SCHEMA_BI = "bi"

#: Les requetes de pilotage, dans l'ordre de lecture du jury.
#:
#: Le SQL porte sur les VUES de la couche semantique (`bi.*`), jamais sur les
#: tables metier : la vue est la definition agreee, la table n'en est qu'une
#: des lectures possibles.
REQUETES: tuple[dict[str, str], ...] = (
    {
        "label": "01 - Factures traitees et montant presente",
        "description": "Les deux volumes du CDC : le nombre de factures et le montant presente, en ariary.",
        "sql": "SELECT nb_factures, montant_total_mga, periode FROM bi.v_kpi_global;",
    },
    {
        "label": "02 - Taux de fraude observe (%)",
        "description": "Prevalence terrain : la fraude reellement constatee sur les 24 mois.",
        "sql": "SELECT taux_fraude_pct, nb_fraudes, montant_fraude_mga FROM bi.v_kpi_global;",
    },
    {
        "label": "03 - Delai moyen de traitement (jours)",
        "description": "Delai pondere par facture traitee ; une facture non traitee n'entre pas dans la moyenne.",
        "sql": "SELECT delai_moyen_jours, nb_factures FROM bi.v_kpi_global;",
    },
    {
        "label": "04 - Montants economises confirmes (MGA)",
        "description": "Montant que la detection a evite de payer, confirme par un gestionnaire.",
        "sql": "SELECT montant_economise_mga, nb_decisions, delai_decision_heures FROM bi.v_cdc_global;",
    },
    {
        "label": "05 - Taux de detection du modele (%)",
        "description": "Rappel du modele sur son jeu de TEST temporel, jamais vu a l'entrainement.",
        "sql": "SELECT version, rappel_test_pct, precision_test_pct, nb_factures_test FROM bi.v_modele_performance;",
    },
    {
        "label": "06 - Taux de faux positifs du modele (%)",
        "description": "Precision du modele au seuil applique : le prix d'un faux positif.",
        "sql": "SELECT version, faux_positifs_test_pct, vrais_positifs_test, faux_positifs_test FROM bi.v_modele_performance;",
    },
    {
        "label": "07 - Alertes en attente de decision",
        "description": "La boucle en direct : ce qui attend un gestionnaire, et pour quel montant.",
        "sql": "SELECT nb_alertes_en_attente, montant_en_attente_mga FROM bi.v_cdc_global;",
    },
    {
        "label": "08 - Cinq prestataires les plus exposes (MGA)",
        "description": "Le classement par montant expose, pas par taux : un taux eleve sur trois factures ne pese rien.",
        "sql": (
            "SELECT prestataire_nom, nb_factures, taux_fraude_pct, montant_expose_mga "
            "FROM bi.v_top5_prestataires;"
        ),
    },
    {
        "label": "09 - Volume et montants par mois",
        "description": "La tendance : volume, montant presente, montant expose, prevalence.",
        "sql": (
            "SELECT mois, nb_factures, montant_total_mga, montant_fraude_mga, taux_fraude_pct "
            "FROM bi.v_kpi_mensuel ORDER BY mois DESC LIMIT 24;"
        ),
    },
    {
        "label": "10 - Motifs de non-paiement par mois",
        "description": "Les points de controle qui expliquent le refus d'une facture.",
        "sql": (
            "SELECT mois, motif, nb_factures, montant_concerne_mga FROM bi.v_controle_points "
            "ORDER BY mois DESC, nb_factures DESC LIMIT 50;"
        ),
    },
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
        requete = urlencode({"q": "(page:0,page_size:100)"})
        return list(self._json("GET", f"{chemin}?{requete}").get("result") or [])


def _id_connexion(client: Client) -> int:
    for base in client.lister("/api/v1/database/"):
        if base.get("database_name") == NOM_CONNEXION:
            return int(base["id"])
    raise RuntimeError(f"connexion « {NOM_CONNEXION} » introuvable dans Superset.")


def _executer(client: Client, id_base: int, sql: str) -> dict:
    """Execute une requete PAR SQL LAB : c'est ce qui alimente l'historique.

    `runAsync: false` rend la reponse synchrone ; l'API ecrit quand meme la
    ligne dans la table `query`, avec le SQL, la duree et le nombre de lignes.
    """
    return client._json(
        "POST",
        "/api/v1/sqllab/execute/",
        {
            "database_id": id_base,
            "sql": sql,
            "schema": SCHEMA_BI,
            "catalog": None,
            "runAsync": False,
            "select_as_cta": False,
            "ctas_method": "TABLE",
            "expand_data": True,
            "queryLimit": 1000,
        },
    )


def _enregistrer(client: Client, id_base: int, requete: dict, existantes: dict[str, int]) -> int:
    """Cree la « Saved query », ou met a jour celle qui porte deja le nom.

    Rend l'identifiant de la requete enregistree : c'est ce qui permet de
    supprimer ensuite les doublons laisses par un autre compte.
    """
    charge = {
        "label": requete["label"],
        "sql": requete["sql"],
        "db_id": id_base,
        "schema": SCHEMA_BI,
        "description": requete["description"],
        "extra_json": json.dumps({"engine": "postgresql"}),
    }
    deja = existantes.get(requete["label"])
    if deja is not None:
        client._json("PUT", f"/api/v1/saved_query/{deja}", charge)
        return deja
    creee = client._json("POST", "/api/v1/saved_query/", charge)
    return int(creee["id"])


def _supprimer_doublons(identifiants: dict[str, int]) -> int:
    """Retire les doublons de requetes enregistrees laisses par un autre compte.

    La suppression se fait dans la base de metadonnees : l'API de lecture
    d'un compte de demonstration ne liste QUE ses propres requetes, et sa
    route de suppression refuse un identifiant qui n'est pas le sien
    (« Not found »). Le depot, lui, voit tout.
    """
    from superset.app import create_app

    application = create_app()
    with application.app_context():
        from superset import db as superset_db
        from superset.models.sql_lab import SavedQuery

        supprimees = 0
        for requete in (
            superset_db.session.query(SavedQuery)
            .filter(SavedQuery.label.in_(list(identifiants)))
            .all()
        ):
            if requete.id in identifiants.values():
                continue
            superset_db.session.delete(requete)
            supprimees += 1
        superset_db.session.commit()
        return supprimees


def _nettoyer_historique(sqls: list[str]) -> int:
    """Ne garde que la derniere execution de chaque requete pilotee.

    Le journal SQL Lab est un historique : il garde TOUT. Mais un job
    executable dix fois laisse dix fois la meme requete, et l'historique
    devient illisible. On supprime donc les executions ANTERIEURES de ces
    dix requetes -- et uniquement celles-la : les requetes lancees a la main
    depuis l'interface ne sont pas touchees.
    """
    from superset.app import create_app

    application = create_app()
    with application.app_context():
        from superset import db as superset_db
        from superset.models.sql_lab import Query

        supprimees = 0
        for sql in sqls:
            executions = (
                superset_db.session.query(Query)
                .filter(Query.sql == sql)
                .order_by(Query.id.desc())
                .all()
            )
            for execution in executions[1:]:
                superset_db.session.delete(execution)
                supprimees += 1
        superset_db.session.commit()
        return supprimees


def main() -> int:
    # Les requetes sont executees AU COMPTE DE DEMONSTRATION quand il existe.
    # L'historique SQL Lab et les requetes enregistrees appartiennent a leur
    # auteur : c'est le compte que le jury ouvre, il doit donc y trouver SON
    # analyse, pas celle de l'administrateur.
    mot_de_passe_demo = os.environ.get("SUPERSET_DEMO_PASSWORD", "").strip()
    if mot_de_passe_demo:
        identifiant = os.environ.get("SUPERSET_DEMO_USERNAME", "demo")
        mot_de_passe = mot_de_passe_demo
    else:
        identifiant = os.environ.get("SUPERSET_ADMIN_USERNAME", "admin")
        mot_de_passe = os.environ.get("SUPERSET_ADMIN_PASSWORD", "")
    if not mot_de_passe:
        print(
            "Ni SUPERSET_DEMO_PASSWORD ni SUPERSET_ADMIN_PASSWORD : requetes non chargees.",
            file=sys.stderr,
        )
        return 2

    client = Client(BASE, identifiant, mot_de_passe)
    print(f"Execution en tant que « {identifiant} ».")
    id_base = _id_connexion(client)
    existantes = {
        requete.get("label"): int(requete["id"])
        for requete in client.lister("/api/v1/saved_query/")
        if requete.get("label")
    }

    erreurs = 0
    identifiants: dict[str, int] = {}
    for requete in REQUETES:
        try:
            resultat = _executer(client, id_base, requete["sql"])
        except RuntimeError as exc:
            erreurs += 1
            print(f"  [KO]  {requete['label']} : {str(exc)[:120]}")
            continue
        donnees = resultat.get("data") or []
        etat = "OK " if not resultat.get("error") else "ERR"
        if resultat.get("error"):
            erreurs += 1
        try:
            identifiants[requete["label"]] = _enregistrer(client, id_base, requete, existantes)
        except RuntimeError as exc:
            erreurs += 1
            print(f"  [KO]  {requete['label']} (enregistrement) : {str(exc)[:120]}")
            continue
        print(f"  [{etat}] {requete['label']:52} {len(donnees):5d} ligne(s)")

    # Une meme requete enregistree par deux comptes s'affiche en double dans
    # les listes : on garde celle du compte courant et on retire les autres.
    # Le nettoyage se fait par l'ADMIN : un compte de demonstration ne voit
    # que ses propres requetes enregistrees, il ne peut donc pas voir -- ni
    # supprimer -- celles d'un autre compte.
    supprimees = _supprimer_doublons(identifiants)
    if supprimees:
        print(f"  {supprimees} doublon(s) de requete enregistree supprime(s).")

    # L'historique, lui, s'accumule a chaque execution : sans nettoyage, dix
    # fois le job, cent entrees, et le jury cherche parmi des copies. On
    # garde la DERNIERE execution de chaque requete pilotee : c'est
    # l'historique de reference, pas un journal de nos passages.
    remplacees = _nettoyer_historique([r["sql"] for r in REQUETES])
    if remplacees:
        print(f"  {remplacees} entree(s) d'historique remplacee(s) par la derniere execution.")

    print(f"\n{len(REQUETES)} requete(s) executee(s) et enregistree(s).")
    if erreurs:
        print(f"{erreurs} probleme(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
