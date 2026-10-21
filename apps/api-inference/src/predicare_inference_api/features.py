"""Featurisation d'une facture soumise aux variables du modele.

Ce module est un ADAPTATEUR, pas une implementation. La transformation
facture -> variables vit dans `predicare.features`, dans le socle partage :
l'entrainement (`apps/ml-training`) appelle exactement la meme fonction.

C'est la seule facon de garantir la parite entre ce que le modele a appris et
ce qu'il note en production. Une variable calculee ici et la, meme formule,
diverge un jour : c'est le piege classique du "on refait la featurisation dans
le notebook". Il n'y a donc plus de code de calcul dans ce fichier, seulement
la traduction entre le schema de l'API et le type attendu par le socle.

Les quatre agregations d'historique (actes du mois, montant du mois, actes du
jour, reutilisation d'ordonnance) evoquees en Phase 2.2 ne font PAS partie du
modele servi : `models/*/features.json` contient les 32 variables de
`NOMS_FEATURES`, et aucune n'est une agregation d'historique. Les ajouter
impose un re-entrainement (v3) ET une requete d'historique a l'inference, qui
doivent arriver ensemble. En attendant, aucun historique n'entre dans le
vecteur : mieux vaut des variables absentes qu'un historique envoye a zero,
qui ferait diverger l'entrainement et la production sans que rien ne le
signale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd

from predicare.features import (
    Contrat,
    FactureBrute,
    LigneFacture,
    Ordonnance,
    Prestataire,
    Referentiels,
    calculer_features,
)
from predicare.schemas import InvoiceSubmission


@dataclass(slots=True)
class InvoiceFeatures:
    """Vecteur de variables d'une facture, aligne sur le modele."""

    values: dict[str, float] = field(default_factory=dict)
    #: References introuvables : signalees au gestionnaire plutot que cachees.
    #: Une facture qui glisse entre les mailles du referentiel doit pouvoir
    #: l'etre, sinon la qualite du referentiel se degrade en silence.
    references_manquantes: list[str] = field(default_factory=list)

    def as_row(self, feature_names: list[str]) -> list[float]:
        """Aligne sur l'ordre attendu par le modele.

        Une variable absente vaut 0 et une variable inconnue est ignoree :
        le modele reste chargeable meme si l'on ajoute une feature.
        """
        return [float(self.values.get(name, 0.0)) for name in feature_names]

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([self.values])


def _jour(valeur: datetime | date | None) -> date | None:
    if isinstance(valeur, datetime):
        return valeur.date()
    return valeur


def build_features(
    invoice: InvoiceSubmission,
    referentiels: Referentiels | None = None,
    *,
    ordonnance: Ordonnance | None = None,
    contrat: Contrat | None = None,
    prestataire: Prestataire | None = None,
    assure_annee_naissance: int | None = None,
    assure_sexe: str = "",
) -> InvoiceFeatures:
    """Construit les variables d'une facture.

    `referentiels` vient du modele charge (`referentiels.json`). Les elements
    de contexte facultatifs (ordonnance, contrat, prestataire, profil assure)
    sont resolus par l'appelant : ici, on ne fait aucun appel base, ce qui
    garde cette fonction testable sans PostgreSQL.

    Tous les arguments de contexte sont OPTIONNELS et leur defaut est neutre.
    Une facture resoumise avec un pseudonyme inconnu, une prescription
    introuvable ou un prestataire absent de la table est donc NOTEE quand
    meme, avec les variables correspondantes a leur valeur neutre. C'est le
    comportement attendu du jour J : le jury soumet 20 factures inedites,
    dont certaines referencent des entites absentes de la base.
    """
    facture = FactureBrute(
        montant_total=invoice.montant_total,
        date_facture=_jour(invoice.date_facture),
        lignes=tuple(
            LigneFacture(
                code=ligne.code_acte,
                quantite=ligne.quantite,
                montant_unitaire=ligne.montant_unitaire,
                date_acte=ligne.date_acte,
            )
            for ligne in invoice.lignes
        ),
        ordonnance=ordonnance,
        contrat=contrat,
        prestataire=prestataire,
        assure_annee_naissance=assure_annee_naissance,
        assure_sexe=assure_sexe,
        prestataire_id=invoice.prestataire_id,
    )
    valeurs = calculer_features(facture, referentiels or Referentiels())
    return InvoiceFeatures(
        values=valeurs,
        references_manquantes=list(facture.references_manquantes),
    )
