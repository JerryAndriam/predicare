# Configuration d'exploitation

Fichiers de configuration des services optionnels. Aucun de ces fichiers
n'est obligatoire pour que la plateforme fonctionne : ils ajoutent de la
visibilite et du pilotage.

| Dossier | Service | Commande |
| --- | --- | --- |
| `prometheus/` | Collecte des metriques | `make up-observability` |
| `grafana/` | Tableaux de bord de supervision | `make up-observability` |
| `superset/` | Pilotage decisionnel (BI) | `make up-bi` |
| `mlflow/` | Suivi des experiences ML | `make up-mlops` |
| `backup/` | Planification des sauvegardes | `make up-backup` |

## Repartition memoire

| Profil | Contenu | Services | Memoire |
| --- | --- | --- | --- |
| *(aucun)* | coeur, lance par `make up` | db, redis, 3 API, web, gateway, n8n | ~4,6 Go |
| `workers` | traitements de fond | worker-ingest, worker-ai | ~1,1 Go |
| `email` | messagerie de developpement | mailpit | ~0,1 Go |
| `bi` | pilotage decisionnel | superset (+ superset-init, superset-import one-shot) | ~0,9 Go |
| `observability` | supervision | prometheus, grafana | ~0,5 Go |
| `mlops` | suivi ML | mlflow | ~0,6 Go |
| `ops` | sauvegarde | backup | ~0,1 Go |

Deux jobs one-shot alimentent le coeur et ne tournent jamais en continu :
`migrate` (schemas + creation des bases n8n, superset et mlflow) et `seed`
(chargement des donnees). Le profil `bi` en ajoute un troisieme,
`superset-init`, qui prepare la base de metadonnees de l'outil.

## Brouillon / TODO

- [ ] Regles d'alerte Prometheus (disponibilite, latence P95, derive)
- [ ] Tableaux de bord Grafana : latence, volume, erreurs, cache semantique
- [x] Connexion BI et datasets Superset enregistres par `superset-import`
- [ ] Creer les tableaux de bord (ils s'appuient sur les datasets deja poses)
- [ ] Configuration MLflow : artefacts sur volume local

Proprietaire : Jerry
