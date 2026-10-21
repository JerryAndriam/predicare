# Sauvegarde et restauration

Exigence du CDC : sauvegarde quotidienne scriptee, restauration egaleeement.
Le conteneur `backup` joue `pg_dump.sh` via supercronic ; la restauration
reste une **commande explicite**.

## Fichiers

| Fichier | Role |
| --- | --- |
| `pg_dump.sh` | Sauvegarde compressee + purge a 14 jours + verification d'integrite |
| `pg_restore.sh` | Restauration avec confirmation et sauvegarde de securite prealable |

## Commandes

```bash
make up-backup   # demarre la planification quotidienne
make backup      # sauvegarde immediate
make backups     # liste des archives disponibles
make restore     # restaure la derniere archive (demande confirmation)
```

## Deux choix deliberes

1. **La restauration n'est jamais automatique.** Une restauration declenchee
   par une erreur de script ecraserait les donnees de la journee.
2. **`pg_dump.sh` verifie l'archive apres l'ecriture** (`gzip -t`). Une
   sauvegarde jamais relue n'est pas une sauvegarde.

## Brouillon / TODO

- [ ] Test de restauration complet dans la CI (restaure sur base vide)
- [ ] Documentation de la procedure de reprise apres incident majeur
- [ ] Chiffrement des archives au repos (etude de necessite FinOps)

Proprietaire : Jerry
