# Chargement initial des donnees

Phases **1.2** (chargement) et **1.4** (qualite) du plan d'action. Job execute
au premier demarrage de la plateforme (compose depend de sa sortie reussie).

## Trois modules

| Module | Role | Besoin d'une base ? |
| --- | --- | --- |
| `load_initial_data.py` | Chargement des 14 CSV en base (Phase 1.2) | **Oui** (PostgreSQL) |
| `qualite_donnees.py` | Analyse, regles metier, rapport (Phase 1.4) | **Non** |
| `validation.py` | Porte d'integrite avant toute ecriture | **Non** |

`load_initial_data.py` enchaine les deux garde-fous avant d'ouvrir la moindre
transaction : `validation.py` refuse un fichier douteux, `qualite_donnees.py`
ecarte les factures invalides. Aucun ecrit n'a lieu si l'un des deux echoue.

`validation.py` relit les CSV **par lui-meme**, sans passer par
`qualite_donnees.lire_tous` : un controle qui partage le chemin de lecture du
code qu'il controle ne peut pas attraper une erreur de ce chemin. Le cout est
une seconde lecture des 44 Mo, soit quelques secondes.

## Fonctionnement

1. Lit les 14 CSV de `/data/raw` (dossier `./data/raw` sur l'hote).
2. **Valide et nettoie** (Phase 1.4) : types, valeurs manquantes, doublons,
   dates, integrite referentielle, puis les 10 regles de facture invalide.
   Les factures invalides sont **ecartees et journalisees**, jamais chargees.
3. Charge dans l'ordre des dependances : referentiels -> assures -> contrats
   -> ordonnances -> factures -> lignes -> labels.
4. Pseudonymise chaque assure (`core.assure`) ; les identites reelles sont
   chiffrees a part dans `core.identite_chiffree` (Phase 1.3).
5. Idempotent (`ON CONFLICT`) : le job peut etre rejoue sans risque.

## Fichiers attendus (jeu de l'encadrement)

Les 14 fichiers, a deposer dans `./data/raw` :

`referentiel_actes.csv`, `referentiel_medicaments.csv`, `prestataires.csv`,
`assures.csv`, `identites_pii.csv`, `contrats.csv`, `garanties.csv`,
`grille_tarifaire.csv`, `ordonnances.csv`, `ordonnance_lignes.csv`,
`factures.csv`, `lignes_facture.csv`, `labels_fraude.csv`,
`labels_prestataires.csv`.

Les deux fichiers de labels sont acceptes a la racine **ou** dans `labels/`.

## Executer le controle de qualite seul (sans base)

Depuis la racine du depot :

```powershell
$env:DATA_RAW_DIR="C:\chemin\vers\dataset"   # dossier des 14 CSV
uv run --frozen --package predicare-seed python -m predicare_seed.qualite_donnees
```

Le rapport s'ecrit dans `reports/qualite_donnees_phase1_4.md`
(surchargeable avec `$env:RAPPORT_DIR`).

> Ne pas lancer les scripts avec le Python du systeme : ils ont besoin de
> l'environnement du projet (`uv run`) et, pour le loader, d'une base en
> marche. `python load_initial_data.py` echouerait sur
> `ModuleNotFoundError: No module named 'sqlalchemy'`.

## Charger en base

```powershell
make reload-data          # demarre la base puis lance le loader (Docker)
```

## Sans donnees

Si `/data/raw` est vide ou absent, le job journalise un avertissement et
**sort en succes**. La plateforme demarre normalement, avec une base vide :
mieux vaut une base vide qu'une pile qui refuse de demarrer le jour J.

## Lot du jury (F17 du CDC)

Le CDC exige vingt factures inédites le jour J, dont des factures invalides.
Le front ne sait pas importer un lot ; le job `predicare_seed.lot_jury` porte
ce parcours côté exploitation.

Le fichier `data/seed/lot_20_factures.json` est la **source unique** :

| Cas | Nombre | Attendu |
| --- | --- | --- |
| `valide`, alerte | 7 | notée, score au-dessus du seuil, visible dans la file |
| `valide`, conforme | 8 | notée, score sous le seuil |
| `invalide:<champ>` | 5 | rejetée par l'API en nommant le champ fautif |

Le job est un **client d'api-core**, pas un chargeur SQL : il appelle
`POST /api/core/factures/soumettre`, qui valide, vérifie les référentiels,
note et persiste. Rejouer la validation dans le job créerait une seconde
vérité, et le jour J une facture acceptée par le job pourrait être refusée
par le front.

```sh
DEMO_PASSWORD='<mot-de-passe>' make comptes    # une seule fois
DEMO_PASSWORD='<mot-de-passe>' make lot-jury
make lot-jury ARGS=--dry-run                   # lecture seule
make lot-jury ARGS=--rescorer                  # rejoue les factures déjà notées
```

Le job est idempotent : une facture qui a déjà une prédiction est ignorée
(`--rescorer` lève ce filtre). Les factures invalides ne laissent aucune
trace en base, puisque la validation précède l'écriture.

Le même fichier est consommé par `tests/e2e/test_lot_jury_e2e.py`, qui vérifie le
cycle complet : notation → file d'alertes → détail SHAP → décision →
historique.

## Choisi et justifie (Phase 1.4)

- **Types** : une valeur non convertible n'est jamais inventee -> rejet.
- **Manquants** : un vide *structurel* reste `NULL` (ex. `date_radiation`) ;
  un vide *obligatoire* fait rejeter la facture ; sinon valeur par defaut.
- **Doublons** : seuls les doublons *exacts* sont supprimes. Un doublon de
  cle metier (`numero_facture`) est conserve : c'est le signal de la fraude.
- **Dates** : on distingue l'*erreur* (date impossible -> rejet) du *signal de
  fraude* (soin hors contrat, prestataire radie -> conserve tel quel).

Proprietaire : Cherica
