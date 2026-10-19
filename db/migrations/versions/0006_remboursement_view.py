"""Vue `core.remboursement` pour l'outil SQL de l'agent RAG.

Revision ID: 0006_remboursement_view
Revises: 0005_schema_bi
Create Date: 2026-10-19

L'agent RAG ne dispose que de `core.facture` et `core.remboursement` dans
sa liste blanche. Or le schema ne contenait pas de table `remboursement` :
l'historique de remboursement est porte par `core.facture` (statut,
montant_pris_en_charge, date_traitement).

On expose ici une vue en lecture seule qui renomme les colonnes utiles pour
l'agent, sans dupliquer de donnees. La vue est en `core` pour respecter la
liste blanche de `sql_tool.py` et les droits du compte `predicare_ro`.
"""

from __future__ import annotations

from alembic import op

revision = "0006_remboursement_view"
down_revision = "0005_schema_bi"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE VIEW core.remboursement AS
        SELECT
            f.id            AS id,
            f.assure_id     AS assure_id,
            f.date_facture  AS date_facture,
            f.date_traitement AS date_remboursement,
            f.montant_total AS montant_total,
            f.montant_pris_en_charge AS montant_rembourse,
            f.statut        AS statut,
            f.motif_rejet   AS motif_rejet,
            f.reference     AS reference
        FROM core.facture f;
        """
    )
    op.execute("GRANT SELECT ON core.remboursement TO predicare_ro;")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS core.remboursement;")