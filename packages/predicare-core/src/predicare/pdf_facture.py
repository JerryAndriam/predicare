"""Lecture des factures PDF deposees par le jury.

Le CDC impose que le jury fournisse vingt factures inedites le jour J, en PDF.
Un PDF n'est pas un CSV, et le jury peut apporter N'IMPORTE QUEL gabarit :
aucune mise en page n'est garantie. Le module lit donc en deux passes.

1. les CHAMPS D'EN-TETE (date, assure, prestataire, total) par ANCRES DE
   LIBELLES : « N° facture », « Patient », « Date de facture », « Total »...
   et la valeur qui suit. C'est robuste a un document en vrac, sans tableau.
2. les LIGNES DE FACTURE par un LECTEUR DE TABLEAU : `pypdf` en mode `layout`
   restitue l'alignement des colonnes par des espaces, l'en-tete est reconnu a
   ses libelles (« Code », « Designation », « Qte », « P.U. », « Montant »)
   quelles que soient leur ordre et leur position. Un repli sur le texte
   simple couvre les PDF ou le mode `layout` n'aboutit pas, et un dernier
   repli sur les ancres couvre les factures ecrites en clair.

Deux responsabilites, volontairement separees :

1. l'EXTRACTION (`extraire_facture`, `payload_de`) est PURE : aucun acces base,
   aucun reseau. C'est ce qui la rend testable sans PostgreSQL et ce qui permet
   a l'API d'import (A.11) de la reutiliser telle quelle ;
2. la RESOLUTION (`resoudre_assure`, `resoudre_prestataire`, `resoudre_acte`)
   prend une `Session` SQLAlchemy et applique une politique STRICTE : on ne
   cree JAMAIS de referentiel. Une valeur inconnue est rejetee en nommant le
   champ technique attendu par l'API (`assure_pseudonyme`, `prestataire_id`,
   `lignes.0.code_acte`, `montant_total`...).

Regle RGPD : `core.identite_chiffree` n'est jamais dechiffree ici. La seule
voie pour passer d'un nom a un pseudonyme est l'index hors-ligne construit
depuis `data/raw/identites_pii.csv`.
"""

from __future__ import annotations

import csv
import hashlib
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import NamedTuple

from pypdf import PdfReader
from sqlalchemy import text
from sqlalchemy.orm import Session

#: Les cinq premiers octets de tout PDF valide.
PDF_MAGIC = b"%PDF-"

#: En dessous de ce nombre de caracteres utiles, le PDF n'a pas de couche texte.
SEUIL_TEXTE_UTILE = 20

#: Le message de scan, montre tel quel a l'utilisateur.
MESSAGE_SCAN = "PDF sans couche texte (scan) : OCR requis. Fournissez un PDF texte."


class FactureIllisibleError(ValueError):
    """Le fichier n'est pas une facture exploitable.

    Le message est montrable a l'utilisateur : il dit ce qui manque, jamais une
    trace technique.
    """


class PdfSansTexteError(FactureIllisibleError):
    """PDF sans couche texte (scan) : OCR requis."""


class ChampIntrouvableError(FactureIllisibleError):
    """Un champ obligatoire n'a pas ete trouve dans le document."""


@dataclass(frozen=True)
class FactureExtraite:
    """Une facture lue dans un PDF, avant toute resolution en base.

    Les champs `assure` et `prestataire` portent la valeur BRUTE du document :
    pseudonyme, identifiant, nom ou code. C'est la resolution qui tranche.
    """

    reference: str
    assure: str
    prestataire: str
    date_facture: str
    lignes: tuple[dict, ...]
    montant_total: float
    source: str
    #: Candidats prestataire, du plus sur au plus douteux : code `PRE-...`,
    #: libelle explicite, enseigne, puis NIF/O.N.M. La resolution essaie les
    #: suivants quand le premier ne correspond a rien, au lieu de rejeter une
    #: facture dont le NIF est exact mais l'enseigne mal orthographiee.
    prestataires: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Normalisation de texte
# ---------------------------------------------------------------------------
def _normaliser_typographie(texte: str) -> str:
    """Remplace les artefacts typographiques qui cassent la lecture.

    Les accents sont CONSERVES ici : ils portent du sens. La comparaison des
    libelles, elle, se fait sans accents (voir `_cle`).
    """
    texte = texte.replace("\u00a0", " ").replace("\u202f", " ")
    texte = texte.replace("\u2007", " ").replace("\u2009", " ")
    texte = texte.replace("\u00ad", "")
    texte = texte.replace("\u200b", "").replace("\ufeff", "")
    texte = texte.replace("\u2019", "'").replace("\u2018", "'")
    texte = texte.replace("\u201c", '"').replace("\u201d", '"')
    texte = texte.replace("\u00ba", "\u00b0")
    for tiret in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015"):
        texte = texte.replace(tiret, "-")
    return texte


def _sans_accents(texte: str) -> str:
    """Retire les diacritiques sans changer l'ordre des caracteres."""
    decompose = unicodedata.normalize("NFKD", texte)
    return "".join(caractere for caractere in decompose if not unicodedata.combining(caractere))


def _cle(texte: str) -> str:
    """Cle de comparaison : sans accents, sans casse, espaces compactes."""
    return re.sub(r"\s+", " ", _sans_accents(texte)).strip().upper()


def _mot(texte: str) -> str:
    """Cle d'un libelle de colonne : ponctuation reduite a des espaces.

    « P.U. » et « P U » doivent designer la meme colonne ; « Total ligne » et
    « TOTAL-LIGNE » aussi. On ne garde que les lettres, les chiffres et les
    espaces.
    """
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", _cle(texte))).strip()


# ---------------------------------------------------------------------------
# Lecture du PDF
# ---------------------------------------------------------------------------
def est_pdf(donnees: bytes) -> bool:
    """Vrai si les octets commencent par `%PDF-`.

    On tolere un BOM et des espaces avant la signature : certains scanners
    ajoutent un en-tete avant le document.
    """
    debut = donnees.lstrip(b"\xef\xbb\xbf \t\r\n")
    return debut.startswith(PDF_MAGIC)


def extraire_texte(donnees: bytes) -> str:
    """Le texte de toutes les pages, dans l'ordre, typographie normalisee.

    Portage de `ingest_rag._lire_pdf` (corpus de contrats) : `pypdf` extrait
    le texte page par page, et l'on joint les pages par un saut de ligne.
    """
    if not est_pdf(donnees):
        raise FactureIllisibleError("Ce fichier n'est pas un PDF.")
    try:
        lecteur = PdfReader(BytesIO(donnees))
        pages = [page.extract_text() or "" for page in lecteur.pages]
    except Exception as exc:  # pypdf leve des types varies selon la corruption
        raise FactureIllisibleError(f"PDF illisible : {exc}") from exc
    return _normaliser_typographie("\n".join(pages))


def extraire_texte_mis_en_page(donnees: bytes) -> str:
    """Le texte de toutes les pages, en conservant l'alignement des colonnes.

    `extract_text()` aplatit un tableau : les cellules d'une meme ligne se
    retrouvent dispersees, et rien ne dit a quelle colonne elles appartiennent.
    Le mode `layout` de `pypdf` reconstruit la geometrie par des espaces, ce
    qui rend le tableau lisible ligne par ligne. Il ne sert qu'aux LIGNES ;
    les champs d'en-tete restent lus sur le texte simple, ou l'ancrage est
    plus fiable qu'une position.

    Une page dont la geometrie n'est pas exploitable retombe sur le texte
    simple : une facture lisible ne doit pas echouer pour un mode d'extraction.
    """
    if not est_pdf(donnees):
        raise FactureIllisibleError("Ce fichier n'est pas un PDF.")
    try:
        lecteur = PdfReader(BytesIO(donnees))
        pages: list[str] = []
        for page in lecteur.pages:
            try:
                pages.append(page.extract_text(extraction_mode="layout") or "")
            except Exception:  # geometrie indisponible : le texte simple suffit
                pages.append(page.extract_text() or "")
    except Exception as exc:  # pypdf leve des types varies selon la corruption
        raise FactureIllisibleError(f"PDF illisible : {exc}") from exc
    return _normaliser_typographie("\n".join(pages))


def detecter_scan(texte: str) -> bool:
    """Vrai quand le PDF n'a pas de couche texte exploitable.

    Un scan produit une page image : `extract_text` rend une chaine vide ou
    quelques artefacts. On compte les caracteres alphanumeriques, pas les
    espaces : un PDF de scan n'est pas « lu » parce qu'il contient des sauts
    de ligne.
    """
    utiles = sum(1 for caractere in texte if caractere.isalnum())
    return utiles < SEUIL_TEXTE_UTILE


# ---------------------------------------------------------------------------
# Ancres de libelles
# ---------------------------------------------------------------------------
class _Ancre(NamedTuple):
    groupe: str
    reste: str
    libelle: str


#: Les variantes de libelles, par champ. L'ordre n'importe pas : la recherche
#: privilegie toujours le libelle le plus long (« Date de facture » avant
#: « Date », « Code acte » avant « Code »).
_LIBELLES: dict[str, tuple[str, ...]] = {
    "reference": (
        "N° de facture",
        "N° facture",
        "No de facture",
        "No facture",
        "Numero de facture",
        "Numero facture",
        "Facture n°",
        "Facture no",
        "Reference facture",
        "Reference",
        "Ref facture",
        "Ref",
    ),
    "assure": (
        "N° assure",
        "No assure",
        "Numero assure",
        "Numero de l'assure",
        "Assure principal",
        "Nom de l'assure",
        "Nom patient",
        "Nom et prenoms",
        "Assure",
        "Beneficiaire",
        "Adherent",
        "Patient",
    ),
    "prestataire": (
        "Nom du prestataire",
        "Nom prestataire",
        "N° O.N.M",
        "No O.N.M",
        "Numero O.N.M",
        "Numero ONM",
        "N° ONM",
        "Etablissement",
        "Prestataire",
        "Pharmacie",
        "Cabinet",
        "Clinique",
        "Laboratoire",
        "NIF",
    ),
    "date": (
        "Date de facture",
        "Date facture",
        "Date d'emission",
        "Date emission",
        "Date des soins",
        "Date de soin",
        "Date du jour",
        "Date",
    ),
    "date_acte": (
        "Date de l'acte",
        "Date acte",
        "Date du soin",
        "Date soin",
    ),
    "acte": (
        "Libelle de l'acte",
        "Libelle acte",
        "Code de l'acte",
        "Code acte",
        "Designation",
        "Acte",
        "Code",
    ),
    "quantite": (
        "Quantite",
        "Qte",
        "Nombre",
        "Nb",
    ),
    "pu": (
        "Montant unitaire",
        "Prix unitaire",
        "P.U.",
        "P.U",
        "PU",
    ),
    "total": (
        "Montant total",
        "Net a payer",
        "Total a payer",
        "Total TTC",
        "Total general",
        "Total",
    ),
}

#: Libelles tries du plus long au plus court, avec leur groupe.
_ANCRES: tuple[tuple[str, str], ...] = tuple(
    sorted(
        ((libelle, groupe) for groupe, libelles in _LIBELLES.items() for libelle in libelles),
        key=lambda couple: len(_cle(couple[0])),
        reverse=True,
    )
)

_MOTIFS = {
    libelle: re.compile(r"\s+".join(re.escape(partie) for partie in _cle(libelle).split()))
    for libelle, _ in _ANCRES
}

#: Un code d'acte ressemble a `DENT-CONS`, `MED-PARA500`, `CONS_001`...
_RESSEMBLE_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{1,19}$")


def _ancre(ligne: str) -> _Ancre | None:
    """Le libelle reconnu dans une ligne et la valeur qui le suit.

    `pypdf` pouvant coller libelle et valeur sur la meme ligne, le « reste »
    est ce qui vient apres le libelle. Il peut etre vide : la valeur est alors
    a la ligne suivante (traite par `_valeurs_groupe`).
    """
    cible = _sans_accents(ligne).upper()
    for libelle, groupe in _ANCRES:
        recherche = _MOTIFS[libelle].search(cible)
        if recherche is None:
            continue
        debut, fin = recherche.span()
        # Un libelle court ne doit pas matcher au milieu d'un mot.
        if debut > 0 and cible[debut - 1].isalnum():
            continue
        if fin < len(cible) and cible[fin].isalnum():
            continue
        # « Sous-total » n'est pas le total de la facture.
        if groupe == "total" and "SOUS" in cible[:debut]:
            continue
        # « Date de naissance » n'est pas la date de la facture.
        if groupe == "date" and "NAISSANCE" in cible[fin:]:
            continue
        reste = ligne[fin:].lstrip(" \t:=\uff1a\u00a0\u202f")
        return _Ancre(groupe=groupe, reste=reste.strip(), libelle=libelle)
    return None


def _lignes_utiles(texte: str) -> list[str]:
    """Les lignes non vides, espaces compactes, separateurs retires."""
    lignes: list[str] = []
    for brute in texte.splitlines():
        ligne = re.sub(r"\s+", " ", brute).strip()
        if not ligne:
            continue
        if re.fullmatch(r"[-_.=*~\s]+", ligne):
            continue
        lignes.append(ligne)
    return lignes


def _valeurs_groupe(lignes: list[str], groupe: str, *, multiples: bool = False) -> list[str]:
    """Les valeurs qui suivent les libelles d'un groupe, dans l'ordre du texte.

    `multiples=True` sert aux actes : un libelle « Code acte » peut etre suivi
    de plusieurs codes quand `pypdf` a aplati un tableau en colonnes.
    """
    valeurs: list[str] = []
    for index, ligne in enumerate(lignes):
        ancre = _ancre(ligne)
        if ancre is None or ancre.groupe != groupe:
            continue
        if ancre.reste:
            valeurs.append(ancre.reste)
            continue
        # Valeur a la ligne suivante : on saute les lignes vides, on s'arrete
        # des qu'un nouveau libelle apparait.
        suivant = index + 1
        while suivant < len(lignes):
            candidat = lignes[suivant]
            suivant += 1
            if not candidat:
                continue
            if _ancre(candidat) is not None:
                break
            accepte = _RESSEMBLE_CODE.match(candidat) is not None
            if groupe == "acte" and _cle(ancre.libelle).startswith("LIBELLE"):
                accepte = True
            if groupe != "acte":
                accepte = True
            if not accepte:
                break
            valeurs.append(candidat)
            if not multiples:
                break
    return valeurs


def _valeur_champ(lignes: list[str], groupe: str) -> str:
    valeurs = _valeurs_groupe(lignes, groupe)
    return valeurs[0] if valeurs else ""


#: Un code prestataire du referentiel (`PRE-00062`).
_CODE_PRESTATAIRE = re.compile(r"^PRE-[A-Za-z0-9]+$")

#: Les libelles qui peuvent designer l'enseigne en tete de document plutot que
#: le prestataire lui-meme. « CABINET MEDICAL ESPOIR » en haut de page n'est
#: pas la valeur du champ `prestataire_id`.
_LIBELLES_PRESTATAIRE_GENERIQUES = frozenset(
    {"PHARMACIE", "CABINET", "CLINIQUE", "LABORATOIRE", "ETABLISSEMENT"}
)

#: Les libelles qui portent un IDENTIFIANT (exact en base, mais muet pour
#: l'utilisateur) : ils passent apres le nom de l'etablissement.
_LIBELLES_PRESTATAIRE_IDENTIFIANTS = frozenset(
    {"NIF", "N O N M", "NO O N M", "NUMERO O N M", "NUMERO ONM", "N ONM", "ONM"}
)

#: Un identifiant d'assure : `ASS-...` (brut) ou `assr_...` (pseudonyme).
_IDENTIFIANT_ASSURE = re.compile(r"\b(?:ASS|assr)[-_][A-Za-z0-9]{4,}\b")

#: Les mots d'en-tete qui ne sont jamais une enseigne.
_MOTS_ENTETE = frozenset(
    {
        "FACTURE",
        "FACTURES",
        "DEVIS",
        "RECU",
        "ORDONNANCE",
        "NOTE",
        "TICKET",
        "AVOIR",
        "PAGE",
        "DOCUMENT",
    }
)


def _valeur_apres(lignes: list[str], index: int, ancre: _Ancre) -> str:
    """La valeur ecrite a la ligne suivante, s'il y en a une.

    `pypdf` separe souvent le libelle de sa valeur. On s'arrete des qu'un
    nouveau libelle apparait : sinon la ligne suivante serait lue comme une
    valeur alors qu'elle appartient a un autre champ.
    """
    suivant = index + 1
    while suivant < len(lignes):
        candidat = lignes[suivant]
        suivant += 1
        if not candidat:
            continue
        if _ancre(candidat) is not None:
            return ""
        if (
            ancre.groupe == "acte"
            and not _RESSEMBLE_CODE.match(candidat)
            and not _cle(ancre.libelle).startswith("LIBELLE")
        ):
            return ""
        return candidat
    return ""


def _enseigne(lignes: list[str]) -> str:
    """Le nom de l'etablissement, quand il ouvre le document.

    Une facture commence presque toujours par l'enseigne. La valeur n'est
    qu'un CANDIDAT : si elle ne correspond a aucun prestataire, la resolution
    essaie les indices suivants. On ecarte donc les lignes qui sont deja un
    champ, une adresse ou un numero.
    """
    for ligne in lignes[:8]:
        candidat = ligne.strip()
        if not candidat:
            continue
        if _ancre(candidat) is not None:
            return ""
        if any(mot in _MOTS_ENTETE for mot in _mot(candidat).split()):
            continue
        if re.search(r"\d{2,}", candidat):  # telephone, NIF, code postal
            continue
        if not 2 <= len(candidat.split()) <= 8:
            continue
        if sum(1 for caractere in candidat if caractere.isalpha()) < 3:
            continue
        return candidat
    return ""


def _candidats_prestataire(lignes: list[str]) -> list[str]:
    """Les indices de prestataire du document, du plus sur au plus douteux.

    Un document porte souvent plusieurs indices — enseigne en tete, libelle
    explicite, NIF, code interne — et ils ne se valent pas. Les rendre tous,
    dans l'ordre, permet a la resolution d'essayer le suivant quand le plus
    visible ne correspond a rien : une enseigne mal orthographiee ne fait plus
    perdre une facture dont le NIF est exact.
    """
    trouves: list[tuple[str, str, bool]] = []
    for index, ligne in enumerate(lignes):
        ancre = _ancre(ligne)
        if ancre is None or ancre.groupe != "prestataire":
            continue
        reste = ancre.reste
        if not reste:
            reste = _valeur_apres(lignes, index, ancre)
        if not reste:
            continue
        libelle = _mot(ancre.libelle)
        meme_ligne = ancre.reste != ""
        if libelle in _LIBELLES_PRESTATAIRE_GENERIQUES and meme_ligne and ":" not in ligne:
            # « Pharmacie Vatolampy » : l'ancre fait partie du nom. La retirer
            # donnerait « Vatolampy », introuvable dans `core.prestataire`.
            cible = _sans_accents(ligne).upper()
            correspondance = _MOTIFS[ancre.libelle].search(cible)
            prefixe = ligne[: correspondance.end()].strip() if correspondance else ancre.libelle
            reste = f"{prefixe} {reste}".strip()
        trouves.append((reste, libelle, bool(re.search(r"[:=]", ligne))))

    candidats: list[str] = []

    def _ajouter(valeur: str) -> None:
        # Un meme libelle peut porter deux indices (« NIF 520... - ONM-81702 ») :
        # les separer multiplie les chances d'en reconnaitre un.
        for part in re.split(r"\s+-\s+", valeur.strip()):
            propre = part.strip(" -")
            if propre and propre not in candidats:
                candidats.append(propre)

    # 1. un code du referentiel : la seule preuve non ambigue.
    for valeur, _, _ in trouves:
        if _CODE_PRESTATAIRE.match(valeur):
            _ajouter(valeur)
    # 2. un libelle explicite, avec separateur puis sans.
    for valeur, libelle, separateur in trouves:
        if separateur and libelle not in _LIBELLES_PRESTATAIRE_IDENTIFIANTS:
            _ajouter(valeur)
    for valeur, libelle, _ in trouves:
        if libelle not in _LIBELLES_PRESTATAIRE_IDENTIFIANTS:
            _ajouter(valeur)
    # 3. l'enseigne en tete de document.
    _ajouter(_enseigne(lignes))
    # 4. les identifiants : exacts, mais ils ne nomment pas l'etablissement.
    for valeur, libelle, _ in trouves:
        if libelle in _LIBELLES_PRESTATAIRE_IDENTIFIANTS:
            _ajouter(valeur)
    return candidats


def _valeur_prestataire(lignes: list[str]) -> str:
    """Le meilleur indice de prestataire (le premier candidat)."""
    candidats = _candidats_prestataire(lignes)
    return candidats[0] if candidats else ""


#: Priorite des libelles de date : la date de FACTURE prime sur la date des
#: soins, qui peut differer (constate sur 7 factures sur 30 du lot de test).
_PRIORITE_DATE = (
    "DATE DE FACTURE",
    "DATE FACTURE",
    "DATE D EMISSION",
    "DATE EMISSION",
    "DATE DU JOUR",
    "DATE DES SOINS",
    "DATE DE SOIN",
    "DATE",
)


def _valeur_date(lignes: list[str]) -> str:
    """La date de facture, en preferant le libelle le plus explicite."""
    candidats: list[tuple[int, str]] = []
    for index, ligne in enumerate(lignes):
        ancre = _ancre(ligne)
        if ancre is None or ancre.groupe != "date":
            continue
        valeur = ancre.reste or _valeur_apres(lignes, index, ancre)
        if not valeur:
            continue
        libelle = _mot(ancre.libelle)
        rang = (
            _PRIORITE_DATE.index(libelle)
            if libelle in _PRIORITE_DATE
            else len(_PRIORITE_DATE)
        )
        candidats.append((rang, valeur))
    if not candidats:
        return ""
    return min(candidats, key=lambda couple: couple[0])[1]


def _valeur_assure(lignes: list[str]) -> str:
    """L'assure du document, en preferant un IDENTIFIANT a un nom.

    Un nom ne se resout qu'avec l'index hors-ligne des identites, absent de
    l'API ; un `ASS-...` se pseudonymise directement et se verifie en base.
    Preferer l'identifiant rend donc l'import independant d'un fichier de
    donnees personnelles.
    """
    valeurs: list[tuple[int, str]] = []
    for index, ligne in enumerate(lignes):
        ancre = _ancre(ligne)
        if ancre is None or ancre.groupe != "assure":
            continue
        valeur = ancre.reste or _valeur_apres(lignes, index, ancre)
        if not valeur:
            continue
        identifiant = _IDENTIFIANT_ASSURE.search(valeur)
        if identifiant is not None:
            valeurs.append((0, identifiant.group(0)))
        else:
            valeurs.append((1, valeur))
    if valeurs:
        return min(valeurs, key=lambda couple: couple[0])[1]
    # L'identifiant peut apparaitre sans libelle (« ASS-... » seul).
    for ligne in lignes:
        identifiant = _IDENTIFIANT_ASSURE.search(ligne)
        if identifiant is not None:
            return identifiant.group(0)
    return ""


# ---------------------------------------------------------------------------
# Lecture d'un tableau de facture
# ---------------------------------------------------------------------------
#: Les colonnes d'une ligne de facture, avec les libelles qu'on rencontre.
#: L'ordre de cette liste n'impose rien : c'est l'EN-TETE du document qui
#: donne la position de chaque colonne. Un gabarit qui place « Montant » avant
#: « P.U. », ou qui ajoute une colonne, reste donc lisible.
_ROLES_TABLEAU: tuple[tuple[str, frozenset[str]], ...] = (
    (
        "code",
        frozenset(
            {
                "CODE",
                "CODE ACTE",
                "CODE DE L ACTE",
                "CODE MEDICAMENT",
                "CODE PRODUIT",
                "CODE PRESTATION",
                "REFERENCE",
                "REF",
                "ARTICLE",
            }
        ),
    ),
    (
        "libelle",
        frozenset(
            {"DESIGNATION", "LIBELLE", "DESCRIPTION", "PRESTATION", "ACTE", "PRODUIT", "SOIN"}
        ),
    ),
    ("quantite", frozenset({"QTE", "QUANTITE", "NOMBRE", "NB", "QTY", "NBR"})),
    (
        "pu",
        frozenset({"P U", "PU", "PRIX UNITAIRE", "PRIX U", "MONTANT UNITAIRE", "PRIX", "TARIF"}),
    ),
    (
        "montant",
        frozenset(
            {"MONTANT", "TOTAL LIGNE", "MONTANT LIGNE", "TOTAL", "MONTANT AR", "MONTANT MGA"}
        ),
    ),
)

#: Les libelles qui ferment le tableau (pied de facture).
_FIN_TABLEAU = (
    "TOTAL",
    "SOUS TOTAL",
    "ARRETE",
    "ARRETEE",
    "NET A PAYER",
    "MONTANT TOTAL",
    "SIGNATURE",
    "CACHET",
    "TVA",
    "IBAN",
    "COORDONNEES",
    "MERCI",
)


def _cellules(ligne: str) -> list[str]:
    """Decoupe une ligne mise en page en cellules.

    Le mode `layout` separe les colonnes par au moins deux espaces ; un espace
    isole reste a l'interieur d'un libelle (« Consultation generale »).
    """
    return [cellule.strip() for cellule in re.split(r"\s{2,}", ligne.strip()) if cellule.strip()]


def _role_colonne(cellule: str) -> str | None:
    """Le role d'un libelle de colonne, ou `None`."""
    mot = _mot(cellule)
    for role, libelles in _ROLES_TABLEAU:
        if mot in libelles:
            return role
    return None


def _roles_entete(cellules: list[str]) -> dict[str, int]:
    """Les positions des colonnes reconnues dans une ligne d'en-tete."""
    roles: dict[str, int] = {}
    for position, cellule in enumerate(cellules):
        role = _role_colonne(cellule)
        if role is not None and role not in roles:
            roles[role] = position
    return roles


def _entete_valide(roles: dict[str, int]) -> bool:
    """Un en-tete de facture doit au moins porter un code et un montant."""
    return len(roles) >= 3 and "code" in roles and ("montant" in roles or "pu" in roles)


def _montant_ou_none(valeur: str) -> float | None:
    try:
        return normaliser_montant(valeur)
    except ValueError:
        return None


def _dernier_montant(cellules: list[str]) -> float | None:
    """Le dernier montant lisible d'une ligne (« TOTAL ... 23 000 Ar »)."""
    for cellule in reversed(cellules):
        valeur = _montant_ou_none(cellule)
        if valeur is not None:
            return valeur
    return None


def _ligne_tableau(cellules: list[str], roles: dict[str, int], surplus: int) -> dict | None:
    """Une ligne de facture, ou `None` si la ligne n'en est pas une.

    `surplus` est le nombre de cellules en trop par rapport a l'en-tete :
    elles appartiennent toutes a la colonne « libelle », la seule qui puisse
    contenir des espaces que la mise en page n'a pas separes.
    """
    position_libelle = roles.get("libelle", 1)

    def _cellule(role: str) -> str:
        position = roles.get(role)
        if position is None:
            return ""
        if position > position_libelle:
            position += surplus
        return cellules[position] if 0 <= position < len(cellules) else ""

    code = _cellule("code").strip()
    if not code or _RESSEMBLE_CODE.match(code) is None:
        return None

    libelle = " ".join(cellules[position_libelle : position_libelle + surplus + 1]).strip()
    quantite = _entier(_cellule("quantite"), 0)
    prix = _montant_ou_none(_cellule("pu"))
    montant = _montant_ou_none(_cellule("montant"))

    if quantite <= 0:
        quantite = 1
    if prix is None and montant is not None:
        prix = montant / quantite
    if prix is None:
        return None
    if montant is None:
        montant = prix * quantite

    return {
        "code_acte": code,
        "quantite": quantite,
        "montant_unitaire": round(prix, 2),
        "libelle": libelle,
        "montant": round(montant, 2),
    }


def _lire_tableau_mis_en_page(texte: str) -> tuple[list[dict], float | None]:
    """Les lignes d'un tableau de facture, lues par colonnes.

    Rend `(lignes, total)` : `total` est le montant de la ligne « TOTAL »
    rencontree, quand elle en porte un.
    """
    lignes = [ligne.rstrip() for ligne in texte.splitlines() if ligne.strip()]
    entete: tuple[int, int, dict[str, int]] | None = None
    for index, ligne in enumerate(lignes):
        cellules = _cellules(ligne)
        if len(cellules) < 3:
            continue
        roles = _roles_entete(cellules)
        if _entete_valide(roles):
            entete = (index, len(cellules), roles)
            break
    if entete is None:
        return [], None

    debut, nombre_colonnes, roles = entete
    lues: list[dict] = []
    total: float | None = None
    for ligne in lignes[debut + 1 :]:
        cellules = _cellules(ligne)
        if not cellules:
            continue
        if any(_mot(cellules[0]).startswith(fin) for fin in _FIN_TABLEAU):
            montant = _dernier_montant(cellules[1:])
            if montant is not None:
                total = montant
            break
        surplus = max(0, len(cellules) - nombre_colonnes)
        lue = _ligne_tableau(cellules, roles, surplus)
        if lue is None:
            # Une designation coupee par la mise en page continue seule : on
            # la recolle a la ligne precedente au lieu de la perdre.
            if lues and len(cellules) == 1:
                lues[-1]["libelle"] = (lues[-1]["libelle"] + " " + cellules[0]).strip()
            continue
        lues.append(lue)
    return lues, total


def _lire_tableau_texte(lignes: list[str]) -> tuple[list[dict], float | None]:
    """Repli : tableau lu sur le texte simple, ou les cellules sont en colonne.

    Sans geometrie, `pypdf` rend une cellule par ligne. On reconnait l'en-tete
    comme une SUITE de libelles de colonnes, puis on groupe les lignes
    suivantes par paquets de N. Ce repli ne s'applique que si l'en-tete est
    complet, sinon il inventerait des lignes.
    """
    for index in range(len(lignes) - 2):
        roles: dict[str, int] = {}
        suivant = index
        while suivant < len(lignes):
            role = _role_colonne(lignes[suivant])
            if role is None or role in roles:
                break
            roles[role] = len(roles)
            suivant += 1
        if len(roles) < 4 or not _entete_valide(roles):
            continue
        nombre_colonnes = len(roles)
        corps = lignes[suivant:]
        lues: list[dict] = []
        total: float | None = None
        index_courant = 0
        while index_courant + nombre_colonnes <= len(corps):
            cellules = corps[index_courant : index_courant + nombre_colonnes]
            if any(_mot(cellules[0]).startswith(fin) for fin in _FIN_TABLEAU):
                montant = _dernier_montant(cellules[1:])
                if montant is not None:
                    total = montant
                break
            lue = _ligne_tableau(cellules, roles, 0)
            if lue is None:
                break
            lues.append(lue)
            index_courant += nombre_colonnes
        return lues, total
    return [], None


# ---------------------------------------------------------------------------
# Normalisation des dates et des montants
# ---------------------------------------------------------------------------
_MOIS = {
    "JANVIER": 1,
    "FEVRIER": 2,
    "MARS": 3,
    "AVRIL": 4,
    "MAI": 5,
    "JUIN": 6,
    "JUILLET": 7,
    "AOUT": 8,
    "SEPTEMBRE": 9,
    "OCTOBRE": 10,
    "NOVEMBRE": 11,
    "DECEMBRE": 12,
}


def normaliser_montant(valeur: str) -> float:
    """« 20 000 Ar », « 39 000,50 MGA », « 1 234.56 » -> 20000.0, 39000.5...

    Le dernier separateur rencontre est decimal ; les autres sont des
    separateurs de milliers. Les devises (`Ar`, `MGA`, `Ariary`) sont ignorees.
    """
    texte = _normaliser_typographie(str(valeur)).strip()
    negatif = texte.startswith("-") or (texte.startswith("(") and texte.endswith(")"))
    nettoye = re.sub(r"[^0-9,.]", "", texte)
    if not nettoye or not re.search(r"\d", nettoye):
        raise ValueError(f"Montant illisible : {valeur!r}")

    if "," in nettoye and "." in nettoye:
        if nettoye.rfind(",") > nettoye.rfind("."):
            nettoye = nettoye.replace(".", "").replace(",", ".")
        else:
            nettoye = nettoye.replace(",", "")
    elif "," in nettoye:
        if nettoye.count(",") == 1 and len(nettoye.split(",")[-1]) <= 2:
            nettoye = nettoye.replace(",", ".")
        else:
            nettoye = nettoye.replace(",", "")
    elif nettoye.count(".") > 1:
        parties = nettoye.split(".")
        nettoye = "".join(parties[:-1]) + "." + parties[-1]

    try:
        montant = float(nettoye)
    except ValueError as exc:
        raise ValueError(f"Montant illisible : {valeur!r}") from exc
    return round(-montant if negatif else montant, 2)


def normaliser_date(valeur: str) -> str:
    """« 20/10/2026 », « 2026-10-20 », « 20 octobre 2026 » -> ISO 8601.

    La date de facture est une date, pas un instant : l'heure est minuit.
    """
    texte = _sans_accents(_normaliser_typographie(str(valeur))).strip().upper()

    correspondance = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", texte)
    if correspondance:
        annee, mois, jour = (int(partie) for partie in correspondance.groups())
    else:
        correspondance = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", texte)
        if correspondance:
            jour, mois, annee = (int(partie) for partie in correspondance.groups())
        else:
            correspondance = re.search(r"(\d{1,2})(?:ER)?\s+([A-Z]+)\s+(\d{4})", texte)
            if correspondance is None or correspondance.group(2) not in _MOIS:
                raise ValueError(f"Date illisible : {valeur!r}")
            jour = int(correspondance.group(1))
            mois = _MOIS[correspondance.group(2)]
            annee = int(correspondance.group(3))

    try:
        valide = date(annee, mois, jour)
    except ValueError as exc:
        raise ValueError(f"Date illisible : {valeur!r}") from exc
    return f"{valide.year:04d}-{valide.month:02d}-{valide.day:02d}T00:00:00"


def _entier(valeur: str, defaut: int = 1) -> int:
    correspondance = re.search(r"-?\d+", _normaliser_typographie(valeur))
    return int(correspondance.group()) if correspondance else defaut


# ---------------------------------------------------------------------------
# Extraction d'une facture
# ---------------------------------------------------------------------------
def reference_deterministe(donnees: bytes) -> str:
    """Une reference stable et deterministe : `FAC-` + sha256 tronque.

    `core.facture.reference` est UNIQUE et l'enregistrement ignore
    silencieusement un doublon. Un UUID ferait donc creer 20 doublons a chaque
    rejeu du meme fichier ; le hachage rend le depot idempotent.
    """
    return f"FAC-{hashlib.sha256(donnees).hexdigest()[:12].upper()}"


def _champ_manquant(nom: str, champ: str) -> ChampIntrouvableError:
    if champ == "lignes.0.code_acte":
        # Diagnostic utile quand le document n'a aucun tableau lisible : dire
        # « champ introuvable » sans plus laisserait l'utilisateur sans piste.
        return ChampIntrouvableError(
            f"Aucune ligne de facture lisible dans le PDF ({nom}) : un tableau "
            "avec un code d'acte par ligne est attendu (champ technique : "
            "lignes.0.code_acte)."
        )
    return ChampIntrouvableError(f"Champ introuvable dans le PDF ({nom}) : {champ}")


def _lire_lignes(donnees: bytes, lignes_texte: list[str]) -> tuple[list[dict], float | None]:
    """Les lignes de facture, par trois lectures de la plus structuree a la plus libre.

    1. le tableau lu par colonnes (`layout`) : le cas nominal ;
    2. le tableau lu sur le texte simple, quand chaque cellule est sur sa ligne ;
    3. les ancres de libelles, pour une facture ecrite en clair
       (« Code acte : LAB-NFS »).

    Le premier resultat non vide gagne : une lecture ne doit jamais inventer
    des lignes pour en remplacer d'autres.
    """
    try:
        texte_mis_en_page = extraire_texte_mis_en_page(donnees)
    except FactureIllisibleError:
        texte_mis_en_page = ""
    if texte_mis_en_page:
        lues, total = _lire_tableau_mis_en_page(texte_mis_en_page)
        if lues:
            return lues, total

    lues, total = _lire_tableau_texte(lignes_texte)
    if lues:
        return lues, total

    codes = _valeurs_groupe(lignes_texte, "acte", multiples=True)
    quantites = _valeurs_groupe(lignes_texte, "quantite", multiples=True)
    prix = _valeurs_groupe(lignes_texte, "pu", multiples=True)
    lignes: list[dict] = []
    for index, code in enumerate(codes):
        quantite = _entier(quantites[index]) if index < len(quantites) else 1
        try:
            montant_unitaire = normaliser_montant(prix[index]) if index < len(prix) else 0.0
        except ValueError:
            montant_unitaire = 0.0
        lignes.append(
            {
                "code_acte": code,
                "quantite": quantite,
                "montant_unitaire": montant_unitaire,
            }
        )
    return lignes, None


def extraire_facture(
    donnees: bytes, *, nom: str = "", prestataire_defaut: str = ""
) -> FactureExtraite:
    """Lit une facture PDF, sans base ni reseau.

    Les champs obligatoires manquants levent `ChampIntrouvableError` en nommant
    le champ TECHNIQUE attendu par l'API. Un PDF scanne leve
    `PdfSansTexteError` ; un fichier qui n'est pas un PDF leve
    `FactureIllisibleError`.

    `prestataire_defaut` est le repli de `--prestataire` (et de l'import API) :
    il ne s'applique QUE si le document ne porte aucun prestataire. Le defaut
    vide conserve le comportement strict du contrat public.
    """
    source = nom or "document.pdf"
    if not est_pdf(donnees):
        raise FactureIllisibleError(f"Ce fichier n'est pas un PDF : {source}")

    texte = extraire_texte(donnees)
    if detecter_scan(texte):
        raise PdfSansTexteError(MESSAGE_SCAN)

    lignes_texte = _lignes_utiles(texte)

    assure = _valeur_assure(lignes_texte)
    candidats_prestataire = _candidats_prestataire(lignes_texte)
    prestataire = (
        candidats_prestataire[0] if candidats_prestataire else ""
    ) or prestataire_defaut
    date_brute = _valeur_date(lignes_texte)
    total_brut = _valeur_champ(lignes_texte, "total")

    try:
        date_facture = normaliser_date(date_brute) if date_brute else ""
    except ValueError:
        date_facture = ""

    lignes_lues, total_tableau = _lire_lignes(donnees, lignes_texte)

    for champ, valeur in (
        ("assure_pseudonyme", assure),
        ("prestataire_id", prestataire),
        ("date_facture", date_facture),
        ("lignes.0.code_acte", lignes_lues[0]["code_acte"] if lignes_lues else ""),
    ):
        if not valeur:
            raise _champ_manquant(source, champ)

    lignes = [
        {
            "code_acte": lue["code_acte"],
            "quantite": lue["quantite"],
            "montant_unitaire": lue["montant_unitaire"],
            "date_acte": date_facture,
        }
        for lue in lignes_lues
    ]

    somme = round(sum(ligne["quantite"] * ligne["montant_unitaire"] for ligne in lignes), 2)
    try:
        montant_total = normaliser_montant(total_brut) if total_brut else None
    except ValueError:
        montant_total = None

    # Un total absent se lit dans la ligne « TOTAL » du tableau, puis se
    # calcule a partir des lignes.
    if montant_total is None:
        montant_total = total_tableau
    if montant_total is None:
        # Ni total, ni prix unitaire : il n'y a rien a calculer, le champ est
        # reellement absent du document.
        if all(ligne["montant_unitaire"] <= 0 for ligne in lignes):
            raise _champ_manquant(source, "montant_total")
        montant_total = somme
    elif montant_total < 0:
        montant_total = somme

    # Le total du document est conserve meme s'il s'ecarte de la somme : c'est
    # l'API qui rejette l'incoherence (condition « rejet propre »), pas
    # l'extraction.
    return FactureExtraite(
        reference=reference_deterministe(donnees),
        assure=assure,
        prestataire=prestataire,
        date_facture=date_facture,
        lignes=tuple(lignes),
        montant_total=round(montant_total, 2),
        source=source,
        prestataires=tuple(candidats_prestataire),
    )


def payload_de(
    extraite: FactureExtraite,
    *,
    assure_pseudonyme: str | None = None,
    prestataire_id: str | None = None,
) -> dict:
    """La charge `InvoiceSubmission` attendue par `POST /factures/soumettre`.

    Les surcharges viennent de la resolution en base : un nom devient un
    pseudonyme, un nom d'etablissement devient un code `PRE-...`.
    """
    return {
        "facture_id": extraite.reference,
        "assure_pseudonyme": (
            assure_pseudonyme if assure_pseudonyme is not None else extraite.assure
        ),
        "prestataire_id": (prestataire_id if prestataire_id is not None else extraite.prestataire),
        "date_facture": extraite.date_facture,
        "montant_total": extraite.montant_total,
        "lignes": [dict(ligne) for ligne in extraite.lignes],
    }


# ---------------------------------------------------------------------------
# Resolution stricte en base : on ne cree JAMAIS de referentiel
# ---------------------------------------------------------------------------
def _chemin_identites() -> Path:
    """L'index hors-ligne des identites, dans l'ordre de priorite du produit."""
    impose = os.environ.get("IDENTITES_PII", "").strip()
    if impose:
        return Path(impose)
    conteneur = Path("/data/raw/identites_pii.csv")
    if conteneur.exists():
        return conteneur
    return Path("data/raw/identites_pii.csv")


def _index_identites() -> dict[str, set[str]]:
    """« NOM PRENOMS » et « PRENOMS NOM » normalises -> identifiants bruts.

    C'est la SEULE voie nom -> identifiant. `core.identite_chiffree` n'est
    jamais dechiffree ici : le RGPD impose que les noms restent hors base.
    """
    chemin = _chemin_identites()
    if not chemin.exists():
        raise ChampIntrouvableError(
            f"assure_pseudonyme : index des identites introuvable ({chemin}). "
            "Definissez IDENTITES_PII vers le CSV identites_pii.csv."
        )
    index: dict[str, set[str]] = {}
    try:
        with chemin.open(encoding="utf-8-sig", newline="") as flux:
            for ligne in csv.DictReader(flux):
                assure_id = (ligne.get("assure_id") or "").strip()
                nom = (ligne.get("nom") or "").strip()
                prenoms = (ligne.get("prenoms") or "").strip()
                if not assure_id or not nom:
                    continue
                cle_nom = _cle(f"{nom} {prenoms}")
                cle_inversee = _cle(f"{prenoms} {nom}")
                index.setdefault(cle_nom, set()).add(assure_id)
                if cle_inversee != cle_nom:
                    index.setdefault(cle_inversee, set()).add(assure_id)
    except OSError as exc:
        raise ChampIntrouvableError(
            f"assure_pseudonyme : index des identites illisible ({chemin}) : {exc}"
        ) from exc
    return index


def _verifier_assure(session: Session, pseudonyme: str, valeur: str) -> str:
    existe = session.execute(
        text("SELECT 1 FROM core.assure WHERE pseudonyme = :valeur"),
        {"valeur": pseudonyme},
    ).scalar()
    if existe is None:
        raise ChampIntrouvableError(f"assure_pseudonyme : valeur inconnue ({valeur})")
    return pseudonyme


def resoudre_assure(session: Session, valeur: str) -> str:
    """Un pseudonyme, un `ASS-...`, ou un nom -> le pseudonyme en base.

    Trois paliers, dans cet ordre : pseudonyme deja calcule, identifiant brut
    a pseudonymiser, puis index hors-ligne des identites. Aucune creation.
    """
    from predicare.crypto import pseudonymize

    brut = valeur.strip()
    if not brut:
        raise ChampIntrouvableError("assure_pseudonyme : valeur vide")

    if brut.startswith("assr_"):
        return _verifier_assure(session, brut, brut)

    if re.fullmatch(r"ASS-[A-Za-z0-9]+", brut):
        return _verifier_assure(session, pseudonymize("assr", brut), brut)

    candidats = sorted(_index_identites().get(_cle(brut), set()))
    if not candidats:
        raise ChampIntrouvableError(f"assure_pseudonyme : valeur inconnue ({brut})")
    if len(candidats) > 1:
        liste = " ; ".join(candidats)
        raise ChampIntrouvableError(f"assure_pseudonyme : valeur ambigue ({brut}) : {liste}")

    return _verifier_assure(session, pseudonymize("assr", candidats[0]), brut)


def resoudre_prestataire(session: Session, valeur: str, *, ville: str | None = None) -> str:
    """Un code `PRE-...`, un nom, un numero O.N.M ou un NIF -> le code en base.

    `core.prestataire.nom` n'est pas UNIQUE : une ville peut lever l'ambiguite.
    Sans discriminant, plusieurs candidats sont une ERREUR qui les nomme ; on
    ne devine jamais.
    """
    brut = valeur.strip()
    if not brut:
        raise ChampIntrouvableError("prestataire_id : valeur vide")

    if _cle(brut).startswith("PRE-"):
        code = session.execute(
            text("SELECT code FROM core.prestataire WHERE code = :valeur"),
            {"valeur": brut},
        ).scalar()
        if code is not None:
            return str(code)
        raise ChampIntrouvableError(f"prestataire_id : valeur inconnue ({brut})")

    lignes = session.execute(
        text("SELECT code, nom, ville, numero_onm, nif FROM core.prestataire")
    ).all()
    cible = _cle(brut)

    def _correspond(identifiant: object) -> bool:
        return _cle(str(identifiant or "")) == cible

    candidats = [ligne for ligne in lignes if _correspond(ligne[1])]
    if not candidats:
        # Le PDF peut porter « N° O.N.M » ou « NIF » a la place du nom : la
        # correspondance reste exacte, donc deterministe.
        candidats = [ligne for ligne in lignes if _correspond(ligne[3]) or _correspond(ligne[4])]
    if ville:
        candidats = [ligne for ligne in candidats if _cle(str(ligne[2] or "")) == _cle(ville)]

    if not candidats:
        raise ChampIntrouvableError(f"prestataire_id : valeur inconnue ({brut})")
    if len(candidats) > 1:
        liste = " ; ".join(
            f"{ligne[0]} - {ligne[1] or ''} - {ligne[2] or ''}" for ligne in candidats
        )
        raise ChampIntrouvableError(f"prestataire_id : valeur ambigue ({brut}) : {liste}")
    return str(candidats[0][0])


def resoudre_prestataire_parmi(
    session: Session, valeurs: tuple[str, ...] | list[str], *, ville: str | None = None
) -> str:
    """Le premier candidat prestataire qui se resout.

    Un PDF porte souvent plusieurs indices : l'enseigne en tete, un libelle
    explicite, un NIF. Les essayer dans l'ordre evite de rejeter une facture
    dont le NIF est exact sous pretexte que l'enseigne est mal orthographiee.
    L'ambiguite, elle, reste une erreur : on ne devine pas entre deux
    prestataires.
    """
    candidats = [valeur for valeur in valeurs if str(valeur).strip()]
    derniere: ChampIntrouvableError | None = None
    for valeur in candidats:
        try:
            return resoudre_prestataire(session, valeur, ville=ville)
        except ChampIntrouvableError as exc:
            derniere = exc
    if derniere is not None:
        raise derniere
    raise ChampIntrouvableError("prestataire_id : valeur vide")


def resoudre_acte(session: Session, valeur: str) -> str:
    """Un code d'acte OU de medicament -> le code du referentiel.

    Une facture de pharmacie ne porte pas de code d'acte : ses lignes sont des
    medicaments (`MED-...`), ranges dans `core.medicament`. Les deux
    referentiels sont donc interroges, dans cet ordre, et le code rendu est
    celui que l'API saura ranger dans `core.ligne_facture` (colonne `acte_id`
    ou `medicament_id`).

    Aucune creation : un code absent des deux referentiels est hors vocabulaire
    et doit etre rejete en le nommant.
    """
    brut = valeur.strip()
    if not brut:
        raise ChampIntrouvableError("lignes.0.code_acte : valeur vide")

    for table in ("core.acte", "core.medicament"):
        code = session.execute(
            text(f"SELECT code FROM {table} WHERE UPPER(code) = :valeur"),
            {"valeur": brut.upper()},
        ).scalar()
        if code is not None:
            return str(code)

    cible = _cle(brut)
    for table in ("core.acte", "core.medicament"):
        for code, libelle in session.execute(text(f"SELECT code, libelle FROM {table}")).all():
            if _cle(str(libelle or "")) == cible:
                return str(code)

    raise ChampIntrouvableError(f"lignes.0.code_acte : valeur inconnue ({brut})")
