"""Featurisation : d'une facture brute aux variables du modele.

Phase 2.2 du plan d'action. Les agregations par assure, prestataire et acte
sont calculees ici et nowhere ailleurs : le service d'inference est le seul
autorise a transformer une facture en vecteur, ce qui garantit que
l'entrainement et la production appliquent exactement la meme fonction.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from predicare.schemas import InvoiceSubmission

#: Plafonds "sains" retenus a l'entrainement. Une valeur superieure signale
#: une surconsommation ; c'est ce que le modele doit apprendre a detecter.
PLAFFOND_MENSUEL_PAR_ACTE = 4
PLAFFOND_MENSUEL_ASSURE = 2_000.0
PLAFFOND_PAR_PRESTATAIRE_JOUR = 50


@dataclass(slots=True)
class InvoiceFeatures:
    """Vecteur de variables d'une facture, aligne sur le modele."""

    values: dict[str, float] = field(default_factory=dict)

    def as_row(self, feature_names: list[str]) -> list[float]:
        """Aligne sur l'ordre attendu par le modele.

        Une variable absente vaut 0 et une variable inconnue est ignoree :
        le modele reste chargeable meme si l'on ajoute une feature.
        """
        return [float(self.values.get(name, 0.0)) for name in feature_names]

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([self.values])


def build_features(
    invoice: InvoiceSubmission,
    *,
    actes_du_mois: int = 0,
    montant_mois_assure: float = 0.0,
    actes_meme_jour: int = 1,
    actes_meme_couple_acte_ordonnance: int = 0,
) -> InvoiceFeatures:
    """Construit les variables d'une facture.

    Les quatre agregations fournies par l'appelant viennent de requetes SQL
    d'historique. Ce choix garde la fonction pure et testable : elle ne fait
    jamais d'appel base elle-meme, donc un test unitaire ne necessite pas de
    PostgreSQL.
    """
    montant_total = invoice.montant_total
    nb_lignes = len(invoice.lignes)
    quantite_totale = sum(ligne.quantite for ligne in invoice.lignes)
    montant_moyen = montant_total / nb_lignes if nb_lignes else 0.0
    montant_max = max(
        (ligne.quantite * ligne.montant_unitaire for ligne in invoice.lignes), default=0.0
    )

    ecart_prescription = max(0, actes_meme_couple_acte_ordonnance - actes_du_mois)

    values: dict[str, float] = {
        # Volume et structure
        "montant_total": montant_total,
        "montant_moyen_ligne": montant_moyen,
        "montant_max_ligne": montant_max,
        "nb_lignes": float(nb_lignes),
        "quantite_totale": float(quantite_totale),
        # Surconsommation
        "actes_du_mois": float(actes_du_mois),
        "actes_meme_jour": float(actes_meme_jour),
        "montant_mois_assure": montant_mois_assure,
        "ratio_montant_mois": (
            montant_mois_assure / PLAFFOND_MENSUEL_ASSURE if PLAFFOND_MENSUEL_ASSURE else 0.0
        ),
        "depassement_plafond_acte": float(actes_du_mois - PLAFFOND_MENSUEL_PAR_ACTE),
        "depassement_plafond_prestataire": float(actes_meme_jour - PLAFFOND_PAR_PRESTATAIRE_JOUR),
        # Coherence prescription / maladie
        "doublon_ordonnance": float(actes_meme_couple_acte_ordonnance),
        "ecart_prescription_acte": float(ecart_prescription),
        # Divers
        "diversification_actes": float(len({ligne.code_acte for ligne in invoice.lignes})),
        "ratio_quantite": (quantite_totale / nb_lignes) if nb_lignes else 0.0,
    }
    return InvoiceFeatures(values=values)
