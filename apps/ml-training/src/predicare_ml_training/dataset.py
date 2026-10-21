"""Assemblage du jeu d'entrainement a partir des 14 CSV bruts.

Ce module ne fait qu'une chose : transformer les fichiers de l'encadrement en
deux objets pret a l'emploi.

- `Referentiels` : les referentiels statiques, serialises avec le modele pour
  que l'inference note avec exactement la meme grille tarifaire.
- `JeuDonnees` : une facture = une ligne de `X` (dans l'ordre de
  `NOMS_FEATURES`), une cible `y`, et le contexte (ordonnance, contrat,
  assure) que `predicare.features` consomme.

Le nettoyage et le rejet des factures invalides ne sont PAS reimplementes ici :
ils sont delegates a `predicare_seed.qualite_donnees`, deja utilise par le
chargement en base. Une seule implementation des 10 regles d'invalidite, donc
aucun ecart possible entre ce que le modele a vu et ce que la base contient.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from predicare.features import (
    NOMS_FEATURES,
    Acte,
    Contrat,
    FactureBrute,
    GarantieCategorie,
    LigneFacture,
    Medicament,
    Ordonnance,
    Prestataire,
    Referentiels,
    calculer_features,
)
from predicare.logging_config import get_logger
from predicare_seed.qualite_donnees import lire_tous, valider_factures

logger = get_logger("ml-training")

#: Colonnes de `core.facture` qui resultedent de la DECISION historique de
#: paiement et qui ne doivent jamais devenir des variables : elles fuient la
#: cible (70 % des factures rejetees sont frauduleuses contre 7 % des payees).
#: Liste reprise de la Phase 0.4 et du README racine.
COLONNES_FUITE = ("statut", "motif_rejet", "montant_pris_en_charge", "date_traitement")


class DonneesAbsentesError(RuntimeError):
    """Le dossier des 14 CSV est introuvable ou incomplet."""


@dataclass(slots=True)
class JeuDonnees:
    """Le jeu d'entrainement, pret a etre scinde par date."""

    #: Une ligne par facture, colonnes = NOMS_FEATURES.
    X: pd.DataFrame
    #: 0 = saine, 1 = frauduleuse.
    y: pd.Series
    #: Date de soin, axe du decoupage temporel.
    dates: pd.Series
    facture_ids: list[str]
    #: Segments pour l'audit d'equite (Phase 9.4).
    segments: pd.DataFrame
    #: Type de fraude, vide pour les factures saines. Sert au diagnostic
    #: "quelle famille de fraude le modele rate-t-il", jamais a l'entrainement.
    types_fraude: pd.Series
    referentiels: Referentiels
    #: Empreinte des donnees : elle identifie le jeu d'entrainement dans
    #: `metadata.json` et permet de dire "ce modele a ete entraine sur quoi".
    empreinte: str = ""
    #: Nombre de factures ecartees par les regles d'invalidite.
    rejets: int = 0
    references_manquantes: dict[str, int] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.X)


# ---------------------------------------------------------------------------
# Lectures typiques
# ---------------------------------------------------------------------------
def _entier(valeur: object, defaut: int = 0) -> int:
    try:
        if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
            return defaut
        return int(float(valeur))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return defaut


def _reel(valeur: object, defaut: float = 0.0) -> float:
    try:
        if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
            return defaut
        nombre = float(valeur)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return defaut
    return nombre if np.isfinite(nombre) else defaut


def _booleen(valeur: object, defaut: bool = False) -> bool:
    """Meme lecture tolerante que `predicare.features._booleen`.

    Dupliquee volontairement plutot qu'importee : `_booleen` est prive, et
    exposer une API de parsing dans le socle pour un seul usage de
    l'entrainement n'en vaut pas la peine. Les deux lectures sont testees
    conjointement par `tests/test_features_parite.py`.
    """
    if isinstance(valeur, bool):
        return valeur
    if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
        return defaut
    if isinstance(valeur, str):
        normalise = valeur.strip().lower()
        if normalise in {"1", "true", "oui", "yes", "vrai"}:
            return True
        if normalise in {"0", "false", "non", "no", "faux"}:
            return False
        return defaut
    try:
        return float(valeur) != 0.0  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return defaut


def _texte(valeur: object) -> str:
    if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
        return ""
    return str(valeur).strip()


def _jour(valeur: object) -> date | None:
    """Date seule, que la valeur vienne d'un CSV ou d'un horodatage."""
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
        return None
    texte = _texte(valeur)
    if not texte:
        return None
    try:
        return datetime.fromisoformat(texte).date()
    except ValueError:
        return None


def _instant(valeur: object) -> datetime | None:
    """Horodatage complet, combine a la date de soin et a l'heure du CSV.

    `lignes_facture.csv` ne porte pas d'heure : c'est `factures.heure_soin`.
    On recombine les deux pour que `soin_hors_horaire` soit calculable a
    l'entrainement exactement comme en service, ou la date d'acte est un
    horodatage.
    """
    jour = _jour(valeur)
    if jour is None:
        return None
    return datetime(jour.year, jour.month, jour.day)


def _heure(valeur: object) -> int | None:
    texte = _texte(valeur)
    if not texte:
        return None
    for gabarit in ("%H:%M", "%H:%M:%S", "%Hh%M"):
        try:
            return datetime.strptime(texte, gabarit).hour
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Referentiels
# ---------------------------------------------------------------------------
def construire_referentiels(donnees: Mapping[str, pd.DataFrame]) -> Referentiels:
    """Assemble les referentiels statiques depuis les CSV bruts.

    Les grilles tarifaires sont chargees dans une seule table dont la cle est
    `<prestataire_id>|<code>`, exactement le format attendu par
    `Referentiels.tarif_grille` : c'est ce qui garantit que l'inference et
    l'entrainement indexent la grille de la meme facon.
    """
    actes = {
        _texte(r["code_acte"]): Acte(
            categorie=_texte(r["categorie"]).upper(),
            specialite=_texte(r["specialite"]).upper(),
            tarif_min=_reel(r["tarif_min"]),
            tarif_reference=_reel(r["tarif_reference"]),
            tarif_max=_reel(r["tarif_max"]),
            ordonnance_requise=_booleen(r["ordonnance_requise"]),
            entente_prealable=_booleen(r["entente_prealable"]),
            sexe_requis=_texte(r["sexe_requis"]).upper(),
            age_min=_entier(r["age_min"]),
            age_max=_entier(r["age_max"], 120),
        )
        for _, r in donnees["actes"].iterrows()
    }

    medicaments = {
        _texte(r["code_medicament"]): Medicament(
            prix_reference=_reel(r["prix_reference"]),
            remboursable=_booleen(r["remboursable"], True),
            classe=_texte(r["classe"]).upper(),
            chronique=_booleen(r["chronique"]),
        )
        for _, r in donnees["medicaments"].iterrows()
    }

    grille = {
        f"{_texte(r['prestataire_id'])}|{_texte(r['code'])}": _reel(r["tarif_pratique"])
        for _, r in donnees["grille"].iterrows()
    }

    prestataires = {
        _texte(r["prestataire_id"]): Prestataire(
            # `statut` vaut ACTIF ou RADIE ; le CSV porte la lettre, pas le booleen.
            radie=_texte(r["statut"]).upper() == "RADIE",
            conventionne=_booleen(r["conventionne"], True),
            date_conventionnement=_jour(r["date_conventionnement"]),
            date_fin_convention=_jour(r["date_fin_convention"]),
            jours_ouverture=_texte(r["jours_ouverture"]),
            heure_ouverture=_entier(r["heure_ouverture"]),
            heure_fermeture=_entier(r["heure_fermeture"], 24),
            niveau_tarif=_texte(r["niveau_tarif"]).upper() or "RAISONNABLE",
            type_prestataire=_texte(r["type_prestataire"]).upper(),
            note_qualite=_entier(r["note_qualite"]),
        )
        for _, r in donnees["prestataires"].iterrows()
    }

    garanties = {
        f"{_texte(r['formule']).upper()}|{_texte(r['categorie']).upper()}": GarantieCategorie(
            taux_remboursement=_reel(r["taux_remboursement"]),
            plafond_annuel_categorie=_reel(r["plafond_annuel_categorie"]),
            plafond_annuel_global=_reel(r["plafond_annuel_global"], 3_000_000.0) or 3_000_000.0,
            delai_carence_jours=_entier(r["delai_carence_jours"]),
            actes_exclus=frozenset(
                code.strip() for code in _texte(r["actes_exclus"]).split("|") if code.strip()
            ),
        )
        for _, r in donnees["garanties"].iterrows()
    }

    contrats = {
        _texte(r["contrat_id"]): Contrat(
            date_effet=_jour(r["date_effet"]),
            date_fin=_jour(r["date_fin"]),
            formule=_texte(r["formule"]).upper(),
        )
        for _, r in donnees["contrats"].iterrows()
    }

    return Referentiels(
        actes=actes,
        medicaments=medicaments,
        grille=grille,
        prestataires=prestataires,
        garanties=garanties,
        contrats=contrats,
    )


# ---------------------------------------------------------------------------
# Contextes par facture
# ---------------------------------------------------------------------------
def _ordonnances(donnees: Mapping[str, pd.DataFrame]) -> dict[str, tuple[str, Ordonnance]]:
    """`ordonnance_id` -> (assure_id, Ordonnance) avec ses codes prescrits.

    Les codes prescrits sont regroupes en un seul `frozenset` par ordonnance.
    47 804 ordonnances : le regroupement se fait en vectoriel pandas, jamais
    ligne a ligne, pour que le chargement reste sous la seconde.
    """
    table = donnees["ordonnances"]
    lignes = donnees["ordonnance_lignes"]

    codes_par_ordonnance: dict[str, set[str]] = {}
    if len(lignes):
        couples = (
            lignes[["ordonnance_id", "code"]]
            .assign(
                **{
                    "ordonnance_id": lignes["ordonnance_id"].map(_texte),
                    "code": lignes["code"].map(_texte),
                }
            )
            .drop_duplicates()
        )
        couples = couples[couples["ordonnance_id"] != ""]
        codes_par_ordonnance = {
            groupe["ordonnance_id"].iloc[0]: set(groupe["code"])
            for _, groupe in couples.groupby("ordonnance_id", sort=False)
        }

    contextes: dict[str, tuple[str, Ordonnance]] = {}
    for _, r in table.iterrows():
        identifiant = _texte(r["ordonnance_id"])
        if not identifiant:
            continue
        contextes[identifiant] = (
            _texte(r["assure_id"]),
            Ordonnance(
                prescripteur_id=_texte(r["prescripteur_id"]),
                date_prescription=_jour(r["date_prescription"]),
                validite_jours=_entier(r["validite_jours"]),
                codes_prescrits=frozenset(codes_par_ordonnance.get(identifiant, ())),
            ),
        )
    return contextes


def _profils_assures(donnees: Mapping[str, pd.DataFrame]) -> dict[str, tuple[int | None, str]]:
    """`assure_id` -> (annee de naissance, sexe).

    Ni le nom, ni la date de naissance exacte, ni les coordonnees : seuls deux
    champs non nominatifs sont retenus, parce que ce sont les seuls necessaires
    a la coherence profil et qu'ils restent minimaux au sens du RGPD.
    """
    table = donnees["assures"]
    if table.empty or "assure_id" not in table.columns:
        return {}
    if "annee_naissance" not in table.columns:
        annees: dict[str, int | None] = {}
    else:
        annees = dict(
            zip(
                table["assure_id"].map(_texte),
                (_entier(v, 0) or None for v in table["annee_naissance"]),
                strict=True,
            )
        )
    sexes = (
        dict(zip(table["assure_id"].map(_texte), table["sexe"].map(_texte), strict=True))
        if "sexe" in table.columns
        else {}
    )
    return {
        identifiant: (annees.get(identifiant), sexes.get(identifiant, ""))
        for identifiant in set(annees) | set(sexes)
    }


def _tranche_age(annee_naissance: object, reference: date) -> str:
    annee = _entier(annee_naissance)
    if not annee:
        return "inconnu"
    age = reference.year - annee
    if age < 18:
        return "0-17"
    if age < 30:
        return "18-29"
    if age < 50:
        return "30-49"
    if age < 65:
        return "50-64"
    return "65+"


# ---------------------------------------------------------------------------
# Empreinte
# ---------------------------------------------------------------------------
def empreinte_donnees(donnees: Mapping[str, pd.DataFrame]) -> str:
    """Empreinte stable du contenu, pas des horodatages de fichier.

    Elle identifie le jeu d'entrainement dans `metadata.json` et permet de
    rejouer exactement le meme entrainement, ou de prouver qu'un modele a ete
    entraine sur un jeu donne. Hash de la taille ET du contenu de chaque table,
    ce qui la rend sensible a une seule valeur modifiee.
    """
    empreinte = hashlib.sha256()
    for domaine in sorted(donnees):
        table = donnees[domaine]
        empreinte.update(domaine.encode("utf-8"))
        empreinte.update(str(len(table)).encode("utf-8"))
        empreinte.update("|".join(map(str, table.columns)).encode("utf-8"))
        # Onagre les valeurs, pas chaque cellule : le cout resterait lineaire
        # en octets mais la resistance aux collisions serait meilleure.
        empreinte.update(pd.util.hash_pandas_object(table, index=False).values.tobytes())
    return f"sha256:{empreinte.hexdigest()}"


# ---------------------------------------------------------------------------
# Assemblage
# ---------------------------------------------------------------------------
def charger_jeu(dossier: Path) -> JeuDonnees:
    """Lit les 14 CSV, ecarte les factures invalides, produit X / y / segments.

    Le rejet est confie a `valider_factures` : c'est la meme fonction que celle
    du chargement en base, donc le modele ne peut pas avoir ete entraine sur une
    facture que la base refuserait.
    """
    dossier = Path(dossier)
    if not dossier.exists():
        raise DonneesAbsentesError(
            f"Dossier de donnees introuvable : {dossier}. "
            "Copiez les 14 CSV de l'encadrement dans ./data/raw."
        )

    donnees = lire_tous(dossier)
    logger.info("donnees.lues", domaines=len(donnees))

    valides, rejets = valider_factures(
        donnees["factures"],
        donnees["lignes_facture"],
        donnees["actes"],
        donnees["medicaments"],
        donnees["assures"],
        donnees["prestataires"],
    )
    if len(rejets):
        logger.warning("factures.rejetees", nombre=len(rejets))
    ids_rejetes = set(rejets["facture_id"]) if len(rejets) else set()

    referentiels = construire_referentiels(donnees)
    ordonnances = _ordonnances(donnees)
    profils = _profils_assures(donnees)

    lignes = donnees["lignes_facture"]
    lignes = lignes[~lignes["facture_id"].isin(ids_rejetes)]
    lignes_par_facture: dict[str, list[tuple[str, int, float, object]]] = {}
    for identifiant, groupe in lignes.groupby("facture_id", sort=False):
        identifiant = _texte(identifiant)
        if identifiant:
            lignes_par_facture[identifiant] = [
                (
                    _texte(r["code"]),
                    _entier(r["quantite"], 1),
                    _reel(r["prix_unitaire"]),
                    r["montant"],
                )
                for _, r in groupe.iterrows()
            ]

    # Le label est lu depuis le CSV, jamais depuis `core.facture.statut` :
    # c'est la seule source de verite sur la cible.
    labels = donnees["labels_fraude"]
    labels = labels[["facture_id", "est_fraude", "type_fraude"]].copy()
    labels["facture_id"] = labels["facture_id"].map(_texte)
    labels = labels[~labels["facture_id"].isin(ids_rejetes)]
    cible = dict(zip(labels["facture_id"], labels["est_fraude"].map(_entier), strict=True))
    types = dict(zip(labels["facture_id"], labels["type_fraude"].map(_texte), strict=True))

    factures = valides.copy()
    factures["facture_id"] = factures["facture_id"].map(_texte)
    factures["date_soin"] = factures["date_soin"].map(_jour)
    factures["date_facture"] = factures["date_facture"].map(_jour)
    factures["heure_soin"] = factures.get("heure_soin", pd.Series([None] * len(factures))).map(
        _heure
    )
    factures["montant_total"] = factures["montant_total"].map(_reel)
    factures["ordonnance_id"] = factures.get(
        "ordonnance_id", pd.Series([None] * len(factures))
    ).map(_texte)
    factures["contrat_id"] = factures.get("contrat_id", pd.Series([None] * len(factures))).map(
        _texte
    )
    factures["prestataire_id"] = factures["prestataire_id"].map(_texte)
    factures["assure_id"] = factures["assure_id"].map(_texte)

    # Une facture sans label n'est pas entrainable : on la retire plutot que de
    # la faire entrer avec une cible par defaut, qui biaiserait l'apprentissage.
    factures = factures[factures["facture_id"].isin(cible)]
    factures = factures.sort_values("date_soin", kind="stable").reset_index(drop=True)

    matrice: list[list[float]] = []
    cibles: list[int] = []
    dates: list[date] = []
    identifiants: list[str] = []
    types_fraude: list[str] = []
    segments: list[dict[str, str]] = []
    manquantes_totales: dict[str, int] = {}

    # Import local : `predicare.features` est le socle, l'import se fait ici
    # pour que l'erreur soit lisible si le module n'est pas installe.
    records = factures.to_dict("records")
    for enregistrement in records:
        identifiant = enregistrement["facture_id"]
        soin = enregistrement["date_soin"]
        if soin is None:
            continue  # `DATE_IMPOSSIBLE` aurait du la rejeter ; garde-fou.

        date_facture = enregistrement["date_facture"]
        # `lignes_facture.csv` ne porte pas l'heure du soin : on la reprend de
        # `factures.heure_soin` pour que la date d'entree soit un horodatage,
        # exactement comme le `date_acte` que reçoit le service d'inference.
        heure = enregistrement["heure_soin"] or 0

        detail = lignes_par_facture.get(identifiant, [])
        lignes_facture = [
            LigneFacture(
                code=code,
                quantite=quantite,
                montant_unitaire=montant,
                date_acte=datetime(soin.year, soin.month, soin.day, heure),
            )
            for code, quantite, montant, _ in detail
        ]
        if not lignes_facture:
            # `FACTURE_SANS_LIGNE` l'aurait rejetee ; si on arrive ici, c'est
            # que le registre n'a pas rejoue la meme validation.
            continue

        identifiant_ordonnance = enregistrement["ordonnance_id"]
        ordonnance = None
        assure_id = enregistrement["assure_id"]
        if identifiant_ordonnance and identifiant_ordonnance in ordonnances:
            _, ordonnance = ordonnances[identifiant_ordonnance]

        annee, sexe = profils.get(assure_id, (None, ""))

        facture = FactureBrute(
            montant_total=enregistrement["montant_total"],
            date_facture=date_facture,
            lignes=lignes_facture,
            ordonnance=ordonnance,
            contrat=referentiels.contrats.get(enregistrement["contrat_id"]),
            prestataire=referentiels.prestataires.get(enregistrement["prestataire_id"]),
            assure_annee_naissance=annee,
            assure_sexe=sexe,
            prestataire_id=enregistrement["prestataire_id"],
        )
        valeurs = calculer_features(facture, referentiels)
        for reference in facture.references_manquantes:
            manquantes_totales[reference] = manquantes_totales.get(reference, 0) + 1

        matrice.append([valeurs[nom] for nom in NOMS_FEATURES])
        cibles.append(cible[identifiant])
        dates.append(soin)
        identifiants.append(identifiant)
        types_fraude.append(types.get(identifiant, ""))

        prestataire = referentiels.prestataires.get(enregistrement["prestataire_id"])
        segments.append(
            {
                "tranche_age": _tranche_age(annee, soin),
                "niveau_tarif": (
                    prestataire.niveau_tarif if prestataire is not None else "INCONNU"
                ),
                "type_prestataire": (
                    prestataire.type_prestataire if prestataire is not None else "INCONNU"
                ),
                "formule": (
                    referentiels.contrats.get(enregistrement["contrat_id"], Contrat()).formule
                    or "INCONNUE"
                ),
            }
        )

    jeu = JeuDonnees(
        X=pd.DataFrame(matrice, columns=list(NOMS_FEATURES)),
        y=pd.Series(cibles, name="est_fraude", dtype="int8"),
        dates=pd.Series(dates, name="date_soin"),
        facture_ids=identifiants,
        segments=pd.DataFrame(segments),
        types_fraude=pd.Series(types_fraude, name="type_fraude"),
        referentiels=referentiels,
        rejets=len(rejets),
        references_manquantes=dict(sorted(manquantes_totales.items(), key=lambda p: -p[1])[:20]),
    )
    jeu.empreinte = empreinte_donnees(donnees)
    return jeu


def decouper_temporel(
    dates: Sequence[date],
    *,
    mois_validation: int = 3,
    mois_test: int = 3,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Decoupe STRICTEMENT temporelle, jamais aleatoire.

    Le test est la periode la plus recente et n'est utilise qu'une fois, a la
    toute fin, pour le compte rendu. Une facture de juillet n'entre donc jamais
    dans l entrainement d'un modele teste sur juillet : c'est exactement le
    fuite temporelle que le plan d'action interdit.

    Rend trois masques booleanes (entrainement, validation, test) qui
    partitionnent exactement l'ensemble des lignes.
    """
    if not len(dates):
        raise ValueError("Aucune date a decouper.")
    instants = pd.Series(pd.to_datetime(pd.Series(list(dates))))
    dernier = instants.max()

    # La validation est la fenetre qui precede le test, et le test est la fin de
    # l'historique. Les deux bornes se partagent pour que la partition couvre
    # chaque instant exactement une fois.
    debut_validation = dernier - pd.DateOffset(months=mois_validation + mois_test)
    debut_test = dernier - pd.DateOffset(months=mois_test)

    entrainement = (instants < debut_validation).to_numpy()
    validation = ((instants >= debut_validation) & (instants < debut_test)).to_numpy()
    test = (instants >= debut_test).to_numpy()

    if not entrainement.any() or not test.any():
        raise ValueError(
            "Periode de donnees trop courte pour un decoupage temporel : "
            f"{len(dates)} factures entre {instants.min().date()} et {dernier.date()}. "
            "Reducez `mois_validation` / `mois_test`."
        )
    return entrainement, validation, test
