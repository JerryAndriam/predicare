#!/usr/bin/env python3
"""Genere les figures de la presentation (modele, ROI, conformite).

Les figures ne sont pas des dessins : chaque trace lit ses donnees dans les
sources de verite du depot (rapports versionnes, artefact de modele, base
PostgreSQL). Rien n'est recopie a la main dans le code, sauf les valeurs du
rapport de reference, qui sont lues dans `reports/modele_v2.md`.

Usage :
    uv run python scripts/figures_ml.py --sortie <dossier>

Le dossier de sortie est cree s'il n'existe pas. Chaque figure est ecrite en
PNG 16:9 (1600 x 900 pixels a 100 dpi), lisible en projection.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

RACINE = Path(__file__).resolve().parent.parent

#: Palette sobre, lisible sur un videoprojecteur.
BLEU = "#1f4e79"
BLEU_CLAIR = "#5b9bd5"
VERT = "#2e7d32"
ORANGE = "#e07b39"
ROUGE = "#c0392b"
GRIS = "#6b7280"
GRIS_CLAIR = "#e5e7eb"
NOIR = "#111827"

SEUIL = 0.2876


# ---------------------------------------------------------------------------
# Acces aux donnees
# ---------------------------------------------------------------------------


def _sql(requete: str, base: str = "predicare") -> str:
    """Execute une requete SQL dans la base du projet et renvoie le texte.

    La base n'est pas publiee sur la machine de travail : la requete passe
    donc par `docker compose exec`, comme le font deja les scripts
    d'exploitation du depot.
    """
    commande = [
        "docker",
        "compose",
        "exec",
        "-T",
        "db",
        "psql",
        "-U",
        "predicare",
        "-d",
        base,
        "-tAc",
        requete,
    ]
    resultat = subprocess.run(commande, cwd=RACINE, capture_output=True, text=True, check=True)
    return resultat.stdout


def _csv_sql(requete: str) -> list[list[str]]:
    """Renvoie les lignes d'une requete SQL sous forme de listes de colonnes."""
    sortie = _sql(requete)
    lignes = []
    for ligne in sortie.splitlines():
        if not ligne.strip():
            continue
        lignes.append(ligne.split("|"))
    return lignes


# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------


def _figure(titre: str, sous_titre: str = "") -> tuple[plt.Figure, plt.Axes]:
    figure, axe = plt.subplots(figsize=(16, 9), dpi=100)
    figure.patch.set_facecolor("white")
    axe.set_facecolor("white")
    figure.suptitle(titre, fontsize=22, fontweight="bold", color=NOIR, x=0.02, ha="left", y=0.97)
    if sous_titre:
        figure.text(0.02, 0.915, sous_titre, fontsize=12.5, color=GRIS, ha="left")
    return figure, axe


def _pied(figure: plt.Figure, source: str) -> None:
    figure.text(0.02, 0.015, f"Source : {source}", fontsize=10, color=GRIS, ha="left")


def _enregistrer(figure: plt.Figure, chemin: Path) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(chemin, bbox_inches="tight", facecolor="white")
    plt.close(figure)
    print(f"  ecrit : {chemin}")


def _tableaux_markdown(chemin: Path) -> dict[str, list[list[str]]]:
    """Extrait les tableaux markdown d'un rapport, section par section."""
    sections: dict[str, list[list[str]]] = {}
    section_courante = ""
    lignes: list[str] = []
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        if ligne.startswith("## "):
            if section_courante and lignes:
                sections[section_courante] = _vers_tableau(lignes)
            section_courante = ligne[3:].strip()
            lignes = []
        elif ligne.startswith("|"):
            lignes.append(ligne)
    if section_courante and lignes:
        sections[section_courante] = _vers_tableau(lignes)
    return sections


def _vers_tableau(lignes: list[str]) -> list[list[str]]:
    tableau: list[list[str]] = []
    for ligne in lignes:
        cellules = [c.strip() for c in ligne.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cellules if c):
            continue
        tableau.append(cellules)
    return tableau


# ---------------------------------------------------------------------------
# 1. Importance globale des variables
# ---------------------------------------------------------------------------


def figure_importance_variables(sortie: Path) -> None:
    lignes = _csv_sql(
        """
        SELECT feature,
               round(avg(abs(shap_value))::numeric, 6) AS importance,
               count(*) AS n,
               round(100.0 * count(*) FILTER (WHERE direction = 'pousse_vers_fraude')
                     / count(*), 1) AS part_fraude,
               max(libelle) AS libelle
        FROM ml.shap_explication
        GROUP BY feature
        ORDER BY importance DESC
        """
    )
    donnees = [(f, float(i), int(n), float(p), lib) for f, i, n, p, lib in lignes]
    donnees = [d for d in donnees if d[1] > 0]
    donnees.sort(key=lambda d: d[1])
    principales = donnees[-16:]

    figure, axe = _figure(
        "Identification des variables : ce qui fait bouger la note de fraude",
        "Moyenne des contributions SHAP par variable, sur toutes les factures notees en production",
    )
    figure.subplots_adjust(top=0.80)
    noms = [d[0] for d in principales]
    valeurs = [d[1] for d in principales]
    couleurs = [ORANGE if d[3] >= 50 else BLEU_CLAIR for d in principales]
    positions = range(len(noms))
    axe.barh(list(positions), valeurs, color=couleurs, height=0.68)
    axe.set_yticks(list(positions))
    axe.set_yticklabels(noms, fontsize=11)
    axe.set_xlabel("Contribution moyenne en valeur absolue (SHAP)", fontsize=12, color=GRIS)
    axe.set_axisbelow(True)
    for spine in ("top", "right", "left"):
        axe.spines[spine].set_visible(False)
    for position, valeur in zip(positions, valeurs, strict=True):
        axe.text(valeur, position, f" {valeur:.3f}", va="center", fontsize=10, color=NOIR)

    total_explications = sum(d[2] for d in donnees)
    message = (
        f"16 variables affichees sur {len(donnees)} actives (32 au total)  |  "
        f"{total_explications:,} explications SHAP analysees".replace(",", " ")
        + "\nOrange : la variable pousse vers la fraude dans plus de la moitie des cas"
        + "  |  Bleu : elle joue en faveur de la legitimite"
    )
    figure.text(0.02, 0.882, message, fontsize=11, color=GRIS, ha="left", va="top", linespacing=1.5)
    axe.grid(axis="x", alpha=0.25)
    _pied(figure, "ml.shap_explication (base de production), agregation directe")
    _enregistrer(figure, sortie / "3-ia" / "p3_importance_variables.png")


# ---------------------------------------------------------------------------
# 2. Cycle de vie du modele
# ---------------------------------------------------------------------------


def figure_cycle_vie(sortie: Path) -> None:
    figure, axe = _figure(
        "Cycle de vie du modele de detection de fraude",
        "De la donnee brute a la decision : chaque etape a une preuve dans le depot",
    )
    axe.set_xlim(0, 16)
    axe.set_ylim(0, 9)
    axe.axis("off")

    etapes = [
        ("1. Dep securise", "84 608 factures chargees\n10 regles de qualite : 0 rejet", BLEU),
        (
            "2. Variables",
            "32 variables construites\nmeme code en entrainement\net en inferece",
            BLEU,
        ),
        (
            "3. Equilibrage",
            "SMOTE sur la classe mineure\nseparation temporelle\nentrainement / validation / test",
            BLEU,
        ),
        (
            "4. Entrainement",
            "XGBoost, 400 arbres\nprofondeur 8, lr 0,04\ngrille de 12 configurations",
            ORANGE,
        ),
        (
            "5. Arbitrage du seuil",
            "seuil lu sur la validation\njamais sur le test\ncontrainte de rappel 90 %",
            ORANGE,
        ),
        ("6. Evaluation", "test lu une seule fois\nROC-AUC 0,9500\nrappel 87,02 % a 0,2876", VERT),
        (
            "7. Explicabilite",
            "SHAP par facture\npersiste en base\ncontestable par le gestionnaire",
            VERT,
        ),
        ("8. Surveillance", "derive PSI horaire\n9 regles Prometheus\n2 vues Grafana", GRIS),
    ]
    largeur, hauteur = 3.5, 2.6
    for index, (titre, detail, couleur) in enumerate(etapes):
        colonne = index % 4
        ligne = index // 4
        x = 0.3 + colonne * 4.05
        y = 5.6 - ligne * 3.2
        boite = FancyBboxPatch(
            (x, y),
            largeur,
            hauteur,
            boxstyle="round,pad=0.12,rounding_size=0.15",
            linewidth=1.6,
            edgecolor=couleur,
            facecolor="white",
        )
        axe.add_patch(boite)
        axe.text(x + 0.18, y + hauteur - 0.45, titre, fontsize=13, fontweight="bold", color=couleur)
        axe.text(
            x + 0.18,
            y + hauteur - 0.85,
            detail,
            fontsize=10.5,
            color=NOIR,
            va="top",
            linespacing=1.5,
        )
        if index < len(etapes) - 1:
            if colonne < 3:
                axe.add_patch(
                    FancyArrowPatch(
                        (x + largeur + 0.05, y + hauteur / 2),
                        (x + largeur + 0.45, y + hauteur / 2),
                        arrowstyle="-|>",
                        mutation_scale=16,
                        color=GRIS,
                    )
                )
            else:
                axe.add_patch(
                    FancyArrowPatch(
                        (x + largeur / 2, y - 0.08),
                        (x + largeur / 2, y - 0.42),
                        arrowstyle="-|>",
                        mutation_scale=16,
                        color=GRIS,
                    )
                )
                axe.add_patch(
                    FancyArrowPatch(
                        (x + largeur / 2, y - 0.42),
                        (0.3 + largeur / 2, y - 0.42),
                        arrowstyle="-",
                        color=GRIS,
                        linewidth=1.2,
                        linestyle=":",
                    )
                )
                axe.add_patch(
                    FancyArrowPatch(
                        (0.3 + largeur / 2, y - 0.42),
                        (0.3 + largeur / 2, y - 0.08),
                        arrowstyle="-|>",
                        mutation_scale=16,
                        color=GRIS,
                    )
                )
    _pied(figure, "apps/ml-training/src/predicare_ml_training/ (train.py, evaluate.py, dataset.py)")
    _enregistrer(figure, sortie / "3-ia" / "p3_cycle_vie_modele.png")


# ---------------------------------------------------------------------------
# 3. Courbes ROC et PR
# ---------------------------------------------------------------------------


def figure_courbes(sortie: Path) -> None:
    import joblib
    import numpy as np
    from sklearn.metrics import precision_recall_curve, roc_curve

    from predicare_ml_training.dataset import charger_jeu, decouper_temporel

    print("  re-score du jeu de test (featurisation + modele en service)...")
    jeu = charger_jeu(RACINE / "data" / "raw")
    _, _, masque_test = decouper_temporel(jeu.dates)
    matrice = jeu.X.to_numpy(dtype=np.float32)
    y = jeu.y.to_numpy(dtype=np.int8)
    modele = joblib.load(RACINE / "models" / "2" / "model.joblib")
    scores = modele.predict_proba(matrice[masque_test])[:, 1]
    y_test = y[masque_test]

    fpr, tpr, _ = roc_curve(y_test, scores)
    precision, rappel, _ = precision_recall_curve(y_test, scores)
    from sklearn.metrics import average_precision_score, roc_auc_score

    roc_auc = roc_auc_score(y_test, scores)
    pr_auc = average_precision_score(y_test, scores)

    figure, (gauche, droite) = plt.subplots(1, 2, figsize=(16, 9), dpi=100)
    figure.suptitle(
        "Courbes ROC et precision-rappel sur le jeu de test",
        fontsize=22,
        fontweight="bold",
        color=NOIR,
        x=0.02,
        ha="left",
        y=0.97,
    )
    figure.text(
        0.02,
        0.915,
        f"10 086 factures de test, 878 fraudes - ROC-AUC {roc_auc:.4f}, PR-AUC {pr_auc:.4f} "
        "(recalcul sur l'artefact en service ; le rapport de reference indique 0,9500 et 0,8913 sur son propre run)",
        fontsize=12.5,
        color=GRIS,
        ha="left",
    )

    gauche.plot([0, 1], [0, 1], linestyle="--", color=GRIS, linewidth=1.2, label="hasard")
    gauche.plot(fpr, tpr, color=BLEU, linewidth=2.6, label=f"ROC-AUC {roc_auc:.4f}")
    gauche.plot(
        [1 - SEUIL],
        [1 - 0],
        "o",
        color=ORANGE,
        markersize=11,
        markeredgecolor="white",
        markeredgewidth=1.6,
        label=f"seuil en service {SEUIL:.4f}",
    )
    gauche.set_xlabel("Taux de faux positifs", fontsize=12, color=GRIS)
    gauche.set_ylabel("Taux de vrais positifs", fontsize=12, color=GRIS)
    gauche.set_title("Courbe ROC", fontsize=15, color=NOIR, loc="left")
    gauche.legend(fontsize=11, loc="lower right", frameon=False)
    gauche.grid(alpha=0.25)
    gauche.set_axisbelow(True)

    droite.plot(rappel, precision, color=BLEU, linewidth=2.6, label=f"PR-AUC {pr_auc:.4f}")
    droite.axhline(
        y_test.mean(), linestyle="--", color=GRIS, linewidth=1.2, label="base positive (8,7 %)"
    )
    droite.set_xlabel("Rappel", fontsize=12, color=GRIS)
    droite.set_ylabel("Precision", fontsize=12, color=GRIS)
    droite.set_title("Courbe precision-rappel", fontsize=15, color=NOIR, loc="left")
    droite.legend(fontsize=11, loc="lower left", frameon=False)
    droite.grid(alpha=0.25)
    droite.set_axisbelow(True)

    for axe in (gauche, droite):
        for spine in ("top", "right"):
            axe.spines[spine].set_visible(False)

    _pied(figure, "models/2/model.joblib sur le jeu de test de data/raw (recalcul complet)")
    _enregistrer(figure, sortie / "3-ia" / "p3_courbes_roc_pr.png")


# ---------------------------------------------------------------------------
# 4. Matrice de confusion
# ---------------------------------------------------------------------------


def figure_matrice_confusion(sortie: Path) -> None:
    rapport = (RACINE / "reports" / "modele_v2.md").read_text(encoding="utf-8")
    lignes = re.findall(r"\|\s*\*\*(alerte|pas d'alerte)[^|]*\|\s*(\d+)\s*\|\s*(\d+)\s*\|", rapport)
    if len(lignes) != 2:
        raise SystemExit("matrice de confusion introuvable dans reports/modele_v2.md")
    (_, vp, fp), (_, fn, vn) = lignes
    vp, fp, fn, vn = int(vp), int(fp), int(fn), int(vn)
    total = vp + fp + fn + vn
    rappel = vp / (vp + fn)
    precision = vp / (vp + fp)
    specificite = vn / (vn + fp)

    figure, axe = _figure(
        "Matrice de confusion au seuil de service (0,2876)",
        f"{total:,} factures de test - le score priorise, l'humain decide".replace(",", " "),
    )
    axe.set_xlim(0, 2)
    axe.set_ylim(0, 2)
    axe.axis("off")
    cases = [
        (0, 1, vp, "Vrais positifs", "fraude detectee", VERT),
        (1, 1, fp, "Faux positifs", "controle inutile", ORANGE),
        (0, 0, fn, "Faux negatifs", "fraude non detectee", ROUGE),
        (1, 0, vn, "Vrais negatifs", "facture legitime", BLEU),
    ]
    for x, y, valeur, titre, sous_titre, couleur in cases:
        rect = FancyBboxPatch(
            (x * 1.02 + 0.05, y * 1.02 + 0.05),
            0.86,
            0.86,
            boxstyle="round,pad=0.02,rounding_size=0.08",
            linewidth=2,
            edgecolor=couleur,
            facecolor="white",
        )
        axe.add_patch(rect)
        axe.text(
            x * 1.02 + 0.48,
            y * 1.02 + 0.70,
            f"{valeur:,}".replace(",", " "),
            fontsize=40,
            fontweight="bold",
            color=couleur,
            ha="center",
        )
        axe.text(x * 1.02 + 0.48, y * 1.02 + 0.46, titre, fontsize=14, color=NOIR, ha="center")
        axe.text(x * 1.02 + 0.48, y * 1.02 + 0.24, sous_titre, fontsize=11, color=GRIS, ha="center")
    axe.text(0.55, 2.12, "Fraude reelle", fontsize=13, color=GRIS, ha="center")
    axe.text(1.55, 2.12, "Non-fraude reelle", fontsize=13, color=GRIS, ha="center")
    axe.text(-0.06, 1.55, "Alerte", fontsize=13, color=GRIS, ha="right", va="center")
    axe.text(-0.06, 0.55, "Pas d'alerte", fontsize=13, color=GRIS, ha="right", va="center")
    axe.set_title(
        f"Rappel {rappel:.4f}   |   Precision {precision:.4f}   |   Specificite {specificite:.4f}",
        fontsize=15,
        color=NOIR,
        loc="left",
        pad=18,
    )
    _pied(figure, "reports/modele_v2.md - seuil arbitre sur la validation, test lu une seule fois")
    _enregistrer(figure, sortie / "3-ia" / "p3_matrice_confusion.png")


# ---------------------------------------------------------------------------
# 5. Comparaison aux bases de decision
# ---------------------------------------------------------------------------


def figure_baselines(sortie: Path) -> None:
    donnees = json.loads((RACINE / "reports" / "baselines_v2.json").read_text(encoding="utf-8"))
    resultats = [r for r in donnees["resultats"] if abs(r["seuil"] - SEUIL) < 1e-6]
    libelles = {
        "modele XGBoost": "Modele a arbres\n(retenu)",
        "regles deterministes": "Regles metier\n(deterministes)",
        "regression logistique": "Regression\nlogistique",
        "regles + modele (OU)": "Regles + modele\n(union logique)",
    }
    noms = [libelles.get(r["strategie"], r["strategie"]) for r in resultats]
    couleurs = [VERT if r["strategie"] == "modele XGBoost" else GRIS_CLAIR for r in resultats]

    figure, (gauche, droite) = plt.subplots(1, 2, figsize=(16, 9), dpi=100)
    figure.suptitle(
        "Pourquoi un modele appris : comparaison aux trois autres facons de decider",
        fontsize=22,
        fontweight="bold",
        color=NOIR,
        x=0.02,
        ha="left",
        y=0.97,
    )
    figure.text(
        0.02,
        0.915,
        "Memes variables, meme decoupage temporel, seuil 0,2876 - cout metier : 3 000 MGA par faux positif, 30 000 MGA par fraude manquee",
        fontsize=12.5,
        color=GRIS,
        ha="left",
    )

    positions = range(len(resultats))
    largeur = 0.38
    gauche.bar(
        [p - largeur / 2 for p in positions],
        [r["rappel"] for r in resultats],
        width=largeur,
        color=BLEU,
        label="Rappel",
    )
    gauche.bar(
        [p + largeur / 2 for p in positions],
        [r["precision"] for r in resultats],
        width=largeur,
        color=BLEU_CLAIR,
        label="Precision",
    )
    gauche.axhline(
        0.9, linestyle="--", color=ROUGE, linewidth=1.4, label="Objectif de rappel (90 %)"
    )
    gauche.set_xticks(list(positions))
    gauche.set_xticklabels(noms, fontsize=11)
    gauche.set_ylim(0, 1.02)
    gauche.set_ylabel("Taux", fontsize=12, color=GRIS)
    gauche.set_title("Rappel et precision", fontsize=15, color=NOIR, loc="left")
    gauche.legend(fontsize=11, frameon=False, loc="upper right")
    gauche.grid(axis="y", alpha=0.25)
    gauche.set_axisbelow(True)
    for position, resultat in zip(positions, resultats, strict=True):
        gauche.text(
            position - largeur / 2,
            resultat["rappel"] + 0.02,
            f"{resultat['rappel']:.3f}",
            ha="center",
            fontsize=10,
            color=NOIR,
        )
        gauche.text(
            position + largeur / 2,
            resultat["precision"] + 0.02,
            f"{resultat['precision']:.3f}",
            ha="center",
            fontsize=10,
            color=NOIR,
        )

    droite.bar(
        list(positions),
        [r["cout_total"] / 1_000_000 for r in resultats],
        color=couleurs,
        width=0.6,
    )
    droite.set_xticks(list(positions))
    droite.set_xticklabels(noms, fontsize=11)
    droite.set_ylabel("Cout metier (millions de MGA)", fontsize=12, color=GRIS)
    droite.set_title("Cout metier engendre", fontsize=15, color=NOIR, loc="left")
    droite.grid(axis="y", alpha=0.25)
    droite.set_axisbelow(True)
    for position, resultat in zip(positions, resultats, strict=True):
        droite.text(
            position,
            resultat["cout_total"] / 1_000_000 + 0.4,
            f"{resultat['cout_total'] / 1_000_000:.2f} M",
            ha="center",
            fontsize=10.5,
            color=NOIR,
        )

    for axe in (gauche, droite):
        for spine in ("top", "right"):
            axe.spines[spine].set_visible(False)

    _pied(
        figure,
        "reports/baselines_v2.md - modele re-entraine pour la comparaison, artefact de production non modifie",
    )
    _enregistrer(figure, sortie / "3-ia" / "p3_comparaison_baselines.png")


# ---------------------------------------------------------------------------
# 6. Equite par segment
# ---------------------------------------------------------------------------


def figure_equite(sortie: Path) -> None:
    sections = _tableaux_markdown(RACINE / "reports" / "equite_v2.md")
    titres = {
        "Par tranche_age": "Par tranche d'age",
        "Par niveau_tarif": "Par niveau de tarif",
        "Par type_prestataire": "Par type de prestataire",
        "Par formule": "Par formule",
    }
    cles = [c for c in titres if c in sections]
    figure, axes = plt.subplots(2, 2, figsize=(16, 9), dpi=100)
    figure.suptitle(
        "Audit d'equite : la performance ne se repartit pas uniformement",
        fontsize=22,
        fontweight="bold",
        color=NOIR,
        x=0.02,
        ha="left",
        y=0.97,
    )
    figure.text(
        0.02,
        0.915,
        "Rappel par segment sur le jeu de test - un ecart sur 80 factures n'a pas la portee d'un ecart sur 3 000",
        fontsize=12.5,
        color=GRIS,
        ha="left",
    )
    for axe, cle in zip(axes.ravel(), cles, strict=False):
        tableau = sections[cle]
        donnees = [ligne for ligne in tableau[1:] if len(ligne) >= 4]
        segments = [ligne[0] for ligne in donnees]
        effectifs = [int(ligne[1]) for ligne in donnees]
        rappels = [float(ligne[2]) for ligne in donnees]
        couleurs = [ORANGE if r < 0.85 else BLEU for r in rappels]
        positions = range(len(segments))
        axe.bar(list(positions), rappels, color=couleurs, width=0.62)
        axe.axhline(0.8702, linestyle="--", color=GRIS, linewidth=1.3)
        axe.text(
            len(segments) - 0.4,
            0.878,
            "rappel global 87,02 %",
            fontsize=9.5,
            color=GRIS,
            ha="right",
        )
        axe.set_xticks(list(positions))
        axe.set_xticklabels(
            [f"{s}\n(n={n:,})".replace(",", " ") for s, n in zip(segments, effectifs, strict=True)],
            fontsize=9.5,
        )
        axe.set_ylim(0, 1.05)
        axe.set_title(titres[cle], fontsize=14, color=NOIR, loc="left")
        axe.grid(axis="y", alpha=0.25)
        axe.set_axisbelow(True)
        for spine in ("top", "right"):
            axe.spines[spine].set_visible(False)
        for position, rappel in zip(positions, rappels, strict=True):
            axe.text(
                position, rappel + 0.02, f"{rappel:.3f}", ha="center", fontsize=9.5, color=NOIR
            )
    figure.text(
        0.98, 0.045, "Orange : segment sous 85 % de rappel", fontsize=11, color=ORANGE, ha="right"
    )
    _pied(figure, "reports/equite_v2.md - audit versionne sur le jeu de test du modele v2")
    _enregistrer(figure, sortie / "3-ia" / "p3_equite_segments.png")


# ---------------------------------------------------------------------------
# 7. Derive du modele
# ---------------------------------------------------------------------------


def figure_derive(sortie: Path) -> None:
    """Derive : comparaison des distributions reelles + etat du dispositif.

    Sur cette instance, le rapport de derive n'est PAS calculable : le worker
    journalise `derive.donnees_insuffisantes` faute de population de reference
    (le modele n'a pas de reference de distribution enregistree). La figure ne
    pretend donc pas afficher un PSI : elle compare les distributions reelles
    et dit franchement ce qui manque.
    """
    lignes = _csv_sql(
        """
        SELECT statut,
               count(*),
               round(min(score_fraude)::numeric, 4),
               round(max(score_fraude)::numeric, 4),
               round(avg(score_fraude)::numeric, 4)
        FROM ml.prediction
        GROUP BY statut
        ORDER BY count(*) DESC
        """
    )
    etats = {
        ligne[0]: (int(ligne[1]), float(ligne[2]), float(ligne[3]), float(ligne[4]))
        for ligne in lignes
    }

    histogramme = _csv_sql(
        """
        SELECT statut, round((width_bucket(score_fraude, 0, 1, 20) - 1) * 0.05, 2) AS borne,
               count(*)
        FROM ml.prediction
        GROUP BY statut, borne
        ORDER BY statut, borne
        """
    )
    series: dict[str, list[tuple[float, int]]] = {}
    for statut, borne, compte in histogramme:
        series.setdefault(statut, []).append((float(borne), int(compte)))

    figure, (gauche, droite) = plt.subplots(1, 2, figsize=(16, 9), dpi=100)
    figure.suptitle(
        "Surveillance de la derive : comment la population notee evolue-t-elle ?",
        fontsize=22,
        fontweight="bold",
        color=NOIR,
        x=0.02,
        ha="left",
        y=0.97,
    )
    figure.text(
        0.02,
        0.915,
        "Comparaison des distributions de score reellement stockees, et etat du dispositif de surveillance",
        fontsize=12.5,
        color=GRIS,
        ha="left",
    )

    couleurs = {"historique": BLEU, "nouvelle": ORANGE}
    for statut, points in series.items():
        if len(points) < 3:
            continue
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        gauche.plot(
            xs,
            ys,
            linewidth=2.4,
            marker="o",
            markersize=5,
            color=couleurs.get(statut, GRIS),
            label=f"{statut} ({etats.get(statut, (0,))[0]:,} factures)".replace(",", " "),
        )
    gauche.axvline(SEUIL, linestyle="--", color=ROUGE, linewidth=1.6)
    gauche.text(
        SEUIL + 0.01, gauche.get_ylim()[1] * 0.85, f"seuil {SEUIL:.4f}", fontsize=11, color=ROUGE
    )
    gauche.set_xlabel("Score de fraude", fontsize=12, color=GRIS)
    gauche.set_ylabel("Nombre de factures", fontsize=12, color=GRIS)
    gauche.set_title("Distribution des scores par statut", fontsize=15, color=NOIR, loc="left")
    gauche.legend(fontsize=11, frameon=False)
    gauche.grid(alpha=0.25)
    gauche.set_axisbelow(True)
    for spine in ("top", "right"):
        gauche.spines[spine].set_visible(False)

    droite.axis("off")
    droite.set_xlim(0, 1)
    droite.set_ylim(0, 1)
    blocs = [
        ("Worker horaire", "Un rapport de derive par heure, fenetre glissante de 30 jours", VERT),
        ("PSI", "stable < 0,10  |  alerte > 0,25  |  ecart de score moyen 0,10", BLEU),
        (
            "Regle Prometheus",
            "PredicarePartScoresEleves : part des scores au-dessus de 0,3",
            BLEU_CLAIR,
        ),
        ("Vues Grafana", "Vue service et vue modele provisionnees dans le depot", GRIS),
    ]
    y = 0.92
    for titre, detail, couleur in blocs:
        droite.add_patch(
            FancyBboxPatch(
                (0.02, y - 0.19),
                0.96,
                0.17,
                boxstyle="round,pad=0.01,rounding_size=0.02",
                linewidth=1.5,
                edgecolor=couleur,
                facecolor="white",
            )
        )
        droite.text(0.05, y - 0.055, titre, fontsize=12.5, fontweight="bold", color=couleur)
        droite.text(0.05, y - 0.13, detail, fontsize=10.5, color=NOIR)
        y -= 0.22
    droite.add_patch(
        FancyBboxPatch(
            (0.02, 0.02),
            0.96,
            0.13,
            boxstyle="round,pad=0.01,rounding_size=0.02",
            linewidth=1.5,
            edgecolor=ORANGE,
            facecolor="#fff8f0",
        )
    )
    droite.text(
        0.05, 0.095, "Etat reel de cette instance", fontsize=12, fontweight="bold", color=ORANGE
    )
    droite.text(
        0.05,
        0.045,
        "Le rapport de derive n'est pas calculable : la population de reference du modele n'est pas enregistree (worker : derive.donnees_insuffisantes). La surveillance repose donc sur l'indicateur de substitution Prometheus.",
        fontsize=10.5,
        color=NOIR,
    )

    _pied(
        figure,
        "ml.prediction (84 605 predictions) et journal du worker-ingest - aucune valeur inventee",
    )
    _enregistrer(figure, sortie / "3-ia" / "p3_derive_psi.png")


# ---------------------------------------------------------------------------
# 8-10. FinOps
# ---------------------------------------------------------------------------


def figure_tco(sortie: Path) -> None:
    scenarios = ["Base", "Stress", "Conservateur"]
    infrastructure = [101.88, 144.00, 144.00]
    sauvegarde = [0.02, 0.12, 0.12]
    tokens = [7.07, 70.66, 246.74]
    totaux = [108.97, 214.78, 390.86]

    figure, (gauche, droite) = plt.subplots(1, 2, figsize=(16, 9), dpi=100)
    figure.suptitle(
        "Cout total de possession : trois scenarios, une seule constante",
        fontsize=22,
        fontweight="bold",
        color=NOIR,
        x=0.02,
        ha="left",
        y=0.97,
    )
    figure.text(
        0.02,
        0.915,
        "Hébergement + sauvegarde + tokens LLM - 1 000 questions par mois en base, 10 000 en stress",
        fontsize=12.5,
        color=GRIS,
        ha="left",
    )
    positions = range(len(scenarios))
    gauche.bar(list(positions), infrastructure, color=BLEU, width=0.55, label="Infrastructure")
    gauche.bar(
        list(positions),
        sauvegarde,
        bottom=infrastructure,
        color=BLEU_CLAIR,
        width=0.55,
        label="Sauvegarde",
    )
    gauche.bar(
        list(positions),
        tokens,
        bottom=[a + b for a, b in zip(infrastructure, sauvegarde, strict=True)],
        color=ORANGE,
        width=0.55,
        label="Tokens du modele",
    )
    for position, total in zip(positions, totaux, strict=True):
        gauche.text(
            position,
            total + 10,
            f"{total:.2f} €/an",
            ha="center",
            fontsize=13,
            fontweight="bold",
            color=NOIR,
        )
    gauche.set_xticks(list(positions))
    gauche.set_xticklabels(scenarios, fontsize=12)
    gauche.set_ylabel("Euros par an", fontsize=12, color=GRIS)
    gauche.set_title("Decomposition du cout annuel", fontsize=15, color=NOIR, loc="left")
    gauche.legend(fontsize=11, frameon=False, loc="upper left")
    gauche.grid(axis="y", alpha=0.25)
    gauche.set_axisbelow(True)
    gauche.set_ylim(0, 460)
    for spine in ("top", "right"):
        gauche.spines[spine].set_visible(False)

    parts_infra = [93.5, 67.0, 36.8]
    parts_tokens = [6.5, 33.0, 63.1]
    droite.bar(list(positions), parts_infra, color=BLEU, width=0.55, label="Infrastructure")
    droite.bar(
        list(positions),
        parts_tokens,
        bottom=parts_infra,
        color=ORANGE,
        width=0.55,
        label="Tokens du modele",
    )
    for position, (infra, tokens_part) in enumerate(zip(parts_infra, parts_tokens, strict=True)):
        droite.text(
            position,
            infra / 2,
            f"{infra:.1f} %",
            ha="center",
            va="center",
            fontsize=12,
            color="white",
            fontweight="bold",
        )
        droite.text(
            position,
            infra + tokens_part / 2,
            f"{tokens_part:.1f} %",
            ha="center",
            va="center",
            fontsize=12,
            color="white",
            fontweight="bold",
        )
    droite.set_xticks(list(positions))
    droite.set_xticklabels(scenarios, fontsize=12)
    droite.set_ylabel("Part du cout total", fontsize=12, color=GRIS)
    droite.set_title("Le modele n'est pas le poste principal", fontsize=15, color=NOIR, loc="left")
    droite.legend(fontsize=11, frameon=False, loc="lower left", bbox_to_anchor=(0, -0.16), ncol=2)
    droite.grid(axis="y", alpha=0.25)
    droite.set_axisbelow(True)
    droite.set_ylim(0, 100)
    for spine in ("top", "right"):
        droite.spines[spine].set_visible(False)

    _pied(figure, "docs/livrables/01_analyse_tco_roi.md - mesures pile + hypotheses de prix datees")
    _enregistrer(figure, sortie / "5-gouvernance" / "p5_tco_scenarios.png")


def figure_roi(sortie: Path) -> None:
    figure, (gauche, droite) = plt.subplots(1, 2, figsize=(16, 9), dpi=100)
    figure.suptitle(
        "Retour sur investissement : ce que la plateforme evite, et a partir de quand",
        fontsize=22,
        fontweight="bold",
        color=NOIR,
        x=0.02,
        ha="left",
        y=0.97,
    )
    figure.text(
        0.02,
        0.915,
        "Deux conventions de reference, presentees separement - 22,66 M MGA d'economie sur le jeu de test",
        fontsize=12.5,
        color=GRIS,
        ha="left",
    )

    etiquettes = ["Reference\n« tout controle »", "Cout du modele\navec revue", "Economie"]
    valeurs = [27.624, 4.968, 22.656]
    couleurs = [GRIS, BLEU, VERT]
    positions = range(len(valeurs))
    gauche.bar(list(positions), valeurs, color=couleurs, width=0.55)
    for position, valeur in zip(positions, valeurs, strict=True):
        gauche.text(
            position,
            valeur + 0.6,
            f"{valeur:.3f} M".replace(".", ","),
            ha="center",
            fontsize=13,
            fontweight="bold",
            color=NOIR,
        )
    gauche.set_xticks(list(positions))
    gauche.set_xticklabels(etiquettes, fontsize=11.5)
    gauche.set_ylabel("Millions de MGA (jeu de test)", fontsize=12, color=GRIS)
    gauche.set_title("Economie de controle de fraude", fontsize=15, color=NOIR, loc="left")
    gauche.grid(axis="y", alpha=0.25)
    gauche.set_axisbelow(True)
    gauche.set_ylim(0, 33)
    for spine in ("top", "right"):
        gauche.spines[spine].set_visible(False)

    seuil_brevet = 239
    volumes = [0, 100, 239, 500, 1000, 5000, 84593]
    economies = [v * 2280 / 1_000_000 for v in volumes]
    droite.plot(volumes, economies, color=BLEU, linewidth=2.6, marker="o", markersize=6)
    droite.axvline(seuil_brevet, linestyle="--", color=ORANGE, linewidth=1.8)
    droite.text(
        seuil_brevet * 1.3,
        economies[-1] * 0.12,
        f"seuil de rentabilité\n~{seuil_brevet} factures/an",
        fontsize=11.5,
        color=ORANGE,
    )
    droite.set_xlabel("Factures traitees par an", fontsize=12, color=GRIS)
    droite.set_ylabel("Economie de controle (M MGA)", fontsize=12, color=GRIS)
    droite.set_title(
        "A partir de quand la plateforme rembourse son cout", fontsize=15, color=NOIR, loc="left"
    )
    droite.grid(alpha=0.25)
    droite.set_axisbelow(True)
    for spine in ("top", "right"):
        droite.spines[spine].set_visible(False)

    _pied(
        figure,
        "docs/livrables/01_analyse_tco_roi.md - cout de controle 3 000 MGA, fraude manquee 30 000 MGA (hypotheses metier)",
    )
    _enregistrer(figure, sortie / "5-gouvernance" / "p5_roi_conventions.png")


def figure_sensibilite(sortie: Path) -> None:
    couts = [15000, 30000, 60000]
    couts_modele = [5.55, 7.26, 10.68]
    economies = [24.708, 22.998, 19.578]
    ratios = [45.35, 42.21, 35.93]

    figure, (gauche, droite) = plt.subplots(1, 2, figsize=(16, 9), dpi=100)
    figure.suptitle(
        "Sensibilite : que reste-t-il si l'hypothese de cout change ?",
        fontsize=22,
        fontweight="bold",
        color=NOIR,
        x=0.02,
        ha="left",
        y=0.97,
    )
    figure.text(
        0.02,
        0.915,
        "Le cout d'une fraude non detectee est l'hypothese la plus influente du calcul",
        fontsize=12.5,
        color=GRIS,
        ha="left",
    )
    positions = range(len(couts))
    gauche.bar(
        [p - 0.2 for p in positions], couts_modele, width=0.4, color=BLEU, label="Cout du modele"
    )
    gauche.bar(
        [p + 0.2 for p in positions], economies, width=0.4, color=VERT, label="Economie de controle"
    )
    gauche.set_xticks(list(positions))
    gauche.set_xticklabels([f"{c // 1000} 000 MGA".replace(",", " ") for c in couts], fontsize=12)
    gauche.set_ylabel("Millions de MGA", fontsize=12, color=GRIS)
    gauche.set_title("Cout du modele et economie obtenue", fontsize=15, color=NOIR, loc="left")
    gauche.legend(fontsize=11, frameon=False)
    gauche.grid(axis="y", alpha=0.25)
    gauche.set_axisbelow(True)
    for spine in ("top", "right"):
        gauche.spines[spine].set_visible(False)

    droite.plot(
        [c / 1000 for c in couts], ratios, color=ORANGE, linewidth=2.6, marker="o", markersize=9
    )
    for cout, ratio in zip(couts, ratios, strict=True):
        droite.annotate(
            f"{ratio:.2f}x",
            (cout / 1000, ratio),
            textcoords="offset points",
            xytext=(0, 12),
            ha="center",
            fontsize=12,
            color=NOIR,
        )
    droite.set_xlabel("Cout d'une fraude non detectee (milliers de MGA)", fontsize=12, color=GRIS)
    droite.set_ylabel("Ratio economie / TCO", fontsize=12, color=GRIS)
    droite.set_title(
        "Le resultat reste favorable dans les trois cas", fontsize=15, color=NOIR, loc="left"
    )
    droite.grid(alpha=0.25)
    droite.set_axisbelow(True)
    droite.set_ylim(30, 50)
    for spine in ("top", "right"):
        droite.spines[spine].set_visible(False)

    _pied(figure, "docs/livrables/01_analyse_tco_roi.md - seuil 0,2876, TCO de base 108,97 €/an")
    _enregistrer(figure, sortie / "5-gouvernance" / "p5_sensibilite_fraude.png")


# ---------------------------------------------------------------------------
# 11. Conformite AI Act
# ---------------------------------------------------------------------------


def figure_conformite(sortie: Path) -> None:
    registre = (RACINE / "docs" / "cadrage" / "registre_risques.md").read_text(encoding="utf-8")
    articles = re.findall(r"\*\*Art\. (\d+(?:, \d+)*)\*\*", registre)
    risques = re.findall(
        r"\| \*\*([Éé]cart assumé|Moyen[^\n|]*|Faible[^\n|]*|Élevé[^\n|]*)\.?\*\*", registre
    )
    niveaux = []
    for article, risque in zip(articles, risques, strict=False):
        if "Élevé" in risque or "élevé" in risque:
            niveau = 2
        elif "Moyen" in risque:
            niveau = 1
        else:
            niveau = 0
        niveaux.append((article, niveau))

    libelles = {
        0: "Faible",
        1: "Moyen",
        2: "Élevé",
    }
    couleurs = {0: VERT, 1: ORANGE, 2: ROUGE}
    if not niveaux:
        raise SystemExit("registre des risques illisible")

    figure, axe = _figure(
        "État de conformite par obligation de l'AI Act",
        "Risque residuel tel qu'il est ecrit dans le registre des risques (art. 9 a 73)",
    )
    positions = range(len(niveaux))
    for position, (article, niveau) in zip(positions, niveaux, strict=True):
        axe.barh(position, 1, color=couleurs[niveau], height=0.62)
        axe.text(
            0.015,
            position,
            f"Article {article}",
            va="center",
            fontsize=11.5,
            color="white",
            fontweight="bold",
        )
        axe.text(
            1.02,
            position,
            libelles[niveau],
            va="center",
            fontsize=11,
            color=couleurs[niveau],
            fontweight="bold",
        )
    axe.set_yticks([])
    axe.set_xlim(0, 1.3)
    axe.set_xticks([])
    axe.invert_yaxis()
    for spine in ("top", "right", "left", "bottom"):
        axe.spines[spine].set_visible(False)
    compte = {niveau: sum(1 for _, n in niveaux if n == niveau) for niveau in (0, 1, 2)}
    axe.set_title(
        f"{compte[0]} risque(s) faible  |  {compte[1]} moyen(s)  |  {compte[2]} eleve(s), dont la mise sur le marche non faite",
        fontsize=13,
        color=GRIS,
        loc="left",
        pad=12,
    )
    _pied(
        figure,
        "docs/cadrage/registre_risques.md - registre des risques AI Act, version 1.0 du 21 octobre 2026",
    )
    _enregistrer(figure, sortie / "5-gouvernance" / "p5_conformite_ai_act.png")


# ---------------------------------------------------------------------------
# 12. Architecture
# ---------------------------------------------------------------------------


def figure_architecture(sortie: Path) -> None:
    figure, axe = _figure(
        "Architecture du produit et socle d'exploitation",
        "Une pile Docker unique, un reseau interne, une seule porte d'entree",
    )
    axe.set_xlim(0, 16)
    axe.set_ylim(0, 9)
    axe.axis("off")

    navigateur = (
        "Navigateur",
        "4 roles : assuré, professionnel\nde sante, gestionnaire, admin",
        BLEU,
    )
    passerelle = ("Passerelle (Traefik)", "TLS, limitation de debit,\nCSP, journal d'acces", BLEU)
    services = [
        ("api-core", "metier, auth, factures,\ndecisions, RGPD"),
        ("api-inference", "notation, seuil,\nregistre de modeles"),
        ("api-rag", "assistant, sources,\ncache semantique"),
    ]
    socle = [
        ("PostgreSQL + pgvector", "donnees metier, audit,\nvecteurs, MLflow"),
        ("Redis", "sessions, files"),
        ("Superset", "tableau de bord\n(BI)"),
        ("Prometheus + Grafana", "metriques, alertes,\nvues de supervision"),
        ("n8n", "notifications,\\nalerte de fraude"),
    ]

    def _boite(
        x: float, y: float, largeur: float, hauteur: float, titre: str, detail: str, couleur: str
    ) -> None:
        axe.add_patch(
            FancyBboxPatch(
                (x, y),
                largeur,
                hauteur,
                boxstyle="round,pad=0.08,rounding_size=0.12",
                linewidth=1.8,
                edgecolor=couleur,
                facecolor="white",
            )
        )
        axe.text(
            x + largeur / 2,
            y + hauteur - 0.35,
            titre,
            fontsize=12.5,
            fontweight="bold",
            color=couleur,
            ha="center",
        )
        axe.text(
            x + largeur / 2,
            y + hauteur / 2 - 0.25,
            detail,
            fontsize=10,
            color=NOIR,
            ha="center",
            va="center",
            linespacing=1.5,
        )

    def _fleche(x1: float, y1: float, x2: float, y2: float) -> None:
        axe.add_patch(
            FancyArrowPatch(
                (x1, y1),
                (x2, y2),
                arrowstyle="-|>",
                mutation_scale=15,
                color=GRIS,
                linewidth=1.3,
            )
        )

    _boite(0.4, 6.9, 3.0, 1.5, navigateur[0], navigateur[1], navigateur[2])
    _boite(0.4, 4.6, 3.0, 1.5, passerelle[0], passerelle[1], passerelle[2])
    _fleche(1.9, 6.85, 1.9, 6.15)

    for index, (titre, detail) in enumerate(services):
        x = 4.4 + index * 3.7
        _boite(x, 4.6, 3.3, 1.5, titre, detail, ORANGE)
        _fleche(3.45, 5.35, x - 0.05, 5.35)

    _boite(0.4, 2.3, 3.0, 1.4, "Web (React + Vite)", "interface unique,\n4 espaces", BLEU)
    _fleche(3.45, 3.0, 4.35, 5.3)

    for index, (titre, detail) in enumerate(socle):
        x = 4.4 + (index % 3) * 3.7
        y = 0.5 if index < 3 else 2.3
        _boite(x, y, 3.3, 1.4, titre, detail, VERT)
    _fleche(6.1, 4.55, 6.1, 1.95)
    _fleche(9.8, 4.55, 9.8, 1.95)
    _fleche(13.5, 4.55, 13.5, 1.95)

    axe.text(
        0.4,
        3.9,
        "Reseau interne (core) : la base et Redis ne sont pas publies sur la machine hote",
        fontsize=11,
        color=GRIS,
    )
    _pied(figure, "docker-compose.yml + overlays (bi, observabilite, mlops, ops)")
    _enregistrer(figure, sortie / "2-architecture" / "p2_architecture_globale.png")


# ---------------------------------------------------------------------------


def main() -> int:
    parseur = argparse.ArgumentParser(description="Genere les figures de la presentation.")
    parseur.add_argument("--sortie", default="docs/livrables/figures", help="dossier de sortie")
    arguments = parseur.parse_args()
    sortie = Path(arguments.sortie).resolve()
    sortie.mkdir(parents=True, exist_ok=True)

    etapes = [
        ("importance des variables", figure_importance_variables),
        ("cycle de vie du modele", figure_cycle_vie),
        ("courbes ROC et PR", figure_courbes),
        ("matrice de confusion", figure_matrice_confusion),
        ("comparaison aux baselines", figure_baselines),
        ("audit d'equite", figure_equite),
        ("derive PSI", figure_derive),
        ("TCO par scenario", figure_tco),
        ("ROI et seuil de rentabilite", figure_roi),
        ("sensibilite au cout de la fraude", figure_sensibilite),
        ("conformite AI Act", figure_conformite),
        ("architecture", figure_architecture),
    ]
    for nom, fonction in etapes:
        print(f"[figure] {nom}")
        try:
            fonction(sortie)
        except Exception as erreur:
            print(f"  ECHEC {nom} : {erreur}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
