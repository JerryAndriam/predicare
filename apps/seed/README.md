# Chargement initial des donnees

Phases **1.2** (chargement) et **1.4** (qualite) du plan d'action. Job execute
au premier demarrage de la plateforme (compose depend de sa sortie reussie).

## Deux scripts

| Script | Role | Besoin d'une base ? |
| --- | --- | --- |
| `load_initial_data.py` | Chargement des 14 CSV en base (Phase 1.2) | **Oui** (PostgreSQL) |
| `qualite_donnees.py` | Nettoyage + validation + rapport (Phase 1.4) | **Non** |

`load_initial_data.py` appelle `qualite_donnees.py` avant d'ecrire : aucune
facture invalide n'entre en base.

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

## Choisi et justifie (Phase 1.4)

- **Types** : une valeur non convertible n'est jamais inventee -> rejet.
- **Manquants** : un vide *structurel* reste `NULL` (ex. `date_radiation`) ;
  un vide *obligatoire* fait rejeter la facture ; sinon valeur par defaut.
- **Doublons** : seuls les doublons *exacts* sont supprimes. Un doublon de
  cle metier (`numero_facture`) est conserve : c'est le signal de la fraude.
- **Dates** : on distingue l'*erreur* (date impossible -> rejet) du *signal de
  fraude* (soin hors contrat, prestataire radie -> conserve tel quel).

Proprietaire : Cherica
