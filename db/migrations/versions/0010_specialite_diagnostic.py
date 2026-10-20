"""Les specialites qu'un diagnostic peut designer, et leurs mots-cles.

Revision ID: 0010_specialite_diagnostic
Revises: 0009_secret
Create Date: 2026-10-20

Le CDC demande de detecter les anomalies de prescription : doublons,
inadequation entre le diagnostic et l'acte prescribe, ordonnance expiree. Les
deux premiers sont des regles serveur, pas des variables de modele : elles
doivent etre explicites, verifiables, et dire POURQUOI elles refusent.

Cette table relie une specialite clinique aux mots qui la designent dans un
diagnostic libre. Les specialites ne sont pas inventees : ce sont celles
portees par `core.acte.specialite` (CARDIOLOGIE, DERMATOLOGIE, PEDIATRIE,
DENTAIRE, ...). Seuls les mots-cles francais sont une decision humaine, et
elle est ici, versionnee, lisible et extensible.

Un diagnostic qui ne designe aucune specialite connue ne declenche aucune
regle : on refuse ce qu'on sait, on ne devine pas le reste.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_specialite_diagnostic"
down_revision = "0009_secret"
branch_labels = None
depends_on = None

#: (specialite, mot_cle) -- le mot-cle est recherche dans le diagnostic.
MOTS_CLES: tuple[tuple[str, str], ...] = (
    ("GENERALISTE", "generaliste"),
    ("GENERALISTE", "generale"),
    ("CARDIOLOGIE", "cardiologie"),
    ("CARDIOLOGIE", "cardiaque"),
    ("CARDIOLOGIE", "coeur"),
    ("DERMATOLOGIE", "dermatologie"),
    ("DERMATOLOGIE", "dermatologique"),
    ("DERMATOLOGIE", "cutanee"),
    ("PEDIATRIE", "pediatrie"),
    ("PEDIATRIE", "pediatrique"),
    ("PEDIATRIE", "enfant"),
    ("OPHTALMOLOGIE", "ophtalmologie"),
    ("OPHTALMOLOGIE", "ophtalmologique"),
    ("OPHTALMOLOGIE", "oculaire"),
    ("DENTAIRE", "dentaire"),
    ("DENTAIRE", "dentiste"),
    ("DENTAIRE", "dentition"),
    ("GYNECOLOGIE", "gynecologie"),
    ("GYNECOLOGIE", "gynecologique"),
    ("MATERNITE", "maternite"),
    ("MATERNITE", "grossesse"),
    ("MATERNITE", "accouche"),
    ("GASTRO-ENTEROLOGIE", "gastro"),
    ("GASTRO-ENTEROLOGIE", "digestif"),
    ("ENDOCRINOLOGIE", "endocrinologie"),
    ("ENDOCRINOLOGIE", "endocrino"),
    ("NEPHROLOGIE", "nephrologie"),
    ("NEPHROLOGIE", "renale"),
    ("NEUROLOGIE", "neurologie"),
    ("NEUROLOGIE", "neurologique"),
    ("ORL", "orl"),
    ("ORL", "ot rhino"),
    ("ONCOLOGIE", "oncologie"),
    ("ONCOLOGIE", "cancer"),
    ("KINESITHERAPIE", "kinesitherapie"),
    ("KINESITHERAPIE", "reeducation"),
    ("KINESITHERAPIE", "physiotherapie"),
    ("OPTIQUE", "optique"),
    ("OPTIQUE", "lunettes"),
    ("OPTIQUE", "verre"),
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS core.specialite_diagnostic (
            specialite VARCHAR(64) NOT NULL,
            mot_cle     VARCHAR(64) NOT NULL,
            CONSTRAINT specialite_diagnostic_pkey PRIMARY KEY (specialite, mot_cle)
        )
        """
    )
    op.execute(
        """
        COMMENT ON TABLE core.specialite_diagnostic IS
        'Mots-cles qui designent une specialite dans un diagnostic libre. '
        'Base de la regle d''inadequation diagnostic / acte prescrite.'
        """
    )
    for specialite, mot_cle in MOTS_CLES:
        op.execute(
            sa.text(
                """
                INSERT INTO core.specialite_diagnostic (specialite, mot_cle)
                VALUES (:specialite, :mot_cle)
                ON CONFLICT (specialite, mot_cle) DO NOTHING
                """
            ).bindparams(specialite=specialite, mot_cle=mot_cle),
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS core.specialite_diagnostic")
