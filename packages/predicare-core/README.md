# PrediCare - package partage

Bibliotheque transverse utilisee par les trois services API :
configuration, acces PostgreSQL, JWT et RBAC, chiffrement des identites,
journaux structures et metriques Prometheus.

Elle ne contient **aucun** code de flux metier : chaque service reste
autonome et remplacable sans toucher aux autres.

## Contenu de `src/predicare/`

| Module | Role |
| --- | --- |
| `config.py` | Settings issues de l'environnement, cachees par processus |
| `db.py` | Moteur SQLAlchemy, sessions transactionnelles, schemas `core`/`ml`/`audit` |
| `auth.py` | Argon2id pour les mots de passe, JWT HS256 pour les sessions |
| `rbac.py` | Les 4 roles du CDC et la table de permissions |
| `crypto.py` | Chiffrement de la table d'identites, pseudonymisation HMAC |
| `logging_config.py` | Journaux JSON structlog |
| `metrics.py` | Compteurs et histogrammes Prometheus |
| `schemas.py` | Contrats d'interface partages (facture, prediction, SHAP) |
| `errors.py` | Hierarchy d'exceptions metier |

## Brouillon / TODO

- [ ] Persistance des refresh tokens (actuellement un seul access token par session)
- [ ] Cache applicatif Redis dans `db.py` (pool de connexions)
- [ ] Validation du contenu des contrats vectorises a l'indexation
- [ ] Tracer de corrélation par requete (`X-Request-Id`) dans `logging_config`

Proprietaire : Jerry