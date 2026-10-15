# Tests

Suite pytest. Le CDC exige des tests unitaires et une CI qui bloque en cas
d'echec ; les tests d'integration temoignent de la maitrise des parcours.

## Organisation

```
tests/
  conftest.py     fixtures partagees, clients de test
  e2e/            tests de bout en bout sur la pile demarree
```

## Repartition cible

| Type | Couverture | Proprietaire |
| --- | --- | --- |
| Unitaire - validation des factures | 100 % des cas de rejet | Cherica |
| Unitaire - garde-fous RAG | tous les motifs d'injection | Mirado |
| Unitaire - formation SHAP et libelles | cas nominaux | Mirado |
| Integration - API par role | les 4 parcours | Cherica |
| Integration - persistance et sauvegarde | redemarrage, restore | Jerry |

## Brouillon / TODO

- [ ] `conftest.py` avec client httpx et base de test isolee
- [ ] Tests de validation : 20 factures inedites, dont invalides (priorite)
- [ ] Tests d'injection de prompt sur l'agent
- [ ] Test de bascule et de retour arriere du modele
- [ ] Test de persistance apres `docker compose down` puis `up`

Proprietaire : Jerry
