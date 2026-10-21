"""PrediCare - bibliotheque partagee par les trois services API.

Ce package contient uniquement du code transverse : configuration, acces base,
securite, observabilite et schemas metier partages. Aucun code de flux
(Flux 1 inference, Flux 2 RAG, Flux 3 pilotage) ici : chaque service reste
autonome et remplacable independamment.
"""

__version__ = "0.1.0"
