# Suivi des expériences ML (MLflow)

Phase 2.7 du plan d'action : MLflow assure le suivi des expériences et la
traçabilité des versions de modèle.

## Démarrage

```bash
make up-mlops   # ~0,6 Go
```

Interface sur <http://localhost:5000>, artefacts écrits dans
`./artifacts/mlflow`.

## MLflow est hors du chemin d'inférence

C'est un choix structurant, à citer devant le jury.

Les artefacts servis par `api-inference` vivent dans le volume `models`,
pas dans MLflow. Conséquence : **la détection de fraude continue de
fonctionner si ce profil est arrêté**, y compris pendant la soutenance. Le
service d'inférence ne dépend donc d'aucun service externe pour répondre.

MLflow sert à deux choses seulement :

1. tracer les expériences (paramètres, métriques, seuils essayés) ;
2. garder la trace de l'empreinte des données d'entraînement.

## Brouillon / TODO

- [ ] Suivre `train.py` : une expérience par version de modèle
- [ ] Journaliser le choix du seuil et son compromis précision / rappel
- [ ] Rattacher chaque version à son empreinte de données
- [ ] Comparaison graphique des versions dans l'interface

Propriétaire : Jerry