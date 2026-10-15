"""API PrediCare - Flux 1, chaine de detection de fraude.

Une seule responsabilite : transformer une facture en score de fraude
explicable. Validation d'entree stricte, featurisation, scoring XGBoost,
valeurs SHAP, suivi de derive. Ni l'interface, ni l'agent conversationnel :
ce service doit pouvoir etre remplace ou redimensionne sans impacter les
deux autres flux.
"""

__version__ = "0.1.0"

SERVICE_NAME = "api-inference"
