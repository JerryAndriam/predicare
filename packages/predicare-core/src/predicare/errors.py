"""Hierarchy d'exceptions metier.

Un client de l'API doit pouvoir distinguer, sans lire le code HTTP :
une erreur de validation (sa faute), une absence de droits (403 metier),
et une panne interne (a alerter). Chaque exception porte un code stable,
documente dans la reponse API.
"""

from __future__ import annotations

from typing import Any


class PrediCareError(Exception):
    """Erreur metier generique."""

    code = "internal_error"
    http_status = 500

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class InvalidInvoiceError(PrediCareError):
    """Facture refusee a la validation d'entree.

    Critique le jour J : le jury soumet 20 factures inedites. Le message doit
    nommer le champ fautif, sinon le gestionnaire ne peut rien corriger.
    """

    code = "invalid_invoice"
    http_status = 422


class UnauthorizedError(PrediCareError):
    code = "unauthorized"
    http_status = 401


class InvalidInputError(PrediCareError):
    """Entree refusee pour une ressource autre qu'une facture (compte, etc.)."""

    code = "invalid_input"
    http_status = 422


class ForbiddenError(PrediCareError):
    """Role insuffisant, ou tentative d'acces aux donnees d'un autre assure."""

    code = "forbidden"
    http_status = 403


class NotFoundError(PrediCareError):
    code = "not_found"
    http_status = 404


class ConflictError(PrediCareError):
    """Ressource deja existante (adresse e-mail deja utilisee)."""

    code = "conflict"
    http_status = 409


class ModelNotReadyError(PrediCareError):
    """Aucun modele actif, ou bascule impossible."""

    code = "model_not_ready"
    http_status = 503


class DataAccessError(PrediCareError):
    """Acces SQL refuse : le compte est en lecture seule par construction."""

    code = "data_access_denied"
    http_status = 403


class PromptInjectionError(PrediCareError):
    """Entree utilisateur detectee comme tentative d'injection de prompt."""

    code = "prompt_injection_detected"
    http_status = 400
