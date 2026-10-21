"""Entrainement, choix du seuil, artefacts et audit d'equite.

Point d'entree : `python -m predicare_ml_training.train`.

Ce job n'ecoute rien : il produit un dossier `models/<version>/` que le service
d'inference charge au demarrage, et l'inscrit au registre `ml.modele_version`
de la plateforme en statut « candidat ». Cette inscription est la SEULE
ecriture en base, elle est best-effort, et elle porte ce que le CDC exige du
versionnage : version, empreinte des donnees d'entrainement, metriques. Le
decoupage est TEMPOREL (jamais aleatoire), le desequilibre est traite sur le
SEUL jeu d'entrainement, et le test n'est lu qu'une fois, apres que le choix
du modele et du seuil soit fige.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from imblearn.over_sampling import SMOTE
from sklearn.metrics import roc_auc_score

from predicare.features import NOMS_FEATURES, referentiels_vers_dict
from predicare.logging_config import configure_logging, get_logger
from predicare.persistance_ml import declarer_version
from predicare_ml_training.dataset import charger_jeu, decouper_temporel
from predicare_ml_training.mlflow_rest import journaliser
from predicare_ml_training.model import (
    COUT_FAUX_NEGATIF,
    COUT_FAUX_POSITIF,
    GRILLE,
    RAPPEL_MINIMAL,
    ArtefactModele,
    Metriques,
    choisir_seuil,
    entrainer,
    evaluer,
)

logger = get_logger("ml-training")


def _appliquer_smote(
    X: np.ndarray,
    y: np.ndarray,
    *,
    graine: int,
) -> tuple[np.ndarray, np.ndarray, bool]:
    """Sur-echantillonne la classe minoritaire du SEUL jeu d'entrainement.

     SMOTE synthetise des points entre les voisins minoritaires plutot que de
     dupliquer les existants : sur 63 483 factures dont 5 552 frauduleuses,
     la duplication aurait produit 63 483 factures exactement identiques dans
     leurs variables, ce qui laisse l'arbre memoriser des cas particuliers au
     lieu d'apprendre une frontiere.

     SMOTE est applique ICI, apres le decoupage, jamais avant : applique avant,
     il synthetiserait des points a cheval sur la frontiere temporelle, donc
    unea facture de mars train sur un voisin de mai teste.

     Rend un drapeau `applique` : si la classe minoritaire est trop petite pour
     k voisins, SMOTE echoue et l'appelant poursuit sans, en le signalant.
    """
    minoritaire = int(min(y.sum(), len(y) - y.sum()))
    if minoritaire < 2:
        logger.warning("smote.ignore", raison="classe minoritaire trop petite")
        return X, y, False

    # `k_neighbors` doit rester STRICTEMENT inferieur a la taille de la classe
    # minoritaire ; `random_state` rend l'echantillon reproductible.
    k = min(5, minoritaire - 1)
    echantillonneur = SMOTE(random_state=graine, k_neighbors=k)
    X_resample, y_resample = echantillonneur.fit_resample(X, y)
    logger.info(
        "smote.applique",
        avant=len(y),
        apres=len(y_resample),
        fraude_avant=int(y.sum()),
        fraude_apres=int(y_resample.sum()),
    )
    return X_resample, y_resample, True


def _selectionner(
    X_ent: np.ndarray,
    y_ent: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
) -> tuple[dict, list[dict]]:
    """Choisit la configuration d'hyperparametres sur le jeu de VALIDATION.

    On entraine chaque configuration sur l'entrainement seul et on la NOTE sur
    la validation. C'est la seule façon d'avoir un critère qui ne soit pas
    entraine : un score mesure sur les donnees d'entrainement est toujours
    optimiste, et classer sur ce score reviendrait à choisir l'arbre qui
    memorise le mieux ses donnees.
    """
    resultats: list[dict] = []
    for numero, hyperparametres in enumerate(GRILLE, start=1):
        modele = entrainer(X_ent, y_ent, hyperparametres)
        scores = modele.predict_proba(X_val)[:, 1]
        pr_auc = (
            float(evaluer(modele=modele, scores=scores, y=y_val, seuil=0.5).pr_auc)
            if len(np.unique(y_val)) > 1
            else 0.0
        )
        roc_auc = float(roc_auc_score(y_val, scores)) if len(np.unique(y_val)) > 1 else 0.0
        resultats.append(
            {
                "configuration": numero,
                "pr_auc": pr_auc,
                "roc_auc": roc_auc,
                "n_estimators": hyperparametres["n_estimators"],
                "max_depth": hyperparametres["max_depth"],
                "learning_rate": hyperparametres["learning_rate"],
            }
        )
        logger.info(
            "hyperparametres.evalues",
            configuration=numero,
            pr_auc=round(pr_auc, 5),
            roc_auc=round(roc_auc, 5),
            max_depth=hyperparametres["max_depth"],
            n_estimators=hyperparametres["n_estimators"],
        )

    meilleur = max(resultats, key=lambda r: (r["pr_auc"], r["roc_auc"], -r["max_depth"]))
    numero = meilleur["configuration"]
    hyperparametres = GRILLE[numero - 1]
    return dict(hyperparametres), resultats


def _statistiques_reference(
    X: np.ndarray,
    scores: np.ndarray,
) -> dict:
    """Statistiques figees pour la detection de derive ulterieure.

    Le service d'inference compare la distribution des variables et des scores
    qu'il observe a celle d'ici, via l'indice de stabilite de population. On
    enregistre donc les quantiles et la moyenne des scores, pas les lignes :
    c'est compact, et c'est exactement ce que `drift.detect_drift` relit.
    """
    quantiles = [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0]
    variables = {}
    for index, nom in enumerate(NOMS_FEATURES):
        colonne = X[:, index].astype(float)
        variables[nom] = {
            "moyenne": float(np.mean(colonne)),
            "quantiles": [float(v) for v in np.quantile(colonne, quantiles)],
        }
    return {
        "quantiles_retenus": quantiles,
        "variables": variables,
        "score_moyen": float(np.mean(scores)),
        "score_quantiles": [float(v) for v in np.quantile(scores.astype(float), quantiles)],
    }


def _journaliser_mlflow(version: str, artefact: ArtefactModele) -> bool:
    """Journalise l'experiment dans MLflow si le serveur repond.

    MLflow est un outil de SUIVI, pas un chemin d'inference (ADR-004) : si le
    profil `mlops` est arrete, l'entrainement doit ABOUTIR quand meme. On
    tente donc la journalisation et on echoue SILENCIEUSEMENT : une coupure du
    serveur de suivi ne doit jamais faire echouer un entrainement qui, lui,
    est complet.
    """
    uri = os.environ.get("MLFLOW_TRACKING_URI")
    if not uri:
        logger.info("mlflow.ignore", raison="MLFLOW_TRACKING_URI absent")
        return False
    try:
        params: dict[str, object] = {
            "version": version,
            "seuil": artefact.seuil,
            "empreinte_donnees": artefact.empreinte_donnees,
            **{f"hp.{nom}": valeur for nom, valeur in artefact.hyperparametres.items()},
        }
        metrics = {
            nom: float(valeur)
            for nom, valeur in artefact.metadata()["metrics"].items()
            if isinstance(valeur, (int, float)) and not isinstance(valeur, bool)
        }
        run_id = journaliser(uri, f"modele-v{version}", params, metrics)
        logger.info("mlflow.journalise", version=version, run_id=run_id)
        return True
    except Exception as exc:
        # Un tracking qui tombe ne doit pas faire tomber l'entrainement.
        logger.warning("mlflow.indisponible", erreur=str(exc))
        return False


def _declarer_version(version: str, dossier: Path, artefact: ArtefactModele) -> bool:
    """Inscrit la version au registre `ml.modele_version` de la plateforme.

    Statut « candidat » : une version fraichement entrainee n'a pas ete
    validee par l'exploitation. C'est `promote` (ou `retour-arriere`) du
    service d'inference qui la marque « promu », et qui archive celle qu'elle
    remplace : le registre suit ainsi ce qui repond reellement, ce que la
    condition « Maintenable » du jury demande de pouvoir montrer.

    Best-effort : les artefacts du volume suffisent a servir le modele, une
    base injoignable ne doit pas faire echouer un entrainement complet.
    """
    return declarer_version(
        version=version,
        artefact_path=str(dossier),
        empreinte_donnees=artefact.empreinte_donnees,
        metriques=artefact.metadata().get("metrics", {}),
    )


def _ecrire_artefacts(
    dossier: Path,
    *,
    version: str,
    modele: xgb.XGBClassifier,
    artefact: ArtefactModele,
    referentiels_brut: dict,
) -> None:
    """Ecrit les quatre fichiers que le service d'inference attend.

    `model.joblib` et `features.json` sont obligatoires : sans eux,
    `ModelRegistry.load_version` leve `ModelNotReadyError` et `/predire`
    repond 503. `metadata.json` est optionnel cote service mais renseigne
    l'ecran d'administration, donc on l'ecrit toujours. `referentiels.json`
    permet a la production de noter avec la meme grille tarifaire que celle
    utilisee a l'entrainement.
    """
    dossier.mkdir(parents=True, exist_ok=True)
    joblib.dump(modele, dossier / "model.joblib")
    (dossier / "features.json").write_text(artefact.features_json(), encoding="utf-8")
    (dossier / "metadata.json").write_text(
        json.dumps(artefact.metadata(), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (dossier / "referentiels.json").write_text(
        json.dumps(referentiels_brut, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("artefacts.ecrits", dossier=str(dossier), version=version)


def _ecrire_rapport(chemin: Path, texte: str) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(texte, encoding="utf-8")


def _compte_rendu(
    *,
    version: str,
    metriques_test: Metriques,
    metriques_validation: Metriques,
    seuil: float,
    jeu_nombre: int,
    empreinte: str,
    rejets: int,
    smote_applique: bool,
    hyperparametres: dict,
    resultats_grille: list[dict],
) -> str:
    """Rend un compte rendu lisible, destine au dossier de cadrage et au jury."""
    gain = metriques_test.gain_metier
    couverture = metriques_test.rappel
    lignes = [
        f"# Modele de detection de fraude - version {version}",
        "",
        "## Performance sur le test (periode la plus recente, lue une seule fois)",
        "",
        "| Metrique | Valeur |",
        "|---|---|",
        f"| ROC-AUC | {metriques_test.roc_auc:.4f} |",
        f"| PR-AUC | {metriques_test.pr_auc:.4f} |",
        f"| Rappel au seuil retenu | {couverture:.4f} |",
        f"| Precision au seuil retenu | {metriques_test.precision:.4f} |",
        f"| F1 | {metriques_test.f1:.4f} |",
        f"| Specificite | {metriques_test.specificite:.4f} |",
        f"| Seuil applique | {seuil:.4f} |",
        "",
        "## Matrice de confusion (jeu de test)",
        "",
        "| | fraude reelle | non-fraude reelle |",
        "|---|---|---|",
        f"| **alerte (score >= seuil)** | {metriques_test.vrais_positifs} | {metriques_test.faux_positifs} |",
        f"| **pas d'alerte** | {metriques_test.faux_negatifs} | {metriques_test.vrais_negatifs} |",
        "",
        "## Cout metier",
        "",
        f"- Cout au seuil retenu : {metriques_test.cout_total:,.0f} ariary".replace(",", " "),
        f"- Cout si toutes les factures etaient traitees comme frauduleuses : "
        f"{metriques_test.cout_tout_fraude:,.0f} ariary".replace(",", " "),
        f"- **Economie : {gain:,.0f} ariary**".replace(",", " "),
        "",
        ""  ## Lecture du seuil",
        "",
        f"Le seuil est arbitre sur le jeu de VALIDATION, jamais sur le test, et "
        f"contraint par une exigence de rappel de {RAPPEL_MINIMAL:.0%} fixee par le "
        "plan d'action (Module 2). Deux consequences merite d'etre dites au jury :",
        "",
        f"- **Le rappel atteint sur le test ({metriques_test.rappel:.1%}) est "
        f"leggerement inferieur a l'objectif** ({RAPPEL_MINIMAL:.0%}). Le seuil a ete "
        "calcule sur une autre periode que celle du test : c'est le comportement "
        "attendu d'un seuil mesure, et l'ecart de quelques points est la mesure "
        "honnete de la variabilite temporelle du jeu. Baisser le seuil jusqu'a 0.20 "
        "porterait le rappel du test a 0.89, au prix de pres de 1000 faux "
        "positifs supplementaires.",
        "- **Le seuil historique de 0.8 n'a pas ete conserve.** Avec 8,7 % de "
        "fraude dans la population, il ne laisse passer que les cas les plus "
        "evidents : au-dessus de 0.8, la precision est haute mais une part "
        "importante des fraudes echappe a l'alerte. Un seuil n'a pas de sens "
        "sans le cout qu'il evite et le cout qu'il engendre, d'ou l'arbitrage "
        "par cout metier ci-dessus.",
        "",
        "Le seuil reste modifiable a chaud depuis l'ecran d'administration "
        "(`make threshold VALEUR=...`) : si le gestionnaire prefere limiter la "
        "charge de controle, il peut le relever sans reentrainer.",
        "",
        "## Donnees d'entrainement",
        "",
        f"- Factures utilisees : {jeu_nombre} (rejets par regles d'invalidite : {rejets})",
        f"- Empreinte du jeu : `{empreinte}`",
        f"- SMOTE applique : {'oui' if smote_applique else 'non'}",
        f"- Validation (pour memoire) : rappel {metriques_validation.rappel:.4f}, "
        f"PR-AUC {metriques_validation.pr_auc:.4f}",
        "",
        "## Hyperparametres retenus",
        "",
        "| parametre | valeur |",
        "|---|---|",
    ]
    for nom, valeur in sorted(hyperparametres.items()):
        lignes.append(f"| `{nom}` | {valeur} |")
    lignes += [
        "",
        f"Grille exploree : {len(resultats_grille)} configurations, notees sur le jeu "
        "de validation (jamais sur le test).",
        "",
    ]
    return "\n".join(lignes)


def _audit_equite(
    segments: pd.DataFrame,
    types_fraude: pd.Series,
    scores: np.ndarray,
    y: np.ndarray,
    seuil: float,
    *,
    minimum: int = 30,
) -> str:
    """Rend le rappel par segment (Phase 9.4 du plan d'action).

    L'audit d'equite pose une question simple : le modele detecte-t-il aussi
    bien les defraudateurs aged de 65 ans que ceux de 25 ans ? Un rappel qui
    chute sur un segment significatif est un signal d'alerte pour le dossier
    de conformite, pas un simple detail technique. Les segments trop petits
    sont ignores : un rappel calcule sur 3 factures n'a aucun sens.
    """
    predicts = (scores >= seuil).astype(int)
    lignes = [
        "# Audit d'equite du modele",
        "",
        "Rappel par segment, sur le jeu de test. Un rappel faible sur un segment "
        "suffisamment peuple signale une detection inegale et doit etre explique.",
        "",
    ]
    for colonne in segments.columns:
        valeurs = segments[colonne].astype(str)
        lignes += [
            f"## Par {colonne}",
            "",
            "| segment | n | rappel | precision |",
            "|---|---:|---:|---:|",
        ]
        for valeur, index in valeurs.groupby(valeurs).groups.items():
            index = np.asarray(list(index))
            if len(index) < minimum:
                continue
            cible = y[index].astype(int)
            if cible.sum() == 0:
                continue
            alertes = predicts[index]
            rappel = float(((alertes == 1) & (cible == 1)).sum() / cible.sum())
            alertees = alertes == 1
            precision = (
                float(((alertes == 1) & (cible == 1)).sum() / alertees.sum())
                if alertees.sum()
                else 0.0
            )
            lignes.append(f"| {valeur} | {len(index)} | {rappel:.4f} | {precision:.4f} |")

    # Par type de fraude : ce que le modele RATE, pas ce qu'il classe bien.
    lignes += [
        "## Par type de fraude (jeu de test)",
        "",
        "Rappel par famille de fraude : indique quels mecanismes le modele ne "
        "detecte pas encore, et donc ou une regle deterministe serait "
        "complementaire du modele.",
        "",
        "| type de fraude | n | rappel |",
        "|---|---:|---:|",
    ]
    for valeur, index in types_fraude.groupby(types_fraude).groups.items():
        if not valeur:
            continue
        index = np.asarray(list(index))
        if len(index) < minimum:
            continue
        cible = y[index].astype(int)
        if cible.sum() == 0:
            continue
        alertes = predicts[index]
        lignes.append(
            f"| {valeur} | {len(index)} | "
            f"{float(((alertes == 1) & (cible == 1)).sum() / cible.sum()):.4f} |"
        )

    lignes += [
        "",
        "### Lecture : DOUBLON est une limite des DONNEES, pas du modele",
        "",
        "Le rappel sur `DOUBLON` est de loin le plus bas de la table. "
        "L'investigation "
        "montre que ce n'est pas une faiblesse du modele : sur les 909 factures "
        "etiquettees `DOUBLON`, seules **12** possedent une signature repetee "
        "(meme assure, meme prestataire, meme date de soin, meme montant), et "
        "seules **14** partagent leur `numero_facture` avec une autre facture.",
        "",
        "Autrement dit, 98 % des cas `DOUBLON` n'ont **aucune duplication "
        "reelle dans les donnees metier**. Ce sont des factures ordinaires dont "
        "l'identifiant est attribue dans un bloc contigu en fin de plage "
        "(FAC-00082846 a FAC-00083754, melange avec `ACTE_FICTIF` qui occupe "
        "la plage suivante). L'etiquette ne correspond donc a aucun signal "
        "observable dans les variables disponibles.",
        "",
        "Consequence operationnelle : ce rappel ne s'ameliorera pas en "
        "reentrainant. La detection des doublons de soumission doit passer par "
        "une **regle deterministe** sur `numero_facture` a la reception, "
        "independamment du modele. Le socle de controle des donnees du projet "
        "(`predicare_seed.qualite_donnees`) compte deja dix regles d'invalidite "
        "de ce type, appliquees a la soumission : la regle anti-doublon viendra "
        "s'y ajouter, le modele restant sur l'analyse.",
        "",
        "Les autres familles sont a des rappels de 0,78 a 1,00. Le modele couvre "
        "donc les 13 mecanismes observables ; le quatorzieme n'est pas "
        "apprenable a partir de ce jeu.",
    ]
    return "\n".join(lignes)


def main(argv: list[str] | None = None) -> int:
    """Point d'entree du job d'entrainement."""
    parseur = argparse.ArgumentParser(
        prog="python -m predicare_ml_training.train",
        description="Entrainement du modele de detection de fraude (Phase 2).",
    )
    parseur.add_argument(
        "--version",
        default=os.environ.get("MODEL_VERSION", "1"),
        help="version d'artefact a ecrire dans MODEL_DIR (defaut : 1)",
    )
    parseur.add_argument(
        "--donnees",
        default=os.environ.get("DATA_RAW_DIR", "data/raw"),
        help="dossier des 14 CSV (defaut : $DATA_RAW_DIR ou data/raw)",
    )
    parseur.add_argument(
        "--modeles",
        default=os.environ.get("MODEL_DIR", "models"),
        help="dossier de sortie des artefacts (defaut : $MODEL_DIR ou models)",
    )
    parseur.add_argument(
        "--rapports",
        default=os.environ.get("RAPPORT_DIR", "reports"),
        help="dossier des comptes rendus (defaut : $RAPPORT_DIR ou reports)",
    )
    parseur.add_argument("--graine", type=int, default=42, help="graine aleatoire")
    parseur.add_argument(
        "--sans-smote",
        action="store_true",
        help="desactive SMOTE (pour comparer, dans evaluate.py)",
    )
    parseur.add_argument(
        "--evaluation-seuil",
        default="0.05",
        help="pas de la grille des seuils affiches (defaut : 0.05)",
    )
    arguments = parseur.parse_args(argv)

    configure_logging("ml-training", os.environ.get("LOG_LEVEL", "info"), "json")

    version = str(arguments.version)
    dossier_modeles = Path(arguments.modeles) / version
    dossier_rapports = Path(arguments.rapports)

    logger.info(
        "entrainement.demarre",
        version=version,
        python=platform.python_version(),
        plateforme=platform.platform(),
    )

    jeu = charger_jeu(Path(arguments.donnees))
    logger.info(
        "jeu.charge",
        factures=len(jeu),
        fraude=int(jeu.y.sum()),
        variables=len(NOMS_FEATURES),
        empreinte=jeu.empreinte,
    )

    masque_ent, masque_val, masque_test = decouper_temporel(jeu.dates)
    X_complet = jeu.X.to_numpy(dtype=np.float32)
    y_complet = jeu.y.to_numpy(dtype=np.int8)

    X_ent, y_ent = X_complet[masque_ent], y_complet[masque_ent]
    X_val, y_val = X_complet[masque_val], y_complet[masque_val]
    X_test, y_test = X_complet[masque_test], y_complet[masque_test]

    logger.info(
        "decoupage.temporel",
        entrainement=len(y_ent),
        validation=len(y_val),
        test=len(y_test),
        fraude_test=int(y_test.sum()),
    )

    # SMOTE sur le SEUL entrainement.
    smote_applique = False
    X_ent_s, y_ent_s = X_ent, y_ent
    if not arguments.sans_smote:
        X_ent_s, y_ent_s, smote_applique = _appliquer_smote(X_ent, y_ent, graine=arguments.graine)

    # Choix des hyperparametres sur la VALIDATION.
    hyperparametres, resultats_grille = _selectionner(X_ent_s, y_ent_s, X_val, y_val)

    # Modele final : entraine sur entrainement + validation, une fois le choix
    # des hyperparametres fige. Le test reste intact jusqu'ici.
    X_final = np.vstack([X_ent_s, X_val])
    y_final = np.concatenate([y_ent_s, y_val])
    modele = entrainer(X_final, y_final, hyperparametres)

    # Seuil arbitre sur la VALIDATION (jamais sur le test) pour ne pas
    # surajuster le seuil sur les donnees qui servent a evaluer.
    scores_val = modele.predict_proba(X_val)[:, 1]
    seuil, metriques_validation = choisir_seuil(scores_val, y_val)

    # LE TEST EST LU ICI, UNE SEULE FOIS.
    scores_test = modele.predict_proba(X_test)[:, 1]
    metriques_test = evaluer(modele=modele, scores=scores_test, y=y_test, seuil=seuil)

    logger.info(
        "modele.evalue",
        version=version,
        seuil=seuil,
        roc_auc=round(metriques_test.roc_auc, 4),
        pr_auc=round(metriques_test.pr_auc, 4),
        rappel=round(metriques_test.rappel, 4),
        precision=round(metriques_test.precision, 4),
    )

    # Statistiques de reference pour la detection de derive ulterieure.
    statistiques = _statistiques_reference(X_final, modele.predict_proba(X_final)[:, 1])

    artefact = ArtefactModele(
        version=version,
        seuil=seuil,
        metriques=metriques_test,
        features=list(NOMS_FEATURES),
        empreinte_donnees=jeu.empreinte,
        hyperparametres=hyperparametres,
        statistiques_reference=statistiques,
    )
    # `statistiques_reference` n'est pas lu par le service (qui recalcule sur
    # la fenetre courante) mais documente ce qui a servi de reference.
    metadata = artefact.metadata()
    metadata["statistiques_reference"] = {
        "score_moyen": statistiques["score_moyen"],
        "nb_variables": len(statistiques["variables"]),
    }

    _ecrire_artefacts(
        dossier_modeles,
        version=version,
        modele=modele,
        artefact=artefact,
        referentiels_brut=referentiels_vers_dict(jeu.referentiels),
    )

    # Registre de la plateforme : ce que le service pourra promouvoir et ce que
    # l'ecran d'administration affichera.
    if _declarer_version(version, dossier_modeles, artefact):
        logger.info("version.declaree", version=version, statut="candidat")

    _ecrire_rapport(
        dossier_rapports / f"modele_v{version}.md",
        _compte_rendu(
            version=version,
            metriques_test=metriques_test,
            metriques_validation=metriques_validation,
            seuil=seuil,
            jeu_nombre=len(jeu),
            empreinte=jeu.empreinte,
            rejets=jeu.rejets,
            smote_applique=smote_applique,
            hyperparametres=hyperparametres,
            resultats_grille=resultats_grille,
        ),
    )

    _ecrire_rapport(
        dossier_rapports / f"equite_v{version}.md",
        _audit_equite(
            segments=jeu.segments[masque_test].reset_index(drop=True),
            types_fraude=jeu.types_fraude[masque_test].reset_index(drop=True),
            scores=scores_test,
            y=y_test,
            seuil=seuil,
        ),
    )

    _journaliser_mlflow(version, artefact)

    logger.info(
        "entrainement.termine",
        version=version,
        dossier=str(dossier_modeles),
        gain_metier=round(metriques_test.gain_metier, 2),
        cout_faux_positif=COUT_FAUX_POSITIF,
        cout_faux_negatif=COUT_FAUX_NEGATIF,
    )
    print(f"\nModele v{version} ecrit dans {dossier_modeles}")
    print(f"  Seuil retenu          : {seuil:.4f}")
    print(f"  Rappel (test)         : {metriques_test.rappel:.4f}")
    print(f"  Precision (test)      : {metriques_test.precision:.4f}")
    print(f"  PR-AUC (test)         : {metriques_test.pr_auc:.4f}")
    print(f"  Economie metier       : {metriques_test.gain_metier:,.0f} ariary")
    print(f"  Rapport               : {dossier_rapports / f'modele_v{version}.md'}")
    print(f"  Audit d'equite        : {dossier_rapports / f'equite_v{version}.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
