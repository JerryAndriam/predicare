"""Explicabilite SHAP : transformer un score en justification lisible.

Phase 2.6 du plan d'action et exigence explicite du module 3 du cursus
("rapport d'explicabilite SHAP pour chaque alerte"). Un gestionnaire ne lit
pas une valeur SHAP : il lit une phrase. `human_readable` est donc produit
ici, en francais, et non laisse a l'interface.
"""

from __future__ import annotations

import numpy as np

from predicare.schemas import ShapContribution

#: Libelles metier. Le nom technique de la variable n'est jamais presente
#: tel quel dans une alerte : un gestionnaire ne connait pas `ratio_montant_mois`.
#:
#: Les libelles sont ACCENTUES : ils sont lus par un humain, dans une
#: alerte qui doit credible devant un jury. Un libelle sans accent se lit
#: comme une faute de finition, et la valeur d'une explication tient
#: autant a sa forme qu'a son fond.
LIBELLES: dict[str, str] = {
    # --- Structure -----------------------------------------------------------
    "montant_total": "montant total de la facture",
    "log1p_montant_total": "niveau de montant de la facture",
    "montant_moyen_ligne": "montant moyen par ligne",
    "montant_max_ligne": "montant de la ligne la plus élevée",
    "nb_lignes": "nombre de lignes",
    "quantite_totale": "quantité totale facturée",
    "diversification_actes": "variété des actes facturés",
    "nb_categories": "variété des catégories d'acte",
    "categorie_dominante_code": "catégorie d'acte principale",
    "part_actes_specialises": "part des actes spécialisés",
    "ratio_quantite": "quantité moyenne par ligne",
    # --- Tarification --------------------------------------------------------
    "ratio_prix_grille_max": "écart au tarif de la grille du prestataire",
    "ratio_prix_grille_moyen": "écart moyen au tarif de la grille",
    "ecart_prix_grille_max": "montant de l'écart au tarif de la grille",
    "ratio_prix_reference_max": "écart au tarif de référence du référentiel",
    "depasse_tarif_max": "dépassement du tarif maximal autorisé",
    "produit_non_remboursable": "présence d'un produit non remboursable",
    # --- Prescription -------------------------------------------------------
    "taux_lignes_non_prescrites": "lignes facturées absentes de l'ordonnance",
    "ordonnance_absente_requis": "ordonnance obligatoire manquante",
    "ordonnance_expiree": "ordonnance expirée à la date du soin",
    "delai_prescription_jours": "délai entre prescription et soin",
    "prescripteur_different": "prescription émise par un autre praticien",
    # --- Coherence profil ---------------------------------------------------
    "incompatibilite_sexe": "acte incompatible avec le sexe de l'assuré",
    "incompatibilite_age": "acte incompatible avec l'âge de l'assuré",
    # --- Prestataire et horaires --------------------------------------------
    "prestataire_radie": "soin par un prestataire radié",
    "hors_convention": "soin hors période de conventionnement",
    "soin_jour_ferme": "soin réalisé un jour de fermeture",
    "soin_hors_horaire": "soin réalisé hors des horaires d'ouverture",
    "prestataire_niveau_tarif_eleve": "prestataire à niveau tarifaire élevé",
    # --- Garantie et couverture ---------------------------------------------
    "montant_vs_plafond_garantie": "montant rapporté au plafond de la garantie",
    "hors_periode_contrat": "soin hors période de couverture du contrat",
    "taux_actes_exclus": "part des actes exclus par la formule",
}


def _human_readable(feature: str, shap_value: float) -> str:
    libelle = LIBELLES.get(feature, feature.replace("_", " "))
    if shap_value > 0:
        return f"{libelle} : fortement à l'origine du risque de fraude"
    return f"{libelle} : contribue à réduire le risque de fraude"


def shap_to_contributions(
    feature_names: list[str],
    shap_values: np.ndarray,
    base_value: float,
    *,
    top_n: int = 5,
) -> list[ShapContribution]:
    """Convertit un vecteur SHAP en contributions triees par importance.

    On ne renvoie que les `top_n` contributions les plus fortes en valeur
    absolue : les 50 variables du modele noieraient le gestionnaire. Les
    contributions negatives restent visibles, elles justifient la confiance
    accordee a une alerte.
    """
    contributions: list[ShapContribution] = []
    for index, feature in enumerate(feature_names):
        if index >= len(shap_values):
            break
        shap_value = float(shap_values[index])
        contributions.append(
            ShapContribution(
                feature=feature,
                value=0.0,
                shap_value=round(shap_value, 6),
                base_value=round(float(base_value), 6),
                direction="pousse_vers_fraude" if shap_value > 0 else "pousse_vers_legitime",
                human_readable=_human_readable(feature, shap_value),
            )
        )

    contributions.sort(key=lambda c: abs(c.shap_value), reverse=True)
    return contributions[:top_n]


def build_shap_report(contributions: list[ShapContribution], score: float, seuil: float) -> str:
    """Rapport SHAP en texte, envoye tel quel dans la notification Slack."""
    if not contributions:
        return (
            f"Facture notée {score:.0%} (seuil {seuil:.0%}). "
            "Aucune contribution dominante : anomalie diffuse, non attribuée."
        )
    lignes = [
        f"Facture notée {score:.0%} (seuil {seuil:.0%}).",
        "Principaux facteurs :",
    ]
    for rang, contribution in enumerate(contributions, start=1):
        fleche = "+" if contribution.direction == "pousse_vers_fraude" else "-"
        lignes.append(
            f"{rang}. [{fleche}{abs(contribution.shap_value):.3f}] {contribution.human_readable}"
        )
    return "\n".join(lignes)
