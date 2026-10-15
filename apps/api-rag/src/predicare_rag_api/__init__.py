"""API PrediCare - Flux 2, assistant conversationnel agentique.

Un seul propos : repondre a une question d'assure en s'appuyant sur les
contrats PDF (pgvector) et sur son historique de remboursement (SQL en
lecture seule), avec citation des sources. La securite est structurelle :
le compte SQL est en lecture seule et filtre sur l'assure connecte cote
serveur, jamais dans le prompt.
"""

__version__ = "0.1.0"

SERVICE_NAME = "api-rag"
