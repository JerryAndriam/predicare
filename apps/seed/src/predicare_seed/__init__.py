"""Chargement initial des donnees au premier demarrage.

Phase 1.2 du plan d'action. Le job est idempotent : le relancer ne duplique
rien, ce qui permet de le rejouer a chaque demarrage sans risque.

Si aucun jeu de donnees n'est present dans `/data/raw`, le job le signale et
sort en succes. Une pile qui demarre sans donnees reste exploitable pour la
demonstration : c'est preferable a un conteneur en echec au demarrage.
"""

__version__ = "0.1.0"
