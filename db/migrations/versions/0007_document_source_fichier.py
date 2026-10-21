"""Traçabilité du fichier source des segments vectorisés.

Revision ID: 0007_document_source_fichier
Revises: 0006_remboursement_view
Create Date: 2026-10-19

Le decoupage du corpus RAG produit plusieurs familles de segments (un
article, une garantie, une section de guide). Sans le nom du PDF d'origine,
il est impossible de remonter d'un segment a la piece justificative citee.
On ajoute donc une colonne nullable `source_fichier`, et on l'expose en
lecture seule au compte `predicare_ro` comme le reste de la table.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_document_source_fichier"
down_revision = "0006_remboursement_view"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_vectorise",
        sa.Column("source_fichier", sa.String(256), nullable=True),
        schema="core",
    )
    op.execute("GRANT SELECT ON core.document_vectorise TO predicare_ro;")


def downgrade() -> None:
    op.drop_column("document_vectorise", "source_fichier", schema="core")
