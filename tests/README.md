# Tests

Suite pytest. Le CDC exige des tests unitaires et une CI qui bloque en cas
d'echec ; les tests d'integration temoignent de la maitrise des parcours.

## Organisation

```
tests/
  conftest.py     fixtures partagees, clients de test
  e2e/            tests de bout en bout sur la pile demarree
```

## Etat actuel

212 tests, 74 % de couverture, execution en 9 secondes. Aucun ne demarre de
conteneur ni ne touche PostgreSQL : tout porte sur des fonctions pures.

## Repartition cible

| Type | Couverture | Proprietaire |
| --- | --- | --- |
| Unitaire - validation des factures | 100 % des cas de rejet | Cherica |
| Unitaire - garde-fous RAG | tous les motifs d'injection | Mirado |
| Unitaire - formation SHAP et libelles | cas nominaux | Mirado |
| Integration - API par role | les 4 parcours | Cherica |
| Integration - persistance et sauvegarde | redemarrage, restore | Jerry |

## Modules ecrits

| Fichier | Objet | Proprietaire |
| --- | --- | --- |
| `test_validation.py` | Rejets de factures invalides, le cas du jour J | Jerry |
| `test_guardrails.py` | Injection de prompt, separation instruction/donnee | Mirado |
| `test_sql_tool.py` | Liste blanche SQL, refus d'ecriture et d'injection | Mirado |
| `test_rbac.py` | Les quatre roles et la matrice de permissions | Cherica |
| `test_crypto.py` | Pseudonymisation et chiffrement des identites | Jerry |
| `test_explainability.py` | Tri SHAP, libelles, rapport lisible | Mirado |
| `test_semantic_cache.py` | Cache semantique et calcul du gain FinOps | Mirado |
| `test_health.py` | Les trois API se construisent et exposent leur supervision | Jerry |

## Brouillon / TODO

- [x] `conftest.py` avec jeu de facture de reference et cle de chiffrement
- [x] Tests de validation, dont tous les cas de rejet nommes
- [x] Tests d'injection de prompt sur l'agent
- [ ] Test de bascule et de retour arriere du modele
- [ ] Test de persistance apres `docker compose down` puis `up`

Proprietaire : Jerry
