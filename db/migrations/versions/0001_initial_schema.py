"""Schema initial PrediCare TPA.

Revision ID: 0001_initial
Revises:
Create Date: 2026-01-01

Les tables minimales exigees par le CDC section 5 :
referentiel des actes, prestataires, contrats et garanties, assures
pseudonymises, factures et lignes de facture, ordonnances, predictions,
explications SHAP, decisions des gestionnaires, documents vectorises,
journal d'audit.
"""

from __future__ import annotations

import os

import sqlalchemy as sa
import sqlalchemy.dialects.postgresql
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

#: Dimension des vecteurs. Doit correspondre a EMBEDDING_DIMENSION du .env :
#: pgvector refuse une dimension differente a l'insertion.
VECTOR_DIMENSION = 1536


def upgrade() -> None:
    # =====================================================================
    # REFERENTIELS
    # =====================================================================
    op.create_table(
        "acte",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String(20), nullable=False, unique=True),
        sa.Column("libelle", sa.String(256), nullable=False, server_default=sa.text("''")),
        sa.Column("unite", sa.String(20), nullable=False, server_default=sa.text("'acte'")),
        sa.Column("prix_unitaire", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("actif", sa.Boolean, nullable=False, server_default=sa.true()),
        schema="core",
    )

    op.create_table(
        "prestataire",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("nom", sa.String(256), nullable=False, server_default=sa.text("''")),
        sa.Column("specialite", sa.String(128), nullable=False, server_default=sa.text("''")),
        sa.Column("type", sa.String(32), nullable=False, server_default=sa.text("'liberal'")),
        sa.Column("actif", sa.Boolean, nullable=False, server_default=sa.true()),
        schema="core",
    )

    # -----------------------------------------------------------------
    # IDENTITES : table isolee et CHIFFREE (exigence RGPD du CDC).
    # C'est la SEULE table qui contient des donnees nominatives.
    # -----------------------------------------------------------------
    op.create_table(
        "identite_chiffree",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("pseudonyme", sa.String(64), nullable=False, unique=True),
        sa.Column("reference_brute_chiffree", sa.LargeBinary, nullable=False),
        sa.Column("nom_chiffre", sa.LargeBinary, nullable=True),
        sa.Column("coordonnees_chiffrees", sa.LargeBinary, nullable=True),
        sa.Column("date_naissance_chiffree", sa.LargeBinary, nullable=True),
        sa.Column("cle_chiffrement", sa.String(64), nullable=False, server_default=sa.text("'v1'")),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="core",
        comment="Identites reelles, chiffrees. Seule source d'acces nominatif.",
    )

    op.create_table(
        "assure",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("pseudonyme", sa.String(64), nullable=False, unique=True),
        sa.Column("annee_naissance", sa.SmallInteger, nullable=True),
        sa.Column("sexe", sa.String(1), nullable=True),
        sa.Column("commune_code", sa.String(16), nullable=True),
        sa.Column("actif", sa.Boolean, nullable=False, server_default=sa.true()),
        schema="core",
        comment="Aucun nominatif ici : uniquement des pseudonymes.",
    )

    op.create_table(
        "contrat",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("assure_id", sa.Integer, sa.ForeignKey("core.assure.id"), nullable=False),
        sa.Column("numero", sa.String(64), nullable=False, unique=True),
        sa.Column("niveau", sa.String(32), nullable=False, server_default=sa.text("'bronze'")),
        sa.Column("date_debut", sa.Date, nullable=False),
        sa.Column("date_fin", sa.Date, nullable=True),
        schema="core",
    )
    op.create_index("ix_contrat_assure_id", "contrat", ["assure_id"], schema="core")

    op.create_table(
        "garantie",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("contrat_id", sa.Integer, sa.ForeignKey("core.contrat.id"), nullable=False),
        sa.Column("nom", sa.String(128), nullable=False),
        sa.Column("taux_remboursement", sa.Numeric(5, 2), nullable=False),
        sa.Column("plafond_annuel", sa.Numeric(12, 2), nullable=True),
        schema="core",
    )
    op.create_index("ix_garantie_contrat_id", "garantie", ["contrat_id"], schema="core")

    # -----------------------------------------------------------------
    # FACTURATION
    # -----------------------------------------------------------------
    op.create_table(
        "facture",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("reference", sa.String(64), nullable=False, unique=True),
        sa.Column("assure_id", sa.Integer, sa.ForeignKey("core.assure.id"), nullable=False),
        sa.Column("prestataire_id", sa.Integer, sa.ForeignKey("core.prestataire.id"), nullable=False),
        sa.Column("date_facture", sa.DateTime(timezone=True), nullable=False),
        sa.Column("montant_total", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("statut", sa.String(32), nullable=False, server_default=sa.text("'recue'")),
        sa.Column("creee_le", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="core",
    )
    op.create_index("ix_facture_assure_id", "facture", ["assure_id"], schema="core")
    op.create_index("ix_facture_date", "facture", ["date_facture"], schema="core")

    op.create_table(
        "ligne_facture",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("facture_id", sa.Integer, sa.ForeignKey("core.facture.id"), nullable=False),
        sa.Column("acte_id", sa.Integer, sa.ForeignKey("core.acte.id"), nullable=False),
        sa.Column("quantite", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("montant_unitaire", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("date_acte", sa.DateTime(timezone=True), nullable=False),
        schema="core",
    )
    op.create_index("ix_ligne_facture_id", "ligne_facture", ["facture_id"], schema="core")

    op.create_table(
        "ordonnance",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("assure_id", sa.Integer, sa.ForeignKey("core.assure.id"), nullable=False),
        sa.Column("prestataire_id", sa.Integer, sa.ForeignKey("core.prestataire.id"), nullable=False),
        sa.Column("acte_id", sa.Integer, sa.ForeignKey("core.acte.id"), nullable=False),
        sa.Column("date_ordonnance", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quantite", sa.Integer, nullable=False, server_default=sa.text("1")),
        schema="core",
    )
    # Index sur (assure, acte, date) : la detection de doublon d'ordonnance
    # interroge exactement ce triplet.
    op.create_index(
        "ix_ordonnance_doublon",
        "ordonnance",
        ["assure_id", "acte_id", "date_ordonnance"],
        schema="core",
    )

    # -----------------------------------------------------------------
    # CONTRATS VECTORISES (RAG)
    # --------------------------------------------------------------------
    op.create_table(
        "document_vectorise",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("contrat_id", sa.Integer, sa.ForeignKey("core.contrat.id"), nullable=True),
        sa.Column("contrat", sa.String(256), nullable=False),
        sa.Column("article", sa.String(128), nullable=False, server_default=sa.text("'-'")),
        sa.Column("garantie", sa.String(128), nullable=False, server_default=sa.text("'-'")),
        sa.Column("texte", sa.Text, nullable=False),
        sa.Column("page", sa.Integer, nullable=True),
        sa.Column("embedding", Vector(VECTOR_DIMENSION), nullable=False),
        sa.Column("modele_embedding", sa.String(128), nullable=False, server_default=sa.text("''")),
        sa.Column("indexe_le", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="core",
    )
    # Index HNSW : pgvector ne fournit `vector_cosine_ops` que pour HNSW ou
    # IVFFlat. Sur une table de quelques milliers de segments, HNSW donne un
    # meilleur rappel que IVFFlat, qui exige de choisir `lists` a l'avance.
    op.create_index(
        "ix_document_vectorise_embedding",
        "document_vectorise",
        ["embedding"],
        schema="core",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    # -----------------------------------------------------------------
    # MACHINE LEARNING
    # -----------------------------------------------------------------
    op.create_table(
        "modele_version",
        sa.Column("version", sa.String(32), primary_key=True),
        sa.Column("statut", sa.String(16), nullable=False, server_default=sa.text("'candidat'")),
        sa.Column("artefact_path", sa.String(512), nullable=False, server_default=sa.text("''")),
        sa.Column("empreinte_donnees", sa.String(128), nullable=False, server_default=sa.text("''")),
        sa.Column("metriques", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("promu_le", sa.DateTime(timezone=True), nullable=True),
        schema="ml",
    )

    op.create_table(
        "label_fraude",
        sa.Column("facture_id", sa.Integer, sa.ForeignKey("core.facture.id"), primary_key=True),
        sa.Column("label", sa.SmallInteger, nullable=False),
        sa.Column("type_fraude", sa.String(64), nullable=True),
        schema="ml",
    )

    op.create_table(
        "prediction",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("facture_id", sa.Integer, sa.ForeignKey("core.facture.id"), nullable=False),
        sa.Column("model_version", sa.String(32), nullable=False),
        sa.Column("score_fraude", sa.Float, nullable=False),
        sa.Column("seuil_applique", sa.Float, nullable=False),
        sa.Column("is_fraud", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("statut", sa.String(32), nullable=False, server_default=sa.text("'nouvelle'")),
        sa.Column("decided_by", sa.String(128), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="ml",
    )
    # La file d'alertes trie par score decroissant : cet index evite un tri
    # a chaque appel de l'ecran gestionnaire.
    op.create_index(
        "ix_prediction_file_alertes",
        "prediction",
        ["statut", "score_fraude"],
        schema="ml",
    )
    op.create_index("ix_prediction_facture_id", "prediction", ["facture_id"], schema="ml")

    op.create_table(
        "shap_explication",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("prediction_id", sa.Integer, sa.ForeignKey("ml.prediction.id"), nullable=False),
        sa.Column("rang", sa.SmallInteger, nullable=False, server_default=sa.text("1")),
        sa.Column("feature", sa.String(128), nullable=False),
        sa.Column("valeur", sa.Float, nullable=False, server_default=sa.text("0")),
        sa.Column("shap_value", sa.Float, nullable=False, server_default=sa.text("0")),
        sa.Column("base_value", sa.Float, nullable=True),
        sa.Column("direction", sa.String(32), nullable=False, server_default=sa.text("'pousse_vers_fraude'")),
        sa.Column("libelle", sa.String(256), nullable=False, server_default=sa.text("''")),
        schema="ml",
    )
    op.create_index(
        "ix_shap_prediction_id", "shap_explication", ["prediction_id"], schema="ml"
    )

    op.create_table(
        "rapport_derive",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("calcule_le", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("fenetre_jours", sa.Integer, nullable=False, server_default=sa.text("30")),
        sa.Column("psi_global", sa.Float, nullable=False, server_default=sa.text("0")),
        sa.Column("variables_concernees", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("score_moyen_reference", sa.Float, nullable=True),
        sa.Column("score_moyen_courant", sa.Float, nullable=True),
        sa.Column("alerte", sa.Boolean, nullable=False, server_default=sa.false()),
        schema="ml",
    )

    # -----------------------------------------------------------------
    # AUDIT ET EXPLOITATION
    # -----------------------------------------------------------------
    op.create_table(
        "journal",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("acteur", sa.String(128), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("cible", sa.String(128), nullable=True),
        sa.Column("details", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="audit",
    )
    op.create_index("ix_journal_created_at", "journal", ["created_at"], schema="audit")

    op.create_table(
        "decision_gestionnaire",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("prediction_id", sa.Integer, sa.ForeignKey("ml.prediction.id"), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("commentaire", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column("decided_by", sa.String(128), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="audit",
    )

    op.create_table(
        "parametre",
        sa.Column("cle", sa.String(64), primary_key=True),
        sa.Column("valeur", sa.Text, nullable=False),
        sa.Column("modifie_par", sa.String(128), nullable=True),
        sa.Column("modifie_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="audit",
    )

    # -----------------------------------------------------------------
    # COMPTES TECHNIQUES
    # -----------------------------------------------------------------
    op.create_table(
        "utilisateur",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("assured_id", sa.Integer, sa.ForeignKey("core.assure.id"), nullable=True),
        sa.Column("display_name", sa.String(128), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
        schema="core",
    )

    # Role SQL en LECTURE SEULE utilise par l'agent RAG et par Superset.
    # Le droit de lecture reste donc declare DANS la base : un bug applicatif
    # ne peut pas transformer le compte de l'agent en compte d'ecriture.
    #
    # Le mot de passe n'est JAMAIS code en dur : il vient de l'environnement
    # (`PREDICARE_DB_RO_PASSWORD`, present dans .env.example).
    ro_password = os.environ.get("PREDICARE_DB_RO_PASSWORD", "")
    if not ro_password:
        raise RuntimeError(
            "PREDICARE_DB_RO_PASSWORD absent. Definissez-le dans .env avant de lancer "
            "les migrations : le compte en lecture seule de l'agent RAG ne peut pas "
            "etre cree avec un mot de passe par defaut."
        )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'predicare_ro') THEN
                EXECUTE 'DROP OWNED BY predicare_ro';
                EXECUTE 'DROP ROLE predicare_ro';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        f"CREATE ROLE predicare_ro LOGIN PASSWORD '{ro_password.replace(chr(39), chr(39) * 2)}' "
        "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;"
    )
    op.execute("GRANT CONNECT ON DATABASE predicare TO predicare_ro;")
    op.execute("GRANT USAGE ON SCHEMA core, ml TO predicare_ro;")
    op.execute(
        "GRANT SELECT ON ALL TABLES IN SCHEMA core TO predicare_ro;"
    )
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA ml TO predicare_ro;")
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA core GRANT SELECT ON TABLES TO predicare_ro;
        ALTER DEFAULT PRIVILEGES IN SCHEMA ml GRANT SELECT ON TABLES TO predicare_ro;
        """
    )
    # Audit : lecture seule, et seulement le journal. Le compte de l'agent ne
    # doit pas pouvoir voir les decisions des gestionnaires ni les parametres.
    op.execute("GRANT USAGE ON SCHEMA audit TO predicare_ro;")
    op.execute("GRANT SELECT ON audit.journal TO predicare_ro;")


def downgrade() -> None:
    tables_core = (
        "shap_explication",
        "document_vectorise",
        "ordonnance",
        "ligne_facture",
        "facture",
        "garantie",
        "contrat",
        "assure",
        "identite_chiffree",
        "prestataire",
        "acte",
        "utilisateur",
    )
    tables_ml = ("rapport_derive", "prediction", "label_fraude", "modele_version")
    tables_audit = ("journal", "decision_gestionnaire", "parametre")

    for table in tables_core:
        op.drop_table(table, schema="core")
    for table in tables_ml:
        op.drop_table(table, schema="ml")
    for table in tables_audit:
        op.drop_table(table, schema="audit")

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'predicare_ro') THEN
                EXECUTE 'DROP OWNED BY predicare_ro';
                EXECUTE 'DROP ROLE predicare_ro';
            END IF;
        END
        $$;
        """
    )