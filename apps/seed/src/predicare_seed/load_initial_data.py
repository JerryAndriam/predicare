"""Charge le jeu de donnees de l'encadrement dans PostgreSQL.

14 fichiers, environ 436 700 lignes, en une seule transaction.

Trois decisions qui commandent le reste :

1. **COPY, pas INSERT.** Un `executemany` sur 123 270 lignes de
   `lignes_facture` prendrait plusieurs minutes. `COPY` prend quelques
   secondes. Le passeur pandas fournit les lignes sans jamais materialiser
   la table entiere en memoire.

2. **Les cles externes sont resolues en memoire.** Le jeu utilise des
   identifiants lisibles (`FAC-...`, `PRE-...`, `CTR-...`, `ORD-...`,
   `ASS-...`) pendant que le schema porte des entiers `SERIAL`. Six
   dictionnaires font la correspondance pendant le chargement. `core.facture`,
   `core.ordonnance`, `core.contrat` et `core.prestataire` conservent la cle
   externe dans `reference` / `code`, ce qui rend le rechargement reproductible.

3. **Aucune reparation.** Les valeurs manquantes restent NULL : 44 % des
   factures n'ont pas d'ordonnance, et cette absence est un signal, pas un
   defaut. La validation est portee par `predicare_seed.validation`.

Pseudonymisation
----------------
Les assures sont pseudonymises par HMAC-SHA256 (`predicare.crypto`), jamais
nommés. `identites_pii.csv` est le SEUL fichier nominatif du jeu : il alimente
`core.identite_chiffree`, chiffree en Fernet, et rien d'autre. Aucune de ses
valeurs n'atteint une table metier -- c'est l'exigence RGPD du CDC.

Validite metier
---------------
`labels_fraude.csv` livre `est_valide` et `motif_invalidite` vides. L'information
equivalent est portee par `factures.statut` et `factures.motif_rejet` : on la
derive ici. Elle atterrit dans `ml.label_fraude`, jamais dans `core`, ce qui
ecarte par construction toute reprise de ces colonnes comme variables du
modele.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from predicare.config import get_settings
from predicare.crypto import encrypt_value, pseudonymize
from predicare.logging_config import configure_logging, get_logger
from predicare_seed.validation import TABLES_A_PURGER, controler_presence, valider

RAW_DIR = Path("/data/raw")


def _copier(cur, table: str, colonnes: list[str], lignes) -> int:
    """COPY un lot de lignes ; renvoie le nombre ecrit.

    La longueur de chaque tuple est verifiee avant le premier octet ecrit. Sans
    cette assertion, un tuple trop court decale toutes les colonnes suivantes
    et l'erreur PostgreSQL ne parle que de la premiere valeur mal typee, sans
    designer la ligne fautive : le message devient
    `invalid input syntax for type smallint: "t"` sur `age_min`, alors que la
    vraie cause etait un `None` de trop ou de trop peu en amont.
    """
    attendu = len(colonnes)
    total = 0
    for index, ligne in enumerate(lignes, start=1):
        if len(ligne) != attendu:
            raise ValueError(
                f"{table} : ligne {index}, {len(ligne)} valeur(s) pour {attendu} "
                f"colonne(s). Le mapping est decale."
            )
        total += 1
    colonnes_sql = ", ".join(colonnes)
    with cur.copy(f"COPY {table} ({colonnes_sql}) FROM STDIN") as copieur:
        for ligne in lignes:
            copieur.write_row(ligne)
    return total


def _vide(cur) -> None:
    """Purge complete. `CASCADE` emporte les tables enfants.

    `RESTART IDENTITY` n'est pas decoratif : sans lui, `TRUNCATE` vide les
    tables mais laisse les sequences SERIAL a leur valeur courante. Les
    identifiants generes repartiraient alors de 1501 au lieu de 1, et les
    correspondances construites par position -- `acte`, `prestataire`,
    `contrat`, `ordonnance`, `facture` -- designeraient des lignes qui
    n'existent pas. La purge deviendrait, de facon tres discrete, un
    rechargement faux.
    """
    cur.execute("TRUNCATE " + ", ".join(TABLES_A_PURGER) + " RESTART IDENTITY CASCADE")


def charger_actes(conn, courbes, r) -> None:
    """Referentiel des actes ET des medicaments dans `core.acte`.

    Les deux partagent la table parce que `core.grille_tarifaire.acte_id` les
    reference par la meme cle etrangere, et que la grille melange des codes
    d'acte et des codes `MED-*`. Le discriminant est `unite`.
    """
    actes = courbes["referentiel_actes.csv"]
    medicaments = courbes["referentiel_medicaments.csv"]

    lignes: list[tuple] = []
    for _, a in actes.iterrows():
        lignes.append(
            (
                str(a["code_acte"]),
                str(a.get("libelle") or ""),
                "acte",
                float(a.get("tarif_reference") or 0),
                True,
                str(a.get("categorie") or "") or None,
                str(a.get("specialite") or "") or None,
                float(a["tarif_min"]) if pd.notna(a.get("tarif_min")) else None,
                float(a["tarif_max"]) if pd.notna(a.get("tarif_max")) else None,
                None if pd.isna(a.get("ordonnance_requise")) else bool(a["ordonnance_requise"]),
                None if pd.isna(a.get("entente_prealable")) else bool(a["entente_prealable"]),
                str(a["sexe_requis"]) if pd.notna(a.get("sexe_requis")) else None,
                None if pd.isna(a.get("age_min")) else int(a["age_min"]),
                None if pd.isna(a.get("age_max")) else int(a["age_max"]),
                None, None, None,  # colonnes medicament
            )
        )
    for _, m in medicaments.iterrows():
        lignes.append(
            (
                str(m["code_medicament"]),
                str(m.get("libelle") or ""),
                "medicament",
                float(m.get("prix_reference") or 0),
                True,
                "MEDICAMENT", str(m.get("classe") or "") or None,
                # 7 colonnes absentes : tarif_min, tarif_max,
                # ordonnance_requise, entente_prealable, sexe_requis,
                # age_min, age_max. Avec 5 seulement, `remboursable` se
                # retrouvait sur `age_min` et COPY echouait sur « t ».
                None, None, None, None, None, None, None,
                None if pd.isna(m.get("remboursable")) else bool(m["remboursable"]),
                str(m.get("classe") or "") or None,
                None if pd.isna(m.get("chronique")) else bool(m["chronique"]),
            )
        )
    _copier(
        courbes["cur"],
        "core.acte",
        ["code", "libelle", "unite", "prix_unitaire", "actif", "categorie", "specialite",
         "tarif_min", "tarif_max", "ordonnance_requise", "entente_prealable",
         "sexe_requis", "age_min", "age_max", "remboursable", "classe_molecule", "chronique"],
        lignes,
    )
    r.mesurer("core.acte", f"{len(lignes)} lignes")


def charger_garanties(conn, courbes, r) -> None:
    g = courbes["garanties.csv"]
    lignes = [
        (
            str(g["formule"]),
            str(g["categorie"]),
            float(g["taux_remboursement"]),
            float(g["plafond_annuel_categorie"]) if pd.notna(g.get("plafond_annuel_categorie")) else None,
            float(g["franchise_par_facture"]) if pd.notna(g.get("franchise_par_facture")) else None,
            None if pd.isna(g.get("delai_carence_jours")) else int(g["delai_carence_jours"]),
            float(g["plafond_annuel_global"]) if pd.notna(g.get("plafond_annuel_global")) else None,
            float(g["prime_annuelle_par_beneficiaire"]) if pd.notna(g.get("prime_annuelle_par_beneficiaire")) else None,
            None if pd.isna(g.get("attestation_requise")) else bool(g["attestation_requise"]),
            str(g["actes_exclus"]) if pd.notna(g.get("actes_exclus")) else None,
            str(g["pieces_justificatives"]) if pd.notna(g.get("pieces_justificatives")) else None,
        )
        for _, g in g.iterrows()
    ]
    _copier(
        courbes["cur"], "core.garantie_formule",
        ["formule", "categorie", "taux_remboursement", "plafond_annuel_categorie",
         "franchise_par_facture", "delai_carence_jours", "plafond_annuel_global",
         "prime_annuelle_par_beneficiaire", "attestation_requise", "actes_exclus",
         "pieces_justificatives"],
        lignes,
    )
    r.mesurer("core.garantie_formule", f"{len(lignes)} lignes")


def charger_prestataires(conn, courbes, r) -> None:
    p = courbes["prestataires.csv"]
    lignes = [
        (
            str(p["prestataire_id"]),
            str(p.get("nom") or ""),
            str(p.get("specialite") or ""),
            str(p.get("type_prestataire") or "liberal"),
            str(p.get("statut") or "ACTIF").upper() != "RADIE",
            str(p["ville"]) if pd.notna(p.get("ville")) else None,
            str(p["quartier"]) if pd.notna(p.get("quartier")) else None,
            str(p["adresse"]) if pd.notna(p.get("adresse")) else None,
            str(p["telephone"]) if pd.notna(p.get("telephone")) else None,
            str(p["numero_onm"]) if pd.notna(p.get("numero_onm")) else None,
            str(p["nif"]) if pd.notna(p.get("nif")) else None,
            str(p["horaires"]) if pd.notna(p.get("horaires")) else None,
            str(p["jours_ouverture"]) if pd.notna(p.get("jours_ouverture")) else None,
            str(p["heure_ouverture"]) if pd.notna(p.get("heure_ouverture")) else None,
            str(p["heure_fermeture"]) if pd.notna(p.get("heure_fermeture")) else None,
            str(p["niveau_tarif"]) if pd.notna(p.get("niveau_tarif")) else None,
            None if pd.isna(p.get("note_qualite")) else int(p["note_qualite"]),
            None if pd.isna(p.get("conventionne")) else bool(p["conventionne"]),
            None if pd.isna(p.get("date_conventionnement")) else p["date_conventionnement"],
            None if pd.isna(p.get("date_fin_convention")) else p["date_fin_convention"],
        )
        for _, p in p.iterrows()
    ]
    _copier(
        courbes["cur"], "core.prestataire",
        ["code", "nom", "specialite", "type", "actif", "ville", "quartier", "adresse",
         "telephone", "numero_onm", "nif", "horaires", "jours_ouverture",
         "heure_ouverture", "heure_fermeture", "niveau_tarif", "note_qualite",
         "conventionne", "date_conventionnement", "date_fin_convention"],
        lignes,
    )
    courbes["prestataire_id"] = {str(t[0]): i for i, t in enumerate(lignes, start=1)}
    r.mesurer("core.prestataire", f"{len(lignes)} lignes")


def _sql_date(valeur) -> str | None:
    return None if pd.isna(valeur) else str(valeur)[:10]


def charger_contrats(conn, courbes, r) -> None:
    c = courbes["contrats.csv"]
    lignes = [
        (
            str(c["contrat_id"]),
            # `numero` et `niveau` sont NOT NULL depuis 0001, et `numero`
            # porte en plus une contrainte d'unicite. Le jeu n'a aucune de ces
            # colonnes : `numero_police` s'y repete legitimement (deux contrats
            # partagent POL-2025-3761), il ne convient donc pas. On prend
            # `contrat_id`, cle externe garantie unique, et l'on garde
            # `numero_police` dans sa colonne dediee. `niveau` recoit la
            # formule, seule garantie presente dans le jeu.
            str(c["contrat_id"]),
            str(c["formule"]),
            str(c.get("numero_police") or ""),
            str(c.get("souscripteur_nom") or ""),
            str(c.get("secteur") or "") or None,
            str(c["formule"]),
            _sql_date(c.get("date_effet")),
            _sql_date(c.get("date_fin")) if pd.notna(c.get("date_fin")) else None,
            str(c.get("statut") or "ACTIF"),
            None if pd.isna(c.get("nb_beneficiaires")) else int(c["nb_beneficiaires"]),
            _sql_date(c.get("date_effet_police")),
            float(c.get("prime_annuelle_totale") or 0),
        )
        for _, c in c.iterrows()
    ]
    _copier(
        courbes["cur"], "core.contrat",
        ["reference", "numero", "niveau", "numero_police", "souscripteur", "secteur",
         "formule", "date_debut", "date_fin", "statut", "nb_beneficiaires",
         "date_effet_police", "prime_annuelle_totale"],
        lignes,
    )
    courbes["contrat_id"] = {str(t[0]): i for i, t in enumerate(lignes, start=1)}
    r.mesurer("core.contrat", f"{len(lignes)} lignes")


def charger_assures(conn, courbes, r) -> None:
    """Pseudonymise au HMAC. Aucun nom, aucune coordonnee dans `core.assure`.

    La colonne `date_naissance` du jeu est une annee, pas une date : on ne
    conserve que l'annee, conformement a la minimisation RGPD.
    """
    a = courbes["assures.csv"]
    assure_id, pseudonyme = [], []
    lignes: list[tuple] = []
    for _, x in a.iterrows():
        brut = str(x["assure_id"])
        assure_id.append(brut)
        pseudo = pseudonymize("assr", brut)
        pseudonyme.append(pseudo)
        lignes.append(
            (
                pseudo,
                None if pd.isna(x.get("annee_naissance")) else int(x["annee_naissance"]),
                str(x.get("sexe") or "") or None,
                str(x["ville"]) if pd.notna(x.get("ville")) else None,
                str(x.get("rang_beneficiaire") or ""),
            )
        )
    _copier(
        courbes["cur"], "core.assure",
        ["pseudonyme", "annee_naissance", "sexe", "commune_code"], 
        [t[:4] for t in lignes],
    )
    # Le rang du beneficiaire appartient au contrat, pas a l'assure : il va
    # dans `contrat_beneficiaire`, avec les dates d'adhesion et de radiation.
    rang = {brut: lignes[i][4] for i, brut in enumerate(assure_id)}
    courbes["assure_pseudo"] = dict(zip(assure_id, pseudonyme, strict=True))
    courbes["assure_rang"] = rang
    r.mesurer("core.assure", f"{len(lignes)} lignes")


def charger_beneficiaires(conn, courbes, r) -> None:
    a = courbes["assures.csv"]
    pseudo = courbes["assure_pseudo"]
    rang = courbes["assure_rang"]
    contrat = courbes["contrat_id"]

    lignes: list[tuple] = []
    for _, x in a.iterrows():
        brut = str(x["assure_id"])
        lignes.append(
            (
                contrat[str(x["contrat_id"])],
                courbes["assure_row"][pseudo[brut]],
                rang[brut],
                _sql_date(x.get("date_adhesion")),
                _sql_date(x.get("date_radiation")),
            )
        )
    _copier(
        courbes["cur"], "core.contrat_beneficiaire",
        ["contrat_id", "assure_id", "rang_beneficiaire", "date_adhesion", "date_radiation"],
        lignes,
    )
    r.mesurer("core.contrat_beneficiaire", f"{len(lignes)} lignes")


def charger_identites(conn, courbes, r) -> None:
    """Seul point d'entree des donnees nominatives, et il est chiffre.

    `identites_pii.csv` contient nom, prenoms, date de naissance, telephone,
    email, adresse et numero de CIN. Rien de tout cela n'atteint une table
    metier : le tout part en Fernet dans `core.identite_chiffree`.
    """
    p = courbes["identites_pii.csv"]
    pseudo = courbes["assure_pseudo"]
    lignes: list[tuple] = []
    for _, x in p.iterrows():
        brut = str(x["assure_id"])
        nom = f"{x.get('nom') or ''} {x.get('prenoms') or ''}".strip()
        coordonnees = " | ".join(
            str(x[c])
            for c in ("telephone", "email", "adresse", "ville", "numero_cin")
            if pd.notna(x.get(c))
        )
        lignes.append(
            (
                pseudo[brut],
                encrypt_value(brut).encode(),
                encrypt_value(nom).encode(),
                encrypt_value(coordonnees).encode() if coordonnees else None,
                encrypt_value(str(x["date_naissance"])).encode()
                if pd.notna(x.get("date_naissance"))
                else None,
            )
        )
    _copier(
        courbes["cur"], "core.identite_chiffree",
        ["pseudonyme", "reference_brute_chiffree", "nom_chiffre", "coordonnees_chiffrees",
         "date_naissance_chiffree"],
        lignes,
    )
    r.mesurer("core.identite_chiffree", f"{len(lignes)} lignes (chiffre)")


def charger_ordonnances(conn, courbes, r) -> None:
    o = courbes["ordonnances.csv"]
    pseudo = courbes["assure_pseudo"]
    prest = courbes["prestataire_id"]
    lignes: list[tuple] = []
    for _, x in o.iterrows():
        prescripteur = str(x.get("prescripteur_id") or "")
        lignes.append(
            (
                str(x["ordonnance_id"]),
                courbes["assure_row"][pseudo[str(x["assure_id"])]],
                prest.get(prescripteur),
                _sql_date(x.get("date_prescription")),
                None if pd.isna(x.get("validite_jours")) else int(x["validite_jours"]),
                str(x.get("type_ordonnance") or "") or None,
                str(x["diagnostic"]) if pd.notna(x.get("diagnostic")) else None,
                str(x["renseignement_clinique"]) if pd.notna(x.get("renseignement_clinique")) else None,
            )
        )
    _copier(
        courbes["cur"], "core.ordonnance",
        ["reference", "assure_id", "prestataire_id", "date_ordonnance", "validite_jours",
         "type_ordonnance", "diagnostic", "renseignement_clinique"],
        lignes,
    )
    courbes["ordonnance_id"] = {str(t[0]): i for i, t in enumerate(lignes, start=1)}
    r.mesurer("core.ordonnance", f"{len(lignes)} lignes")


def charger_ordonnance_lignes(conn, courbes, r) -> None:
    ol = courbes["ordonnance_lignes.csv"]
    acte = courbes["acte_id"]
    ordonnance = courbes["ordonnance_id"]
    lignes = [
        (
            ordonnance[str(ol.iloc[i]["ordonnance_id"])],
            int(ol.iloc[i]["num_ligne"]),
            acte[str(ol.iloc[i]["code"])],
            str(ol.iloc[i]["libelle"]) if pd.notna(ol.iloc[i].get("libelle")) else None,
            int(ol.iloc[i]["quantite"]),
            str(ol.iloc[i]["posologie"]) if pd.notna(ol.iloc[i].get("posologie")) else None,
        )
        for i in range(len(ol))
    ]
    _copier(
        courbes["cur"], "core.ordonnance_ligne",
        ["ordonnance_id", "num_ligne", "acte_id", "libelle", "quantite", "posologie"],
        lignes,
    )
    r.mesurer("core.ordonnance_ligne", f"{len(lignes)} lignes")


def charger_factures(conn, courbes, r) -> None:
    f = courbes["factures.csv"]
    pseudo = courbes["assure_pseudo"]
    row_assure = courbes["assure_row"]
    prest = courbes["prestataire_id"]
    contrat = courbes["contrat_id"]
    ordonnance = courbes["ordonnance_id"]

    lignes: list[tuple] = []
    for _, x in f.iterrows():
        lignes.append(
            (
                str(x["facture_id"]),
                row_assure[pseudo[str(x["assure_id"])]],
                prest.get(str(x["prestataire_id"])),
                float(x.get("montant_total") or 0),
                str(x.get("statut") or "EN_COURS"),
                str(x.get("numero_facture") or "") or None,
                contrat.get(str(x["contrat_id"])) if pd.notna(x.get("contrat_id")) else None,
                ordonnance.get(str(x["ordonnance_id"])) if pd.notna(x.get("ordonnance_id")) else None,
                str(x.get("type_facture") or "") or None,
                _sql_date(x.get("date_soin")) if pd.notna(x.get("date_soin")) else None,
                str(x["heure_soin"]) if pd.notna(x.get("heure_soin")) else None,
                _sql_date(x.get("date_facture")) if pd.notna(x.get("date_facture")) else None,
                str(x.get("canal_reception") or "") or None,
                str(x.get("mode_reglement") or "") or None,
                str(x["attestation_pec_id"]) if pd.notna(x.get("attestation_pec_id")) else None,
                str(x["entente_prealable_id"]) if pd.notna(x.get("entente_prealable_id")) else None,
                str(x.get("devise") or "MGA"),
                None if pd.isna(x.get("nb_lignes")) else int(x["nb_lignes"]),
                float(x["montant_eligible"]) if pd.notna(x.get("montant_eligible")) else None,
                float(x["montant_pris_en_charge"]) if pd.notna(x.get("montant_pris_en_charge")) else None,
                float(x["reste_a_charge"]) if pd.notna(x.get("reste_a_charge")) else None,
                str(x["motif_rejet"]) if pd.notna(x.get("motif_rejet")) else None,
                _sql_date(x.get("date_traitement")) if pd.notna(x.get("date_traitement")) else None,
            )
        )
    _copier(
        courbes["cur"], "core.facture",
        ["reference", "assure_id", "prestataire_id", "montant_total", "statut",
         "numero_facture", "contrat_id", "ordonnance_id", "type_facture", "date_soin",
         "heure_soin", "date_facture", "canal_reception", "mode_reglement",
         "attestation_pec_id", "entente_prealable_id", "devise", "nb_lignes",
         "montant_eligible", "montant_pris_en_charge", "reste_a_charge",
         "motif_rejet", "date_traitement"],
        lignes,
    )
    courbes["facture_id"] = {str(t[0]): i for i, t in enumerate(lignes, start=1)}
    r.mesurer("core.facture", f"{len(lignes)} lignes")


def charger_lignes_facture(conn, courbes, r) -> None:
    lf = courbes["lignes_facture.csv"]
    acte = courbes["acte_id"]
    facture = courbes["facture_id"]
    # `date_acte` est NOT NULL depuis 0001, et `lignes_facture.csv` n'a aucune
    # colonne de date : la date du soin appartient a la facture mere. Le plan
    # de l'API lit d'ailleurs `date_soin`, pas `date_acte`.
    date_soin = courbes["facture_date_soin"]
    lignes = [
        (
            facture[str(lf.iloc[i]["facture_id"])],
            None if pd.isna(lf.iloc[i].get("num_ligne")) else int(lf.iloc[i]["num_ligne"]),
            acte[str(lf.iloc[i]["code"])],
            str(lf.iloc[i]["libelle"]) if pd.notna(lf.iloc[i].get("libelle")) else None,
            str(lf.iloc[i]["type_ligne"]) if pd.notna(lf.iloc[i].get("type_ligne")) else None,
            int(lf.iloc[i]["quantite"]),
            float(lf.iloc[i]["prix_unitaire"]),
            float(lf.iloc[i]["montant"]),
            date_soin[str(lf.iloc[i]["facture_id"])],
        )
        for i in range(len(lf))
    ]
    _copier(
        courbes["cur"], "core.ligne_facture",
        ["facture_id", "num_ligne", "acte_id", "libelle", "type_ligne", "quantite",
         "montant_unitaire", "montant", "date_acte"],
        lignes,
    )
    r.mesurer("core.ligne_facture", f"{len(lignes)} lignes")


def charger_grille(conn, courbes, r) -> None:
    g = courbes["grille_tarifaire.csv"]
    prest = courbes["prestataire_id"]
    acte = courbes["acte_id"]
    lignes = [
        (prest[str(g.iloc[i]["prestataire_id"])], acte[str(g.iloc[i]["code"])],
         float(g.iloc[i]["tarif_pratique"]))
        for i in range(len(g))
    ]
    _copier(courbes["cur"], "core.grille_tarifaire",
            ["prestataire_id", "acte_id", "tarif_pratique"], lignes)
    r.mesurer("core.grille_tarifaire", f"{len(lignes)} lignes")


def charger_labels(conn, courbes, r) -> None:
    """Labels de fraude, et validite metier derivee de `factures.statut`.

    `labels_fraude.csv` livre `est_valide` et `motif_invalidite` vides. La meme
    information existe dans `core.facture` sous forme de `statut` et
    `motif_rejet` : 1 992 factures sont REJETEE avec l'un des huit motifs
    documentes. On la derive plutot que de laisser vide.

    Ces colonnes atterrissent dans `ml`, jamais dans `core` : le CDC distingue
    les donnees metier d'un fichier de labels separe, et cette disposition
    ecarte par construction que le feature engineering prenne une colonne de
    decision historique pour une variable explicative.
    """
    labels = courbes["labels_fraude.csv"]
    facture = courbes["facture_id"]
    statut = courbes["facture_statut"]
    motif = courbes["facture_motif"]

    lignes = []
    invalides = 0
    for _, x in labels.iterrows():
        ref = str(x["facture_id"])
        st = statut.get(ref, "")
        rejetee = str(st).upper() == "REJETEE"
        if rejetee:
            invalides += 1
        lignes.append(
            (
                facture[ref],
                int(x["est_fraude"]),
                str(x["type_fraude"]) if pd.notna(x.get("type_fraude")) else None,
                str(x["detail_fraude"]) if pd.notna(x.get("detail_fraude")) else None,
                not rejetee,
                motif.get(ref) if rejetee else None,
            )
        )
    _copier(
        courbes["cur"], "ml.label_fraude",
        ["facture_id", "label", "type_fraude", "detail_fraude", "est_valide", "motif_invalidite"],
        lignes,
    )
    r.mesurer("ml.label_fraude", f"{len(lignes)} lignes, dont {invalides} invalides")

    lp = courbes["labels_prestataires.csv"]
    prest = courbes["prestataire_id"]
    lignes_p = [
        (prest[str(lp.iloc[i]["prestataire_id"])], int(lp.iloc[i]["est_suspect"]))
        for i in range(len(lp))
    ]
    _copier(courbes["cur"], "ml.label_prestataire", ["prestataire_id", "est_suspect"], lignes_p)
    r.mesurer("ml.label_prestataire", f"{len(lignes_p)} lignes")


def main() -> int:
    """Point d'entree du conteneur `seed`."""
    debut = time.monotonic()
    configure_logging("seed", get_settings().log_level, get_settings().log_format)
    logger = get_logger("seed")

    presents, manquants = controler_presence(RAW_DIR)
    if not presents:
        logger.warning(
            "donnees.absentes",
            chemin=str(RAW_DIR),
            message=(
                "Aucun jeu de donnees trouve. La base reste vide mais la plateforme "
                "demarre. Depposez les CSV dans ./data/raw puis lancez `make reload-data`."
            ),
        )
        return 0

    logger.info("donnees.presentes", fichiers=len(presents))
    if manquants:
        logger.warning("donnees.incompletes", manquants=sorted(manquants))

    # --- Lecture -------------------------------------------------------
    logger.info("lecture.debut")
    courbes: dict[str, pd.DataFrame] = {}
    for nom in presents:
        courbes[nom] = pd.read_csv(RAW_DIR / nom, low_memory=False)
    logger.info("lecture.terminee", duree_s=round(time.monotonic() - debut, 1))

    # --- Validation, AVANT toute ecriture -------------------------------
    rapport = valider(courbes)
    for cle, valeur in sorted(rapport.mesures.items()):
        logger.info("mesure", element=cle, valeur=valeur)
    if not rapport.ok:
        logger.error("validation.echouee", anomalies=rapport.anomalies)
        for anomalie in rapport.anomalies:
            print(f"  [ANOMALIE] {anomalie}", flush=True)
        print("", flush=True)
        print("  Chargement annule : aucun ecrit en base.", flush=True)
        return 1
    logger.info("validation.ok")

    # --- Chargement, dans une seule transaction -------------------------
    from predicare.db import session_scope

    with session_scope() as session:
        cur = session.connection().connection.cursor()
        # Le curseur est range dans le dictionnaire partage : tous les
        # `charger_*` le retrouvent sans le recevoir en parametre.
        courbes["cur"] = cur

        _vide(cur)
        logger.info("purge.terminee")

        # `core.acte` et `core.assure` d'abord : tout le reste s'y reference.
        charger_actes(session, courbes, rapport)
        cur.execute("SELECT id, code FROM core.acte")
        courbes["acte_id"] = {c: i for i, c in cur.fetchall()}

        charger_garanties(session, courbes, rapport)
        charger_prestataires(session, courbes, rapport)

        # Les identifiants generes par SERIAL sont captures par ordre
        # d'insertion : COPY les renvoie dans l'ordre du passeur.
        charger_assures(session, courbes, rapport)
        cur.execute("SELECT id, pseudonyme FROM core.assure ORDER BY id")
        courbes["assure_row"] = {p: i for i, p in cur.fetchall()}

        charger_contrats(session, courbes, rapport)
        charger_beneficiaires(session, courbes, rapport)
        charger_identites(session, courbes, rapport)
        charger_ordonnances(session, courbes, rapport)
        charger_ordonnance_lignes(session, courbes, rapport)
        charger_factures(session, courbes, rapport)

        courbes["facture_date_soin"] = {
            str(x["facture_id"]): _sql_date(x.get("date_soin"))
            for _, x in courbes["factures.csv"].iterrows()
        }
        charger_lignes_facture(session, courbes, rapport)
        charger_grille(session, courbes, rapport)

        # Les statuts sont lus AVANT les labels : c'est de `core.facture`
        # que derives `est_valide` et `motif_invalidite`.
        cur.execute("SELECT reference, statut, motif_rejet FROM core.facture")
        courbes["facture_statut"] = {ref: st for ref, st, _ in cur.fetchall()}
        courbes["facture_motif"] = {
            ref: m for ref, _, m in cur.fetchall() if m is not None
        }
        cur.close()

        charger_labels(session, courbes, rapport)

    duree = time.monotonic() - debut
    logger.info("chargement.termine", duree_s=round(duree, 1), tables=len(rapport.mesures))
    print("", flush=True)
    for cle, valeur in sorted(rapport.mesures.items()):
        print(f"  {cle:32} {valeur}", flush=True)
    print(f"\n  Chargement termine en {duree:.1f}s.\n", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
