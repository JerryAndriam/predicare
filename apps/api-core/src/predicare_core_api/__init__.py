"""API PrediCare - Flux 3 et socle d'exploitation.

Responsabilites : authentification et 4 roles, gestion des factures et de
leur historique, file d'alertes et decisions gestionnaire, ecran
d'administration (seuil, canaux, secrets, metriques, sante), journal
d'audit. Aucun calcul de modele ici : c'est le role de `api-inference`.
"""

__version__ = "0.1.0"

SERVICE_NAME = "api-core"
