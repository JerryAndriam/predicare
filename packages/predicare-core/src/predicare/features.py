"""Featurisation : d'une facture brute au vecteur de variables du modele.

Ce module est la SOURCE UNIQUE de la transformation facture -> variables.
L'entrainement (`apps/ml-training`) et l'inference (`apps/api-inference`)
appellent tous les deux `calculer_features` : c'est la seule facon de garantir
qu'un modele est note sur exactement les memes variables dans les deux mondes.
Une variable ajoutee ici doit l'etre dans les deux, jamais dans un seul.

Deux proprietes non negociables :

1. AUCUNE dependance externe. Ni pandas, ni base, ni reseau, ni horloge
   systeme. Les fonctions sont pures : meme entree, meme sortie, sur n'importe
   quelle machine. Un test unitaire ne demande donc ni conteneur ni PostgreSQL.

2. AUCUNE EXCEPTION. Une reference manquante (acte inconnu, prestataire
   inconnu, ordonnances introuvable, assure inconnu) ne doit jamais faire
   echouer la notation : la variable prend sa valeur neutre. Une facture
   inhabituelle doit etre NOTEE, pas reque 500. La base compte les references
   manquantes dans `references_manquantes` pour que la qualite du referentiel
   reste observable.

Perimetre : la version 1 (v1) n'utilise que des informations disponibles au
moment de la reception d'une facture ET un historique nul. Les agregats
historiques (surconsommation, fractionnement, reutilisation d'ordonnance) sont
deliberement absents : ils necessiteraient une requete d'historique a
l'inference, et un modele entrainner avec des agregats servis a zero decale
silencieusement la production. Ils arriveront en v2 avec l'enrichissement SQL.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

#: Devise unique du jeu de donnees (dictionnaire : « Devise Ariary (MGA) »).
DEVISE_ATTENDUE = "MGA"

#: Plafond annuel de reference utilise quand la formule de garantie est
#: inconnue. C'est le plafond le plus bas des trois formules du referentiel :
#: une valeur WILLE-CONSEQUENTE, pas un nombre sorti de l'air.
PLAFOND_ANNUEL_DEFAUT = 3_000_000.0

#: Ordre canonique des 32 variables. Cet ordre est celui de `features.json`
#: et donc celui du vecteur passe a `predict_proba`. Il est fige ici : le
#: renommer casse les modeles deja entraines.
NOMS_FEATURES: tuple[str, ...] = (
    # --- Structure de la facture -------------------------------------------
    "montant_total",
    "log1p_montant_total",
    "nb_lignes",
    "quantite_totale",
    "montant_moyen_ligne",
    "montant_max_ligne",
    "ratio_quantite",
    "diversification_actes",
    "nb_categories",
    "categorie_dominante_code",
    "part_actes_specialises",
    # --- Tarification -------------------------------------------------------
    "ratio_prix_grille_max",
    "ratio_prix_grille_moyen",
    "ecart_prix_grille_max",
    "ratio_prix_reference_max",
    "depasse_tarif_max",
    "produit_non_remboursable",
    # --- Prescription -------------------------------------------------------
    "taux_lignes_non_prescrites",
    "ordonnance_absente_requis",
    "ordonnance_expiree",
    "delai_prescription_jours",
    "prescripteur_different",
    # --- Coherence assure / referentiel -------------------------------------
    "incompatibilite_sexe",
    "incompatibilite_age",
    # --- Prestataire, convention, horaires ----------------------------------
    "prestataire_radie",
    "hors_convention",
    "soin_jour_ferme",
    "soin_hors_horaire",
    "prestataire_niveau_tarif_eleve",
    # --- Garantie et couverture ---------------------------------------------
    "montant_vs_plafond_garantie",
    "hors_periode_contrat",
    "taux_actes_exclus",
)

#: Ordre d'encodage ordinal des categories d'acte. Volontairement fige :
#: l'encodage est arbitraire mais reproductible, et un arbre peut le couper.
#: `CATEGORIE_INCONNUE` absorbe tout code absent du referentiel.
CATEGORIES_ACTES: tuple[str, ...] = (
    "CONSULTATION",
    "PHARMACIE",
    "LABORATOIRE",
    "IMAGERIE",
    "DENTAIRE",
    "KINESITHERAPIE",
    "MATERNITE",
    "OPTIQUE",
    "HOSPITALISATION",
)
CODE_CATEGORIE_INCONNUE = len(CATEGORIES_ACTES)

#: Specialites qui signifient « consultation complexe ». Une part elevee de ces
#: actes n'est pas frauduleuse en soi, mais elle change le profil de risque.
SPECIALITES_GENERALISTES = frozenset({"", "GENERALISTE"})


# ---------------------------------------------------------------------------
# Referentiels
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Acte:
    """Reference d'un acte du referentiel."""

    categorie: str = ""
    specialite: str = ""
    tarif_min: float = 0.0
    tarif_reference: float = 0.0
    tarif_max: float = 0.0
    ordonnance_requise: bool = False
    entente_prealable: bool = False
    sexe_requis: str = ""
    age_min: int = 0
    age_max: int = 120


@dataclass(frozen=True, slots=True)
class Medicament:
    """Reference d'un produit du referentiel."""

    prix_reference: float = 0.0
    remboursable: bool = True
    classe: str = ""
    chronique: bool = False


@dataclass(frozen=True, slots=True)
class Prestataire:
    """Attributes de conventionnement et d'ouverture d'un prestataire."""

    radie: bool = False
    conventionne: bool = True
    date_conventionnement: date | None = None
    date_fin_convention: date | None = None
    jours_ouverture: str = ""
    heure_ouverture: int = 0
    heure_fermeture: int = 24
    niveau_tarif: str = "RAISONNABLE"
    type_prestataire: str = ""
    note_qualite: int = 0


@dataclass(frozen=True, slots=True)
class GarantieCategorie:
    """Regles de remboursement d'une categorie pour une formule."""

    taux_remboursement: float = 0.0
    plafond_annuel_categorie: float = 0.0
    plafond_annuel_global: float = PLAFOND_ANNUEL_DEFAUT
    delai_carence_jours: int = 0
    actes_exclus: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Contrat:
    """Periode de couverture et formule d'un contrat."""

    date_effet: date | None = None
    date_fin: date | None = None
    formule: str = ""


@dataclass(frozen=True, slots=True)
class Ordonnance:
    """Ordonnance liee a la facture : sa validite et ce qu'elle prescrit.

    C'est la seule entite du contexte que l'inference doit aller chercher en
    base : les ordonnances sont creees en continu, elles ne peuvent donc pas
    etre versionnees avec le modele comme le referentiel.
    """

    prescripteur_id: str = ""
    date_prescription: date | None = None
    validite_jours: int = 0
    codes_prescrits: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Referentiels:
    """Les referentiels statiques, versionnes avec le modele.

    Ils sont petits (58 actes, 28 medicaments, 251 prestataires, 3 242 tarifs
    de grille, 27 garanties, 1 500 contrats) et statiques : les charger en
    memoire au demarrage evite six requetes par facture et rend la
    featurisation pure. Leur version voyage avec le modele : un changement de
    grille tarifaire impose un re-entrainement, ce qui evite de servir un
    modele note avec une grille perimee.
    """

    actes: Mapping[str, Acte] = field(default_factory=dict)
    medicaments: Mapping[str, Medicament] = field(default_factory=dict)
    #: Cle "<prestataire_id>|<code>" -> tarif pratique.
    grille: Mapping[str, float] = field(default_factory=dict)
    prestataires: Mapping[str, Prestataire] = field(default_factory=dict)
    #: "<formule>|<categorie>" -> regles.
    garanties: Mapping[str, GarantieCategorie] = field(default_factory=dict)
    contrats: Mapping[str, Contrat] = field(default_factory=dict)

    def tarif_grille(self, prestataire_id: str, code: str) -> float | None:
        return self.grille.get(f"{prestataire_id}|{code}")

    def garantie(self, formule: str, categorie: str) -> GarantieCategorie | None:
        return self.garanties.get(f"{formule}|{categorie}")


REFERENTIELS_VIDES = Referentiels()


# ---------------------------------------------------------------------------
# Facture d'entree
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class LigneFacture:
    """Une ligne de facture, vue par la featurisation.

    `date_acte` accepte un `datetime` : l'API de soumission transmet une
    horodatage, et c'est de lui qu'on tire l'heure du soin. Le CSV d'origine
    porte l'heure dans une colonne separee, que l'appelant lui injecte.
    """

    code: str
    quantite: int = 1
    montant_unitaire: float = 0.0
    date_acte: date | datetime | None = None


@dataclass(frozen=True, slots=True)
class FactureBrute:
    """Tout ce que la featurisation a besoin, et rien de plus.

    Les champs optionnels correspondent a des informations absentes de la
    payload de soumission : le service d'inference les resout en base quand il
    peut, et laisse a None quand il ne peut pas. La featurisation degrade
    alors vers ses valeurs neutres au lieu d'echouer.
    """

    montant_total: float = 0.0
    date_facture: date | None = None
    lignes: Sequence[LigneFacture] = ()
    #: Ordonnance resolue par l'appelant (jamais par ce module).
    ordonnance: Ordonnance | None = None
    #: Contrat resolu par l'appelant.
    contrat: Contrat | None = None
    #: Prestataire resolu par l'appelant, ou lu dans le referentiel.
    prestataire: Prestataire | None = None
    #: Annee de naissance et sexe de l'assure, si l'appelant les connait.
    assure_annee_naissance: int | None = None
    assure_sexe: str = ""
    #: Identifiants, uniquement utilises pour croiser le referentiel.
    prestataire_id: str = ""
    #: Liste des references introuvables, remplie par `calculer_features`.
    references_manquantes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Fonctions utilitaires (locales : ce module n'expose que deux API)
# ---------------------------------------------------------------------------
def _entier(valeur: Any, defaut: int = 0) -> int:
    try:
        if valeur is None or valeur == "":
            return defaut
        return int(float(valeur))
    except (TypeError, ValueError):
        return defaut


def _reel(valeur: Any, defaut: float = 0.0) -> float:
    try:
        if valeur is None or valeur == "":
            return defaut
        nombre = float(valeur)
    except (TypeError, ValueError):
        return defaut
    return nombre if math.isfinite(nombre) else defaut


def _texte(valeur: Any) -> str:
    if valeur is None:
        return ""
    return str(valeur).strip()


def _date(valeur: Any) -> date | None:
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    texte = _texte(valeur)
    if not texte:
        return None
    for gabarit in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(texte[: len(gabarit) + 6], gabarit).date()
        except ValueError:
            continue
    return None


def _jour(valeur: date | datetime) -> date:
    """Le jour, que l'appelant ait fourni une date ou un horodatage."""
    return valeur.date() if isinstance(valeur, datetime) else valeur


def _booleen(valeur: Any, defaut: bool = False) -> bool:
    """Lecture tolérante : `1`/`0`, `true`/`false`, `"1"`/`"0"`, `1.0`."""
    if isinstance(valeur, bool):
        return valeur
    if valeur is None or valeur == "":
        return defaut
    if isinstance(valeur, str):
        normalise = valeur.strip().lower()
        if normalise in {"1", "true", "oui", "yes", "vrai"}:
            return True
        if normalise in {"0", "false", "non", "no", "faux"}:
            return False
        return defaut
    try:
        return float(valeur) != 0.0
    except (TypeError, ValueError):
        return defaut


def _divise(numerateur: float, denominateur: float, defaut: float = 0.0) -> float:
    """Division sure : un denominateur nul ou non fini rend `defaut`.

    Sans ce garde-fou, une facture a montant total nul produirait un `inf`
    qui traverse l'entrainement et fait echouer `TreeExplainer` en service.
    """
    if denominateur == 0 or not math.isfinite(denominateur):
        return defaut
    resultat = numerateur / denominateur
    return resultat if math.isfinite(resultat) else defaut


def _borne(valeur: float, minimum: float = -1e6, maximum: float = 1e9) -> float:
    """Force une variable dans un intervalle exploitable par un arbre.

    Un `inf` ou un `NaN` dans le jeu d'entrainement produit un modele qui
    refuse de predire sur une valeur voisine. Mieux vaut une valeur extreme
    bornee, qui reste un signal fort et ne casse rien.
    """
    if not math.isfinite(valeur):
        return 0.0
    return max(minimum, min(maximum, valeur))


def _jours_fermes(jours_ouverture: str) -> set[int]:
    """Jours de la semaine declares fermes.

    `jours_ouverture` est une chaine de chiffres, `7` signifiant dimanche
    (`"1234567"` = ouvert tous les jours, `"123456"` = ferme le dimanche).
    Une valeur absente ou incomprehensible ne ferme aucun jour : on ne veut pas
    inventer une fermeture.
    """
    if not jours_ouverture:
        return set()
    return set(range(1, 8)) - {int(c) for c in jours_ouverture if c.isdigit()}


# ---------------------------------------------------------------------------
# Chargement des referentiels
# ---------------------------------------------------------------------------
def _acte(brut: Mapping[str, Any]) -> Acte:
    return Acte(
        categorie=_texte(brut.get("categorie")).upper(),
        specialite=_texte(brut.get("specialite")).upper(),
        tarif_min=_reel(brut.get("tarif_min")),
        tarif_reference=_reel(brut.get("tarif_reference")),
        tarif_max=_reel(brut.get("tarif_max")),
        ordonnance_requise=_booleen(brut.get("ordonnance_requise")),
        entente_prealable=_booleen(brut.get("entente_prealable")),
        sexe_requis=_texte(brut.get("sexe_requis")).upper(),
        age_min=_entier(brut.get("age_min")),
        age_max=_entier(brut.get("age_max"), 120),
    )


def _medicament(brut: Mapping[str, Any]) -> Medicament:
    return Medicament(
        prix_reference=_reel(brut.get("prix_reference")),
        remboursable=_booleen(brut.get("remboursable"), True),
        classe=_texte(brut.get("classe")).upper(),
        chronique=_booleen(brut.get("chronique")),
    )


def _prestataire(brut: Mapping[str, Any]) -> Prestataire:
    return Prestataire(
        radie=_booleen(brut.get("radie")),
        conventionne=_booleen(brut.get("conventionne"), True),
        date_conventionnement=_date(brut.get("date_conventionnement")),
        date_fin_convention=_date(brut.get("date_fin_convention")),
        jours_ouverture=_texte(brut.get("jours_ouverture")),
        heure_ouverture=_entier(brut.get("heure_ouverture")),
        heure_fermeture=_entier(brut.get("heure_fermeture"), 24),
        niveau_tarif=_texte(brut.get("niveau_tarif")).upper() or "RAISONNABLE",
        type_prestataire=_texte(brut.get("type_prestataire")).upper(),
        note_qualite=_entier(brut.get("note_qualite")),
    )


def _liste_codes(valeur: Any) -> frozenset[str]:
    """Codes listes dans une chaine ou un tableau JSON.

    `actes_exclus` est une chaine `A|B|C` dans le CSV, mais l'artefact JSON
    sérialise un tableau. Sans cette double lecture, `str(["IMG-IRM"])`
    donnerait `"['IMG-IRM']"` et l'exclusion ne serait jamais reconnue.
    """
    if isinstance(valeur, str):
        return frozenset(code.strip() for code in valeur.split("|") if code.strip())
    if isinstance(valeur, Iterable):
        return frozenset(_texte(code) for code in valeur if _texte(code))
    return frozenset()


def _garantie(brut: Mapping[str, Any]) -> GarantieCategorie:
    exclus = _liste_codes(brut.get("actes_exclus"))
    return GarantieCategorie(
        taux_remboursement=_reel(brut.get("taux_remboursement")),
        plafond_annuel_categorie=_reel(brut.get("plafond_annuel_categorie")),
        plafond_annuel_global=_reel(brut.get("plafond_annuel_global"), PLAFOND_ANNUEL_DEFAUT)
        or PLAFOND_ANNUEL_DEFAUT,
        delai_carence_jours=_entier(brut.get("delai_carence_jours")),
        actes_exclus=exclus,
    )


def _contrat(brut: Mapping[str, Any]) -> Contrat:
    return Contrat(
        date_effet=_date(brut.get("date_effet")),
        date_fin=_date(brut.get("date_fin")),
        formule=_texte(brut.get("formule")).upper(),
    )


def charger_referentiels(brut: Mapping[str, Any]) -> Referentiels:
    """Construit les referentiels depuis leur representation JSON.

    La lecture est volontairement tolerante : un champ absent prend sa valeur
    neutre plutot que de lever. Un referentiel incomplet degrade la precision
    du modele, il ne doit pas arreter la production.
    """
    return Referentiels(
        actes={k: _acte(v) for k, v in (brut.get("actes") or {}).items()},
        medicaments={k: _medicament(v) for k, v in (brut.get("medicaments") or {}).items()},
        grille={
            _texte(k): _reel(v)
            for k, v in (brut.get("grille") or {}).items()
            if _texte(k) and "|" in _texte(k)
        },
        prestataires={k: _prestataire(v) for k, v in (brut.get("prestataires") or {}).items()},
        garanties={k: _garantie(v) for k, v in (brut.get("garanties") or {}).items()},
        contrats={k: _contrat(v) for k, v in (brut.get("contrats") or {}).items()},
    )


def lire_referentiels(chemin: Path) -> Referentiels:
    """Charge `referentiels.json` depuis le disque."""
    brut = json.loads(Path(chemin).read_text(encoding="utf-8"))
    return charger_referentiels(brut)


def _iso(valeur: date | None) -> str | None:
    return valeur.isoformat() if valeur is not None else None


def referentiels_vers_dict(referentiels: Referentiels) -> dict[str, Any]:
    """Forme serialisable des referentiels, versionnee avec le modele.

    C'est l'inverse exact de `charger_referentiels` : l'entrainement ecrit ce
    JSON dans `models/<version>/referentiels.json`, et le service d'inference
    le relit au demarrage. Le referentiel sert donc a la fois a l'entrainement
    et a la production, ce qui interdit de servir un modele note avec une
    grille tarifaire perimee.
    """
    return {
        "format": 1,
        "actes": {
            code: {
                "categorie": a.categorie,
                "specialite": a.specialite,
                "tarif_min": a.tarif_min,
                "tarif_reference": a.tarif_reference,
                "tarif_max": a.tarif_max,
                "ordonnance_requise": a.ordonnance_requise,
                "entente_prealable": a.entente_prealable,
                "sexe_requis": a.sexe_requis,
                "age_min": a.age_min,
                "age_max": a.age_max,
            }
            for code, a in referentiels.actes.items()
        },
        "medicaments": {
            code: {
                "prix_reference": m.prix_reference,
                "remboursable": m.remboursable,
                "classe": m.classe,
                "chronique": m.chronique,
            }
            for code, m in referentiels.medicaments.items()
        },
        "grille": dict(referentiels.grille),
        "prestataires": {
            code: {
                "radie": p.radie,
                "conventionne": p.conventionne,
                "date_conventionnement": _iso(p.date_conventionnement),
                "date_fin_convention": _iso(p.date_fin_convention),
                "jours_ouverture": p.jours_ouverture,
                "heure_ouverture": p.heure_ouverture,
                "heure_fermeture": p.heure_fermeture,
                "niveau_tarif": p.niveau_tarif,
                "type_prestataire": p.type_prestataire,
                "note_qualite": p.note_qualite,
            }
            for code, p in referentiels.prestataires.items()
        },
        "garanties": {
            cle: {
                "taux_remboursement": g.taux_remboursement,
                "plafond_annuel_categorie": g.plafond_annuel_categorie,
                "plafond_annuel_global": g.plafond_annuel_global,
                "delai_carence_jours": g.delai_carence_jours,
                "actes_exclus": sorted(g.actes_exclus),
            }
            for cle, g in referentiels.garanties.items()
        },
        "contrats": {
            code: {
                "date_effet": _iso(c.date_effet),
                "date_fin": _iso(c.date_fin),
                "formule": c.formule,
            }
            for code, c in referentiels.contrats.items()
        },
    }


# ---------------------------------------------------------------------------
# Featurisation
# ---------------------------------------------------------------------------
def calculer_features(
    facture: FactureBrute,
    referentiels: Referentiels = REFERENTIELS_VIDES,
) -> dict[str, float]:
    """Transforme une facture en vecteur de variables, sans jamais lever.

    Le dictReturned contient EXACTEMENT les cles de `NOMS_FEATURES`, dans le
    meme ordre. Toute reference absente est notee dans
    `facture.references_manquantes` et remplacee par sa valeur neutre.
    """
    manquantes: set[str] = set()
    lignes = list(facture.lignes)

    # --- Contexte du soin ---------------------------------------------------
    dates_acte = [ligne.date_acte for ligne in lignes if ligne.date_acte is not None]
    date_soin = max(_jour(d) for d in dates_acte) if dates_acte else facture.date_facture
    # L'heure n'est exploitable que si l'appelant a transmis un horodatage :
    # le CSV la porte dans une colonne dediee, l'API dans le timestamp de
    # `date_acte`. Sans elle, la variable reste neutre.
    heures = [d.hour for d in dates_acte if isinstance(d, datetime)]
    heure_soin: int | None = max(heures) if heures else None

    prestataire = facture.prestataire
    if prestataire is None and facture.prestataire_id:
        prestataire = referentiels.prestataires.get(facture.prestataire_id)
    if prestataire is None:
        manquantes.add("prestataire")

    # --- Structure ----------------------------------------------------------
    montant_total = _borne(_reel(facture.montant_total), 0.0, 1e9)
    nb_lignes = len(lignes)
    quantite_totale = sum(max(0, _entier(ligne.quantite, 1)) for ligne in lignes)
    montants = [
        _reel(ligne.montant_unitaire) * max(0, _entier(ligne.quantite, 1)) for ligne in lignes
    ]

    # --- Codes et categories ------------------------------------------------
    codes = [_texte(ligne.code) for ligne in lignes]
    actes_reconnus: list[Acte] = []
    for code in codes:
        acte = referentiels.actes.get(code)
        if acte is not None:
            actes_reconnus.append(acte)
        elif code not in referentiels.medicaments:
            manquantes.add(f"code:{code}")

    categories = [acte.categorie for acte in actes_reconnus if acte.categorie]
    compte_categories: dict[str, int] = {}
    for categorie in categories:
        compte_categories[categorie] = compte_categories.get(categorie, 0) + 1
    categorie_dominante = (
        max(compte_categories, key=lambda c: (compte_categories[c], c)) if compte_categories else ""
    )
    part_specialises = (
        sum(
            1
            for acte in actes_reconnus
            if acte.specialite and acte.specialite not in SPECIALITES_GENERALISTES
        )
        / len(actes_reconnus)
        if actes_reconnus
        else 0.0
    )

    # --- Tarification -------------------------------------------------------
    ratios_grille: list[float] = []
    ecarts_grille: list[float] = []
    ratios_reference: list[float] = []
    depasse_max = 0.0
    non_remboursable = 0.0
    for ligne in lignes:
        code = _texte(ligne.code)
        prix = _reel(ligne.montant_unitaire)
        tarif = referentiels.tarif_grille(facture.prestataire_id, code)
        if tarif:
            ratios_grille.append(_divise(prix, tarif, 1.0))
            ecarts_grille.append(_borne(prix - tarif, -1e6, 1e7))
        if code in referentiels.actes:
            acte = referentiels.actes[code]
            if acte.tarif_reference:
                ratios_reference.append(_divise(prix, acte.tarif_reference, 1.0))
            if acte.tarif_max and prix > acte.tarif_max:
                depasse_max = 1.0
        elif code in referentiels.medicaments:
            medicament = referentiels.medicaments[code]
            if medicament.prix_reference:
                ratios_reference.append(_divise(prix, medicament.prix_reference, 1.0))
            if not medicament.remboursable:
                non_remboursable = 1.0

    # --- Prescription -------------------------------------------------------
    ordonnance = facture.ordonnance
    nb_non_prescrites = 0
    nb_lignes_evaluees = 0
    if ordonnance is not None and ordonnance.codes_prescrits:
        for code in codes:
            if not code:
                continue
            nb_lignes_evaluees += 1
            if code not in ordonnance.codes_prescrits:
                nb_non_prescrites += 1

    ordonnance_requise = any(acte.ordonnance_requise for acte in actes_reconnus)
    ordonnance_expiree = 0.0
    delai_prescription = 0.0
    prescripteur_different = 0.0
    if ordonnance is not None:
        if ordonnance.date_prescription and date_soin:
            delai = (date_soin - ordonnance.date_prescription).days
            delai_prescription = _borne(float(delai), -3650.0, 3650.0)
            if ordonnance.validite_jours and delai > ordonnance.validite_jours:
                ordonnance_expiree = 1.0
        if ordonnance.prescripteur_id and facture.prestataire_id:
            prescripteur_different = (
                1.0 if ordonnance.prescripteur_id != facture.prestataire_id else 0.0
            )

    # --- Coherence assure / referentiel -------------------------------------
    incompatibilite_sexe = 0.0
    incompatibilite_age = 0.0
    if actes_reconnus:
        sexes_requis = {acte.sexe_requis for acte in actes_reconnus if acte.sexe_requis}
        if sexes_requis and facture.assure_sexe:
            incompatibilite_sexe = 1.0 if facture.assure_sexe.upper() not in sexes_requis else 0.0
        if facture.assure_annee_naissance and date_soin:
            age = date_soin.year - facture.assure_annee_naissance
            hors_plage = any(age < acte.age_min or age > acte.age_max for acte in actes_reconnus)
            incompatibilite_age = 1.0 if hors_plage else 0.0
    # `profil_assure` signale un assure INCONNU, pas une simple absence de
    # correspondance : une facture dont tous les actes sont hors de la plage
    # d'age a bien un profil connu, il est simplement incoherent. Dans ce cas
    # il ne faut pas pretendre que l'information manque.
    if facture.assure_annee_naissance is None and not facture.assure_sexe:
        manquantes.add("profil_assure")

    # --- Prestataire, convention, horaires ----------------------------------
    soin_jour_ferme = 0.0
    soin_hors_horaire = 0.0
    hors_convention = 0.0
    if prestataire is not None and date_soin:
        if date_soin.isoweekday() in _jours_fermes(prestataire.jours_ouverture):
            soin_jour_ferme = 1.0
        # Une fermeture a 0 ou 24 signifie « ouvert 24h/24 » (pharmacie) :
        # il n'y a alors pas d'heure de fermeture a depasser.
        if (
            heure_soin is not None
            and 0 < prestataire.heure_fermeture < 24
            and (
                heure_soin >= prestataire.heure_fermeture
                or heure_soin < prestataire.heure_ouverture
            )
        ):
            soin_hors_horaire = 1.0
        if (
            prestataire.date_conventionnement and date_soin < prestataire.date_conventionnement
        ) or (prestataire.date_fin_convention and date_soin > prestataire.date_fin_convention):
            hors_convention = 1.0

    # --- Garantie et couverture ---------------------------------------------
    # Un contrat inconnu se comporte comme un contrat sans periode et sans
    # formule : les tests de couverture restent neutres, et le ratio de
    # plafond retombe sur la valeur de repli documentee plutot que sur 0.
    contrat = facture.contrat or Contrat()
    hors_periode_contrat = 0.0
    montant_vs_plafond = 0.0
    taux_actes_exclus = 0.0
    plafond = _plafond_garantie(referentiels, contrat, actes_reconnus)
    if plafond:
        montant_vs_plafond = _borne(montant_total / plafond, 0.0, 1000.0)
    exclus = _actes_exclus(referentiels, contrat, actes_reconnus)
    if exclus and codes:
        taux_actes_exclus = sum(1 for code in codes if code in exclus) / len(codes)
    if date_soin:
        avant_effet = contrat.date_effet and date_soin < contrat.date_effet
        apres_fin = contrat.date_fin and date_soin > contrat.date_fin
        if (
            avant_effet
            or apres_fin
            or _carence_non_respectee(referentiels, contrat, actes_reconnus, date_soin)
        ):
            hors_periode_contrat = 1.0

    valeurs: dict[str, float] = {
        "montant_total": montant_total,
        "log1p_montant_total": math.log1p(montant_total),
        "nb_lignes": float(nb_lignes),
        "quantite_totale": float(quantite_totale),
        "montant_moyen_ligne": _borne(_divise(montant_total, float(nb_lignes)), 0.0, 1e7),
        "montant_max_ligne": _borne(max(montants) if montants else 0.0, 0.0, 1e9),
        "ratio_quantite": _borne(_divise(quantite_totale, float(nb_lignes)), 0.0, 1000.0),
        "diversification_actes": float(len(set(codes))),
        "nb_categories": float(len(compte_categories)),
        "categorie_dominante_code": float(
            CATEGORIES_ACTES.index(categorie_dominante)
            if categorie_dominante in CATEGORIES_ACTES
            else CODE_CATEGORIE_INCONNUE
        ),
        "part_actes_specialises": _borne(part_specialises, 0.0, 1.0),
        "ratio_prix_grille_max": _borne(max(ratios_grille) if ratios_grille else 1.0, 0.0, 1000.0),
        "ratio_prix_grille_moyen": _borne(
            sum(ratios_grille) / len(ratios_grille) if ratios_grille else 1.0, 0.0, 1000.0
        ),
        "ecart_prix_grille_max": _borne(max(ecarts_grille) if ecarts_grille else 0.0, -1e6, 1e7),
        "ratio_prix_reference_max": _borne(
            max(ratios_reference) if ratios_reference else 1.0, 0.0, 1000.0
        ),
        "depasse_tarif_max": depasse_max,
        "produit_non_remboursable": non_remboursable,
        "taux_lignes_non_prescrites": _borne(
            _divise(float(nb_non_prescrites), float(nb_lignes_evaluees)), 0.0, 1.0
        ),
        "ordonnance_absente_requis": 1.0 if (ordonnance_requise and ordonnance is None) else 0.0,
        "ordonnance_expiree": ordonnance_expiree,
        "delai_prescription_jours": delai_prescription,
        "prescripteur_different": prescripteur_different,
        "incompatibilite_sexe": incompatibilite_sexe,
        "incompatibilite_age": incompatibilite_age,
        "prestataire_radie": 1.0 if prestataire is not None and prestataire.radie else 0.0,
        "hors_convention": hors_convention,
        "soin_jour_ferme": soin_jour_ferme,
        "soin_hors_horaire": soin_hors_horaire,
        "prestataire_niveau_tarif_eleve": 1.0
        if prestataire is not None and prestataire.niveau_tarif in {"ELEVE", "TRES_ELEVE"}
        else 0.0,
        "montant_vs_plafond_garantie": montant_vs_plafond,
        "hors_periode_contrat": hors_periode_contrat,
        "taux_actes_exclus": _borne(taux_actes_exclus, 0.0, 1.0),
    }
    # Derniere ligne de defence : `features.json` ne doit jamais pouvoir
    # contenir un nom absent d'ici, sinon `as_row` le remplirait de zero en
    # silence et le modele se degraderait sans trace.
    assert set(valeurs) == set(NOMS_FEATURES), "NOMS_FEATURES desynchronise"
    for nom in NOMS_FEATURES:
        valeurs[nom] = _borne(valeurs[nom])
    # La liste reste triee et sans doublon : une facture a 200 lignes portant le
    # meme code inconnu ne doit pas produire 200 entrees identiques, et deux
    # appels successifs sur la meme facture non plus.
    facture.references_manquantes[:] = sorted(manquantes)
    return valeurs


def _plafond_garantie(
    referentiels: Referentiels,
    contrat: Contrat,
    actes: Iterable[Acte],
) -> float:
    """Plafond annuel applicable a la facture.

    On privilegie le plafond de CATEGORIE, puis le plafond global de la
    formule, puis `PLAFOND_ANNUEL_DEFAUT` — le plus bas des trois formules du
    referentiel, donc la valeur la plus prudente.

    Le repli n'est jamais `0`. Un ratio calcule sur un plafond nul vaudrait 0
    et se confondrait avec « facture sans rapport au plafond », alors que la
    realite est « plafond inconnu » : le modele lirait un risque faible la
    ou il n'y a aucune information. Un denominaire par defaut, lui, garde la
    variable dans la meme unite a l'entrainement et en service, meme quand la
    formule du contrat n'a pas pu etre resolue.
    """
    categories = sorted({acte.categorie for acte in actes if acte.categorie})
    for categorie in categories:
        garantie = referentiels.garantie(contrat.formule, categorie)
        if garantie is not None and garantie.plafond_annuel_categorie:
            return garantie.plafond_annuel_categorie
    for categorie in categories:
        garantie = referentiels.garantie(contrat.formule, categorie)
        if garantie is not None and garantie.plafond_annuel_global:
            return garantie.plafond_annuel_global
    return PLAFOND_ANNUEL_DEFAUT


def _actes_exclus(
    referentiels: Referentiels,
    contrat: Contrat,
    actes: Iterable[Acte],
) -> frozenset[str]:
    exclus: set[str] = set()
    for acte in actes:
        if not acte.categorie:
            continue
        garantie = referentiels.garantie(contrat.formule, acte.categorie)
        if garantie is not None:
            exclus |= garantie.actes_exclus
    return frozenset(exclus)


def _carence_non_respectee(
    referentiels: Referentiels,
    contrat: Contrat,
    actes: Iterable[Acte],
    date_soin: date,
) -> bool:
    """Le delai de carence de la formule est-il depasse ?

    La carence se compte depuis l'effet du contrat. Elle n'est testee que si
    l'on dispose de la date d'effet ET d'une formule : sans ces deux elements
    le test n'a aucun sens et le modele doit le voir comme neutre.
    """
    if not contrat.formule or contrat.date_effet is None:
        return False
    categories = sorted({acte.categorie for acte in actes if acte.categorie})
    delais = {
        garantie.delai_carence_jours
        for categorie in categories
        if (garantie := referentiels.garantie(contrat.formule, categorie)) is not None
    }
    delais.discard(0)
    if not delais:
        return False
    return (date_soin - contrat.date_effet).days < max(delais)


def vecteur(
    facture: FactureBrute,
    referentiels: Referentiels = REFERENTIELS_VIDES,
    noms: Sequence[str] = NOMS_FEATURES,
) -> list[float]:
    """Vecteur aligne sur l'ordre attendu par le modele.

    Une variable absente vaut 0 et une variable inconnue est ignoree : le
    modele reste chargeable meme si le jeu de variables evolue.
    """
    valeurs = calculer_features(facture, referentiels)
    return [float(valeurs.get(nom, 0.0)) for nom in noms]
