"""Porte de validation des CSV avant tout ecriture en base.

Ce module ne nettoie rien, et c'est un choix.

Mesures sur le jeu fourni (436 710 lignes, 14 fichiers) : zero doublon de cle
primaire, zero cle etrangere orpheline, zero inversion de dates. Les valeurs
manquantes ne sont pas de la salete mais de l'information -- 44 % des factures
n'ont pas d'ordonnance parce que beaucoup d'actes n'en exigent pas, et leur
taux de fraude est meme inferieur a celui des autres. Remplacer ces NULL par
une valeur par defaut detruirait exactement le signal que le modele doit
apprendre.

La Phase 1.4 du plan d'action demande « nettoyer et valider les donnees :
types, valeurs manquantes, doublons, dates incoherentes ». Ici, « nettoyer »
signifie « refuser de charger un fichier douteux », pas « reparer ».

Chaque controle est bloquant et nomme le fichier fautif. Un echec interrompt
le chargement avant le premier ecrit : charger la moitie d'un jeu incoherent
laisserait la base dans un etat pire qu'vide, puisque les tables paraitraient
peuplees.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

#: Fichiers attendus, et ce qui doit etre vrai de chacun.
#: Cle : nom de fichier. Valeur : colonnes exigees.
COLONNES_ATTENDUES: dict[str, tuple[str, ...]] = {
    "referentiel_actes.csv": ("code_acte", "libelle", "tarif_reference"),
    "referentiel_medicaments.csv": ("code_medicament", "libelle", "prix_reference"),
    "prestataires.csv": ("prestataire_id", "nom", "type_prestataire"),
    "contrats.csv": ("contrat_id", "formule", "date_effet"),
    "assures.csv": ("assure_id", "contrat_id", "sexe"),
    "identites_pii.csv": ("assure_id", "nom", "date_naissance"),
    "ordonnances.csv": ("ordonnance_id", "assure_id", "date_prescription"),
    "ordonnance_lignes.csv": ("ordonnance_id", "num_ligne", "code"),
    "factures.csv": ("facture_id", "prestataire_id", "assure_id", "montant_total"),
    "lignes_facture.csv": ("ligne_id", "facture_id", "code", "montant"),
    "garanties.csv": ("formule", "categorie", "taux_remboursement"),
    "grille_tarifaire.csv": ("prestataire_id", "code", "tarif_pratique"),
    "labels_fraude.csv": ("facture_id", "est_fraude"),
    "labels_prestataires.csv": ("prestataire_id", "est_suspect"),
}

#: Tables et colonnes purgees avant chargement, dans l'ordre des dependances.
#: `CASCADE` emporte les tables enfants : `ligne_facture` part avec `facture`,
#: `label_fraude` avec `facture`. L'ordre compte peu avec CASCADE, mais il est
#: ecrit de facon lisible.
TABLES_A_PURGER = (
    "ml.label_fraude",
    "ml.label_prestataire",
    "ml.prediction",
    "ml.shap_explication",
    "ml.rapport_derive",
    "core.ligne_facture",
    "core.facture",
    "core.ordonnance_ligne",
    "core.ordonnance",
    "core.grille_tarifaire",
    "core.contrat_beneficiaire",
    "core.contrat",
    "core.assure",
    "core.identite_chiffree",
    "core.prestataire",
    "core.acte",
    "core.garantie_formule",
)


@dataclass
class Rapport:
    """Resultat de la validation. `ok` a False bloque tout chargement."""

    ok: bool = True
    anomalies: list[str] = field(default_factory=list)
    mesures: dict[str, str] = field(default_factory=dict)

    def ajouter(self, anomalie: str) -> None:
        self.anomalie = anomalie
        self.anomalies.append(anomalie)
        self.ok = False

    def mesurer(self, cle: str, valeur: str) -> None:
        self.mesures[cle] = valeur


def controler_presence(dossier) -> tuple[list[str], list[str]]:
    """Separe fichiers presents et fichiers manquants, sans rien lire."""
    presents = [nom for nom in COLONNES_ATTENDUES if (dossier / nom).exists()]
    manquants = [nom for nom in COLONNES_ATTENDUES if nom not in presents]
    return presents, manquants


def controler_schema(tables: dict[str, pd.DataFrame], rapport: Rapport) -> None:
    """Verifie que chaque CSV porte les colonnes attendues."""
    for nom, requises in COLONNES_ATTENDUES.items():
        if nom not in tables:
            continue
        absentes = [c for c in requises if c not in tables[nom].columns]
        if absentes:
            rapport.ajouter(
                f"{nom} : colonne(s) absente(s) {absentes}. "
                f"Ce fichier ne correspond pas au format attendu."
            )
        else:
            rapport.mesurer(nom, f"{len(tables[nom]):,} lignes".replace(",", " "))


def controler_unicite(tables: dict[str, pd.DataFrame], rapport: Rapport) -> None:
    """Une cle primaire en double rendrait le chargement non idempotent."""
    cles = {
        "referentiel_actes.csv": "code_acte",
        "referentiel_medicaments.csv": "code_medicament",
        "prestataires.csv": "prestataire_id",
        "contrats.csv": "contrat_id",
        "assures.csv": "assure_id",
        "identites_pii.csv": "assure_id",
        "ordonnances.csv": "ordonnance_id",
        "factures.csv": "facture_id",
        "lignes_facture.csv": "ligne_id",
    }
    for nom, cle in cles.items():
        if nom not in tables:
            continue
        doublons = int(tables[nom][cle].duplicated().sum())
        if doublons:
            rapport.ajouter(
                f"{nom} : {doublons} doublon(s) sur la cle primaire {cle}. "
                "Cle externe non unique, chargement impossible."
            )


def controler_integrite(tables: dict[str, pd.DataFrame], rapport: Rapport) -> None:
    """Chaque cle etrangere du CSV doit exister dans la table reference."""
    if "prestataires.csv" not in tables:
        return
    prestataires = set(tables["prestataires.csv"]["prestataire_id"])
    if "factures.csv" in tables:
        orphelines = set(tables["factures.csv"]["prestataire_id"]) - prestataires
        if orphelines:
            rapport.ajouter(
                f"factures.csv : {len(orphelines)} prestataire_id absent(s) de "
                "prestataires.csv."
            )
    if "grille_tarifaire.csv" in tables:
        orphelines = set(tables["grille_tarifaire.csv"]["prestataire_id"]) - prestataires
        if orphelines:
            rapport.ajouter(
                f"grille_tarifaire.csv : {len(orphelines)} prestataire_id absent(s) "
                "de prestataires.csv."
            )
    if "labels_prestataires.csv" in tables:
        orphelines = set(tables["labels_prestataires.csv"]["prestataire_id"]) - prestataires
        if orphelines:
            rapport.ajouter(
                f"labels_prestataires.csv : {len(orphelines)} prestataire_id absent(s) "
                "de prestataires.csv."
            )

    if "actes.csv" not in tables and "referentiel_actes.csv" in tables:
        actes = set(tables["referentiel_actes.csv"]["code_acte"])
        if "referentiel_medicaments.csv" in tables:
            actes |= set(tables["referentiel_medicaments.csv"]["code_medicament"])
        for nom in ("lignes_facture.csv", "ordonnance_lignes.csv"):
            if nom in tables and "code" in tables[nom].columns:
                inconnus = set(tables[nom]["code"]) - actes
                if inconnus:
                    rapport.ajouter(
                        f"{nom} : {len(inconnus)} code(s) absent(s) du referentiel "
                        "des actes et des medicaments."
                    )

    if "factures.csv" in tables:
        factures = set(tables["factures.csv"]["facture_id"])
        for nom in ("lignes_facture.csv", "labels_fraude.csv"):
            if nom in tables and "facture_id" in tables[nom].columns:
                orphelines = set(tables[nom]["facture_id"]) - factures
                if orphelines:
                    rapport.ajouter(
                        f"{nom} : {len(orphelines)} facture_id absent(s) de factures.csv."
                    )

    if "ordonnances.csv" in tables and "ordonnance_lignes.csv" in tables:
        ordonnances = set(tables["ordonnances.csv"]["ordonnance_id"])
        orphelines = set(tables["ordonnance_lignes.csv"]["ordonnance_id"]) - ordonnances
        if orphelines:
            rapport.ajouter(
                f"ordonnance_lignes.csv : {len(orphelines)} ordonnance_id absent(s) "
                "de ordonnances.csv."
            )

    if "assures.csv" in tables and "contrats.csv" in tables:
        contrats = set(tables["contrats.csv"]["contrat_id"])
        orphelines = set(tables["assures.csv"]["contrat_id"]) - contrats
        if orphelines:
            rapport.ajouter(
                f"assures.csv : {len(orphelines)} contrat_id absent(s) de contrats.csv."
            )


def controler_dates(tables: dict[str, pd.DataFrame], rapport: Rapport) -> None:
    """Une date anterieure a sa reference est une incoherence, pas un cas rare."""
    if "factures.csv" in tables:
        f = tables["factures.csv"]
        soin = pd.to_datetime(f["date_soin"], errors="coerce")
        facture = pd.to_datetime(f["date_facture"], errors="coerce")
        reception = pd.to_datetime(f["date_reception"], errors="coerce")
        if int((facture < soin).sum()):
            rapport.ajouter(
                f"factures.csv : {int((facture < soin).sum())} facture(s) anterieure(s) "
                "au soin."
            )
        if int((reception < facture).sum()):
            rapport.ajouter(
                f"factures.csv : {int((reception < facture).sum())} reception(s) "
                "anterieure(s) a la facture."
            )
    if "assures.csv" in tables:
        a = tables["assures.csv"]
        adhesion = pd.to_datetime(a["date_adhesion"], errors="coerce")
        radiation = pd.to_datetime(a["date_radiation"], errors="coerce")
        if int((radiation < adhesion).sum()):
            rapport.ajouter(
                f"assures.csv : {int((radiation < adhesion).sum())} radiation(s) "
                "anterieure(s) a l'adhesion."
            )


def controler_numeriques(tables: dict[str, pd.DataFrame], rapport: Rapport) -> None:
    """Un numerique qui contient du texte casse silencieusement les calculs."""
    controles = {
        "factures.csv": ("montant_total", "montant_eligible", "montant_pris_en_chance"),
        "lignes_facture.csv": ("quantite", "montant"),
        "referentiel_actes.csv": ("tarif_reference",),
        "referentiel_medicaments.csv": ("prix_reference",),
        "garanties.csv": ("taux_remboursement",),
        "grille_tarifaire.csv": ("tarif_pratique",),
    }
    for nom, colonnes in controles.items():
        if nom not in tables:
            continue
        for colonne in colonnes:
            if colonne not in tables[nom].columns:
                continue
            valeurs = tables[nom][colonne].dropna()
            if not valeurs.empty and not pd.api.types.is_numeric_dtype(valeurs):
                rapport.ajouter(f"{nom}.{colonne} : valeur non numerique detectee.")


def controler_labels(tables: dict[str, pd.DataFrame], rapport: Rapport) -> None:
    """Les labels doivent couvrir les factures, sans quoi la cible est biaisee."""
    if "labels_fraude.csv" not in tables or "factures.csv" not in tables:
        return
    labels = set(tables["labels_fraude.csv"]["facture_id"])
    factures = set(tables["factures.csv"]["facture_id"])
    manquants = len(factures - labels)
    if manquants:
        rapport.ajouter(
            f"labels_fraude.csv : {manquants} facture(s) sans label. "
            "La cible supervisee serait incomplete."
        )
    if "est_fraude" in tables["labels_fraude.csv"].columns:
        valeurs = set(tables["labels_fraude.csv"]["est_fraude"].dropna().unique())
        if not valeurs <= {0, 1}:
            rapport.ajouter(
                f"labels_fraude.csv : est_fraude contient {sorted(valeurs)}, "
                "seuls 0 et 1 sont attendus."
            )
        rapport.mesurer("taux de fraude", f"{float(tables['labels_fraude.csv']['est_fraude'].mean()):.4f}")


def valider(tables: dict[str, pd.DataFrame], rapport: Rapport | None = None) -> Rapport:
    """Enchaine tous les controles bloquants."""
    r = rapport or Rapport()
    controler_schema(tables, r)
    if r.ok:
        controler_unicite(tables, r)
        controler_integrite(tables, r)
        controler_dates(tables, r)
        controler_numeriques(tables, r)
        controler_labels(tables, r)
    return r
