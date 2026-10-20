"""Validation d'entree des factures.

Point le plus critique de la note : le jury soumet 20 factures inedites le
jour J, dont des factures invalides. Une facture malformee doit etre REJETEE
proprement, avec un message qui nomme le champ fautif. Une facture mal formee
qui passe jusqu'a l'inference produit un score faux et une alerte injustifiee,
ce qui est le pire resultat possible pour un gestionnaire.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from predicare.errors import InvalidInvoiceError
from predicare.schemas import InvoiceSubmission

#: Plafond metier d'une ligne. Les montants sont en ariary (MGA) : le
#: referentiel contient des actes jusqu'a 2 500 000 MGA et l'historique des
#: lignes jusqu'a 5 460 000 MGA. Un plafond a 10 000 rejetait donc presque
#: toutes les factures reelles.
MONTANT_MAX_SINGULIER = 10_000_000.0
QUANTITE_MAX_LIGNE = 100
DUREE_MAX_RETROACTIVE_JOURS = 365 * 2
DUREE_MAX_ANTICIPATION_JOURS = 1


def _field_error(exc: ValidationError) -> str:
    """Traduit une erreur Pydantic en message exploitable par un gestionnaire."""
    messages: list[str] = []
    for error in exc.errors():
        champ = ".".join(str(part) for part in error["loc"]) or "racine"
        messages.append(f"{champ} : {error['msg']}")
    return " ; ".join(messages)


def validate_invoice(
    payload: dict | InvoiceSubmission, *, now: datetime | None = None
) -> InvoiceSubmission:
    """Valide une facture et retourne l'objet normalise.

    Leve `InvalidInvoiceError` (422) avec un message nommant chaque champ
    fautif. Ne leve jamais d'erreur technique : une facture rejetee est un
    resultat metier normal, pas une panne.
    """
    now = now or datetime.now(UTC)

    if isinstance(payload, InvoiceSubmission):
        invoice = payload
    else:
        try:
            invoice = InvoiceSubmission.model_validate(payload)
        except ValidationError as exc:
            raise InvalidInvoiceError(
                f"Facture invalide - {_field_error(exc)}",
                details={"champs": [_field_error(exc)]},
            ) from exc

    _validate_dates(invoice, now)
    _validate_amounts(invoice)
    return invoice


def _validate_dates(invoice: InvoiceSubmission, now: datetime) -> None:
    """Coherence temporelle : une facture ne peut pas venir du futur, ni d'il y a six ans.

    Le front envoie des dates `datetime-local`, donc naives. On les normalise
    avant comparaison : sans cela, Python leve `TypeError` (naif vs conscient)
    et la facture finit en 500 au lieu d'etre notee.
    """
    problems: list[str] = []

    def _naif_utc(valeur: datetime) -> datetime:
        if valeur.tzinfo is None:
            return valeur
        return valeur.astimezone(UTC).replace(tzinfo=None)

    maintenant = _naif_utc(now)
    date_facture = _naif_utc(invoice.date_facture)

    if date_facture > maintenant + timedelta(days=DUREE_MAX_ANTICIPATION_JOURS):
        problems.append("date_facture : date dans le futur")

    if date_facture < maintenant - timedelta(days=DUREE_MAX_RETROACTIVE_JOURS):
        problems.append("date_facture : date anterieure a la duree de conservation")

    for index, ligne in enumerate(invoice.lignes):
        if _naif_utc(ligne.date_acte) > date_facture + timedelta(days=1):
            problems.append(
                f"lignes.{index}.date_acte : posterieure de plus d'un jour a la date de facture"
            )

    if problems:
        raise InvalidInvoiceError(
            f"Facture invalide - {' ; '.join(problems)}",
            details={"problemes": problems},
        )


def _validate_amounts(invoice: InvoiceSubmission) -> None:
    """Coherence des montants et des quantites."""
    problems: list[str] = []

    for index, ligne in enumerate(invoice.lignes):
        if ligne.quantite > QUANTITE_MAX_LIGNE:
            problems.append(
                f"lignes.{index}.quantite : superieure au maximum de {QUANTITE_MAX_LIGNE}"
            )
        if ligne.montant_unitaire > MONTANT_MAX_SINGULIER:
            problems.append(
                f"lignes.{index}.montant_unitaire : superieur au maximum "
                f"de {MONTANT_MAX_SINGULIER:.0f} EUR"
            )

    montant_calcule = invoice.montant_calcule
    ecart = abs(montant_calcule - invoice.montant_total)
    # Tolerance de 1 % ou 1 EUR : les barèmes comportent des arrondis.
    if montant_calcule > 0 and ecart > max(1.0, montant_calcule * 0.01):
        problems.append(
            f"montant_total : {invoice.montant_total:.2f} EUR incoherent avec le detail "
            f"des lignes ({montant_calcule:.2f} EUR)"
        )

    if problems:
        raise InvalidInvoiceError(
            f"Facture invalide - {' ; '.join(problems)}",
            details={"problemes": problems},
        )
