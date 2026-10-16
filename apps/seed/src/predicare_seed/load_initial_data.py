"""Chargement initial des 14 fichiers de donnees dans PostgreSQL (Phase 1.2).

Ce script remplace l'ancien loader, qui ne lisait que 3 fichiers sur 14 et
attendait des noms de colonnes differents de ceux du jeu de l'encadrement.

Principe
--------
1. On lit les 14 CSV (`qualite_donnees.lire_tous`).
2. On VALIDE et NETTOIE (Phase 1.4) : les factures invalides sont ecartees et
   journalisees, jamais chargees.
3. On charge dans l'ORDRE DES DEPENDANCES (referentiels -> assures ->
   contrats -> factures -> lignes -> labels), en construisant des tables de
   correspondance code metier -> id de base.

Idempotence : relancer le script ne cree pas de doublon (ON CONFLICT). Les
deux seules tables sans cle metier (garantie par contrat, lignes de facture)
ne sont remplies que si elles sont vides.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from predicare.config import get_settings
from predicare.crypto import encrypt_value, get_fernet, pseudonymize
from predicare.db import session_scope
from predicare.logging_config import configure_logging, get_logger
from predicare_seed.qualite_donnees import (
    en_booleen,
    en_date,
    en_decimal,
    en_entier,
    en_texte,
    lire_tous,
    rapport,
    valider_factures,
)

configure_logging("seed", get_settings().log_level, get_settings().log_format)
logger = get_logger("seed")

#: Dossier des CSV. Par defaut le volume du compose ; surchargeable en local.
DATA_RAW_DIR = Path(os.environ.get("DATA_RAW_DIR", "/data/raw"))
#: Dossier du rapport de qualite (le volume des donnees est monte en lecture seule).
RAPPORT_DIR = Path(os.environ.get("RAPPORT_DIR", "/tmp"))


# ---------------------------------------------------------------------------
# Petits utilitaires d'insertion
# ---------------------------------------------------------------------------
def _inserer(session: Session, table: str, colonnes: tuple[str, ...], lignes: list[dict], conflit: str) -> int:
    """INSERT parametre. `conflit` est la clause ON CONFLICT complete."""
    if not lignes:
        return 0
    cols = ", ".join(colonnes)
    params = ", ".join(f":{c}" for c in colonnes)
    session.execute(
        text(f"INSERT INTO {table} ({cols}) VALUES ({params}) {conflit}"), lignes
    )
    return len(lignes)


def _upsert(session: Session, table: str, colonnes: tuple[str, ...], lignes: list[dict], cle: str) -> int:
    """INSERT ... ON CONFLICT (cle) DO UPDATE : rafraichit les referentiels."""
    if not lignes:
        return 0
    cols = ", ".join(colonnes)
    params = ", ".join(f":{c}" for c in colonnes)
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in colonnes if c != cle)
    session.execute(
        text(f"INSERT INTO {table} ({cols}) VALUES ({params}) ON CONFLICT ({cle}) DO UPDATE SET {sets}"),
        lignes,
    )
    return len(lignes)


def _carte(session: Session, requete: str) -> dict[str, int]:
    return {ligne[0]: ligne[1] for ligne in session.execute(text(requete))}


def _compter(session: Session, table: str) -> int:
    return int(session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


# ---------------------------------------------------------------------------
# 1. Referentiels : actes, medicaments, prestataires
# ---------------------------------------------------------------------------
def charger_referentiels(session: Session, d: dict[str, pd.DataFrame]) -> dict[str, dict]:
    actes = [
        {
            "code": en_texte(r["code_acte"]),
            "libelle": en_texte(r["libelle"]) or "",
            "unite": "acte",
            "prix_unitaire": en_decimal(r["tarif_reference"]) or 0,
            "categorie": en_texte(r["categorie"]),
            "specialite": en_texte(r["specialite"]),
            "tarif_min": en_decimal(r["tarif_min"]),
            "tarif_max": en_decimal(r["tarif_max"]),
            "ordonnance_requise": en_booleen(r["ordonnance_requise"]),
            "entente_prealable": en_booleen(r["entente_prealable"]),
            "sexe_requis": en_texte(r["sexe_requis"]),
            "age_min": en_entier(r["age_min"]),
            "age_max": en_entier(r["age_max"]),
        }
        for r in d["actes"].to_dict("records")
    ]
    _upsert(session, "core.acte", tuple(actes[0]), actes, "code")

    medicaments = [
        {
            "code": en_texte(r["code_medicament"]),
            "libelle": en_texte(r["libelle"]) or "",
            "prix_reference": en_decimal(r["prix_reference"]) or 0,
            "remboursable": en_booleen(r["remboursable"]),
            "classe": en_texte(r["classe"]),
            "chronique": en_booleen(r["chronique"]),
        }
        for r in d["medicaments"].to_dict("records")
    ]
    _upsert(session, "core.medicament", tuple(medicaments[0]), medicaments, "code")

    prestataires = [
        {
            "code": en_texte(r["prestataire_id"]),
            "nom": en_texte(r["nom"]) or "",
            "specialite": en_texte(r["specialite"]) or "",
            "type": en_texte(r["type_prestataire"]) or "liberal",
            # statut ACTIF/RADIE -> booleen actif (decision : on n'efface pas
            # la date de fin, on garde les deux informations).
            "actif": en_texte(r["statut"]) == "ACTIF",
            "ville": en_texte(r["ville"]),
            "quartier": en_texte(r["quartier"]),
            "adresse": en_texte(r["adresse"]),
            "telephone": en_texte(r["telephone"]),
            "numero_onm": en_texte(r["numero_onm"]),
            "nif": en_texte(r["nif"]),
            "horaires": en_texte(r["horaires"]),
            "jours_ouverture": en_texte(r["jours_ouverture"]),
            "heure_ouverture": en_texte(r["heure_ouverture"]),
            "heure_fermeture": en_texte(r["heure_fermeture"]),
            "niveau_tarif": en_texte(r["niveau_tarif"]),
            "note_qualite": en_entier(r["note_qualite"]),
            "conventionne": en_booleen(r["conventionne"]),
            "date_conventionnement": en_date(r["date_conventionnement"]),
            "date_fin_convention": en_date(r["date_fin_convention"]),
        }
        for r in d["prestataires"].to_dict("records")
    ]
    _upsert(session, "core.prestataire", tuple(prestataires[0]), prestataires, "code")

    return {
        "actes": _carte(session, "SELECT code, id FROM core.acte"),
        "medicaments": _carte(session, "SELECT code, id FROM core.medicament"),
        "prestataires": _carte(session, "SELECT code, id FROM core.prestataire"),
    }


# ---------------------------------------------------------------------------
# 2. Assures et identites chiffrees (Phase 1.3)
# ---------------------------------------------------------------------------
def charger_assures(session: Session, d: dict[str, pd.DataFrame]) -> dict[str, int]:
    """`core.assure` ne contient QUE des pseudonymes (exigence RGPD).

    On pseudonymise `assure_id` (HMAC, cf. crypto.py) : le meme assure donne
    toujours le meme pseudonyme, mais le pseudonyme n'est pas reversible.
    """
    assures = [
        {
            "pseudonyme": pseudonymize("assr", en_texte(r["assure_id"])),
            "annee_naissance": en_entier(r["annee_naissance"]),
            "sexe": en_texte(r["sexe"]),
            "commune_code": en_texte(r["ville"]),
            # Non radie = toujours actif.
            "actif": en_date(r["date_radiation"]) is None,
        }
        for r in d["assures"].to_dict("records")
    ]
    _inserer(session, "core.assure", tuple(assures[0]), assures, "ON CONFLICT (pseudonyme) DO NOTHING")

    # Identites nominatives : chiffrees et isolees dans leur propre table.
    fernet = get_fernet()
    identites = []
    for r in d["identites"].to_dict("records"):
        coordonnees = {
            "telephone": en_texte(r["telephone"]),
            "email": en_texte(r["email"]),
            "adresse": en_texte(r["adresse"]),
            "ville": en_texte(r["ville"]),
            "numero_cin": en_texte(r["numero_cin"]),
        }
        nom = " ".join(x for x in (en_texte(r["nom"]), en_texte(r["prenoms"])) if x)
        identites.append(
            {
                "pseudonyme": pseudonymize("assr", en_texte(r["assure_id"])),
                "reference_brute_chiffree": encrypt_value(en_texte(r["assure_id"]), fernet).encode(),
                "nom_chiffre": encrypt_value(nom, fernet).encode() if nom else None,
                "coordonnees_chiffrees": encrypt_value(json.dumps(coordonnees, ensure_ascii=False), fernet).encode(),
                "date_naissance_chiffree": (
                    encrypt_value(en_texte(r["date_naissance"]), fernet).encode()
                    if en_texte(r["date_naissance"])
                    else None
                ),
                "cle_chiffrement": "v1",
            }
        )
    _inserer(
        session, "core.identite_chiffree", tuple(identites[0]), identites, "ON CONFLICT (pseudonyme) DO NOTHING"
    )

    par_pseudo = _carte(session, "SELECT pseudonyme, id FROM core.assure")
    return {
        en_texte(r["assure_id"]): par_pseudo[pseudonymize("assr", en_texte(r["assure_id"]))]
        for r in d["assures"].to_dict("records")
    }


# ---------------------------------------------------------------------------
# 3. Contrats, beneficiaires, garanties, grille tarifaire
# ---------------------------------------------------------------------------
def charger_contrats(session: Session, d: dict[str, pd.DataFrame], cartes: dict[str, dict]) -> dict[str, int]:
    assures = cartes["assures"]
    # Assure principal de chaque contrat (celui marque ASSURE_PRINCIPAL).
    principal: dict[str, str] = {
        en_texte(r["contrat_id"]): en_texte(r["assure_id"])
        for r in d["assures"].to_dict("records")
        if en_texte(r["rang_beneficiaire"]) == "ASSURE_PRINCIPAL"
    }

    contrats = [
        {
            "numero": en_texte(r["contrat_id"]),
            "assure_id": assures.get(principal.get(en_texte(r["contrat_id"]), "")),
            "niveau": en_texte(r["formule"]) or "bronze",
            "date_debut": en_date(r["date_effet"]),
            "date_fin": en_date(r["date_fin"]),
            "numero_police": en_texte(r["numero_police"]),
            "souscripteur": en_texte(r["souscripteur_nom"]),
            "secteur": en_texte(r["secteur"]),
            "prime_annuelle_totale": en_decimal(r["prime_annuelle_totale"]),
            "souscripteur_id": en_texte(r["souscripteur_id"]),
            "date_effet_police": en_date(r["date_effet_police"]),
            "statut": en_texte(r["statut"]),
            "nb_beneficiaires": en_entier(r["nb_beneficiaires"]),
        }
        for r in d["contrats"].to_dict("records")
    ]
    _inserer(session, "core.contrat", tuple(contrats[0]), contrats, "ON CONFLICT (numero) DO NOTHING")
    id_contrats = _carte(session, "SELECT numero, id FROM core.contrat")

    beneficiaires = [
        {
            "contrat_id": id_contrats.get(en_texte(r["contrat_id"])),
            "assure_id": assures.get(en_texte(r["assure_id"])),
            "rang_beneficiaire": en_texte(r["rang_beneficiaire"]),
            "date_adhesion": en_date(r["date_adhesion"]),
            "date_radiation": en_date(r["date_radiation"]),
            "assure_principal_id": assures.get(principal.get(en_texte(r["contrat_id"]), "")),
        }
        for r in d["assures"].to_dict("records")
    ]
    _inserer(
        session,
        "core.contrat_beneficiaire",
        tuple(beneficiaires[0]),
        beneficiaires,
        "ON CONFLICT (contrat_id, assure_id) DO NOTHING",
    )

    garanties = [
        {
            "formule": en_texte(r["formule"]),
            "categorie": en_texte(r["categorie"]),
            "taux_remboursement": en_decimal(r["taux_remboursement"]),
            "plafond_annuel_categorie": en_decimal(r["plafond_annuel_categorie"]),
            "franchise_par_facture": en_decimal(r["franchise_par_facture"]),
            "delai_carence_jours": en_entier(r["delai_carence_jours"]),
            "plafond_annuel_global": en_decimal(r["plafond_annuel_global"]),
            "prime_annuelle_par_beneficiaire": en_decimal(r["prime_annuelle_par_beneficiaire"]),
            "attestation_requise": en_booleen(r["attestation_requise"]),
            "actes_exclus": en_texte(r["actes_exclus"]),
            "pieces_justificatives": en_texte(r["pieces_justificatives"]),
        }
        for r in d["garanties"].to_dict("records")
    ]
    _upsert(session, "core.garantie_formule", tuple(garanties[0]), garanties, "formule, categorie")

    # `core.garantie` (exigee par le CDC) : on la materialise par contrat en
    # recopiant les regles de la formule. Sans cle metier, on ne charge que si
    # la table est vide (idempotence).
    if _compter(session, "core.garantie") == 0:
        regles_par_formule: dict[str, list[dict]] = {}
        for g in garanties:
            regles_par_formule.setdefault(g["formule"], []).append(g)
        lignes_garantie = []
        for c in contrats:
            for g in regles_par_formule.get(c["niveau"], []):
                lignes_garantie.append(
                    {
                        "contrat_id": id_contrats.get(c["numero"]),
                        "nom": g["categorie"],
                        "taux_remboursement": g["taux_remboursement"],
                        "plafond_annuel": g["plafond_annuel_categorie"],
                    }
                )
        _inserer(session, "core.garantie", ("contrat_id", "nom", "taux_remboursement", "plafond_annuel"), lignes_garantie, "ON CONFLICT DO NOTHING")

    # Grille tarifaire : un code est SOIT un acte SOIT un medicament.
    grille = []
    ignorees = 0
    for r in d["grille"].to_dict("records"):
        code = en_texte(r["code"])
        acte_id = cartes["actes"].get(code)
        medicament_id = cartes["medicaments"].get(code)
        if acte_id is None and medicament_id is None:  # contrainte CHECK : exactement un
            ignorees += 1
            continue
        grille.append(
            {
                "prestataire_id": cartes["prestataires"].get(en_texte(r["prestataire_id"])),
                "acte_id": acte_id,
                "medicament_id": medicament_id,
                "tarif_pratique": en_decimal(r["tarif_pratique"]),
            }
        )
    if ignorees:
        logger.warning("grille.tarifaire.codes.inconnus", nombre=ignorees)
    _inserer(
        session,
        "core.grille_tarifaire",
        ("prestataire_id", "acte_id", "medicament_id", "tarif_pratique"),
        grille,
        "ON CONFLICT DO NOTHING",
    )
    return id_contrats


# ---------------------------------------------------------------------------
# 4. Ordonnances
# ---------------------------------------------------------------------------
def charger_ordonnances(session: Session, d: dict[str, pd.DataFrame], cartes: dict[str, dict]) -> None:
    ordonnances = [
        {
            "reference": en_texte(r["ordonnance_id"]),
            "assure_id": cartes["assures"].get(en_texte(r["assure_id"])),
            "prestataire_id": cartes["prestataires"].get(en_texte(r["prescripteur_id"])),
            "date_ordonnance": en_date(r["date_prescription"]),
            "type_ordonnance": en_texte(r["type_ordonnance"]),
            "validite_jours": en_entier(r["validite_jours"]),
            "diagnostic": en_texte(r["diagnostic"]),
            "renseignement_clinique": en_texte(r["renseignement_clinique"]),
        }
        for r in d["ordonnances"].to_dict("records")
    ]
    _inserer(session, "core.ordonnance", tuple(ordonnances[0]), ordonnances, "ON CONFLICT (reference) DO NOTHING")
    id_ordos = _carte(session, "SELECT reference, id FROM core.ordonnance")

    lignes = []
    ignorees = 0
    for r in d["ordonnance_lignes"].to_dict("records"):
        code = en_texte(r["code"])
        acte_id = cartes["actes"].get(code)
        medicament_id = cartes["medicaments"].get(code)
        if acte_id is None and medicament_id is None:
            ignorees += 1
            continue
        lignes.append(
            {
                "ordonnance_id": id_ordos.get(en_texte(r["ordonnance_id"])),
                "num_ligne": en_entier(r["num_ligne"]),
                "acte_id": acte_id,
                "medicament_id": medicament_id,
                "libelle": en_texte(r["libelle"]),
                "quantite": en_entier(r["quantite"]) or 1,
                "posologie": en_texte(r["posologie"]),
            }
        )
    if ignorees:
        logger.warning("ordonnance.lignes.codes.inconnus", nombre=ignorees)
    _inserer(
        session,
        "core.ordonnance_ligne",
        ("ordonnance_id", "num_ligne", "acte_id", "medicament_id", "libelle", "quantite", "posologie"),
        lignes,
        "ON CONFLICT (ordonnance_id, num_ligne) DO NOTHING",
    )


# ---------------------------------------------------------------------------
# 5. Factures et lignes de facture
# ---------------------------------------------------------------------------
def charger_factures(
    session: Session, d: dict[str, pd.DataFrame], cartes: dict[str, dict]
) -> tuple[set[str], pd.DataFrame]:
    """Valide (Phase 1.4) puis charge. Rend les factures valides + les rejets."""
    valides, rejets = valider_factures(
        d["factures"], d["lignes_facture"], d["actes"], d["medicaments"], d["assures"], d["prestataires"], d["contrats"]
    )
    if len(rejets):
        logger.warning("factures.rejetees", nombre=len(rejets))

    # Ordonnance -> id (certaines factures n'ont pas d'ordonnance : NULL).
    id_ordos = _carte(session, "SELECT reference, id FROM core.ordonnance")
    contrats = _carte(session, "SELECT numero, id FROM core.contrat")

    factures = [
        {
            "reference": en_texte(r["facture_id"]),
            "assure_id": cartes["assures"].get(en_texte(r["assure_id"])),
            "prestataire_id": cartes["prestataires"].get(en_texte(r["prestataire_id"])),
            "date_facture": en_date(r["date_facture"]),
            "montant_total": en_decimal(r["montant_total"]) or 0,
            "statut": en_texte(r["statut"]) or "recue",
            "numero_facture": en_texte(r["numero_facture"]),
            "contrat_id": contrats.get(en_texte(r["contrat_id"])),
            "ordonnance_id": id_ordos.get(en_texte(r["ordonnance_id"])) if en_texte(r["ordonnance_id"]) else None,
            "type_facture": en_texte(r["type_facture"]),
            "date_soin": en_date(r["date_soin"]),
            "heure_soin": en_texte(r["heure_soin"]),
            "date_reception": en_date(r["date_reception"]),
            "canal_reception": en_texte(r["canal_reception"]),
            "mode_reglement": en_texte(r["mode_reglement"]),
            "attestation_pec_id": en_texte(r["attestation_pec_id"]),
            "entente_prealable_id": en_texte(r["entente_prealable_id"]),
            "devise": en_texte(r["devise"]),
            "nb_lignes": en_entier(r["nb_lignes"]),
            "montant_eligible": en_decimal(r["montant_eligible"]),
            "montant_pris_en_charge": en_decimal(r["montant_pris_en_charge"]),
            "reste_a_charge": en_decimal(r["reste_a_charge"]),
            "motif_rejet": en_texte(r["motif_rejet"]),
            "date_traitement": en_date(r["date_traitement"]),
        }
        for r in valides.to_dict("records")
    ]
    _inserer(session, "core.facture", tuple(factures[0]), factures, "ON CONFLICT (reference) DO NOTHING")
    id_factures = _carte(session, "SELECT reference, id FROM core.facture")

    # Chaque ligne porte la date de soin de sa facture (pas de date propre).
    date_soin = {en_texte(r["facture_id"]): en_date(r["date_soin"]) for r in valides.to_dict("records")}

    if _compter(session, "core.ligne_facture") == 0:
        lignes = []
        ignorees = 0
        for r in d["lignes_facture"].to_dict("records"):
            fid = en_texte(r["facture_id"])
            if fid not in id_factures:  # facture rejetee ou inconnue
                continue
            code = en_texte(r["code"])
            acte_id = cartes["actes"].get(code)
            medicament_id = cartes["medicaments"].get(code)
            if acte_id is None and medicament_id is None:
                ignorees += 1
                continue
            lignes.append(
                {
                    "facture_id": id_factures[fid],
                    "acte_id": acte_id,
                    "medicament_id": medicament_id,
                    "quantite": en_entier(r["quantite"]) or 1,
                    "montant_unitaire": en_decimal(r["prix_unitaire"]) or 0,
                    "date_acte": date_soin.get(fid),
                    "num_ligne": en_entier(r["num_ligne"]),
                    "libelle": en_texte(r["libelle"]),
                }
            )
        if ignorees:
            logger.warning("lignes.facture.codes.inconnus", nombre=ignorees)
        _inserer(
            session,
            "core.ligne_facture",
            ("facture_id", "acte_id", "medicament_id", "quantite", "montant_unitaire", "date_acte", "num_ligne", "libelle"),
            lignes,
            "ON CONFLICT DO NOTHING",
        )

    return set(valides["facture_id"]), rejets


# ---------------------------------------------------------------------------
# 6. Labels
# ---------------------------------------------------------------------------
def charger_labels(session: Session, d: dict[str, pd.DataFrame], factures_valides: set[str]) -> None:
    id_factures = _carte(session, "SELECT reference, id FROM core.facture")
    labels = [
        {
            "facture_id": id_factures.get(en_texte(r["facture_id"])),
            "label": en_entier(r["est_fraude"]) or 0,
            "type_fraude": en_texte(r["type_fraude"]),
            "detail_fraude": en_texte(r["detail_fraude"]),
        }
        for r in d["labels_fraude"].to_dict("records")
        if en_texte(r["facture_id"]) in factures_valides
    ]
    _inserer(session, "ml.label_fraude", tuple(labels[0]), labels, "ON CONFLICT (facture_id) DO NOTHING")

    id_prestas = _carte(session, "SELECT code, id FROM core.prestataire")
    labels_p = [
        {
            "prestataire_id": id_prestas.get(en_texte(r["prestataire_id"])),
            "est_suspect": en_entier(r["est_suspect"]) or 0,
        }
        for r in d["labels_prestataires"].to_dict("records")
    ]
    _inserer(
        session, "ml.label_prestataire", tuple(labels_p[0]), labels_p, "ON CONFLICT (prestataire_id) DO NOTHING"
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def charger_tout(session: Session, d: dict[str, pd.DataFrame]) -> dict[str, int]:
    cartes = charger_referentiels(session, d)
    cartes["assures"] = charger_assures(session, d)
    charger_contrats(session, d, cartes)
    charger_ordonnances(session, d, cartes)
    factures_valides, rejets = charger_factures(session, d, cartes)
    charger_labels(session, d, factures_valides)
    return {
        "factures_valides": len(factures_valides),
        "factures_rejetees": len(rejets),
    }


def main() -> int:
    if not DATA_RAW_DIR.exists():
        logger.warning(
            "donnees.absentes",
            chemin=str(DATA_RAW_DIR),
            message="Aucun jeu de donnees. Deposez les CSV dans ./data/raw puis `make reload-data`.",
        )
        return 0

    donnees = lire_tous(DATA_RAW_DIR)
    logger.info("donnees.detectees", domaines=len(donnees))

    # Rapport de qualite (Phase 1.4), ecrit hors du volume en lecture seule.
    rapport(DATA_RAW_DIR, sortie=RAPPORT_DIR / "rapport_qualite_phase1_4.md")

    with session_scope() as session:
        resultat = charger_tout(session, donnees)

    logger.info("chargement.termine", **resultat)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
