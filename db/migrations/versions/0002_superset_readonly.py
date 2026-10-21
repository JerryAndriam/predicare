"""Role SQL en lecture seule pour le tableau de bord BI (Superset).

Revision ID: 0002_superset_readonly
Revises: 0001_initial
Create Date: 2026-01-02

Pourquoi une migration separee : `0001_initial` est deja appliquee sur les
instances existantes. Modifier une migration appliquee est le moyen
surement le plus rapide de desynchroniser deux installations de la meme
version du projet. Une nouvelle migration s'applique partout, y compris
la ou 0001 tourne deja.

Ce role est DELIBEREMENT distinct de `predicare_ro`, utilise par l'agent
RAG : deux briques, deux identites. Un role vole a l'agent ne donne pas
acces aux tableaux de bord, et l'inverse.
"""

from __future__ import annotations

import os

from alembic import op

revision = "0002_superset_readonly"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Le mot de passe n'est JAMAIS code en dur : il vient de l'environnement.
    mot_de_passe = os.environ.get("SUPERSET_DB_RO_PASSWORD", "")
    if not mot_de_passe:
        raise RuntimeError(
            "SUPERSET_DB_RO_PASSWORD absent. Definissez-le dans .env : le compte en "
            "lecture seule du tableau de bord BI ne peut pas etre cree sans mot de passe."
        )

    echappe = mot_de_passe.replace("'", "''")

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'superset_ro') THEN
                EXECUTE 'DROP OWNED BY superset_ro';
                EXECUTE 'DROP ROLE superset_ro';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        f"CREATE ROLE superset_ro LOGIN PASSWORD '{echappe}' "
        "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;"
    )

    op.execute("GRANT CONNECT ON DATABASE predicare TO superset_ro;")
    op.execute("GRANT USAGE ON SCHEMA core, ml TO superset_ro;")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA core TO superset_ro;")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA ml TO superset_ro;")
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA core GRANT SELECT ON TABLES TO superset_ro;
        ALTER DEFAULT PRIVILEGES IN SCHEMA ml GRANT SELECT ON TABLES TO superset_ro;
        """
    )

    # Aucun acces au schema `audit` : ni journal d'audit, ni decisions des
    # gestionnaires, ni parametres de configuration. Le tableau de bord doit
    # pouvoir mesurer la performance, pas consulter qui a fait quoi.
    op.execute("REVOKE ALL ON SCHEMA audit FROM superset_ro;")


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'superset_ro') THEN
                EXECUTE 'DROP OWNED BY superset_ro';
                EXECUTE 'DROP ROLE superset_ro';
            END IF;
        END
        $$;
        """
    )