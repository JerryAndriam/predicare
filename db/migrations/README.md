# Migrations de schema

Schéma cree par des scripts versionnes (exigence du CDC section 5). Alembic
est lance par le job `migrate`, qui doit aboutir AVANT que les API ne
demarrent.

## Fichiers

| Fichier | Role |
| --- | --- |
| `env.py` | Connexion depuis l'environnement, creation des schemas |
| `versions/0001_initial_schema.py` | Referentiels, facturation, ML, audit, compte RO |
| `versions/0002_superset_readonly.py` | Role SQL en lecture seule pour le tableau de bord BI |
| `versions/0003_enrichissement_schema.py` | Grille tarifaire, contrat de groupe, garanties par formule, ordonnances en lignes |
| `versions/0004_referentiels.py` | Table `core.medicament`, colonnes `medicament_id`, supplement du referentiel des actes |
| `script.py.mako` | Gabarit des migrations suivantes |

La chaine est lineaire : `0001` -> `0002` -> `0003` -> `0004`.

## Actes et medicaments : deux tables, une contrainte

`0004` cree `core.medicament` a cote de `core.acte` et ajoute `medicament_id`
sur `core.ligne_facture`, `core.ordonnance_ligne` et `core.grille_tarifaire`.
`acte_id` devient facultatif, et une contrainte CHECK impose
`(acte_id IS NOT NULL) <> (medicament_id IS NOT NULL)` sur chaque ligne.

La raison est le jeu de donnees : `lignes_facture.csv` compte 61 476 lignes de
type `MEDICAMENT` sur 123 270, et la grille tarifaire melange les deux natures
sous la meme colonne `code`. Un seul tableau aurait porte deux'entites
differentes, sans rien empecher de les confondre a l'ecriture. La contrainte
rend l'erreur impossible plutot que improbable.

## Trois schemas

| Schema | Contenu |
| --- | --- |
| `core` | Referentiels, assures pseudonymises, factures, documents vectorises |
| `ml` | Predictions, explications SHAP, versions de modele, derive |
| `audit` | Journal, decisions gestionnaire, parametres, version Alembic |

## Le compte `predicare_ro`

Cree par la migration initiale : un role PostgreSQL en lecture seule, utilise
par l'agent RAG et par Superset. Le mot de passe vient de
`PREDICARE_DB_RO_PASSWORD` ; il n'est **jamais** code en dur.

## Brouillon / TODO

- [ ] Index supplementaires mesures sur les requetes lentes
- [ ] Politique de purge du journal d'audit (Phase 9.3)
- [ ] Vue materialisee pour les indicateurs du tableau de bord
- [ ] Script de verification de derive du schema en CI

Proprietaire : Cherica
