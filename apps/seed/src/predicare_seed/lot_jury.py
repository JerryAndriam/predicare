"""Soumission du lot de 20 factures inedites du CDC (exigence F17).

Le CDC exige que le jury soumette vingt factures inedites le jour J, dont des
factures invalides. Le front ne sait pas importer un lot : ce job est le
chemin d'exploitation, et il passe par la MEME porte que le formulaire,
`POST /api/core/factures/soumettre`.

Ce choix est delibere. api-core enchaine :

1. la validation `InvoiceSubmission` (champ fautif nomme) ;
2. la verification des references (`core.assure`, `core.prestataire`,
   `core.acte`) ;
3. la notation par le Flux 1 ;
4. l'ecriture de la facture et de la prediction en `statut='nouvelle'`.

Rejouer la validation dans le job ferait diverger deux verites : une facture
acceptee par le job mais refusee par l'API (ou l'inverse) le jour J. Le job
reste donc un CLIENT de l'API ; la seule lecture directe en base est le
controle d'idempotence (references deja notees), qui evite de rouvrir une
alerte deja decidee.

Le fichier `data/seed/lot_20_factures.json` est la source unique : il porte
les factures ET le resultat attendu (`cas_attendu`, `attendu`). Les tests e2e
le consomment tel quel.

Usage :
    docker compose -f docker-compose.yml run --rm seed \\
        python -m predicare_seed.lot_jury

    # ou, depuis l'hote, avec un mot de passe connu :
    DEMO_PASSWORD='...' make lot-jury
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text

from predicare.config import get_settings
from predicare.db import session_scope
from predicare.logging_config import configure_logging, get_logger

logger = get_logger("seed.lot_jury")

#: Dossier des donnees monte en lecture seule dans le conteneur `seed`.
LOT_PAR_DEFAUT = Path(os.environ.get("LOT_JURY", "/data/seed/lot_20_factures.json"))

#: api-core est joignable par son nom de service : le job tourne sur le reseau
#: `core`, comme l'API. Depuis l'hote, surcharger avec `API_CORE_URL`.
API_CORE_PAR_DEFAUT = os.environ.get("API_CORE_URL", "http://api-core:8001").rstrip("/")

#: Champs de metadonnees du lot : tout le reste est la payload d'inference.
META_CLES = ("cas_attendu", "attendu")

MESSAGE_MOT_DE_PASSE = (
    "Mot de passe de demonstration absent. Lancez : DEMO_PASSWORD='<mot-de-passe>' "
    "make comptes (le mot de passe est affiche une seule fois), puis relancez."
)


class LotInvalideError(ValueError):
    """Le fichier de lot ne respecte pas le format d'echange."""


@dataclass(frozen=True, slots=True)
class CasLot:
    """Une facture du lot et le resultat attendu."""

    facture_id: str
    cas_attendu: str
    attendu: dict[str, Any]
    payload: dict[str, Any]

    @property
    def valide(self) -> bool:
        return self.cas_attendu == "valide"

    @property
    def champ_attendu(self) -> str:
        """Champ qui doit etre nomme par le rejet (cas invalide)."""
        return str(self.attendu.get("champ", ""))

    @property
    def alerte_attendue(self) -> bool | None:
        valeur = self.attendu.get("alerte")
        return valeur if isinstance(valeur, bool) else None


@dataclass(slots=True)
class Resultat:
    """Ce que la soumission a reellement produit."""

    facture_id: str
    cas_attendu: str
    statut: str
    score: float | None = None
    alerte: bool | None = None
    message: str = ""
    conforme: bool = True
    details: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Chargement et controle du format d'echange
# ---------------------------------------------------------------------------
def charger_lot(chemin: Path | str = LOT_PAR_DEFAUT) -> list[CasLot]:
    """Lit le lot versionne et verifie sa structure.

    Le controle porte sur le FORMAT, pas sur la validite metier des factures :
    une facture « invalide » doit justement traverser le job pour que l'API la
    rejette. Valider sa payload ici reviendrait a tester le job au lieu de
    tester la porte d'entree.
    """
    chemin = Path(chemin)
    try:
        document = json.loads(chemin.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LotInvalideError(f"Lot introuvable : {chemin}") from exc
    except json.JSONDecodeError as exc:
        raise LotInvalideError(f"Lot illisible ({chemin}) : {exc}") from exc

    if not isinstance(document, dict):
        raise LotInvalideError("Le lot doit etre un objet JSON (version, factures).")
    if document.get("version") != 1:
        raise LotInvalideError("Version de lot non supportee (attendu : 1).")

    factures = document.get("factures")
    if not isinstance(factures, list) or not factures:
        raise LotInvalideError("Le lot doit contenir une liste `factures` non vide.")

    cas: list[CasLot] = []
    identifiants: set[str] = set()
    for rang, brut in enumerate(factures, start=1):
        if not isinstance(brut, dict):
            raise LotInvalideError(f"Facture #{rang} : objet JSON attendu.")
        manquants = [cle for cle in META_CLES if cle not in brut]
        if manquants:
            raise LotInvalideError(f"Facture #{rang} : metadonnees absentes {manquants}.")

        cas_attendu = str(brut["cas_attendu"])
        attendu = brut["attendu"]
        if not isinstance(attendu, dict):
            raise LotInvalideError(f"Facture #{rang} : `attendu` doit etre un objet.")
        if cas_attendu != "valide" and not cas_attendu.startswith("invalide:"):
            raise LotInvalideError(
                f"Facture #{rang} : `cas_attendu` doit valoir `valide` "
                f"ou `invalide:<champ>` (recu : {cas_attendu!r})."
            )
        if cas_attendu == "valide" and not isinstance(attendu.get("alerte"), bool):
            raise LotInvalideError(f"Facture #{rang} : `attendu.alerte` (bool) requis.")
        if cas_attendu.startswith("invalide:") and not attendu.get("champ"):
            raise LotInvalideError(f"Facture #{rang} : `attendu.champ` requis.")

        payload = {cle: valeur for cle, valeur in brut.items() if cle not in META_CLES}
        facture_id = str(payload.get("facture_id") or "")
        if not facture_id:
            raise LotInvalideError(f"Facture #{rang} : `facture_id` requis.")
        if facture_id in identifiants:
            raise LotInvalideError(f"Facture #{rang} : `facture_id` en doublon ({facture_id}).")
        identifiants.add(facture_id)

        cas.append(
            CasLot(
                facture_id=facture_id,
                cas_attendu=cas_attendu,
                attendu=dict(attendu),
                payload=payload,
            )
        )

    return cas


# ---------------------------------------------------------------------------
# Idempotence : ne pas rouvrir une alerte deja traitee
# ---------------------------------------------------------------------------
def references_deja_notees(references: list[str]) -> set[str]:
    """References qui ont deja une prediction, quel que soit son statut.

    Une facture presente en base SANS prediction (ecriture interrompue entre
    les deux INSERT) doit etre rejouee : c'est la seule facon de reparer un
    demi-succes sans intervention manuelle.
    """
    if not references:
        return set()
    try:
        with session_scope() as session:
            rows = session.execute(
                text(
                    """
                    SELECT f.reference
                    FROM core.facture f
                    WHERE f.reference = ANY(:references)
                      AND EXISTS (
                          SELECT 1 FROM ml.prediction p WHERE p.facture_id = f.id
                      )
                    """
                ),
                {"references": references},
            ).scalars()
            return set(rows)
    except Exception as exc:  # base indisponible : rejouer est sans danger
        logger.warning("lot.idempotence.indisponible", erreur=str(exc))
        return set()


# ---------------------------------------------------------------------------
# Client HTTP
# ---------------------------------------------------------------------------
def connecter(
    api_core: str, email: str, mot_de_passe: str, *, timeout: float = 30.0
) -> httpx.Client:
    """Ouvre un client authentifie. Le jeton n'est jamais imprime."""
    client = httpx.Client(base_url=api_core, timeout=timeout)
    try:
        reponse = client.post(
            "/api/core/auth/login",
            json={"email": email, "password": mot_de_passe},
        )
    except httpx.HTTPError as exc:
        client.close()
        raise SystemExit(f"api-core injoignable ({api_core}) : {exc}") from exc

    if reponse.status_code != 200:
        client.close()
        raise SystemExit(
            f"Connexion refusee pour {email} (HTTP {reponse.status_code}). "
            "Verifiez DEMO_PASSWORD et `make comptes`."
        )

    client.headers["Authorization"] = f"Bearer {reponse.json()['access_token']}"
    return client


def soumettre(client: httpx.Client, cas: CasLot) -> Resultat:
    """Envoie une facture et confronte la reponse au resultat attendu."""
    try:
        reponse = client.post("/api/core/factures/soumettre", json=cas.payload)
    except httpx.HTTPError as exc:
        return Resultat(
            facture_id=cas.facture_id,
            cas_attendu=cas.cas_attendu,
            statut="echec",
            message=f"api-core injoignable : {exc}",
            conforme=False,
        )

    if reponse.status_code == 202:
        corps = reponse.json()
        score = float(corps["score_fraude"])
        alerte = bool(corps["is_fraud"])
        if not cas.valide:
            return Resultat(
                facture_id=cas.facture_id,
                cas_attendu=cas.cas_attendu,
                statut="acceptee",
                score=score,
                alerte=alerte,
                message="facture invalide acceptee par l'API",
                conforme=False,
            )
        attendu = cas.alerte_attendue
        conforme = attendu is None or alerte == attendu
        return Resultat(
            facture_id=cas.facture_id,
            cas_attendu=cas.cas_attendu,
            statut="notee",
            score=score,
            alerte=alerte,
            message=f"score {score:.4f}" + ("" if conforme else f", alerte attendue {attendu}"),
            conforme=conforme,
            details=corps,
        )

    if reponse.status_code == 422:
        corps = _corps_json(reponse)
        message = str(corps.get("message", ""))
        if cas.valide:
            return Resultat(
                facture_id=cas.facture_id,
                cas_attendu=cas.cas_attendu,
                statut="rejetee",
                message=message or "facture valide rejetee par l'API",
                conforme=False,
                details=corps,
            )
        champ = cas.champ_attendu
        conforme = champ in message
        return Resultat(
            facture_id=cas.facture_id,
            cas_attendu=cas.cas_attendu,
            statut="rejetee",
            message=message,
            conforme=conforme,
            details=corps,
        )

    return Resultat(
        facture_id=cas.facture_id,
        cas_attendu=cas.cas_attendu,
        statut="echec",
        message=f"HTTP {reponse.status_code} : {reponse.text[:200]}",
        conforme=False,
    )


def _corps_json(reponse: httpx.Response) -> dict[str, Any]:
    try:
        corps = reponse.json()
    except ValueError:
        return {"message": reponse.text[:500]}
    return corps if isinstance(corps, dict) else {"message": str(corps)[:500]}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def executer(
    client: httpx.Client,
    cas: list[CasLot],
    *,
    forcer: bool = False,
    deja_notees: set[str] | None = None,
) -> list[Resultat]:
    """Soumet les cas dans l'ordre du fichier, sans s'arreter au premier ecart."""
    deja_notees = (
        deja_notees
        if deja_notees is not None
        else references_deja_notees([c.facture_id for c in cas])
    )
    resultats: list[Resultat] = []
    for item in cas:
        if item.valide and item.facture_id in deja_notees and not forcer:
            resultats.append(
                Resultat(
                    facture_id=item.facture_id,
                    cas_attendu=item.cas_attendu,
                    statut="ignoree",
                    message="deja notee (--rescorer pour rejouer)",
                )
            )
            continue
        resultat = soumettre(client, item)
        resultats.append(resultat)
        logger.info(
            "lot.cas",
            facture_id=resultat.facture_id,
            statut=resultat.statut,
            conforme=resultat.conforme,
        )
    return resultats


def rapport(resultats: list[Resultat], flux: Callable[[str], None] = print) -> bool:
    """Affiche le detail puis le bilan. Rend True si tout est conforme."""
    flux(f"{'facture':14} {'cas attendu':28} {'resultat':10} {'conforme':8} detail")
    flux("-" * 100)
    for r in resultats:
        detail = r.message
        if r.score is not None and r.statut == "notee":
            detail = f"{detail} / alerte={r.alerte}"
        flux(
            f"{r.facture_id:14} {r.cas_attendu:28} {r.statut:10} "
            f"{'oui' if r.conforme else 'NON':8} {detail}"
        )

    notees = sum(1 for r in resultats if r.statut == "notee")
    rejetees = sum(1 for r in resultats if r.statut == "rejetee")
    ignorees = sum(1 for r in resultats if r.statut == "ignoree")
    alertes = sum(1 for r in resultats if r.alerte is True)
    ecarts = [r for r in resultats if not r.conforme]

    flux("")
    flux(
        f"Bilan : {len(resultats)} factures, {notees} notees, {rejetees} rejetees, "
        f"{ignorees} ignorees (deja notees), {alertes} alertes."
    )
    if ecarts:
        flux(f"ECARTS ({len(ecarts)}) :")
        for r in ecarts:
            flux(f"  - {r.facture_id} ({r.cas_attendu}) : {r.message}")
        return False
    flux("Tous les cas sont conformes.")
    return True


def analyser_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parseur = argparse.ArgumentParser(
        description="Soumet le lot de 20 factures inedites du CDC (F17)."
    )
    parseur.add_argument("--lot", default=str(LOT_PAR_DEFAUT), help="Chemin du fichier de lot.")
    parseur.add_argument("--api-core", default=API_CORE_PAR_DEFAUT, help="URL racine d'api-core.")
    parseur.add_argument("--email", default=os.environ.get("JURY_EMAIL", "pro@predicare.local"))
    parseur.add_argument(
        "--password",
        default=os.environ.get("JURY_PASSWORD") or os.environ.get("DEMO_PASSWORD", ""),
    )
    parseur.add_argument(
        "--rescorer",
        action="store_true",
        help="Rejoue aussi les factures deja notees (rouvre l'alerte).",
    )
    parseur.add_argument(
        "--dry-run",
        action="store_true",
        help="Charge et affiche le lot sans contacter l'API.",
    )
    return parseur.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = analyser_arguments(argv)
    settings = get_settings()
    configure_logging("seed", settings.log_level, settings.log_format)

    try:
        cas = charger_lot(arguments.lot)
    except LotInvalideError as exc:
        print(f"Lot invalide : {exc}", file=sys.stderr)
        return 2

    if arguments.dry_run:
        for item in cas:
            print(f"{item.facture_id:14} {item.cas_attendu:28} {item.payload['montant_total']}")
        print(f"{len(cas)} factures chargees, aucune requete envoyee.")
        return 0

    if not arguments.password:
        print(MESSAGE_MOT_DE_PASSE, file=sys.stderr)
        return 2

    # httpx journalise chaque requete en INFO : le rapport du lot doit rester
    # lisible, et les vingt lignes de transport n'apportent rien a l'operateur.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    client = connecter(arguments.api_core, arguments.email, arguments.password)
    try:
        resultats = executer(client, cas, forcer=arguments.rescorer)
    finally:
        client.close()

    return 0 if rapport(resultats) else 1


if __name__ == "__main__":
    raise SystemExit(main())
