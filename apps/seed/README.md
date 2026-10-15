# Chargement initial des donnees

Phase 1.2 du plan d'action. Job unique, execute au premier demarrage de la
plateforme (compose depend de sa sortie reussie).

## Fonctionnement

1. Lit les CSV de `/data/raw` (dossier `./data/raw` sur l'hote).
2. Charge les referentiels (actes, prestataires) puis les assures.
3. Pseudonymise chaque assure avant ecriture : `core.assure` ne contient que
   `pseudonyme`, `annee_naissance`, `sexe`, `commune_code`. Les identites
   reelles sont chiffrees a part (Phase 1.3).
4. Idempotent (`ON CONFLICT`) : le job peut etre rejoue sans risque.

## Fichiers attendus

| Fichier | Colonnes minimales |
| --- | --- |
| `actes.csv` | `code_acte`, `libelle`, `prix_unitaire` |
| `prestataires.csv` | `id`, `nom`, `specialite` |
| `assures.csv` | `reference`, `date_naissance`, `sexe`, `commune` |
| `contrats.csv` | `id`, `assure_ref`, `niveau`, `date_debut`, `date_fin` |
| `factures.csv` | `id`, `assure_ref`, `prestataire_id`, `date`, `montant` |
| `lignes_facture.csv` | `facture_id`, `code_acte`, `quantite`, `montant_unitaire` |
| `ordonnances.csv` | `id`, `assure_ref`, `prestataire_id`, `code_acte`, `date` |
| `fraudes.csv` | `facture_id`, `label` |

## Sans donnees

Si `/data/raw` est vide ou absent, le job journalise un avertissement et
**sort en succes**. La plateforme demarre normalement, avec une base vide :
mieux vaut une base vide qu'une pile qui refuse de demarrer le jour J.

## Brouillon / TODO

- [ ] Charger `contrats.csv` et `ordonnances.csv`
- [ ] Charger `factures.csv` + `lignes_facture.csv` et creer les predictions
- [ ] Import des labels de `fraudes.csv` dans `ml.label_fraude`
- [ ] **Generateur de donnees synthetiques** (24 mois, labels d'injection
      de fraude) : a faire quand le jeu officiel n'est pas disponible
- [ ] Controles de coherence a l'import : doublons, dates, types, valeurs
      manquantes (Phase 1.4)

Proprietaire : Cherica