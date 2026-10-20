"""Rattachement d'un compte professionnel de sante a un prestataire.

Revision ID: 0008_utilisateur_prestataire
Revises: 0007_document_source_fichier
Create Date: 2026-10-20

Jusqu'ici, un compte `professionnel_sante` pouvait lire TOUTES les factures de
la plateforme : le role ouvrait `facture:lire`, et la requete ne filtrait que
les assures. C'est un trou de perimetre, pas un confort d'affichage.

La colonne est nullable pour ne pas casser les comptes existants ; l'API
refuse explicitement un professionnel non rattache plutot que de lui rendre
l'historique complet. Un administrateur rattache le compte depuis l'ecran
d'administration (ou le seed de demonstration).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_utilisateur_prestataire"
down_revision = "0007_document_source_fichier"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "utilisateur",
        sa.Column(
            "prestataire_id",
            sa.Integer,
            sa.ForeignKey("core.prestataire.id"),
            nullable=True,
        ),
        schema="core",
    )
    op.create_index(
        "ix_utilisateur_prestataire_id",
        "utilisateur",
        ["prestataire_id"],
        schema="core",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_utilisateur_prestataire_id",
        table_name="utilisateur",
        schema="core",
    )
    op.drop_column("utilisateur", "prestataire_id", schema="core")
