# Chargement des donnees

Le jeu synthetique fourni par l'encadrement est charge dans PostgreSQL par le
job `seed`, joue automatiquement au demarrage.

## Ou deposer les fichiers

```bash
cp ~/Documents/predicare/CohorteAI_datagen/dataset/*.csv data/raw/
cp -r ~/Documents/predicare/CohorteAI_datagen/rag_corpus data/rag_corpus
make reload-data
make seed-rag
```

`data/` est gitignore : 44 Mo de donnees de sante restent hors du depot. Le
dossier `rag_corpus/` (31 PDF) alimente le RAG et n'est pas charge ici.

## Les comptes de demonstration

```bash
make comptes
```

Apres les migrations, `core.utilisateur` est **vide** : aucun mot de passe
n'est code en dur dans le depot. `make comptes` est l'etape explicite qui rend
l'interface utilisable — elle cree les quatre comptes du CDC :

| Email | Role | Dossier rattache |
| --- | --- | --- |
| `assure@predicare.local` | Assure | oui (le premier dossier de `core.assure`) |
| `pro@predicare.local` | Professionnel de sante | non |
| `gestionnaire@predicare.local` | Gestionnaire | non |
| `admin@predicare.local` | Administrateur | non |

Le mot de passe vient de `DEMO_PASSWORD` (12 caracteres minimum, Argon2id) :

- **si `DEMO_PASSWORD` est defini**, il est applique aux quatre comptes ;
- **sinon**, un mot de passe aleatoire de 24 caracteres est genere et
  **affiche UNE seule fois**. Il n'est ecrit dans aucun fichier versionne.
  Notez-le, ou fixez-le dans `.env` puis relancez `make comptes`.

La commande est idempotente : la relancer met a jour le mot de passe et le
role au lieu de creer un doublon.

> Ce mot de passe est la seule donnee d'acces dont le script d'evaluation et
> le parcours de bout en bout ont besoin. **Aucun mot de passe n'est code en
> dur dans le depot** : `scripts/e2e_rag.sh` et `tests/e2e/test_rag_parcours.py`
> exigent la variable `DEMO_PASSWORD` et s'arretent avec un message explicite
> si elle est absente.

Avant de lancer le parcours de bout en bout :

```bash
DEMO_PASSWORD='<mot-de-passe>' make comptes   # ou notez celui affiche
DEMO_PASSWORD='<mot-de-passe>' scripts/e2e_rag.sh
```

## Les 14 fichiers

| Fichier | Table | Lignes |
| --- | --- | ---: |
| `referentiel_actes.csv` | `core.acte` (`unite = 'acte'`) | 58 |
| `referentiel_medicaments.csv` | `core.acte` (`unite = 'medicament'`) | 28 |
| `prestataires.csv` | `core.prestataire` | 251 |
| `contrats.csv` | `core.contrat` | 1 500 |
| `assures.csv` | `core.assure` + `core.contrat_beneficiaire` | 4 459 |
| `identites_pii.csv` | `core.identite_chiffree` (**chiffre**) | 4 459 |
| `ordonnances.csv` | `core.ordonnance` | 47 804 |
| `ordonnance_lignes.csv` | `core.ordonnance_ligne` | 82 175 |
| `factures.csv` | `core.facture` | 84 593 |
| `lignes_facture.csv` | `core.ligne_facture` | 123 270 |
| `garanties.csv` | `core.garantie_formule` | 27 |
| `grille_tarifaire.csv` | `core.grille_tarifaire` | 3 242 |
| `labels_fraude.csv` | `ml.label_fraude` | 84 593 |
| `labels_prestataires.csv` | `ml.label_prestataire` | 251 |

Les medicaments partagent `core.acte` parce que `core.grille_tarifaire.acte_id`
les reference par la meme cle etrangere, et que la grille melange des codes
d'acte (`ACC-`, `DEN-`, `IMG-`) et des codes medicament (`MED-`). Le
discriminant est `unite`. Une table separee aurait oblige a casser cette cle.

## Indexer le corpus de contrats (RAG)

```bash
make seed-rag
```

La cible lance `python -m predicare_seed.ingest_rag --apply` dans le service
`seed`, avec le corpus monte en lecture seule. Le script :

1. vérifie si `core.document_vectorise` contient déjà des segments ;
2. découpe chaque PDF du corpus (`RAG_CORPUS_DIR`, `/data/rag_corpus` par
   défaut) en segments — un par article pour les Conditions générales, un par
   ligne du tableau des garanties pour l'article 5, un par type de soins pour
   l'article 7, un par section pour les guides réseau, un par paragraphe
   sinon ;
3. calcule les embeddings par lots de 64 et insère tout l'index dans **une
   seule transaction**.

### `--force` : reindexer

```bash
make seed-rag                    # sans effet si l'index existe déjà
docker compose run --rm seed python -m predicare_seed.ingest_rag --apply --force
```

Sans `--force`, le script **ne relit pas les PDF** et n'ouvre aucune
transaction d'écriture : il journalise `ingestion.ignoree` et sort avec
`{'segments': 0, 'ignores': <nombre>, 'force': False}`. C'est le comportement
idempotent attendu : relancer la commande après un `make up` ne duplique
rien.

Avec `--force`, l'index existant est vidé (`TRUNCATE core.document_vectorise
RESTART IDENTITY`) puis reconstruit. **La décision d'idempotence se prend
avant le découpage** : sans `--force`, aucun PDF n'est même ouvert, et un
corpus absent ou illisible ne peut pas casser un index déjà valide.

Une indexation est **atomique** : si un lot échoue (embedder indisponible,
erreur de dimension de vecteur), la transaction est annulée et aucun lot
partiel ne subsiste. Une relance sans `--force` ne prend donc jamais cet index
incomplet pour un index complet.

Le seul cas où `--force` est nécessaire : le corpus a changé (nouveau PDF,
PDF modifié), ou le **modèle d'embeddings** a changé. Des vecteurs produits
par deux modèles différents n'ont aucun sens de cosinus : le seuil de
similarité deviendrait du bruit, et la recherche remonterait des segments
sans rapport.

### `--dry-run` : inspecter sans écrire

```bash
docker compose run --rm seed python -m predicare_seed.ingest_rag --dry-run
```

Découpe le corpus, affiche le nombre de segments détectés et un exemple, sans
toucher à la base. C'est la commande à lancer en premier quand un PDF du
corpus produit un découpage inattendu.

### Pourquoi l'article 7 est segmenté par type de soins

L'article 7 des Conditions générales liste les pièces justificatives **par type
de soins** (Consultation, Pharmacie, Laboratoire, Imagerie, Hospitalisation,
Maternité, Dentaire, Optique, Kinésithérapie), sur la même page. Regroupés
dans trois segments, les neuf types se disputaient le même embedding : une
question sur l'optique obtenait un cosinus de 0,5471, sous le seuil de
similarité, et la recherche remontait d'abord le guide réseau au lieu de
l'article.

Le découpage isole donc chaque type (« Article 7 - Pièces justificatives -
Optique ») et conserve un segment pour les règles générales (validité des
ordonnances). Le cosinus du même passage passe à 0,6586, et la citation du
jeu de référence atteint 1,00. La correction porte sur le découpage, **pas**
sur le seuil de similarité.

### La colonne `source_fichier`

Chaque segment indexé porte le nom du PDF dont il est issu
(`core.document_vectorise.source_fichier`). Sans cette colonne, il est
impossible de remonter d'un passage cité à la pièce justificative d'origine :
le découpage produit plusieurs familles de segments — un article, une garantie,
une section de guide — et seul le nom du fichier les relie au contrat réel.

La colonne a été ajoutée par la migration **0007**
(`db/migrations/versions/0007_document_source_fichier.py`), sur
`core.document_vectorise`, nullable pour ne pas casser les index déjà
construits. Elle est exposée en lecture seule au compte `predicare_ro`,
comme le reste de la table : l'assistant la cite dans ses réponses.

```bash
make migrate   # applique 0007 (idempotent)
```

Un index construit **avant** la migration 0007 a des `source_fichier` nuls :
il faut le reconstruire avec `--force` pour que les citations soient
traçables jusqu'au fichier.

## Pseudonymisation

Les assures sont pseudonymises par HMAC-SHA256 (`predicare.crypto.pseudonymize`),
cle Derived de `APP_SECRET_KEY`. Le meme `assure_id` donne toujours le meme
pseudonyme, ce qui permet de relier une facture a un dossier sans jamais stocker
l'identite.

`identites_pii.csv` est le **seul** fichier nominatif du lot : nom, prenoms,
date de naissance, telephone, email, adresse, numero de CIN. Il alimente
`core.identite_chiffree` en Fernet (`IDENTITY_ENCRYPTION_KEY`) et **rien
d'autre**. Aucune de ces valeurs n'atteint une table metier — c'est l'exigence
RGPD du CDC.

## Validation avant ecriture

`predicare_seed.validation` controle le jeu **avant** le premier octet ecrit, et
n'amende rien.

Sur le jeu fourni, tout passe : zero doublon de cle primaire, zero cle
etrangere orpheline, zero inversion de dates, zero valeur numerique non
numerique.

Les valeurs manquantes ne sont **pas** des anomalies. 44 % des factures n'ont
pas d'ordonnance, parce que beaucoup d'actes n'en exigent pas ; leur taux de
fraude est meme inferieur a celui des autres. Remplacer ces NULL par une
valeur par defaut detruirait le signal que le modele doit apprendre.

Un controle qui echoue interrompt le chargement avant toute ecriture et nomme
le fichier fautif. Charger la moitie d'un jeu incoherent laisserait la base
dans un etat pire qu'une base vide : les tables paraitraient peuplees.

## Validite metier

`labels_fraude.csv` livre `est_valide` et `motif_invalidite` **vides** sur les
84 593 lignes. L'information n'est pas absente : `factures.statut` et
`factures.motif_rejet` portent 1 992 factures `REJETEE` avec l'un des huit
motifs documentes (CONTROLE_MEDICAL, PIECE_MANQUANTE_ATTESTATION,
ORDONNANCE_PERIMEE, DELAI_DE_CARENCE, HORS_PERIODE_COUVERTURE, PLAFOND_ATTEINT,
ENTENTE_PREALABLE_ABSENTE, PRODUIT_NON_REMBOURSABLE).

Le derive donc au chargement. Le neuvieme motif, `FACTURE_INVALIDE`, n'a aucune
occurrence : il qualifie la facture malformee, cas que le jury fournit et que
`apps/api-inference/validation.py` traite par schema JSON.

## Fuite de donnees : la separation tient par le schema

`statut` et `motif_rejet` sont correles a la fraude — pres de 70 % des factures
rejetees sont frauduleuses, contre 7 % des factures payees. Ces colonnes
resultent de la decision humaine de traitement et **ne doivent jamais servir de
variables au modele**.

Cette interdiction ne repose sur aucun test ni aucune table de registre, mais
sur la disposition elle-meme : `statut` et `motif_rejet` restent dans `core`,
la validite derivee atterrit dans `ml`. Le feature engineering lit `core` pour
les variables et `ml` pour la cible ; il ne peut pas les confondre sans
modifier le schema.

## Rechargement

```bash
make reload-data    # TRUNCATE RESTART IDENTITY CASCADE puis rechargement
```

Le chargement est integralement transactionnel : en cas d'erreur, la base
reste dans son etat anterieur. `RESTART IDENTITY` est indispensable — sans
lui, les sequences `SERIAL` ne repartent pas a 1 et les correspondances
construites par position designeraient des lignes inexistantes.

Le passeur utilise `COPY`, pas `INSERT` : sur 123 270 lignes de
`lignes_facture`, la difference est de plusieurs minutes a quelques secondes.

## Ordre d'insertion

Impose par les cles etrangeres :

```
acte + medicaments  ->  garantie_formule  ->  prestataire
  ->  assure  ->  contrat  ->  contrat_beneficiaire  ->  identite_chiffree
  ->  ordonnance  ->  ordonnance_ligne  ->  facture  ->  ligne_facture
  ->  grille_tarifaire  ->  label_fraude + label_prestataire
```

Six correspondances sont resolues en memoire pendant le parcours :
`assure_id`, `prestataire_id`, `contrat_id`, `ordonnance_id`, `facture_id` et le
`code` d'acte. Les cles externes sont conservees dans `core.facture.reference`,
`core.ordonnance.reference`, `core.contrat.reference` et
`core.prestataire.code`, ce qui rend le rechargement reproductible.

## Note sur la colonne `numero`

`core.contrat.numero` est `NOT NULL` **et unique** depuis 0001. Le jeu ne
fournit pas cette colonne, et `numero_police` ne convient pas : deux contrats
partagent legitimately `POL-2025-3761`. On utilise `contrat_id`, cle externe
garantie unique, et `numero_police` reste dans sa colonne dediee.

## Brouillon / TODO

- [x] Ingerer le `rag_corpus/` (31 PDF) dans `core.document_vectorise` (470 segments)
- [ ] Cas d'invalidite d'entrainement (`FACTURE_INVALIDE` n'a aucune occurrence)
- [ ] Contrat de recette sur effectifs, execute a chaque rechargement

Proprietaire : Cherica
