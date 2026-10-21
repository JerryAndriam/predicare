"""Secrets de la plateforme, ecrits en base et chiffres.

Revision ID: 0009_secret
Revises: 0008_utilisateur_prestataire
Create Date: 2026-10-20

Le CDC demande que les canaux et les secrets soient modifiables SANS CODE et
SANS redemarrage. Jusqu'ici, ils venaient de l'environnement : l'ecran
d'administration pouvait les lister, pas les changer.

Cette table les rend ecrits. La valeur est CHIFFREE (Fernet, la cle
maitresse restant dans l'environnement) : la base ne doit jamais devenir le
lieu ou un secret dort en clair. La priorite de lecture est base > env :
l'environnement reste le valeur de depart, la base permet de la corriger a
l'execution, sans deploiement.

Une ecriture est journalisee dans `audit.journal` : changer un secret est un
acte d'administration, il doit se voir.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_secret"
down_revision = "0008_utilisateur_prestataire"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS core.secret (
            nom        VARCHAR(64)  NOT NULL,
            valeur     TEXT         NOT NULL,
            modifie_par VARCHAR(128),
            modifie_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT secret_pkey PRIMARY KEY (nom)
        )
        """
    )
    op.execute(
        """
        COMMENT ON TABLE core.secret IS
        'Secrets de la plateforme, chiffres (Fernet). Ecris depuis l''ecran '
        'd''administration, priorite de lecture base > environnement.'
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS core.secret")
