"""Referentiels complementaires : medicaments et lignes acte/medicament.

Revision ID: 0004_referentiels
Revises: 0003_enrichissement
Create Date: 2026-01-02

POURQUOI CETTE MIGRATION
------------------------
Le chargement reel des 14 fichiers a revele trois manques du schema. Sans
cette migration, le loader serait oblige de JETER des donnees :

1. `referentiel_medicaments.csv` n'a AUCUNE table d'accueil. Or
   `lignes_facture.csv` contient 61 476 lignes de type MEDICAMENT (la moitie
   des lignes) et `ordonnance_lignes.csv` 21 codes de medicaments. On cree
   donc `core.medicament`.

2. Une ligne de facture (ou d'ordonnance, ou une ligne de grille) est SOIT un
   acte SOIT un medicament, jamais les deux. On ajoute donc une colonne
   `medicament_id` a cote de `acte_id`, on rend `acte_id` optionnel, et on
   impose par contrainte CHECK qu'exactement l'un des deux soit rempli.

3. `core.acte` ne stockait que 5 colonnes, alors que `referentiel_actes.csv`
   en fournit 12 (categorie, specialite, tarif min/max, ordonnance requise,
   entente prealable, restrictions sexe/age). Ces champs portent des regles de
   controle (INCOHERENCE_PROFIL, ACTE_FICTIF) : les perdre reviendrait a
   supprimer des variables du futur modele.

Aucune colonne existante n'est supprimee : la migration est purement additive
(a l'exception des NULL/NOT NULL des rattachements, justifies ci-dessus).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_referentiels"
down_revision = "0003_enrichissement"
branch_labels = None
depends_on = None

#: Colonnes ajoutees a `core.acte` (issues de referentiel_actes.csv).
COLONNES_ACTE = (
    "categorie",
    "specialite",
    "tarif_min",
    "tarif_max",
    "ordonnance_requise",
    "entente_prealable",
    "sexe_requis",
    "age_min",
    "age_max",
)

#: Colonnes ajoutees a `core.contrat` (issues de contrats.csv).
COLONNES_CONTRAT = ("souscripteur_id", "date_effet_police", "statut", "nb_beneficiaires")


def upgrade() -> None:
    # =====================================================================
    # 1. REFERENTIEL DES MEDICAMENTS (nouvelle table)
    #    `remboursable` porte la regle PRODUIT_NON_REMBOURSABLE, `classe` et
    #    `chronique` servent au feature engineering de la Phase 2.
    # =====================================================================
    op.create_table(
        "medicament",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String(20), nullable=False, unique=True),
        sa.Column("libelle", sa.String(256), nullable=False, server_default=sa.text("''")),
        sa.Column("prix_reference", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("remboursable", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("classe", sa.String(64), nullable=True),
        sa.Column("chronique", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("actif", sa.Boolean, nullable=False, server_default=sa.true()),
        schema="core",
        comment="Referentiel des medicaments (codes M*), distinct des actes.",
    )

    # =====================================================================
    # 2. ENRICHISSEMENT DU REFERENTIEL DES ACTES
    # =====================================================================
    op.add_column("acte", sa.Column("categorie", sa.String(64)), schema="core")
    op.add_column("acte", sa.Column("specialite", sa.String(128)), schema="core")
    op.add_column("acte", sa.Column("tarif_min", sa.Numeric(12, 2)), schema="core")
    op.add_column("acte", sa.Column("tarif_max", sa.Numeric(12, 2)), schema="core")
    op.add_column("acte", sa.Column("ordonnance_requise", sa.Boolean), schema="core")
    op.add_column("acte", sa.Column("entente_prealable", sa.Boolean), schema="core")
    op.add_column("acte", sa.Column("sexe_requis", sa.String(8)), schema="core")
    op.add_column("acte", sa.Column("age_min", sa.SmallInteger), schema="core")
    op.add_column("acte", sa.Column("age_max", sa.SmallInteger), schema="core")

    # =====================================================================
    # 3. LIGNE DE FACTURE : acte OU medicament
    #    `num_ligne` et `libelle` viennent du fichier et sont utiles au
    #    diagnostic ; `montant_unitaire` existait deja.
    # =====================================================================
    op.add_column("ligne_facture", sa.Column("medicament_id", sa.Integer), schema="core")
    op.add_column("ligne_facture", sa.Column("num_ligne", sa.SmallInteger), schema="core")
    op.add_column("ligne_facture", sa.Column("libelle", sa.String(256)), schema="core")
    op.alter_column(
        "ligne_facture", "acte_id", existing_type=sa.Integer, nullable=True, schema="core"
    )
    op.create_foreign_key(
        "fk_ligne_facture_medicament",
        "ligne_facture",
        "medicament",
        ["medicament_id"],
        ["id"],
        source_schema="core",
        referent_schema="core",
    )
    # Exactement un des deux : jamais 0 (ligne sans code), jamais 2.
    op.create_check_constraint(
        "ck_ligne_facture_un_seul_code",
        "ligne_facture",
        "(acte_id IS NOT NULL) <> (medicament_id IS NOT NULL)",
        schema="core",
    )

    # =====================================================================
    # 4. LIGNE D'ORDONNANCE : acte OU medicament
    # =====================================================================
    op.add_column("ordonnance_ligne", sa.Column("medicament_id", sa.Integer), schema="core")
    op.alter_column(
        "ordonnance_ligne", "acte_id", existing_type=sa.Integer, nullable=True, schema="core"
    )
    op.create_foreign_key(
        "fk_ordonnance_ligne_medicament",
        "ordonnance_ligne",
        "medicament",
        ["medicament_id"],
        ["id"],
        source_schema="core",
        referent_schema="core",
    )
    op.create_check_constraint(
        "ck_ordonnance_ligne_un_seul_code",
        "ordonnance_ligne",
        "(acte_id IS NOT NULL) <> (medicament_id IS NOT NULL)",
        schema="core",
    )

    # =====================================================================
    # 5. GRILLE TARIFAIRE : le code peut etre un acte ou un medicament
    #    La contrainte d'unicite devient partielle : une par type.
    #    (En PostgreSQL, NULL est distinct de NULL : sans index partiel, deux
    #     lignes « prestataire + medicament » identiques passeraient.)
    # =====================================================================
    op.add_column("grille_tarifaire", sa.Column("medicament_id", sa.Integer), schema="core")
    op.alter_column(
        "grille_tarifaire", "acte_id", existing_type=sa.Integer, nullable=True, schema="core"
    )
    op.drop_constraint("uq_grille_prestataire_acte", "grille_tarifaire", schema="core", type_="unique")
    op.create_index(
        "uq_grille_tarifaire_acte",
        "grille_tarifaire",
        ["prestataire_id", "acte_id"],
        unique=True,
        schema="core",
        postgresql_where=sa.text("acte_id IS NOT NULL"),
    )
    op.create_index(
        "uq_grille_tarifaire_medicament",
        "grille_tarifaire",
        ["prestataire_id", "medicament_id"],
        unique=True,
        schema="core",
        postgresql_where=sa.text("medicament_id IS NOT NULL"),
    )
    op.create_foreign_key(
        "fk_grille_tarifaire_medicament",
        "grille_tarifaire",
        "medicament",
        ["medicament_id"],
        ["id"],
        source_schema="core",
        referent_schema="core",
    )
    op.create_check_constraint(
        "ck_grille_tarifaire_un_seul_code",
        "grille_tarifaire",
        "(acte_id IS NOT NULL) <> (medicament_id IS NOT NULL)",
        schema="core",
    )

    # =====================================================================
    # 6. CONTRAT : complements de contrats.csv
    # =====================================================================
    op.add_column("contrat", sa.Column("souscripteur_id", sa.String(64)), schema="core")
    op.add_column("contrat", sa.Column("date_effet_police", sa.Date), schema="core")
    op.add_column("contrat", sa.Column("statut", sa.String(32)), schema="core")
    op.add_column("contrat", sa.Column("nb_beneficiaires", sa.SmallInteger), schema="core")

    # =====================================================================
    # 7. CONTRAT_BENEFICIAIRE : lien vers l'assure principal
    # =====================================================================
    op.add_column(
        "contrat_beneficiaire", sa.Column("assure_principal_id", sa.Integer), schema="core"
    )
    op.create_foreign_key(
        "fk_contrat_benef_assure_principal",
        "contrat_beneficiaire",
        "assure",
        ["assure_principal_id"],
        ["id"],
        source_schema="core",
        referent_schema="core",
    )

    # =====================================================================
    # 8. LABEL DE FRAUDE : le detail textuel est utile a l'explication
    #    (et a la constitution du jeu de questions du RAG).
    # =====================================================================
    op.add_column("label_fraude", sa.Column("detail_fraude", sa.Text), schema="ml")


def downgrade() -> None:
    # 8. label_fraude
    op.drop_column("label_fraude", "detail_fraude", schema="ml")

    # 7. contrat_beneficiaire
    op.drop_constraint(
        "fk_contrat_benef_assure_principal", "contrat_beneficiaire", schema="core", type_="foreignkey"
    )
    op.drop_column("contrat_beneficiaire", "assure_principal_id", schema="core")

    # 6. contrat
    for nom in reversed(COLONNES_CONTRAT):
        op.drop_column("contrat", nom, schema="core")

    # 5. grille_tarifaire
    op.drop_constraint(
        "ck_grille_tarifaire_un_seul_code", "grille_tarifaire", schema="core", type_="check"
    )
    op.drop_constraint(
        "fk_grille_tarifaire_medicament", "grille_tarifaire", schema="core", type_="foreignkey"
    )
    op.drop_index("uq_grille_tarifaire_medicament", table_name="grille_tarifaire", schema="core")
    op.drop_index("uq_grille_tarifaire_acte", table_name="grille_tarifaire", schema="core")
    op.alter_column(
        "grille_tarifaire", "acte_id", existing_type=sa.Integer, nullable=False, schema="core"
    )
    op.drop_column("grille_tarifaire", "medicament_id", schema="core")
    op.create_unique_constraint(
        "uq_grille_prestataire_acte", "grille_tarifaire", ["prestataire_id", "acte_id"], schema="core"
    )

    # 4. ordonnance_ligne
    op.drop_constraint(
        "ck_ordonnance_ligne_un_seul_code", "ordonnance_ligne", schema="core", type_="check"
    )
    op.drop_constraint(
        "fk_ordonnance_ligne_medicament", "ordonnance_ligne", schema="core", type_="foreignkey"
    )
    op.alter_column(
        "ordonnance_ligne", "acte_id", existing_type=sa.Integer, nullable=False, schema="core"
    )
    op.drop_column("ordonnance_ligne", "medicament_id", schema="core")

    # 3. ligne_facture
    op.drop_constraint(
        "ck_ligne_facture_un_seul_code", "ligne_facture", schema="core", type_="check"
    )
    op.drop_constraint(
        "fk_ligne_facture_medicament", "ligne_facture", schema="core", type_="foreignkey"
    )
    op.alter_column(
        "ligne_facture", "acte_id", existing_type=sa.Integer, nullable=False, schema="core"
    )
    for nom in ("libelle", "num_ligne", "medicament_id"):
        op.drop_column("ligne_facture", nom, schema="core")

    # 2. acte
    for nom in reversed(COLONNES_ACTE):
        op.drop_column("acte", nom, schema="core")

    # 1. medicament
    op.drop_table("medicament", schema="core")
