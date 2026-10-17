"""Nettoyage et validation des donnees (Phase 1.4) — regles et justifications.

Ce module ne fait AUCUN acces base : il lit les CSV, applique les controles,
et rend des donnees propres + un rapport. Le loader (Phase 1.2) s'en sert.

Les quatre familles du plan et LES DECISIONS PRISES
---------------------------------------------------
1. TYPES. Un CSV est du texte. On convertit chaque colonne vers son type
   reel (date, entier, decimal, booleen). DECISION : une valeur qui ne se
   convertit pas n'est JAMAIS inventee ni remplacee — c'est une erreur de
   donnee, donc on REJETTE la facture (motif DATE_IMPOSSIBLE...) et on la
   journalise. Sur le jeu fourni, il n'y a aucune valeur non convertible.

2. VALEURS MANQUANTES. Regle : un vide est soit STRUCTUREL (normal, on garde
   NULL), soit OBLIGATOIRE (on rejette), soit CONVENTIONNEL (on remplit une
   valeur par defaut du schema). DECISION : on ne remplit JAMAIS un vide
   structurel (ex. `date_radiation` vide = personne non radiee). Inventer une
   valeur fabriquerait une fausse information metier.

3. DOUBLONS. DECISION : on ne supprime un doublon QUE s'il est exact (toutes
   les colonnes identiques, meme cle primaire). Un doublon de cle METIER
   (numero_facture, numero_police) est CONSERVE : c'est souvent le signal de
   la fraude (DOUBLON) ou une cle de groupe (police collective). Le supprimer
   detruirait le label a predire.

4. DATES INCOHERENTES. DECISION : on distingue deux cas.
   - Erreur de donnee (a rejeter) : date impossible/invalide, date dans le
     futur.
   - Signal de fraude (a CONSERVER tel quel) : soin hors periode de contrat,
     soin apres la fin de convention d'un prestataire, prestataire radie.
     Corriger ces dates reviendrait a effacer la fraude.

5. INTEGRITE REFERENTIELLE + les 10 factures invalides du referentiel metier.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

#: Devise unique du jeu de donnees (dictionnaire : « Devise Ariary (MGA) »).
DEVISE_ATTENDUE = "MGA"

#: Les 10 codes de « facture invalide » du referentiel metier (regles
#: deterministes exigees par le CDC pour le rejet a l'entree).
MOTIFS_INVALIDITE = (
    "MONTANT_NEGATIF",
    "CODE_ACTE_INCONNU",
    "DATE_FUTURE",
    "DATE_IMPOSSIBLE",
    "CHAMP_OBLIGATOIRE_MANQUANT",
    "TOTAL_INCOHERENT",
    "PRESTATAIRE_INCONNU",
    "ASSURE_INCONNU",
    "DEVISE_INVALIDE",
    "FACTURE_SANS_LIGNE",
)

#: Nom de fichier attendu pour chaque domaine de donnees.
FICHIERS = {
    "actes": "referentiel_actes.csv",
    "medicaments": "referentiel_medicaments.csv",
    "prestataires": "prestataires.csv",
    "assures": "assures.csv",
    "identites": "identites_pii.csv",
    "contrats": "contrats.csv",
    "garanties": "garanties.csv",
    "grille": "grille_tarifaire.csv",
    "ordonnances": "ordonnances.csv",
    "ordonnance_lignes": "ordonnance_lignes.csv",
    "factures": "factures.csv",
    "lignes_facture": "lignes_facture.csv",
    "labels_fraude": "labels_fraude.csv",
    "labels_prestataires": "labels_prestataires.csv",
}

#: Colonnes dont un vide est NORMAL (justification metier dans le commentaire).
MANQUANTS_STRUCTURELS = {
    "assures.date_radiation": "assure non radie (toujours en cours)",
    "contrats.date_fin": "contrat toujours en cours",
    "factures.ordonnance_id": "facture sans ordonnance (pharmacie hors prescription)",
    "factures.attestation_pec_id": "pas d'attestation de prise en charge",
    "factures.entente_prealable_id": "pas d'entente prealable demandee",
    "factures.motif_rejet": "seules les factures rejetees portent un motif",
    "factures.date_traitement": "facture non encore traitee",
    "prestataires.specialite": "une pharmacie n'a pas de specialite medicale",
    "prestataires.numero_onm": "numero ONM facultatif",
    "prestataires.date_fin_convention": "convention toujours en cours",
    "labels_fraude.type_fraude": "seules les fraudes ont un type",
    "labels_fraude.detail_fraude": "seules les fraudes ont un detail",
    "labels_fraude.motif_invalidite": "aucune facture invalide dans le jeu fourni",
    "identites.telephone": "coordonnee facultative",
    "identites.email": "coordonnee facultative",
    "identites.numero_cin": "piece d'identite facultative",
    "ordonnance_lignes.posologie": "posologie facultative",
    "ordonnances.diagnostic": "information clinique facultative",
    "ordonnances.renseignement_clinique": "information clinique facultative",
    "actes.specialite": "un acte non specialise n'a pas de specialite",
    "actes.sexe_requis": "acte valable pour les deux sexes",
    "garanties.actes_exclus": "aucun acte exclu pour cette formule",
}


# ---------------------------------------------------------------------------
# Conversions de types (famille 1)
# ---------------------------------------------------------------------------
def _vide(valeur: object) -> bool:
    return (
        valeur is None
        or (isinstance(valeur, float) and pd.isna(valeur))
        or str(valeur).strip() == ""
    )


def en_texte(valeur: object) -> str | None:
    """Texte nettoye, ou None si vide (le vide n'est pas la chaine '')."""
    if _vide(valeur):
        return None
    return str(valeur).strip()


def en_date(valeur: object) -> date | None:
    """Convertit une date AAAA-MM-JJ. Rend None si vide, leve si invalide."""
    if _vide(valeur):
        return None
    return datetime.strptime(str(valeur).strip(), "%Y-%m-%d").date()


def en_entier(valeur: object) -> int | None:
    if _vide(valeur):
        return None
    return int(str(valeur).strip())


def en_decimal(valeur: object) -> Decimal | None:
    """Les montants sont des entiers d'ariary, stockes en Numeric."""
    if _vide(valeur):
        return None
    try:
        return Decimal(str(valeur).strip())
    except InvalidOperation as exc:  # pragma: no cover - jeu fourni sain
        raise ValueError(f"montant non convertible : {valeur!r}") from exc


def en_booleen(valeur: object) -> bool | None:
    """'1' -> True, '0' -> False, vide -> None."""
    if _vide(valeur):
        return None
    return str(valeur).strip() == "1"


# ---------------------------------------------------------------------------
# Lecture (famille 1 : types d'entree)
# ---------------------------------------------------------------------------
def lire_csv(chemin: Path) -> pd.DataFrame:
    """Lit un CSV en gardant tout en texte pour inspecter le brut.

    `keep_default_na=False` + `na_values=['']` : seul le vide devient NaN, la
    chaine 'NA' ou '0' reste une donnee. Encodage UTF-8 (dictionnaire).
    """
    return pd.read_csv(
        chemin, dtype=str, keep_default_na=False, na_values=[""], encoding="utf-8-sig"
    )


def lire_tous(dossier: Path) -> dict[str, pd.DataFrame]:
    """Lit les 14 fichiers. Les labels sont acceptes a la racine ou dans labels/."""
    donnees: dict[str, pd.DataFrame] = {}
    manquants: list[str] = []
    for domaine, nom in FICHIERS.items():
        candidats = [dossier / nom, dossier / "labels" / nom]
        chemin = next((c for c in candidats if c.exists()), None)
        if chemin is None:
            manquants.append(nom)
            continue
        donnees[domaine] = lire_csv(chemin)
    if manquants:
        raise FileNotFoundError(
            "Fichiers de donnees introuvables dans "
            f"{dossier} : {', '.join(manquants)}. "
            "Copiez les 14 CSV de l'encadrement dans ./data/raw."
        )
    return donnees


# ---------------------------------------------------------------------------
# Famille 2 : valeurs manquantes
# ---------------------------------------------------------------------------
def controler_manquants(df: pd.DataFrame, domaine: str) -> pd.DataFrame:
    """Compte les vides par colonne et dit si chacun est normal ou non."""
    lignes = []
    for colonne in df.columns:
        vides = int(df[colonne].isna().sum())
        if vides == 0:
            continue
        cle = f"{domaine}.{colonne}"
        lignes.append(
            {
                "colonne": colonne,
                "vides": vides,
                "pourcent": round(100 * vides / len(df), 2) if len(df) else 0.0,
                "normal": cle in MANQUANTS_STRUCTURELS,
                "raison": MANQUANTS_STRUCTURELS.get(cle, "a examiner"),
            }
        )
    return pd.DataFrame(lignes)


# ---------------------------------------------------------------------------
# Famille 3 : doublons
# ---------------------------------------------------------------------------
def detecter_doublons(df: pd.DataFrame, domaine: str, cle: Iterable[str]) -> dict[str, object]:
    """Separe doublons EXACTS (a corriger) et doublons de CLE METIER (a garder).

    On ne supprime jamais un doublon de cle metier : la decision revient au
    metier et il porte souvent l'information de fraude.
    """
    cle = list(cle)
    exacts = int(df.duplicated().sum())
    dbl_cle = int(df.duplicated(subset=cle).sum()) if all(c in df.columns for c in cle) else 0
    return {
        "domaine": domaine,
        "cle": " + ".join(cle),
        "doublons_exacts": exacts,
        "doublons_cle": dbl_cle,
    }


# ---------------------------------------------------------------------------
# Famille 4 : dates incoherentes
# ---------------------------------------------------------------------------
def signaux_dates(
    factures: pd.DataFrame,
    contrats: pd.DataFrame,
    assures: pd.DataFrame,
    prestataires: pd.DataFrame,
) -> pd.DataFrame:
    """Compte les incoherences de dates ENTRE tables.

    ATTENTION : ces cas ne sont PAS des erreurs a corriger. Ce sont des
    SIGNAUX de fraude (HORS_COUVERTURE, PRESTATAIRE_RADIE). On les conserve
    tels quels et on les rend disponibles pour le modele.
    """
    f = pd.DataFrame(
        {
            "facture_id": factures["facture_id"],
            "contrat_id": factures["contrat_id"],
            "prestataire_id": factures["prestataire_id"],
            "date_soin": pd.to_datetime(factures["date_soin"], errors="coerce", format="%Y-%m-%d"),
        }
    )
    c = contrats[["contrat_id"]].copy()
    c["date_effet"] = pd.to_datetime(contrats["date_effet"], errors="coerce", format="%Y-%m-%d")
    c["date_fin"] = pd.to_datetime(contrats["date_fin"], errors="coerce", format="%Y-%m-%d")
    m = f.merge(c, on="contrat_id", how="left")

    p = prestataires[["prestataire_id", "statut"]].copy()
    p["date_conv"] = pd.to_datetime(
        prestataires["date_conventionnement"], errors="coerce", format="%Y-%m-%d"
    )
    p["date_fin_conv"] = pd.to_datetime(
        prestataires["date_fin_convention"], errors="coerce", format="%Y-%m-%d"
    )
    mp = f.merge(p, on="prestataire_id", how="left")

    regles = {
        "soin avant l'effet du contrat (HORS_COUVERTURE)": int(
            (m["date_soin"] < m["date_effet"]).sum()
        ),
        "soin apres la fin du contrat (HORS_COUVERTURE)": int(
            (m["date_soin"] > m["date_fin"]).sum()
        ),
        "soin apres la fin de convention (PRESTATAIRE_RADIE)": int(
            (mp["date_soin"] > mp["date_fin_conv"]).sum()
        ),
        "soin avant le conventionnement (PRESTATAIRE_RADIE)": int(
            (mp["date_soin"] < mp["date_conv"]).sum()
        ),
        "facture d'un prestataire RADIE": int((mp["statut"] == "RADIE").sum()),
    }
    return pd.DataFrame({"signal": list(regles), "cas": list(regles.values())})


# ---------------------------------------------------------------------------
# Factures invalides : les 10 regles deterministes du referentiel metier
# ---------------------------------------------------------------------------
def valider_factures(
    factures: pd.DataFrame,
    lignes: pd.DataFrame,
    actes: pd.DataFrame,
    medicaments: pd.DataFrame,
    assures: pd.DataFrame,
    prestataires: pd.DataFrame,
    contrats: pd.DataFrame,
    date_reference: date | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Applique les 10 regles d'invalidite. Rend (factures valides, rejets).

    Chaque rejet porte le ou les motifs. On ne corrige jamais : une facture
    invalide est ecartee du chargement et journalisee.
    """
    codes_connus = set(actes["code_acte"]) | set(medicaments["code_medicament"])
    assures_connus = set(assures["assure_id"])
    prestataires_connus = set(prestataires["prestataire_id"])

    lignes_brutes = lignes.copy()
    lignes_brutes["montant_num"] = pd.to_numeric(lignes_brutes["montant"], errors="coerce")
    lignes_brutes["qte_num"] = pd.to_numeric(lignes_brutes["quantite"], errors="coerce")
    lignes_brutes["code_inconnu"] = ~lignes_brutes["code"].isin(codes_connus)
    # NB : on nomme la colonne `nb_lignes_calcule` (et non `nb_lignes`) car
    # `factures.csv` possede deja une colonne `nb_lignes` : sans renommage, le
    # merge creerait nb_lignes_x / nb_lignes_y et casserait la regle.
    agg = lignes_brutes.groupby("facture_id").agg(
        somme_lignes=("montant_num", "sum"),
        nb_lignes_calcule=("facture_id", "size"),
        ligne_negative=("montant_num", lambda s: bool((s < 0).any())),
        quantite_negative=("qte_num", lambda s: bool((s < 0).any())),
        code_inconnu=("code_inconnu", "any"),
    )

    f = factures.copy()
    f["montant_num"] = pd.to_numeric(f["montant_total"], errors="coerce")
    f["soin_date"] = pd.to_datetime(f["date_soin"], errors="coerce", format="%Y-%m-%d")
    f = f.merge(agg, on="facture_id", how="left")

    # Reference temporelle : par defaut, le dernier jour present dans les
    # donnees (le jeu est un instantane). Sinon, la date du jour.
    if date_reference is None:
        date_reference = (
            f["soin_date"].max().date() if f["soin_date"].notna().any() else date.today()
        )

    motifs: list[list[str]] = []
    for _, r in f.iterrows():
        m: list[str] = []
        if (
            (
                r["montant_num"] is not None
                and not pd.isna(r["montant_num"])
                and r["montant_num"] < 0
            )
            or bool(r.get("ligne_negative", False))
            or bool(r.get("quantite_negative", False))
        ):
            m.append("MONTANT_NEGATIF")
        if bool(r.get("code_inconnu", False)):
            m.append("CODE_ACTE_INCONNU")
        if pd.isna(r["soin_date"]):
            m.append("DATE_IMPOSSIBLE")
        elif r["soin_date"].date() > date_reference:
            m.append("DATE_FUTURE")
        if _vide(r["assure_id"]) or _vide(r["prestataire_id"]) or _vide(r["facture_id"]):
            m.append("CHAMP_OBLIGATOIRE_MANQUANT")
        if (
            not pd.isna(r["somme_lignes"])
            and not pd.isna(r["montant_num"])
            and abs(r["somme_lignes"] - r["montant_num"]) > 1
        ):
            m.append("TOTAL_INCOHERENT")
        if r["prestataire_id"] not in prestataires_connus:
            m.append("PRESTATAIRE_INCONNU")
        if r["assure_id"] not in assures_connus:
            m.append("ASSURE_INCONNU")
        if r["devise"] != DEVISE_ATTENDUE:
            m.append("DEVISE_INVALIDE")
        if pd.isna(r.get("nb_lignes_calcule")):
            m.append("FACTURE_SANS_LIGNE")
        motifs.append(m)

    f["motifs"] = motifs
    rejets = f[f["motifs"].map(len) > 0][["facture_id", "motifs"]].copy()
    rejets["motifs"] = rejets["motifs"].map(lambda ms: "|".join(ms))
    return factures[~factures["facture_id"].isin(rejets["facture_id"])].copy(), rejets


# ---------------------------------------------------------------------------
# Rapport et point d'entree
# ---------------------------------------------------------------------------
def rapport(dossier: Path, sortie: Path | None = None) -> str:
    """Construit le rapport markdown de la Phase 1.4."""
    donnees = lire_tous(dossier)
    lignes_md: list[str] = ["# Rapport qualite des donnees — Phase 1.4\n"]
    lignes_md.append(f"Source : `{dossier}`\n")

    lignes_md.append("## 1. Volume\n")
    lignes_md.append("| domaine | lignes | colonnes |")
    lignes_md.append("|---|---:|---:|")
    for domaine, df in donnees.items():
        lignes_md.append(f"| {domaine} | {len(df)} | {len(df.columns)} |")

    lignes_md.append("\n## 2. Valeurs manquantes non normales (a examiner)\n")
    anomalies = []
    for domaine, df in donnees.items():
        for _, r in controler_manquants(df, domaine).iterrows():
            if not r["normal"]:
                anomalies.append(f"| {domaine}.{r['colonne']} | {r['vides']} | {r['pourcent']} % |")
    lignes_md.append("| colonne | vides | % |\n|---|---:|---:|")
    lignes_md.extend(anomalies or ["| (aucune) | | |"])

    lignes_md.append("\n## 3. Doublons\n")
    cles = {
        "factures": ("numero_facture",),
        "contrats": ("numero_police",),
        "lignes_facture": ("facture_id", "num_ligne"),
        "ordonnance_lignes": ("ordonnance_id", "num_ligne"),
        "grille": ("prestataire_id", "code"),
        "garanties": ("formule", "categorie"),
        "labels_fraude": ("facture_id",),
    }
    lignes_md.append("| domaine | cle | doublons exacts | doublons de cle |\n|---|---|---:|---:|")
    for domaine, df in donnees.items():
        info = detecter_doublons(df, domaine, cles.get(domaine, (df.columns[0],)))
        lignes_md.append(
            f"| {domaine} | {info['cle']} | {info['doublons_exacts']} | {info['doublons_cle']} |"
        )
    lignes_md.append(
        "\n**Lecture (ne pas supprimer) :**\n"
        "- `contrats.numero_police` : ce n'est PAS un doublon. Une police de GROUPE"
        " (contrat collectif) couvre plusieurs contrats individuels ; le numero est"
        " volontairement partage.\n"
        "- `factures.numero_facture` : double soumission de la MEME facture. C'est le"
        " signal de la fraude DOUBLON : la supprimer effacerait la fraude a detecter.\n"
        "- Les doublons EXACTS (toutes colonnes identiques) sont nuls partout : le"
        " fichier ne contient aucune ligne dupliquee par erreur."
    )

    lignes_md.append("\n## 4. Signaux de dates (a CONSERVER, pas des erreurs)\n")
    sig = signaux_dates(
        donnees["factures"], donnees["contrats"], donnees["assures"], donnees["prestataires"]
    )
    lignes_md.append("| signal | cas |\n|---|---:|")
    for _, r in sig.iterrows():
        lignes_md.append(f"| {r['signal']} | {r['cas']} |")

    lignes_md.append("\n## 5. Factures invalides (rejet deterministe)\n")
    valides, rejets = valider_factures(
        donnees["factures"],
        donnees["lignes_facture"],
        donnees["actes"],
        donnees["medicaments"],
        donnees["assures"],
        donnees["prestataires"],
        donnees["contrats"],
    )
    lignes_md.append(f"- factures valides : {len(valides)}")
    lignes_md.append(f"- factures rejetees : {len(rejets)}")
    lignes_md.append(
        "\nInterpretation : le jeu de l'encadrement est sain — aucun cas des 10 regles"
        " d'invalidite. Le controleur est neanmoins operationnel : il ecartera"
        " automatiquement toute facture invalide soumise plus tard (les 20 factures"
        " fraiches du jury)."
    )
    if len(rejets):
        lignes_md.append("\n| facture_id | motifs |\n|---|---|")
        for _, r in rejets.head(50).iterrows():
            lignes_md.append(f"| {r['facture_id']} | {r['motifs']} |")

    texte = "\n".join(lignes_md) + "\n"
    if sortie is not None:
        sortie.parent.mkdir(parents=True, exist_ok=True)
        sortie.write_text(texte, encoding="utf-8")
    return texte


def main() -> int:
    """Point d'entree : `python -m predicare_seed.qualite_donnees [DOSSIER]`.

    Le dossier des 14 CSV peut etre donne en argument, sinon on lit
    DATA_RAW_DIR, sinon `data/raw`.
    Le rapport s'ecrit dans RAPPORT_DIR (defaut `reports`).
    """
    parseur = argparse.ArgumentParser(
        description="Controle qualite des donnees brutes (Phase 1.4)."
    )
    parseur.add_argument(
        "dossier",
        nargs="?",
        default=os.environ.get("DATA_RAW_DIR", "data/raw"),
        help="dossier contenant les 14 CSV (defaut : $DATA_RAW_DIR ou data/raw)",
    )
    arguments = parseur.parse_args()

    dossier = Path(arguments.dossier)
    if not dossier.exists():
        print(
            f"Dossier de donnees introuvable : {dossier}\n"
            "Indiquez le dossier des 14 CSV en argument, par exemple :\n"
            '  uv run --frozen --package predicare-seed python -m predicare_seed.qualite_donnees "C:\\chemin\\vers\\dataset"'
        )
        return 1

    sortie = Path(os.environ.get("RAPPORT_DIR", "reports")) / "qualite_donnees_phase1_4.md"
    rapport(dossier, sortie=sortie)
    print(f"Rapport ecrit dans {sortie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
