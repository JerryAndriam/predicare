# Migrations de schema

Schéma cree par des scripts versionnes (exigence du CDC section 5). Alembic
est lance par le job `migrate`, qui doit aboutir AVANT que les API ne
demarrent.

## Fichiers

| Fichier | Role |
| --- | --- |
| `env.py` | Connexion depuis l'environnement, creation des schemas |
| `versions/0001_initial_schema.py` | Referentiels, facturation, ML, audit, compte RO |
| `script.py.mako` | Gabarit des migrations suivantes |

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
