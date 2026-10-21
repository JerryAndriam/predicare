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

677 tests, 18 ignores (`e2e` et acces PostgreSQL sans plateforme), execution
en environ 2 minutes. La grande majorite ne demarre ni conteneur ni base : elle
porte sur des fonctions pures ou des artefacts temporaires. Les tests qui
interrogent PostgreSQL sautent proprement quand la pile n'est pas demarree.

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
| `test_notifications.py` | Webhook n8n de bascule : URL vide, payload, timeout, jamais d'exception | Mirado |
| `test_n8n_workflow.py` | Contrat JSON des workflows : connexions, branches d'erreur, aucun secret | Mirado |
| `test_lot_jury.py` | Les 20 factures F17, rejets nommes, attentes du lot | Jerry |
| `test_derive.py` | PSI, detection de derive, persistance tolerante aux pannes de base | Mirado |
| `test_persistance_ml.py` | Aller-retour reel prediction/SHAP/seuil/rapport de derive | Jerry |

## Brouillon / TODO

- [x] `conftest.py` avec jeu de facture de reference et cle de chiffrement
- [x] Tests de validation, dont tous les cas de rejet nommes
- [x] Tests d'injection de prompt sur l'agent
- [x] Test de bascule et de retour arriere du modele
- [ ] Test de persistance apres `docker compose down` puis `up`

Proprietaire : Jerry
