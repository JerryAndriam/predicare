# Journaux de décision d'architecture (ADR)

Un ADR enregistre une décision d'architecture, les alternatives écartées et
la raison du choix. Le format est court et daté, jamais réécrit après coup :
on en ajoute un nouveau quand une décision change.

## Format

```markdown
# ADR-NNN : titre de la décision

Date : AAAA-MM-JJ
Statut : proposée / acceptée / remplacée par ADR-NNN

## Contexte
Quel problème résout-on ? Quelles contraintes pèsent ?

## Décision
Ce que l'on choisit, en une phrase.

## Alternatives écartées
Ce que l'on aurait pu faire, et pourquoi ce n'est pas retenu.

## Conséquences
Ce que la décision rend facile, difficile, ou impossible.
```

## Décisions déjà prises

| Réf | Décision | Conséquence principale |
| --- | --- | --- |
| ADR-001 | Une base PostgreSQL unique avec pgvector, pas de base vectorielle séparée | Sauvegarde et restauration atomiques, une seule instance à exploiter |
| ADR-002 | Trois services FastAPI alignés sur les trois flux du CDC | Chaque flux est remplaçable sans impacter les autres ; plus de code à écrire |
| ADR-003 | Les dépendances Python sont gérées par uv, avec verrou commité | Builds reproductibles au bit, une seule résolution pour tous les services |
| ADR-004 | MLflow hors du chemin d'inférence | La détection de fraude survit à l'arrêt du profil `mlops` |
| ADR-005 | Passerelle à configuration statique, sans `docker.sock` | Une surface d'attaque de moins, un routage lisible et déterministe |
| ADR-006 | Base n8n et Superset créées par le job de migration | `docker compose up` fonctionne sur une machine vierge |
| ADR-007 | Comptes SQL `predicare_ro` et `superset_ro` séparés | Un rôle volé à l'agent n'ouvre pas les tableaux de bord, et l'inverse |

## Reste à faire

- [ ] Rédiger les ADR-001 à ADR-007 au format ci-dessus.
- [ ] ADR sur le choix du seuil de décision et son compromis.
- [ ] ADR sur la réécriture du `.env` : rupture de la connexion base.
