"""Environnement Alembic : connexion issue de l'environnement applicatif.

Le schema n'est declare qu'ici, jamais dans les migrations : une migration
qui cree un schema la casse si le schema existe deja. Les migrations ne font
que creer des tables et des index.

Ce module fait deux preparations avant de jouer les migrations :
l'extension pgvector et les trois schemas applicatifs, puis les bases
annexes des briques externes (n8n, Superset, MLflow).
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import Connection, Engine, engine_from_config, pool, text

from predicare.config import get_settings
from predicare.logging_config import get_logger

logger = get_logger("migrate")

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().db_url)

target_metadata = None

#: Bases annexes creees pour les briques qui partagent l'instance
#: PostgreSQL. Elles ne font pas partie du schema applicatif : Alembic ne
#: les connait pas, seul `CREATE DATABASE` les fait exister.
BASES_AUXILIAIRES = {
    "N8N_DB_NAME": "n8n",
    "SUPERSET_DB_NAME": "superset",
    "MLFLOW_DB_NAME": "mlflow",
}


def run_migrations_offline() -> None:
    """Mode `--sql` : genere le SQL sans se connecter."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema="audit",
    )
    with context.begin_transaction():
        context.run_migrations()


def creer_bases_auxiliaires(engine: Engine) -> list[str]:
    """Cree les bases des briques externes qui partagent l'instance.

    PostgreSQL refuse `CREATE DATABASE` a l'interieur d'une transaction :
    on utilise donc une connexion dediee en AUTOCOMMIT. Sans ces bases,
    n8n, Superset et MLflow echouent au demarrage avec
    "database does not exist" et redemarrent en boucle sans raison visible.

    Idempotent : une base deja presente est ignoree.
    """
    creees: list[str] = []
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        existantes = {
            row[0]
            for row in connection.execute(
                text("SELECT datname FROM pg_database WHERE datistemplate = false")
            )
        }
        for variable, defaut in BASES_AUXILIAIRES.items():
            nom = os.getenv(variable, defaut).strip()
            if not nom or nom in existantes:
                continue
            # Le nom vient du .env : on neutralise les guillemets.
            echappe = nom.replace('"', '""')
            connection.execute(text(f'CREATE DATABASE "{echappe}"'))
            creees.append(nom)
            logger.info("base.auxiliaire.creee", base=nom)
    return creees


def _assurer_schemas(connection: Connection) -> None:
    """Cree l'extension et les trois schemas avant toute migration.

    `vector` est une extension TRUSTEE de l'image pgvector : le proprietaire
    de la base peut la creer sans etre superutilisateur. Elle doit exister
    AVANT la migration initiale, sinon la colonne `embedding` de type
    `vector` echoue et le message d'erreur ne parle que du type manquant.
    """
    connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    for schema in ("core", "ml", "audit"):
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))


def run_migrations_online() -> None:
    """Mode normal : se connecte a PostgreSQL et joue les migrations."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    # Bases annexes d'abord : elles sont creees sur l'instance, hors du
    # schema applicatif, et doivent exister avant que les services qui les
    # utilisent ne demarrent.
    creer_bases_auxiliaires(connectable)

    with connectable.connect() as connection:
        _assurer_schemas(connection)
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema="audit",
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
