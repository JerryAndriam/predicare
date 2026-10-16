# Migrations de schema

Schema cree par des scripts versionnes (exigence du CDC section 5). Alembic est
lance par le job `migrate`, qui doit aboutir AVANT que les API ne demarrent.

## Fichiers

| Fichier | Role |
| --- | --- |
| `env.py` | Connexion depuis l'environnement, creation de l'extension et des schemas |
| `versions/0001_initial_schema.py` | Referentiels, facturation, ML, audit, compte `predicare_ro` |
| `versions/0002_superset_readonly.py` | Role SQL en lecture seule pour le tableau de bord BI |
| `versions/0003_enrichissement_schema.py` | Grille tarifaire, contrat de groupe, garanties par formule, ordonnances en lignes |
| `script.py.mako` | Gabarit des migrations suivantes |

La chaine est lineaire et sans branche : `0001` -> `0002` -> `0003`. Chaque
revision declare son `down_revision`, donc `alembic downgrade -1` remonte d'un
cran a chaque fois.

## Trois schemas

| Schema | Contenu |
| --- | --- |
| `core` | Referentiels, assures pseudonymises, factures, documents vectorises |
| `ml` | Predictions, explications SHAP, versions de modele, derive |
| `audit` | Journal, decisions gestionnaire, parametres, version Alembic |

**La table de version est `audit.alembic_version`, pas `public.alembic_version`.**
`env.py` fixe `version_table_schema="audit"`. La chercher dans `public` echoue
avec « relation does not exist » et donne faussement l'impression qu'aucune
migration n'a jamais tourne.

## Commandes

```bash
make migrate      # applique les migrations en attente
make db-status    # version appliquee en base contre version attendue par le code
make shell-db     # psql interactif
make db-sql Q="SELECT count(*) FROM core.facture"
```

## Pourquoi `make up` execute `migrate` via `run --rm`

`migrate` est un **one-shot** (`restart: "no"`). `docker compose up -d` ne le
relance pas : Compose reutilise le conteneur sorti tant que son `config-hash`
correspond, et ce hash couvre la definition du service (YAML, image,
environnement) -- **pas** le contenu de `./db/migrations`, qui est monte en
lecture seule.

Consequence reellement observee sur ce projet : une migration ajoutee apres le
premier demarrage n'etait jamais appliquee. La base restait en `0002` alors que
le code attendait `0003`, `migrate` sortait en code 0, et `make wait` — qui ne
verifiait que le code de sortie — concluait que la plateforme etait prete. Cinq
tables et une quarantaine de colonnes manquaient, en silence.

`make up` et `make start` lisent donc :

```
up -d db redis   ->   run --rm migrate   ->   up -d
```

`run --rm` cree un conteneur neuf a chaque fois : le defaut ne peut pas revenir.
`make db-status`, appele en fin de `make wait`, transforme une future derive en
echec visible plutot qu'en silence.

## Acces manuel a PostgreSQL

**Aucun port TCP n'est publie sur la machine.** Le reseau `core` est
`internal: true`, et Docker n'active la publication d'un port que si le
conteneur est attache a au moins un reseau **non** interne. Un
`psql localhost:55432` echoue donc en `Connection refused` : ce n'est pas une
panne. Aucun client graphique (DBeaver, pgAdmin) ne peut se connecter non plus.

Tout passe par `docker compose exec` :

```bash
make shell-db                              # psql interactif
make shell-db ROLE=predicare_ro            # meme chose en lecture seule
make db-sql Q="SELECT version_num FROM audit.alembic_version"
make db-sql FILE=analyse.sql               # fichier de l'hote, envoye sur stdin
cat rapport.sql | make db-sql              # ou directement par stdin
```

`ON_ERROR_STOP=1` est positionne par `make db-sql` : sans lui, psql continue
apres une erreur et renvoie 0, donc un script a moitie applique paraitrait
reussi.

`ROLE=predicare_ro` sert a demontrer le moindre privilege sur un cas reel : la
meme requete aboutit en `predicare` et echoue sur le schema `audit` en
`predicare_ro`.

## pgvector

L'extension est creee par `env.py` avant toute migration :

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

`core.document_vectorise.embedding` est un `vector(1536)`, la dimension devant
corderonner avec `EMBEDDING_DIMENSION` du `.env` : pgvector refuse l'insertion
d'un vecteur d'une autre dimension. L'index HNSW `ix_document_vectorise_embedding`
utilise `vector_cosine_ops`, que pgvector ne fournit que pour HNSW ou IVFFlat.

Verifier depuis la machine :

```bash
make db-sql Q="SELECT atttypmod FROM pg_attribute
               WHERE attrelid='core.document_vectorise'::regclass
                 AND attname='embedding'"
```

## Les comptes en lecture seule

Crees par les migrations, jamais a la main, et **jamais** avec un mot de passe
code en dur : ils viennent de `PREDICARE_DB_RO_PASSWORD` et
`SUPERSET_DB_RO_PASSWORD`, et la migration echoue bruyamment si la variable est
absente.

| Role | Usage | Portee |
| --- | --- | --- |
| `predicare_ro` | agent RAG | `SELECT` sur `core` et `ml` |
| `superset_ro` | tableau de bord BI | `SELECT` sur `core` et `ml`, **aucun acces a `audit`** |

Les deux benefit d'un `ALTER DEFAULT PRIVILEGES`, pose par les migrations 0001 et
0002. C'est ce qui fait qu'une table creee par une migration ulterieure est
automatiquement lisible par les deux : sans lui, un simple
`GRANT SELECT ON ALL TABLES` n'aurait couvert que les tables existantes a
l'instant ou il s'execute.

## Brouillon / TODO

- [x] Verification de derive du schema (`make db-status`, branche dans `make wait`)
- [x] Test manuel du `downgrade` de 0003 sur base jetable
- [ ] Index supplementaires mesures sur les requetes lentes
- [ ] Politique de purge du journal d'audit (Phase 9.3)
- [ ] Vue materialisee pour les indicateurs du tableau de bord

Proprietaire : Cherica
