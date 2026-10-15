# Pilotage decisionnel (Apache Superset)

Phase 7 du plan d'action. Superset affiche les indicateurs de pilotage :
volumes traites, montants economises, taux de detection, delai de
traitement, taux de faux positifs.

Demarrage : `make up-bi` (~0,9 Go). Interface sur <http://localhost:8088>,
identifiants dans `.env` (`SUPERSET_ADMIN_USERNAME` / `SUPERSET_ADMIN_PASSWORD`).

## Fichiers

| Fichier | Role |
| --- | --- |
| `Dockerfile` | Image mince sur `apache/superset:6.1.0` + pilote PostgreSQL |
| `superset_config.py` | Connexions, mode lecture seule, options |
| `init.sh` | Job unique : schema des metadonnees + compte administrateur |
| `register_datasets.py` | Job unique : connexion BI + 5 datasets documentes |

## Deux connexions, et il ne faut pas les confondre

| Connexion | Base | Droits | Usage |
| --- | --- | --- | --- |
| Metadonnees Superset | `superset` | lecture ecriture | comptes, dashboards, preferences |
| Source BI | `predicare` | **lecture seule** | donnees metier |

Confondre les deux est le piege principal : pointer les metadonnees sur la
connexion BI rend le demarrage impossible, et l'inverse donnerait a l'outil
de BI les droits d'ecriture sur les donnees de l'assureur.

## Trois barrieres d'ecriture

1. Le role `superset_ro` n'a aucun droit d'ecriture (migration `0002`).
2. L'URI de la source BI porte `default_transaction_read_only=on`.
3. `allow_dml=False` sur l'entree de base de donnees dans Superset.

## Brouillon / TODO

- [x] Image, configuration, compte administrateur, datasets enregistres
- [ ] Creer les tableaux de bord a partir des datasets (volumes, detection,
      montants economises, delai, faux positifs)
- [ ] Publier la connexion BI en lecture seule pour le role gestionnaire
- [ ] Documenter chaque indicateur dans le dashboard (definition, source,
      frequence de mise a jour) — les donnees sont dans `register_datasets.py`
- [ ] Alertes Superset sur depassement de seuil

Proprietaire : Jerry
