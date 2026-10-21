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
| `register_dashboard.py` | Job unique : les 12 tuiles et le tableau de bord de reference |
| `preparer_embed.py` | Job unique : role invite, dashboard embedded, compte de service |

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

## Embedding dans l'application

Le tableau est aussi affiche dans `/pilotage` de l'application, sans seconde
connexion. La page React utilise `@superset-ui/embedded-sdk` et demande un
guest token court a `POST /api/core/pilotage/guest-token` ; api-core le signe
en s'authentifiant avec un compte de service dedie.

Le tableau reste accessible directement sur <http://localhost:8088> : la
passerelle route a la fois `/bi` (prefixe historique) et les chemins absolus
de Superset (`/superset`, `/static`, `/api/v1`, `/login`, `/embedded`).

| Variable | Role |
| --- | --- |
| `SUPERSET_GUEST_ROLE` | nom du role invite, en lecture seule + menus de consultation |
| `SUPERSET_GUEST_TOKEN_SECRET` | cle de signature des guest tokens (obligatoire) |
| `SUPERSET_PUBLIC_URL` | origine publique, utilisee comme audience du token |
| `SUPERSET_EMBED_ALLOWED_DOMAINS` | domaines autorises a afficher l'iframe |
| `SUPERSET_BI_SERVICE_USERNAME` / `_PASSWORD` | compte de service utilise par api-core |
| `SUPERSET_DASHBOARD_SLUG` | slug du tableau expose dans l'application |

Pourquoi un compte **Admin** pour le service : Superset classe
`can_grant_guest_token` dans `ADMIN_ONLY_PERMISSIONS`. Le compte est dedie a
cet usage et son mot de passe est distinct de `SUPERSET_ADMIN_PASSWORD`.

Le role invite recoit aussi les droits des menus de consultation : `View
query`, `View as table`, `Download` et `Drill to detail`. Ce sont des lectures
et des exports ; `Explore`, le partage par e-mail et SQL Lab restent refuses.
`View query` expose le SQL genere et `Download` permet l'export des donnees :
ces deux droits sont volontaires, et doivent etre retires de
`DROITS_INTERACTION` si le perimetre metier l'exige.

`make up-bi` execute `register_dashboard.py` puis `preparer_embed.py`. Le
second est idempotent : il recree la liste blanche du role invite, reaffecte
le tableau, et remet a jour le compte de service. Si `SUPERSET_GUEST_TOKEN_SECRET`
ou `SUPERSET_BI_SERVICE_PASSWORD` manque, le job s'arrete avec un message
explicite plutot que de creer un token avec une cle par defaut.

Diagnostic rapide :

```bash
# le tableau doit repondre 200 avec le Referer de l'application
curl -H "Referer: http://localhost:8080/pilotage" \
  "http://localhost:8080/embedded/<uuid>"

# le compte de service doit pouvoir demander un token
docker compose -f docker-compose.yml -f docker-compose.bi.yml \
  run --rm superset-dashboard
```

## Brouillon / TODO

- [x] Image, configuration, compte administrateur, datasets enregistres
- [x] Creer les tableaux de bord a partir des datasets (volumes, detection,
      montants economises, delai, faux positifs)
- [x] Publier le tableau en lecture seule dans l'application, sans seconde connexion
- [ ] Documenter chaque indicateur dans le dashboard (definition, source,
      frequence de mise a jour) — les donnees sont dans `register_datasets.py`
- [ ] Alertes Superset sur depassement de seuil

Proprietaire : Jerry
