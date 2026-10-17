"""Enrichissement du schema PrediCare TPA.

Revision ID: 0003_enrichissement
Revises: 0002_superset_readonly
Create Date: 2026-01-02

Le schema minimal de 0001 ne suffit pas a charger fidelement les 24 mois de
donnees fournies : le jeu de donnees est PLUS RICHE que les tables minimales
exigees par le CDC. Cette migration AJOUTE (elle n'efface rien) :

1. core.prestataire            : ville, adresse, convention, horaires, note...
2. core.facture                : date de soin, type, canal, montants, numero...
3. core.grille_tarifaire       (nouvelle) : tarif pratique par prestataire
4. core.contrat                : + core.contrat_beneficiaire (nouvelle)
                                 -> contrats de groupe (jusqu'a 7 personnes)
5. core.garantie_formule       (nouvelle) : regles de remboursement par formule
6. core.ordonnance             : + core.ordonnance_ligne (nouvelle)
                                 -> une ordonnance = plusieurs lignes
7. ml.label_prestataire        (nouvelle) : prestataires suspects

RAPPEL SUR LES COLONNES DE FUITE : `statut`, `motif_rejet`,
`montant_pris_en_charge` et `date_traitement` sont STOCKEES (utiles pour
l'audit et la BI) mais le modele de detection NE DOIT JAMAIS les utiliser
comme variables : elles encodent la decision humaine passee.

Les droits de lecture des comptes `predicare_ro` (agent RAG, 0001) et
`superset_ro` (BI, 0002) sont deja couverts par les `ALTER DEFAULT PRIVILEGES`
poses dans ces migrations pour les schemas core et ml : les tables creees ici
en heritent automatiquement, sans GRANT supplementaire.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_enrichissement"
down_revision = "0002_superset_readonly"
branch_labels = None
depends_on = None


#: Colonnes ajoutees a `core.prestataire` (identite et convention).
COLONNES_PRESTATAIRE = (
    "ville", "quartier", "adresse", "telephone", "numero_onm", "nif",
    "horaires", "jours_ouverture", "heure_ouverture", "heure_fermeture",
    "niveau_tarif", "note_qualite", "conventionne",
    "date_conventionnement", "date_fin_convention",
)

#: Colonnes ajoutees a `core.facture`. Celles marquees FUITE sont interdites
#: comme variables du modele.
COLONNES_FACTURE = (
    "numero_facture", "contrat_id", "ordonnance_id", "type_facture",
    "date_soin", "heure_soin", "date_reception", "canal_reception",
    "mode_reglement", "attestation_pec_id", "entente_prealable_id", "devise",
    "nb_lignes", "montant_eligible", "montant_pris_en_charge",  # FUITE
    "reste_a_charge", "motif_rejet",  # FUITE
    "date_traitement",  # FUITE
)

#: Colonnes ajoutees a `core.ordonnance` (en-tete de l'ordonnance).
COLONNES_ORDONNANCE = (
    "reference", "type_ordonnance", "validite_jours", "diagnostic",
    "renseignement_clinique",
)

#: Colonnes ajoutees a `core.contrat` (contrat de groupe).
COLONNES_CONTRAT = ("numero_police", "souscripteur", "secteur", "prime_annuelle_totale")


def upgrade() -> None:
    # =====================================================================
    # 1. PRESTATAIRE : identite, convention, horaires
    #    Sans ces colonnes, on perd la ville, le conventionnement et les
    #    dates de convention, qui servent directement a la detection.
    # =====================================================================
    op.add_column("prestataire", sa.Column("ville", sa.String(128)), schema="core")
    op.add_column("prestataire", sa.Column("quartier", sa.String(128)), schema="core")
    op.add_column("prestataire", sa.Column("adresse", sa.String(256)), schema="core")
    op.add_column("prestataire", sa.Column("telephone", sa.String(32)), schema="core")
    op.add_column("prestataire", sa.Column("numero_onm", sa.String(64)), schema="core")
    op.add_column("prestataire", sa.Column("nif", sa.String(64)), schema="core")
    op.add_column("prestataire", sa.Column("horaires", sa.String(64)), schema="core")
    op.add_column("prestataire", sa.Column("jours_ouverture", sa.String(64)), schema="core")
    op.add_column("prestataire", sa.Column("heure_ouverture", sa.String(8)), schema="core")
    op.add_column("prestataire", sa.Column("heure_fermeture", sa.String(8)), schema="core")
    op.add_column("prestataire", sa.Column("niveau_tarif", sa.String(32)), schema="core")
    op.add_column("prestataire", sa.Column("note_qualite", sa.SmallInteger), schema="core")
    op.add_column("prestataire", sa.Column("conventionne", sa.Boolean), schema="core")
    op.add_column("prestataire", sa.Column("date_conventionnement", sa.Date), schema="core")
    op.add_column("prestataire", sa.Column("date_fin_convention", sa.Date), schema="core")

    # =====================================================================
    # 2. FACTURE : la fiche complete
    # =====================================================================
    op.add_column("facture", sa.Column("numero_facture", sa.String(64)), schema="core")
    op.add_column("facture", sa.Column("contrat_id", sa.Integer), schema="core")
    op.add_column("facture", sa.Column("ordonnance_id", sa.Integer), schema="core")
    op.add_column("facture", sa.Column("type_facture", sa.String(32)), schema="core")
    op.add_column("facture", sa.Column("date_soin", sa.DateTime(timezone=True)), schema="core")
    op.add_column("facture", sa.Column("heure_soin", sa.String(8)), schema="core")
    op.add_column("facture", sa.Column("date_reception", sa.DateTime(timezone=True)), schema="core")
    op.add_column("facture", sa.Column("canal_reception", sa.String(32)), schema="core")
    op.add_column("facture", sa.Column("mode_reglement", sa.String(32)), schema="core")
    op.add_column("facture", sa.Column("attestation_pec_id", sa.String(64)), schema="core")
    op.add_column("facture", sa.Column("entente_prealable_id", sa.String(64)), schema="core")
    op.add_column("facture", sa.Column("devise", sa.String(8)), schema="core")
    op.add_column("facture", sa.Column("nb_lignes", sa.Integer), schema="core")
    op.add_column("facture", sa.Column("montant_eligible", sa.Numeric(12, 2)), schema="core")
    op.add_column("facture", sa.Column("montant_pris_en_charge", sa.Numeric(12, 2)), schema="core")
    op.add_column("facture", sa.Column("reste_a_charge", sa.Numeric(12, 2)), schema="core")
    op.add_column("facture", sa.Column("motif_rejet", sa.String(64)), schema="core")
    op.add_column("facture", sa.Column("date_traitement", sa.DateTime(timezone=True)), schema="core")

    op.create_foreign_key(
        "fk_facture_contrat", "facture", "contrat",
        ["contrat_id"], ["id"], source_schema="core", referent_schema="core",
    )
    op.create_foreign_key(
        "fk_facture_ordonnance", "facture", "ordonnance",
        ["ordonnance_id"], ["id"], source_schema="core", referent_schema="core",
    )
    # Index utiles : le decoupage temporel s'appuie sur date_soin, et la
    # recherche de doublons sur numero_facture (non unique : 553 doublons
    # volontaires dans le jeu de donnees).
    op.create_index("ix_facture_date_soin", "facture", ["date_soin"], schema="core")
    op.create_index("ix_facture_numero", "facture", ["numero_facture"], schema="core")

    # =====================================================================
    # 3. GRILLE TARIFAIRE : prix pratique par prestataire et par acte
    #    Base de la detection de surfacturation.
    # =====================================================================
    op.create_table(
        "grille_tarifaire",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("prestataire_id", sa.Integer, sa.ForeignKey("core.prestataire.id"), nullable=False),
        sa.Column("acte_id", sa.Integer, sa.ForeignKey("core.acte.id"), nullable=False),
        sa.Column("tarif_pratique", sa.Numeric(12, 2), nullable=False),
        sa.UniqueConstraint("prestataire_id", "acte_id", name="uq_grille_prestataire_acte"),
        schema="core",
    )
    op.create_index(
        "ix_grille_tarifaire_prestataire", "grille_tarifaire", ["prestataire_id"], schema="core"
    )

    # =====================================================================
    # 4. CONTRATS DE GROUPE
    #    Un contrat couvre jusqu'a 7 beneficiaires : "1 contrat = 1 assure"
    #    n'est plus tenable. On rend `assure_id` optionnel et le lien se fait
    #    par la table `contrat_beneficiaire`.
    # =====================================================================
    op.alter_column("contrat", "assure_id", existing_type=sa.Integer, nullable=True, schema="core")
    op.add_column("contrat", sa.Column("numero_police", sa.String(64)), schema="core")
    op.add_column("contrat", sa.Column("souscripteur", sa.String(256)), schema="core")
    op.add_column("contrat", sa.Column("secteur", sa.String(64)), schema="core")
    op.add_column("contrat", sa.Column("prime_annuelle_totale", sa.Numeric(12, 2)), schema="core")

    op.create_table(
        "contrat_beneficiaire",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("contrat_id", sa.Integer, sa.ForeignKey("core.contrat.id"), nullable=False),
        sa.Column("assure_id", sa.Integer, sa.ForeignKey("core.assure.id"), nullable=False),
        sa.Column("rang_beneficiaire", sa.String(32), nullable=True),
        sa.Column("date_adhesion", sa.Date, nullable=True),
        sa.Column("date_radiation", sa.Date, nullable=True),
        sa.UniqueConstraint("contrat_id", "assure_id", name="uq_contrat_beneficiaire"),
        schema="core",
    )
    op.create_index(
        "ix_contrat_beneficiaire_assure", "contrat_beneficiaire", ["assure_id"], schema="core"
    )

    # =====================================================================
    # 5. GARANTIES PAR FORMULE : regles de remboursement
    #    Les regles dependent de la formule (ESSENTIEL/CONFORT/PREMIUM) et de
    #    la categorie d'acte, pas d'un contrat precis.
    # =====================================================================
    op.create_table(
        "garantie_formule",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("formule", sa.String(32), nullable=False),
        sa.Column("categorie", sa.String(64), nullable=False),
        sa.Column("taux_remboursement", sa.Numeric(5, 2), nullable=False),
        sa.Column("plafond_annuel_categorie", sa.Numeric(12, 2), nullable=True),
        sa.Column("franchise_par_facture", sa.Numeric(12, 2), nullable=True),
        sa.Column("delai_carence_jours", sa.SmallInteger, nullable=True),
        sa.Column("plafond_annuel_global", sa.Numeric(12, 2), nullable=True),
        sa.Column("prime_annuelle_par_beneficiaire", sa.Numeric(12, 2), nullable=True),
        sa.Column("attestation_requise", sa.Boolean, nullable=True),
        sa.Column("actes_exclus", sa.Text, nullable=True),
        sa.Column("pieces_justificatives", sa.Text, nullable=True),
        sa.UniqueConstraint("formule", "categorie", name="uq_garantie_formule"),
        schema="core",
    )

    # =====================================================================
    # 6. ORDONNANCES : en-tete + N lignes
    #    `acte_id` n'est plus obligatoire sur l'en-tete : les actes sont
    #    desormais portes par les lignes.
    # =====================================================================
    op.alter_column("ordonnance", "acte_id", existing_type=sa.Integer, nullable=True, schema="core")
    op.add_column("ordonnance", sa.Column("reference", sa.String(64)), schema="core")
    op.add_column("ordonnance", sa.Column("type_ordonnance", sa.String(32)), schema="core")
    op.add_column("ordonnance", sa.Column("validite_jours", sa.SmallInteger), schema="core")
    op.add_column("ordonnance", sa.Column("diagnostic", sa.String(256)), schema="core")
    op.add_column("ordonnance", sa.Column("renseignement_clinique", sa.Text), schema="core")
    op.create_unique_constraint(
        "uq_ordonnance_reference", "ordonnance", ["reference"], schema="core"
    )

    op.create_table(
        "ordonnance_ligne",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ordonnance_id", sa.Integer, sa.ForeignKey("core.ordonnance.id"), nullable=False),
        sa.Column("num_ligne", sa.SmallInteger, nullable=False),
        sa.Column("acte_id", sa.Integer, sa.ForeignKey("core.acte.id"), nullable=False),
        sa.Column("libelle", sa.String(256), nullable=True),
        sa.Column("quantite", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("posologie", sa.String(256), nullable=True),
        sa.UniqueConstraint("ordonnance_id", "num_ligne", name="uq_ordonnance_ligne"),
        schema="core",
    )
    op.create_index(
        "ix_ordonnance_ligne_ordonnance", "ordonnance_ligne", ["ordonnance_id"], schema="core"
    )

    # =====================================================================
    # 7. LABEL PRESTATAIRE : prestataires suspects (donnee d'entrainement)
    # =====================================================================
    op.create_table(
        "label_prestataire",
        sa.Column(
            "prestataire_id", sa.Integer, sa.ForeignKey("core.prestataire.id"), primary_key=True
        ),
        sa.Column("est_suspect", sa.SmallInteger, nullable=False, server_default=sa.text("0")),
        schema="ml",
    )


def downgrade() -> None:
    # 7. label prestataire
    op.drop_table("label_prestataire", schema="ml")

    # 6. ordonnance + ordonnance_ligne
    op.drop_index("ix_ordonnance_ligne_ordonnance", table_name="ordonnance_ligne", schema="core")
    op.drop_table("ordonnance_ligne", schema="core")
    op.drop_constraint("uq_ordonnance_reference", "ordonnance", schema="core", type_="unique")
    for nom in reversed(COLONNES_ORDONNANCE):
        op.drop_column("ordonnance", nom, schema="core")
    op.alter_column("ordonnance", "acte_id", existing_type=sa.Integer, nullable=False, schema="core")

    # 5. garantie par formule
    op.drop_table("garantie_formule", schema="core")

    # 4. contrat de groupe
    op.drop_index("ix_contrat_beneficiaire_assure", table_name="contrat_beneficiaire", schema="core")
    op.drop_table("contrat_beneficiaire", schema="core")
    for nom in reversed(COLONNES_CONTRAT):
        op.drop_column("contrat", nom, schema="core")
    op.alter_column("contrat", "assure_id", existing_type=sa.Integer, nullable=False, schema="core")

    # 3. grille tarifaire
    op.drop_index("ix_grille_tarifaire_prestataire", table_name="grille_tarifaire", schema="core")
    op.drop_table("grille_tarifaire", schema="core")

    # 2. facture
    op.drop_index("ix_facture_numero", table_name="facture", schema="core")
    op.drop_index("ix_facture_date_soin", table_name="facture", schema="core")
    op.drop_constraint("fk_facture_ordonnance", "facture", schema="core", type_="foreignkey")
    op.drop_constraint("fk_facture_contrat", "facture", schema="core", type_="foreignkey")
    for nom in reversed(COLONNES_FACTURE):
        op.drop_column("facture", nom, schema="core")

    # 1. prestataire
    for nom in reversed(COLONNES_PRESTATAIRE):
        op.drop_column("prestataire", nom, schema="core")
