"""Droits des personnes : opposition, et traçabilite de l'effacement.

Revision ID: 0011_droits_personnes
Revises: 0010_specialite_diagnostic
Create Date: 2026-10-20

Le CDC renvoie a la conformite, et le dossier de cadrage est explicite sur
l'effacement : « supprimer la ligne d'identite rend le pseudonyme non
re-identifiable, mais les factures et predictions restent ».

Cette migration prepare le terrain :

* `core.assure.opposition` : la personne s'oppose au traitement de ses
  donnees. L'opposition n'efface rien, elle arrete la SERVITION : c'est une
  decision differente, qui ne doit pas dependre de l'effacement.
* `core.assure.efface_le` : la date de l'effacement, pour tracer ce qui a
  ete efface sans garder l'identite. La LIGNE est ensuite supprimee ; la
  colonne sert au journal d'effacement et a la preuve, pas a la conservation
  du dossier.

Le dossier de cadrage fixe aussi des DUREES de conservation (3 ans les
predictions, 10 ans les factures, 5 ans l'audit). Elles sont portees par
`audit.parametre`, pas par une colonne : une duree se change, une colonne
non.
"""

from __future__ import annotations

from alembic import op

revision = "0011_droits_personnes"
down_revision = "0010_specialite_diagnostic"
branch_labels = None
depends_on = None

DUREES = {
    "duree_conservation_predictions_ans": "3",
    "duree_conservation_factures_ans": "10",
    "duree_conservation_audit_ans": "5",
}


def upgrade() -> None:
    op.execute("ALTER TABLE core.assure ADD COLUMN IF NOT EXISTS opposition BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE core.assure ADD COLUMN IF NOT EXISTS efface_le TIMESTAMPTZ")
    op.execute(
        """
        COMMENT ON COLUMN core.assure.opposition IS
        'Opposition de la personne au traitement de ses donnees : la '
        'SERVITION est arretee, l''effacement reste une decision separee.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN core.assure.efface_le IS
        'Date de l''effacement. La ligne est ensuite supprimee : la colonne '
        'trace l''evenement, elle ne conserve pas le dossier.'
        """
    )
    for cle, valeur in DUREES.items():
        op.execute(
            f"""
            INSERT INTO audit.parametre (cle, valeur, modifie_par, modifie_at)
            VALUES ('{cle}', '{valeur}', 'migration', now())
            ON CONFLICT (cle) DO NOTHING
            """
        )


def downgrade() -> None:
    op.execute("ALTER TABLE core.assure DROP COLUMN IF EXISTS efface_le")
    op.execute("ALTER TABLE core.assure DROP COLUMN IF EXISTS opposition")
