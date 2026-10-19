"""Referentiels et labels complets du jeu de donnees PrediCare TPA.

Pourquoi cette migration existe
--------------------------------
Les migrations 0001 et 0003 ont ete ecrites contre le jeu de donnees fourni
par l'encadrement, mais elles n'en couvrirent qu'une partie. Plusieurs
colonnes des CSV n'avaient nulle part ou atterrir, ce qui rendait le
chargement initial impossible a bloquer, sans erreur visible : le chargeur
cherchait `actes.csv` et `fraudes.csv` (fichiers qui n'existent pas) et faisait
`row["reference"]` sur `assures.csv`, dont la premiere colonne est `assure_id`.

Colonnes ajoutees, par besoin identifie :

- `core.acte` : le referentiel conditionne le calcul des remboursements et les
  controles metier (tarifs min/max, ordonnance obligatoire, entente prealable,
  restrictions de sexe et d'age). Sans ces colonnes, les types de fraude
  `SURFACTURATION` et `INCOHERENCE_PROFIL` ne sont pas detectables.
- `core.acte` (3 colonnes medicament) : les medicaments sont des actes au sens
  du modele -- `core.grille_tarifaire.acte_id` les reference par la meme cle
  etrangere, et le jeu contient des codes `MED-*`. Lesversible est `unite`.
  Une table separee aurait oblige a casser cette cle etrangere.
- `core.contrat.formule` : c'est la clef de jointure vers `core.garantie_formule`
  (ESSENTIEL / CONFORT / PREMIUM). Sans elle, aucun calcul de taux.
- `core.ligne_facture.num_ligne`, `type_ligne`, `libelle`, `montant` :
  `ordonnance_lignes` et `lignes_facture` sont positionnees, le montant
  distingue le total d'une ligne de son prix unitaire.
- `core.contrat.reference` : la cle externe `CTR-...`. Les trois autres cles
  externes ont deja leur colonne -- `core.facture.reference` et
  `core.ordonnance.reference` creees par 0001 et 0003, `core.prestataire.code`
  des la 0001. Sans celle-ci, `make reload-data` perdrait la correspondance des
  contrats apres un rechargement.
- `ml.label_fraude.est_valide`, `motif_invalidite`, `detail_fraude` :
  voir la section suivante.

Validite metier, et non pas "erreur de saisie"
----------------------------------------------
Dans le jeu fourni, `labels_fraude.csv` livre `est_valide` et
`motif_invalidite` vides sur les 84 593 lignes. L'information n'est pas
absente pour autant : elle est portee par `factures.statut` et
`factures.motif_rejet`, ou 1 992 factures sont `REJETEE` avec l'un des huit
motifs documentes.

On derive donc l'indicateur au chargement plutot que de le laisser NULL, ce
qui donne a la logique de rejet des cas de test reels au lieu de zero.

Ces colonnes vivent dans le schema `ml`, pas dans `core`. C'est volontaire :
le CDC distingue les donnees metier d'un fichier de labels de fraude separe,
et cette disposition empeche structurellement le feature engineering de
prendre une colonne de decision historique pour une variable explicative.

Fuite de donnees
----------------
`core.facture.statut` et `core.facture.motif_rejet` sont correles a la fraude :
pres de 70 % des factures rejetees sont frauduleuses, contre 7 % des factures
payees. Ces colonnes resultant de la decision humaine de traitement et ne
doivent JAMAIS servir de variables au modele de detection.

Cette separation est assuree par le schema, pas par une garde logique :
`statut` et `motif_rejet` restent dans `core`, la validityite derivee est dans
`ml`. Le feature engineering lit `core` pour les variables et `ml` pour la
cible.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_referentiels"
down_revision = "0003_enrichissement"
branch_labels = None
depends_on = None


#: Colonnes du referentiel des actes et des medicaments.
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
    # Les trois suivantes decrivent les medicaments, distingues par
    # `unite = 'medicament'`. Elles ne sont remplies que pour ces lignes.
    "remboursable",
    "classe_molecule",
    "chronique",
)

#: Colonnes de contrat absentes de 0001 et 0003.
COLONNES_CONTRAT = (
    "reference",
    "formule",
    "statut",
    "nb_beneficiaires",
    "date_effet_police",
)

#: Colonnes de ligne de facture. 0001 n'avait que `date_acte` et
#: `montant_unitaire`, ce qui confondait le prix unitaire du total de ligne.
COLONNES_LIGNE_FACTURE = ("num_ligne", "type_ligne", "libelle", "montant")

#: Colonnes de label completes.
COLONNES_LABEL_FRAUDE = ("detail_fraude", "est_valide", "motif_invalidite")


def upgrade() -> None:
    # =====================================================================
    # 1. REFERENTIEL DES ACTES ET DES MEDICAMENTS
    # =====================================================================
    op.add_column("acte", sa.Column("categorie", sa.String(64)), schema="core")
    op.add_column("acte", sa.Column("specialite", sa.String(128)), schema="core")
    op.add_column("acte", sa.Column("tarif_min", sa.Numeric(12, 2)), schema="core")
    op.add_column("acte", sa.Column("tarif_max", sa.Numeric(12, 2)), schema="core")
    op.add_column("acte", sa.Column("ordonnance_requise", sa.Boolean), schema="core")
    op.add_column("acte", sa.Column("entente_prealable", sa.Boolean), schema="core")
    op.add_column("acte", sa.Column("sexe_requis", sa.String(1)), schema="core")
    op.add_column("acte", sa.Column("age_min", sa.SmallInteger), schema="core")
    op.add_column("acte", sa.Column("age_max", sa.SmallInteger), schema="core")
    op.add_column("acte", sa.Column("remboursable", sa.Boolean), schema="core")
    op.add_column("acte", sa.Column("classe_molecule", sa.String(64)), schema="core")
    op.add_column("acte", sa.Column("chronique", sa.Boolean), schema="core")

    # La grille tarifaire melange actes et medicaments dans la meme colonne
    # `code`. Un index unique sur `code` garantit qu'un code ne designate
    # qu'un code et un prix de reference, sinon la comparaison tarifaire du
    # modele serait ambigue.
    op.create_index("ix_acte_code_unite", "acte", ["code", "unite"], schema="core", unique=True)

    # =====================================================================
    # 2. CONTRAT DE GROUPE : formule, statut et cle externe
    # =====================================================================
    op.add_column("contrat", sa.Column("reference", sa.String(16)), schema="core")
    op.add_column("contrat", sa.Column("formule", sa.String(32)), schema="core")
    op.add_column("contrat", sa.Column("statut", sa.String(32)), schema="core")
    op.add_column("contrat", sa.Column("nb_beneficiaires", sa.Integer), schema="core")
    op.add_column("contrat", sa.Column("date_effet_police", sa.Date), schema="core")
    op.create_index("ix_contrat_reference", "contrat", ["reference"], schema="core", unique=True)

    # =====================================================================
    # 3. ORDONNANCE : rien a ajouter
    # =====================================================================
    # `core.ordonnance.reference` existe deja, cree par 0003 avec une
    # contrainte d'unicite. Il accueille deja la cle externe `ORD-...`
    # (11 caracteres, la colonne en accepte 64). Cette section n'existe que
    # pour prevent la redondance : ajouter la colonne ici echouerait sur
    # `DuplicateColumn`, ce qui est arrive au premier essai.

    # =====================================================================
    # 4. LIGNES DE FACTURE : position dans la facture et montant total
    # =====================================================================
    for nom, type_col in (
        ("num_ligne", sa.SmallInteger()),
        ("type_ligne", sa.String(16)),
        ("libelle", sa.String(256)),
        ("montant", sa.Numeric(12, 2)),
    ):
        op.add_column("ligne_facture", sa.Column(nom, type_col), schema="core")

    # =====================================================================
    # 5. LABELS : validite metier et detail
    # =====================================================================
    op.add_column("label_fraude", sa.Column("detail_fraude", sa.Text), schema="ml")
    op.add_column("label_fraude", sa.Column("est_valide", sa.Boolean), schema="ml")
    op.add_column("label_fraude", sa.Column("motif_invalidite", sa.String(64)), schema="ml")


def downgrade() -> None:
    op.drop_column("label_fraude", "motif_invalidite", schema="ml")
    op.drop_column("label_fraude", "est_valide", schema="ml")
    op.drop_column("label_fraude", "detail_fraude", schema="ml")

    for nom in reversed(COLONNES_LIGNE_FACTURE):
        op.drop_column("ligne_facture", nom, schema="core")

    op.drop_index("ix_contrat_reference", table_name="contrat", schema="core")
    for nom in reversed(COLONNES_CONTRAT):
        op.drop_column("contrat", nom, schema="core")

    op.drop_index("ix_acte_code_unite", table_name="acte", schema="core")
    for nom in reversed(COLONNES_ACTE):
        op.drop_column("acte", nom, schema="core")
