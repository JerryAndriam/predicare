# Sauvegarde et restauration

Exigence du CDC : sauvegarde quotidienne scriptee, restauration egaleeement.
Le conteneur `backup` joue `pg_dump.sh` via supercronic ; la restauration
reste une **commande explicite**.

## Fichiers

| Fichier | Role |
| --- | --- |
| `pg_dump.sh` | Sauvegarde compressee, chiffree si la cle est fournie, purge a 14 jours, verification d'integrite |
| `pg_restore.sh` | Restauration avec confirmation et sauvegarde de securite prealable ; dechiffre si necessaire |

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
3. **Le chiffrement est explicite.** Si `BACKUP_CLE_FILE` est
   defini, l'archive est chiffree en AES-256-CBC avec PBKDF2 (200 000
   iterations) ; sinon elle reste en clair. La cle ne doit pas etre stockee
   avec les archives.

## TODO

- [ ] Test de restauration complet dans la CI (restaure sur base vide)
- [ ] Documentation de la procedure de reprise apres incident majeur
- [ ] Rotation et sauvegarde de la cle de chiffrement

Proprietaire : Jerry
