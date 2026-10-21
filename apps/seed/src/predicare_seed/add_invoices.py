"""Un seul chemin pour ajouter des factures : le format s'adapte, la porte non.

Le CDC demande que le jury soumette vingt factures inedites le jour J. Il ne
precise pas le format, et il ne peut pas le preciser : c'est au produit de
s'accommoder du fichier qu'on lui donne.

Ce module reconnait donc les formats que la plateforme sait lire, et les
normalise vers UNE porte : `POST /api/core/factures/soumettre`. C'est la meme
porte que le formulaire du professionnel, donc la validation, la notation, les
explications SHAP et l'alerte se comportent EXACTEMENT comme en production.
Un adaptateur qui rejouerait la validation en local creerait une seconde
verite -- le piege que le lot du jury avait deja evite.

Formats reconnus, sans drapeau
--------------------------------
* **PDF de facture** : le format que le jury apporte le jour J. Le texte est
  extrait par ancres de libelles (voir `predicare.pdf_facture`), puis resolu
  en base quand elle est joignable.
* **JSON « lot »** : un tableau, une facture seule, ou l'enveloppe
  `{version, factures: [...]}`. C'est le format du lot versionne et celui
  que l'onglet « Import de lot » du front accepte.
* **CSV « front »** : l'en-tete `assure_pseudonyme, prestataire_id,
  date_facture, code_acte, quantite, montant_unitaire, date_acte`, une
  ligne par facture. C'est le format que le front sait lire aussi.
* **CSV « data/raw »** : l'en-tete du chargement initial (`facture_id`,
  `assure_id`, ...), les lignes de prestation etant regroupees depuis le
  fichier frere `lignes_facture.csv`.

Ce que la commande NE FAIT PAS
------------------------------
Elle n'ecrase rien. Une facture deja presente est IGNOREE (comptee comme
« deja presente »), la porte d'entree etant idempotente sur la reference.
Une facture invalide est REJETEE en nommant le champ fautif, et rien n'est
ecrit. Seul un score peut etre recalcule : un redepot renote, c'est voulu.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from predicare.crypto import pseudonymize
from predicare.db import session_scope
from predicare.logging_config import get_logger
from predicare.pdf_facture import (
    ChampIntrouvableError,
    FactureExtraite,
    FactureIllisibleError,
    est_pdf,
    extraire_facture,
    payload_de,
    resoudre_acte,
    resoudre_assure,
    resoudre_prestataire,
)

logger = get_logger(__name__)

#: Le lot canonique, quand aucun fichier n'est donne.
LOT_PAR_DEFAUT = Path(os.environ.get("LOT_JURY", "/data/seed/lot_20_factures.json"))
API_CORE_PAR_DEFAUT = os.environ.get("API_CORE_URL", "http://api-core:8001").rstrip("/")

#: Les formats reconnus, dans l'ordre de detection.
FORMAT_PDF = "PDF"
FORMAT_JSON = "JSON"
FORMAT_CSV_FRONT = "CSV (front)"
FORMAT_CSV_RAW = "CSV (data/raw)"


class FichierInvalideError(ValueError):
    """Le fichier n'est dans aucun format reconnu."""


@dataclass(slots=True)
class FactureNormalisee:
    """Une facture, quel que soit le format d'origine.

    Le payload est celui de la porte d'entree : c'est elle qui valide, note
    et alerte. La commande ne fait que traduire le fichier.
    """

    facture_id: str
    payload: dict[str, Any]
    cas_attendu: str = "valide"
    attendu: dict[str, Any] = field(default_factory=dict)

    @property
    def valide(self) -> bool:
        return self.cas_attendu == "valide"

    @property
    def champ_attendu(self) -> str:
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
# Detection et normalisation
# ---------------------------------------------------------------------------
def _ligne_csv(entete: list[str], valeurs: list[str]) -> dict[str, str]:
    return {
        colonne.strip(): (valeurs[index].strip() if index < len(valeurs) else "")
        for index, colonne in enumerate(entete)
    }


def _est_csv_raw(entete: list[str]) -> bool:
    colonnes = {c.strip().lower() for c in entete}
    return "facture_id" in colonnes and "assure_id" in colonnes


def _est_csv_front(entete: list[str]) -> bool:
    colonnes = {c.strip().lower() for c in entete}
    return "assure_pseudonyme" in colonnes and "code_acte" in colonnes


def _payload_de_front(champs: dict[str, str], reference: str) -> dict[str, Any]:
    """Un CSV « front » donne UNE facture avec UN acte.

    Le total n'est pas dans le fichier : c'est l'interface qui le calcule
    sous les yeux du professionnel. L'adaptateur fait de meme, sinon la
    porte d'entree refuse la facture pour un champ absent.
    """
    ligne = {
        "code_acte": champs.get("code_acte", ""),
        "quantite": champs.get("quantite", "1"),
        "montant_unitaire": champs.get("montant_unitaire", ""),
        "date_acte": champs.get("date_acte") or champs.get("date_facture", ""),
    }
    try:
        total = round(float(ligne["quantite"]) * float(ligne["montant_unitaire"]), 2)
    except (TypeError, ValueError):
        total = 0.0
    return {
        # La reference DOIT voyager avec la facture : c'est elle qui rend le
        # depot idempotent. Sans elle, l'API tire une reference aleatoire et
        # le meme fichier creerait une nouvelle facture a chaque passage.
        "facture_id": reference,
        "assure_pseudonyme": champs.get("assure_pseudonyme", ""),
        "prestataire_id": champs.get("prestataire_id", ""),
        "date_facture": champs.get("date_facture", ""),
        "montant_total": total,
        "lignes": [ligne],
    }


def _payload_de_raw(
    facture: dict[str, str], lignes: list[dict[str, str]], reference: str
) -> dict[str, Any]:
    """Une facture « data/raw » donne UNE facture avec SES actes."""
    return {
        "facture_id": reference,
        "assure_pseudonyme": pseudonymize("assr", facture["assure_id"]),
        "prestataire_id": facture.get("prestataire_id", ""),
        "date_facture": facture.get("date_facture", ""),
        "montant_total": facture.get("montant_total", ""),
        "lignes": [
            {
                "code_acte": ligne.get("code", ""),
                "quantite": ligne.get("quantite", "1"),
                "montant_unitaire": ligne.get("prix_unitaire", ""),
                "date_acte": ligne.get("date_acte") or facture.get("date_facture", ""),
            }
            for ligne in lignes
        ],
    }


def _lire_csv(chemin: Path) -> list[dict[str, str]]:
    with chemin.open(encoding="utf-8-sig", newline="") as flux:
        lecteur = csv.reader(flux, delimiter=";")
        lignes = list(lecteur)
    if not lignes:
        raise FichierInvalideError(f"CSV vide : {chemin}")
    entete = lignes[0]
    return [_ligne_csv(entete, ligne) for ligne in lignes[1:] if any(v.strip() for v in ligne)]


def _lire_csv_raw(chemin: Path) -> list[FactureNormalisee]:
    factures = _lire_csv(chemin)
    if not _est_csv_raw(list(factures[0].keys())):
        raise FichierInvalideError(f"Le CSV {chemin} n'est pas au schema data/raw.")
    fichier_lignes = chemin.with_name("lignes_facture.csv")
    lignes_par_facture: dict[str, list[dict[str, str]]] = {}
    if fichier_lignes.exists():
        for ligne in _lire_csv(fichier_lignes):
            lignes_par_facture.setdefault(ligne.get("facture_id", ""), []).append(ligne)

    resultat: list[FactureNormalisee] = []
    for facture in factures:
        identifiant = facture.get("facture_id", "")
        if not identifiant:
            continue
        resultat.append(
            FactureNormalisee(
                facture_id=identifiant,
                payload=_payload_de_raw(
                    facture, lignes_par_facture.get(identifiant, []), identifiant
                ),
            )
        )
    return resultat


def _lire_csv_front(chemin: Path) -> list[FactureNormalisee]:
    lignes = _lire_csv(chemin)
    if not lignes or not _est_csv_front(list(lignes[0].keys())):
        raise FichierInvalideError(f"Le CSV {chemin} n'est pas au format du front.")
    resultat: list[FactureNormalisee] = []
    for index, champs in enumerate(lignes, start=1):
        identifiant = (
            champs.get("facture_id") or champs.get("reference") or f"{chemin.stem}-{index}"
        )
        resultat.append(
            FactureNormalisee(
                facture_id=identifiant,
                payload=_payload_de_front(champs, identifiant),
            )
        )
    return resultat


def _lire_json(chemin: Path) -> list[FactureNormalisee]:
    try:
        document = json.loads(chemin.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FichierInvalideError(f"JSON illisible ({chemin}) : {exc}") from exc

    if isinstance(document, list):
        elements: list[Any] = document
    elif isinstance(document, dict) and isinstance(document.get("factures"), list):
        elements = document["factures"]
    elif isinstance(document, dict):
        elements = [document]
    else:
        raise FichierInvalideError(f"Structure JSON non reconnue ({chemin}).")

    resultat: list[FactureNormalisee] = []
    for index, element in enumerate(elements, start=1):
        if not isinstance(element, dict):
            raise FichierInvalideError(f"Facture #{index} : objet JSON attendu.")
        payload = {
            cle: valeur for cle, valeur in element.items() if cle not in ("cas_attendu", "attendu")
        }
        if "assure_id" in payload and "assure_pseudonyme" not in payload:
            payload["assure_pseudonyme"] = pseudonymize("assr", str(payload.pop("assure_id")))
        identifiant = str(payload.get("facture_id") or payload.get("reference") or f"#{index}")
        payload.setdefault("facture_id", identifiant)
        resultat.append(
            FactureNormalisee(
                facture_id=identifiant,
                payload=payload,
                cas_attendu=str(element.get("cas_attendu", "valide")),
                attendu=element.get("attendu") or {},
            )
        )
    return resultat


def detecter_format(chemin: Path) -> str:
    """Le format d'un fichier, sans le lire entierement.

    Les OCTETS sont lus en premier : un PDF n'est pas du texte, et l'ouvrir en
    UTF-8 leve un `UnicodeDecodeError` qui ferait tomber tout le lot. Le repli
    CSV reste enveloppe pour la meme raison : un binaire inconnu devient un
    refus nomme, pas une trace technique.
    """
    chemin = Path(chemin)
    with chemin.open("rb") as flux:
        debut = flux.read(1024)
    if est_pdf(debut):
        return FORMAT_PDF

    if chemin.suffix.lower() == ".json":
        return FORMAT_JSON
    try:
        with chemin.open(encoding="utf-8-sig", newline="") as flux:
            lecteur = csv.reader(flux, delimiter=";")
            entete = next(lecteur, [])
    except UnicodeDecodeError as exc:
        raise FichierInvalideError(f"Fichier binaire non reconnu : {chemin}") from exc
    if not entete:
        return FORMAT_JSON
    if _est_csv_raw(entete):
        return FORMAT_CSV_RAW
    if _est_csv_front(entete):
        return FORMAT_CSV_FRONT
    return FORMAT_JSON


def _resoudre_ou_brut(extraite: FactureExtraite, *, prestataire: str = "") -> dict[str, Any]:
    """La charge API, avec resolution en base QUAND elle est joignable.

    Decision de produit : la resolution ne doit pas bloquer la LECTURE du
    fichier. Le job `add_invoices` tourne dans un conteneur qui voit la base,
    mais un poste de developpement ou une base momentanement absente ne doit
    pas transformer un PDF lisible en echec. Si la base n'est pas joignable (ou
    si une valeur est inconnue), on garde la valeur BRUTE : l'API rejettera en
    nommant le champ (`assure_pseudonyme`, `prestataire_id`,
    `lignes.N.code_acte`), ce qui est exactement le comportement attendu.

    `prestataire` vient de `--prestataire` : il ne s'applique qu'aux PDF qui
    ne portent aucun prestataire.
    """
    assure = extraite.assure
    code_prestataire = extraite.prestataire or prestataire
    lignes = [dict(ligne) for ligne in extraite.lignes]

    try:
        with session_scope() as session:
            try:
                assure = resoudre_assure(session, extraite.assure)
            except ChampIntrouvableError as exc:
                logger.warning("pdf.assure_non_resolu", fichier=extraite.source, erreur=str(exc))

            if code_prestataire:
                try:
                    code_prestataire = resoudre_prestataire(session, code_prestataire)
                except ChampIntrouvableError as exc:
                    logger.warning(
                        "pdf.prestataire_non_resolu", fichier=extraite.source, erreur=str(exc)
                    )

            for index, ligne in enumerate(lignes):
                try:
                    ligne["code_acte"] = resoudre_acte(session, str(ligne["code_acte"]))
                except ChampIntrouvableError as exc:
                    logger.warning(
                        "pdf.acte_non_resolu",
                        fichier=extraite.source,
                        index=index,
                        erreur=str(exc),
                    )
    except Exception as exc:
        # Base injoignable (ou configuration absente) : valeurs brutes.
        logger.warning("pdf.resolution_base_indisponible", fichier=extraite.source, erreur=str(exc))

    payload = payload_de(extraite, assure_pseudonyme=assure, prestataire_id=code_prestataire)
    payload["lignes"] = lignes
    return payload


def _lire_facture_pdf(chemin: Path, *, prestataire: str = "") -> FactureNormalisee:
    """Un PDF -> une facture normalisee, prete pour la meme porte que les autres."""
    donnees = chemin.read_bytes()
    extraite = extraire_facture(donnees, nom=chemin.name, prestataire_defaut=prestataire)
    return FactureNormalisee(
        facture_id=extraite.reference,
        payload=_resoudre_ou_brut(extraite, prestataire=prestataire),
    )


def lire_fichier(chemin: Path, *, prestataire: str = "") -> tuple[str, list[FactureNormalisee]]:
    """Lit un fichier et renvoie son format et ses factures normalisees."""
    chemin = Path(chemin)
    if not chemin.exists():
        raise FichierInvalideError(f"Fichier introuvable : {chemin}")
    if chemin.is_dir():
        raise FichierInvalideError(f"{chemin} est un dossier : indiquez un fichier.")
    format_ = detecter_format(chemin)
    if format_ == FORMAT_PDF:
        return format_, [_lire_facture_pdf(chemin, prestataire=prestataire)]
    if format_ == FORMAT_JSON:
        return format_, _lire_json(chemin)
    if format_ == FORMAT_CSV_RAW:
        return format_, _lire_csv_raw(chemin)
    return format_, _lire_csv_front(chemin)


# ---------------------------------------------------------------------------
# La porte : l'API, comme le formulaire
# ---------------------------------------------------------------------------
def _mot_de_passe() -> str:
    return os.environ.get("JURY_PASSWORD") or os.environ.get("DEMO_PASSWORD", "")


def connecter(api_core: str, email: str, mot_de_passe: str) -> httpx.Client:
    """Une session authentifiee, ou l'echec nomme.

    Le compte doit avoir le droit de deposer : le role du gestionnaire ou de
    l'administrateur. Un professionnel ne peut deposer que pour son propre
    prestataire -- c'est une regle de perimetre, pas un detail.
    """
    if not mot_de_passe:
        raise SystemExit(
            "Mot de passe de demonstration absent. Lancez : "
            "DEMO_PASSWORD='<mot-de-passe>' make comptes, puis relancez."
        )
    client = httpx.Client(base_url=api_core, timeout=30.0)
    reponse = client.post("/api/core/auth/login", json={"email": email, "password": mot_de_passe})
    if reponse.status_code != 200:
        client.close()
        raise SystemExit(
            f"Connexion refusee pour {email} (HTTP {reponse.status_code}). "
            "Verifiez le mot de passe et `make comptes`."
        )
    client.headers["Authorization"] = f"Bearer {reponse.json()['access_token']}"
    return client


def soumettre(client: httpx.Client, facture: FactureNormalisee) -> Resultat:
    """Depose une facture par la porte d'entree, et rend ce qui s'est passe.

    La porte repond 202 quand la facture est notee : c'est la reponse
    normale, pas une erreur. Le 422 (ou 400, 409) nomme le champ fautif
    quand la facture est rejetee.
    """
    try:
        reponse = client.post("/api/core/factures/soumettre", json=facture.payload)
    except httpx.HTTPError as exc:
        return Resultat(
            facture_id=facture.facture_id,
            cas_attendu=facture.cas_attendu,
            statut="echec",
            message=f"api-core injoignable : {exc}",
            conforme=False,
        )

    if reponse.status_code in (200, 202):
        corps = reponse.json()
        score = float(corps.get("score_fraude", 0.0))
        seuil = float(corps.get("seuil_applique", 0.0))
        return Resultat(
            facture_id=facture.facture_id,
            cas_attendu=facture.cas_attendu,
            statut="notee",
            score=score,
            alerte=score >= seuil,
            message=f"score {score:.4f} / seuil {seuil:.4f}",
            details=corps,
        )
    if reponse.status_code in (400, 409, 422):
        corps = _corps_json(reponse)
        message = str(corps.get("message") or corps.get("detail") or reponse.text)
        bruts = corps.get("details")
        details = (
            {str(cle): valeur for cle, valeur in bruts.items()} if isinstance(bruts, dict) else {}
        )
        return Resultat(
            facture_id=facture.facture_id,
            cas_attendu=facture.cas_attendu,
            statut="rejetee",
            message=message,
            details=details,
        )
    return Resultat(
        facture_id=facture.facture_id,
        cas_attendu=facture.cas_attendu,
        statut="echec",
        message=f"HTTP {reponse.status_code}",
    )


# ---------------------------------------------------------------------------
# La conformite, quand le fichier porte des resultats attendus
# ---------------------------------------------------------------------------
def _corps_json(reponse: httpx.Response) -> dict[str, Any]:
    """Le corps d'une erreur, quand c'est du JSON."""
    try:
        corps = reponse.json()
    except ValueError:
        return {}
    return corps if isinstance(corps, dict) else {}


def evaluer(resultat: Resultat, facture: FactureNormalisee) -> Resultat:
    """Compare le resultat a l'attendu, quand le fichier en porte un."""
    if not facture.attendu:
        return resultat
    if facture.cas_attendu == "valide":
        if resultat.statut != "notee":
            resultat.conforme = False
        elif facture.alerte_attendue is not None and resultat.alerte is not None:
            resultat.conforme = resultat.alerte == facture.alerte_attendue
    else:
        if resultat.statut != "rejetee" or (
            facture.champ_attendu and facture.champ_attendu not in resultat.message
        ):
            resultat.conforme = False
    return resultat


def rapport(
    resultats: list[Resultat],
    formats: dict[str, str],
    flux: Callable[[str], None] = print,
) -> bool:
    """Le rapport, identique quel que soit le format recu."""
    lus = len(resultats)
    notees = [r for r in resultats if r.statut == "notee"]
    rejetees = [r for r in resultats if r.statut == "rejetee"]
    echecs = [r for r in resultats if r.statut == "echec"]
    non_soumis = [r for r in resultats if r.statut == "non_soumis"]
    alertes = [r for r in notees if r.alerte]
    ecarts = [r for r in resultats if not r.conforme]

    flux("")
    flux("Bilan de l'import des factures")
    flux("------------------------------------")
    for chemin, format_ in formats.items():
        flux(f"  {chemin} : {format_}")
    flux(f"Factures lues   : {lus}")
    flux(f"Notées          : {len(notees)}")
    flux(f"Rejetées        : {len(rejetees)}")
    if echecs:
        flux(f"Échecs          : {len(echecs)}")
    if non_soumis:
        flux(f"Non soumis      : {len(non_soumis)} (dry-run)")
    flux(f"Alertes         : {len(alertes)}")
    if echecs:
        flux("")
        flux("Échecs (fichier isolé) :")
        for resultat in echecs:
            flux(f"  {resultat.facture_id:14} {resultat.message}")
    if rejetees:
        flux("")
        flux("Rejets (champ nommé) :")
        for resultat in rejetees:
            flux(f"  {resultat.facture_id:14} {resultat.message}")
    if ecarts:
        flux("")
        flux(f"Écarts ({len(ecarts)}) :")
        for resultat in ecarts:
            flux(f"  {resultat.facture_id} ({resultat.cas_attendu}) : {resultat.message}")
    return not ecarts and not echecs


def executer(
    chemins: list[Path],
    *,
    api_core: str,
    email: str,
    mot_de_passe: str,
    flux: Callable[[str], None] = print,
    dry_run: bool = False,
    prestataire: str = "",
) -> bool:
    """Le cycle complet : lecture, normalisation, depot, rapport.

    L'isolation est PAR FICHIER : un PDF corrompu produit un `Resultat` en
    echec et les autres fichiers continuent. Un seul fichier illisible ne doit
    jamais faire perdre les dix-neuf autres.

    En `dry_run`, on lit et on resout, mais on n'appelle pas l'API. Le statut
    des factures est alors `non_soumis` : ce n'est ni une note, ni un rejet, ni
    un echec, et le bilan doit le dire sans ambiguite.
    """
    factures: list[FactureNormalisee] = []
    formats: dict[str, str] = {}
    echecs: list[Resultat] = []

    for chemin in chemins:
        if chemin.is_dir():
            # Un dossier : chaque fichier qu'il contient passe par la
            # detection. C'est la forme du depot `data/import/`. Les fichiers
            # caches (`.gitkeep`) ne sont pas des factures.
            fichiers = [fichier for fichier in sorted(chemin.glob("*")) if fichier.is_file()]
        else:
            fichiers = [chemin]

        for fichier in fichiers:
            if fichier.name.startswith("."):
                continue
            try:
                format_, lues = lire_fichier(fichier, prestataire=prestataire)
            except (FichierInvalideError, FactureIllisibleError, OSError) as exc:
                formats[str(fichier)] = "illisible"
                echecs.append(
                    Resultat(
                        facture_id=fichier.name,
                        cas_attendu="valide",
                        statut="echec",
                        message=str(exc),
                        conforme=False,
                    )
                )
                continue
            formats[str(fichier)] = format_
            factures.extend(lues)

    if not factures and not echecs:
        raise FichierInvalideError("Aucune facture trouvee dans les fichiers indiques.")

    if dry_run:
        resultats = [
            *echecs,
            *[
                Resultat(
                    facture_id=facture.facture_id,
                    cas_attendu=facture.cas_attendu,
                    statut="non_soumis",
                    message="non soumis (dry-run)",
                )
                for facture in factures
            ],
        ]
        return rapport(resultats, formats, flux)

    client = connecter(api_core, email, mot_de_passe)
    try:
        resultats = [
            *echecs,
            *[evaluer(soumettre(client, facture), facture) for facture in factures],
        ]
    finally:
        client.close()
    return rapport(resultats, formats, flux)


def analyser_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument(
        "--fichier",
        action="append",
        default=None,
        help=(
            "Fichier de factures (PDF, JSON ou CSV) ou dossier. Repetable. "
            "Defaut : le lot canonique."
        ),
    )
    parseur.add_argument("--api-core", default=API_CORE_PAR_DEFAUT)
    parseur.add_argument("--email", default=os.environ.get("JURY_EMAIL", "admin@predicare.local"))
    parseur.add_argument("--mot-de-passe", default=_mot_de_passe())
    parseur.add_argument(
        "--prestataire",
        default="",
        help="Code prestataire impose aux PDF qui n'en portent pas (ex. PRE-00155).",
    )
    parseur.add_argument(
        "--dry-run",
        action="store_true",
        help="Lit, resout et affiche le bilan sans appeler l'API.",
    )
    return parseur.parse_args(list(argv) if argv is not None else None)


def main(argv: list[str] | None = None) -> int:
    arguments = analyser_arguments(argv)
    chemins = [Path(chemin) for chemin in (arguments.fichier or [str(LOT_PAR_DEFAUT)])]
    try:
        succes = executer(
            chemins,
            api_core=arguments.api_core,
            email=arguments.email,
            mot_de_passe=arguments.mot_de_passe,
            dry_run=arguments.dry_run,
            prestataire=arguments.prestataire,
        )
    except FichierInvalideError as exc:
        print(f"ECHEC : {exc}", file=sys.stderr)
        return 2
    return 0 if succes else 1


if __name__ == "__main__":
    raise SystemExit(main())
