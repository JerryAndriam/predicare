# Workflows n8n

Phase 4 du plan d'action et chantier C4. Les workflows **versionnés** dans
`workflows/` sont la source de vérité : ils sont importables sur une machine
vierge, relus en pull request et restaurés par Git. L'interface n8n sert à les
éditer et à les exporter (`make n8n-export`), pas à les stocker.

## Les trois workflows

| Fichier | Webhook | Déclencheur | Rôle |
| --- | --- | --- | --- |
| `PK-Bascule-Modele.json` | `POST /webhook/bascule-modele` | `api-inference`, après une promotion de modèle réussie | Prévient Slack et e-mail de la bascule. Best-effort : une notification perdue ne défait pas la bascule. |
| `PK-Alerte-Fraude.json` | `POST /webhook/alerte-fraude` | Appelant externe : écran de gestion, lot du jury, test de recette | **Re-score** la facture brute via `POST /api/inference/predire`, répond le score et le SHAP, puis notifie si le score dépasse le seuil. **Ce n'est pas la cible d'api-core.** |
| `PK-Alerte-Fraude-Interne.json` | `POST /webhook/alerte-fraude-interne` | `api-core`, après une facture du parcours web au-dessus du seuil de notification | Reçoit une charge **déjà notée** (score + `rapport_shap`), ne rejoue pas l'inférence, répond 200 puis notifie Slack et e-mail. **C'est la cible de `N8N_ALERTE_WEBHOOK_URL`.** |

## Qui appelle quoi

```text
Parcours web (api-core) --POST /webhook/alerte-fraude-interne--> PK-Alerte-Fraude-Interne
        -> répond 200 immédiatement (api-core n'attend ni Slack ni SMTP)
        -> IF score >= body.seuil_notification
              vrai  -> Slack -> e-mail
              faux  -> aucune interruption humaine (facture déjà dans la file)

Appelant externe --POST /webhook/alerte-fraude--> PK-Alerte-Fraude
        -> POST /api/inference/predire (validation, score, SHAP, persistance)
        -> répond 200 (score + rapport_shap)
        -> IF score >= SEUIL_NOTIFICATION_SLACK -> Slack -> e-mail

api-inference --POST /webhook/bascule-modele--> PK-Bascule-Modele -> Slack -> e-mail
```

**Règle de câblage** : api-core ne doit **jamais** appeler `alerte-fraude`. Sa
charge n'est pas une facture mais un résultat de notation (score + SHAP) ; le
workflow `PK-Alerte-Fraude` la revaliderait comme une facture brute et
répondrait 422, puis n8n 502 — aucune notification ne partirait. Le workflow
`PK-Alerte-Fraude-Interne` est le seul qui lit `body.rapport_shap` sans
re-scorer.

### Charge envoyée par api-core

Construite par `notifier_alerte()` dans
`apps/api-core/src/predicare_core_api/notifications.py` :

```json
{
  "facture_id": "FAC-1A2B3C4D5E6F",
  "score_fraude": 0.985813,
  "seuil_applique": 0.2876,
  "seuil_notification": 0.8,
  "rapport_shap": "SHAP — ...",
  "model_version": "2",
  "assure_pseudonyme": "assr_...",
  "montant_total": 12345.0
}
```

`montant_total` est optionnel (absent si la facture ne le porte pas). Le
workflow interne ne valide pas cette charge comme une facture : il lit
directement `body.score_fraude`, `body.rapport_shap` et `body.seuil_notification`.

## Chaîne d'alerte autonome (re-score)

Le workflow `PK-Alerte-Fraude` reste utilisable seul : un appelant externe POSTe
la facture brute sur son webhook, le workflow appelle ensuite
`POST /api/inference/predire` :

```text
appelant → webhook n8n → api-inference (validation, score, SHAP, persistance)
        → réponse au client (score + rapport_shap)
        → IF score >= SEUIL_NOTIFICATION_SLACK
              vrai  → Slack → e-mail
              faux  → aucune interruption humaine (la facture reste dans la file)
```

La réponse au client part **avant** Slack et l'e-mail (`Repondre au client`) :
le score et le rapport SHAP ne dépendent pas de la disponibilité de Slack ou
du SMTP. `responseMode: responseNode` rend cette réponse déterministe ; avec
`lastNode`, elle dépendait du dernier nœud exécuté.

## Seuils : détection et notification

Deux seuils restent volontairement distincts :

- `FRAUD_ALERT_THRESHOLD` (0,2876) est le **seuil de détection** : il décide de
  l'entrée dans la file du gestionnaire et de l'écriture dans `ml.prediction`.
- le **seuil de notification** (0,8) est une **interruption humaine**,
  réservée aux cas très nets. C'est la valeur littérale du CDC (Flux 1).

Pour la chaîne web, le seuil de notification a **une seule source**, api-core,
et il est envoyé dans la charge (`seuil_notification`) :

1. `audit.parametre` clé `seuil_notification` — réglage d'exploitation, relu à
   chaque alerte, sans redémarrage ;
2. `N8N_SEUIL_NOTIFICATION` — configuration de la machine, lue au démarrage ;
3. `0,8` — valeur du CDC si rien n'est configuré.

Le résultat ne descend jamais sous le seuil de détection effectif
(`get_threshold()`, alimenté par `audit.parametre.seuil_alerte` et
`FRAUD_ALERT_THRESHOLD`) : on ne notifie pas une facture que le modèle n'a pas
retenue. Avec les valeurs du dépôt, la notification reste donc à 0,8.

Côté n8n, le nœud `Score au-dessus du seuil de notification` de
`PK-Alerte-Fraude-Interne` préfère `body.seuil_notification` et ne retombe sur
`SEUIL_NOTIFICATION_SLACK` que si le champ est absent (appel direct). Le
workflow `PK-Alerte-Fraude` (re-score) garde `SEUIL_NOTIFICATION_SLACK`, car
il ne reçoit pas de seuil dans sa facture brute.

## Chaîne de bascule de modèle (Phase 8.2)

`api-inference` appelle le webhook **après** une bascule réussie, depuis
`ModelRegistry.promote_candidate` — point de passage unique des deux chemins
(api-core et appel direct `make model-promote`). La notification est
best-effort : URL vide = désactivée, n8n injoignable = avertissement
`modele.bascule_non_notifiee`, la bascule reste appliquée.

Payload envoyé par `api-inference` :

```json
{
  "evenement": "modele.bascule",
  "version_avant": "1",
  "version_apres": "2",
  "timestamp": "2026-10-20T10:00:00+00:00",
  "acteur": "admin@predicare.local",
  "service": "api-inference"
}
```

`acteur` est le sujet du jeton administrateur, transmis par api-core via
l'en-tête `X-Acteur`. Il vaut `null` pour un appel direct au registre.

Configuration, dans `.env` :

```dotenv
N8N_BASCULE_WEBHOOK_URL=http://n8n:5678/webhook/bascule-modele
```

L'URL interne utilise le **nom du service Compose**, pas `localhost`. Après
modification, `docker compose up -d --force-recreate api-inference` (la
configuration est lue au démarrage). Le workflow doit être importé et actif ;
sinon n8n répond 404 et l'avertissement est journalisé.

## Gestion d'erreur et journalisation

### `PK-Alerte-Fraude` (re-score)

Le workflow autonome a deux branches d'erreur explicites :

| Panne | Comportement | Trace |
| --- | --- | --- |
| API d'inférence en 4xx/5xx ou injoignable | `Repondre echec inference` répond **502** avec « aucune notification n'a été envoyée », puis `Inference indisponible` arrête l'exécution. Aucun nœud Slack/e-mail n'est atteint. | `execution_entity.status = 'error'` |
| Slack en échec | L'e-mail part quand même (`continueRegularOutput`). Après l'e-mail, `Notification en echec ?` inspecte les deux résultats et `Notification en echec` arrête l'exécution. | `execution_entity.status = 'error'` |
| E-mail en échec | Même contrôle final ; Slack a déjà été tenté. | `execution_entity.status = 'error'` |

C'est la garantie « pas de notification fantôme » : les notifications sont
**en aval** de la réponse de l'inférence et de la condition de seuil. Une
facture invalide (422) ne peut pas produire d'alerte.

### `PK-Alerte-Fraude-Interne` (api-core)

Le workflow répond **200** avant Slack et l'e-mail : api-core ne doit pas
attendre un tiers pour valider un dépôt de facture déjà noté et enregistré.
Les deux canaux sont best-effort et indépendants (`continueRegularOutput`) :
une panne Slack n'empêche pas l'e-mail, et l'inverse n'annule pas la réponse
déjà envoyée. L'état final de l'exécution (`success` / `error`) et la sortie de
chaque nœud restent le journal d'exploitation ; api-core n'en dépend pas.

Le seul cas d'erreur visible côté api-core est un webhook injoignable ou un
statut HTTP non 2xx : la facture reste enregistrée, et `notifier_alerte()`
renvoie `envoye: false` avec le motif affiché au front.

Le journal d'exploitation est celui de n8n, dans sa propre base PostgreSQL
(base `n8n`). Pour suivre les deux chaînes d'alerte :

```bash
docker compose exec -T db psql -U predicare -d n8n -c \
"SELECT e.id, w.name, e.status, e.mode, e.\"startedAt\", e.\"stoppedAt\"
 FROM execution_entity e
 JOIN workflow_entity w ON w.id = e.\"workflowId\"
 WHERE w.name IN ('PK-Alerte-Fraude', 'PK-Alerte-Fraude-Interne')
 ORDER BY e.id DESC LIMIT 10;"
```

Le détail par nœud (message d'erreur, sortie Slack `{data:"ok"}`, réponse SMTP
`accepted`) est visible dans l'interface :

```text
http://localhost:5678/workflow/<id>/executions/<execution>
```

On n'écrit **pas** dans `audit.journal` depuis n8n : cela demanderait de donner
à l'outil d'orchestration un accès en écriture à la base applicative, ou un
jeton de service supplémentaire. `execution_entity` est le journal de la
chaîne d'orchestration ; `audit.journal` reste le journal métier écrit par les
API.

## Preuve de bout en bout

Prérequis :

- pile démarrée (`make up`) et Mailpit (`make up-email`) ;
- `SLACK_WEBHOOK_URL` renseigné dans `.env` (Slack → Apps → Incoming Webhooks),
  puis `docker compose up -d --force-recreate n8n` pour relire l'environnement ;
- workflows importés et actifs (`make n8n-import`).

```bash
make e2e-n8n
```

Le script `scripts/e2e_n8n.sh` vérifie, sur la pile réelle :

1. le workflow est actif et le webhook `POST /webhook/alerte-fraude` enregistré ;
2. une facture du lot F17 au-dessus du seuil répond **200** avec `score_fraude`
   et `rapport_shap` ;
3. l'e-mail réel arrive dans Mailpit avec le rapport SHAP lisible ;
4. l'exécution n8n est `success` — donc le nœud Slack a répondu 2xx, puisque
   tout échec Slack/e-mail bascule l'exécution en `error` ;
5. une facture invalide répond **502**, n'ajoute **aucun** e-mail et laisse
   l'exécution en `error` : l'échec est journalisé, sans notification fantôme.

### Vérifier le webhook interne seul (cible d'api-core)

Le script `e2e-n8n.sh` prouve le workflow autonome (`alerte-fraude`). Pour
prouver la cible réelle d'api-core, envoyer la charge que `notifier_alerte()`
construit :

```bash
curl -sS -o /tmp/alerte-interne.json -w '%{http_code}\n' \
  -X POST http://localhost:5678/webhook/alerte-fraude-interne \
  -H 'Content-Type: application/json' \
  -d '{
    "facture_id": "FAC-DEMO-INTERNE",
    "score_fraude": 0.985813,
    "seuil_applique": 0.2876,
    "seuil_notification": 0.8,
    "rapport_shap": "SHAP — variables contributives : montant_total (+0.42), acte (+0.18)",
    "model_version": "2",
    "assure_pseudonyme": "assr_demo",
    "montant_total": 12345.0
  }'
```

Attendu : **200** et `{"recu":true,"canal_slack":true|false}`. Un **422** ou
un **502** signale que l'URL pointe encore vers `alerte-fraude` (re-score)
au lieu de `alerte-fraude-interne`.

Recette du 20/10/2026 sur cette pile : `FAC-JURY-001` notée **0,985813**,
Slack `{data:"ok"}`, e-mail « Alerte fraude — FAC-JURY-001 (score 0.985813) »
avec le rapport SHAP, exécution `success`. La facture invalide (montant hors
bornes) a répondu 502, Mailpit est resté inchangé et l'exécution est passée en
`error`. La chaîne de bascule a été prouvée séparément : payload `v1 → v2`,
Slack `{data:"ok"}`, e-mail « Bascule de modèle — v1 → v2 », exécution
`success` ; un premier essai avec un corps Slack non sérialisé a produit un
`400 invalid_payload`, l'e-mail est quand même parti et l'exécution a été
marquée `error` — c'est exactement le comportement attendu de la branche
d'erreur.

Recette du 21/10/2026 sur la cible réelle d'api-core : `curl` sur
`/webhook/alerte-fraude-interne` avec la charge ci-dessus → **200**
`{"recu":true,"canal_slack":true}`, exécution n8n `success`, e-mail « Alerte
fraude — FAC-DEMO-INTERNE (score 0.985813) » reçu dans Mailpit. Deuxième
essai avec `score_fraude = 0.85` et `seuil_notification = 0.95` : l'exécution
prend la branche « Sous le seuil de notification » et **aucune** notification
ne part — preuve que n8n lit bien le seuil envoyé par api-core, et non la
variable d'environnement 0,8.

## Credentials et exploitation sur chaque poste

Les workflows ne contiennent **aucun secret**. La liste **exacte** des
credentials n8n à recréer après un import sur un nouveau poste est courte :

| Credential n8n | Type | Utilisée par | Réglage |
| --- | --- | --- | --- |
| `Mailpit (dev)` | SMTP (`smtp`) | les nœuds « Notifier par e-mail » des **trois** workflows (`PK-Alerte-Fraude`, `PK-Alerte-Fraude-Interne`, `PK-Bascule-Modele`) | Host `mailpit`, port `1025`, SSL/TLS désactivé, aucune authentification |
| *(aucune)* | Slack | les nœuds « Notifier Slack » | Le Slack passe par `SLACK_WEBHOOK_URL` dans `.env`, pas par une credential n8n : le nœud lit `$env.SLACK_WEBHOOK_URL`. |

Il n'y a donc **qu'une seule credential n8n** à recréer (`Mailpit (dev)`). En
production, créer la credential du vrai SMTP sous le même nom ou sélectionner
la nouvelle dans les trois nœuds e-mail.

### Recréer les credentials en 5 lignes

1. Renseigner `SLACK_WEBHOOK_URL` dans `.env` (Slack → Apps → Incoming Webhooks), puis `docker compose up -d --force-recreate n8n`.
2. Dans n8n : **Credentials → New → SMTP**, nommer la credential **`Mailpit (dev)`**, Host `mailpit`, Port `1025`, SSL/TLS désactivé, aucune authentification.
3. Enregistrer, puis ouvrir les **trois** workflows et sélectionner `Mailpit (dev)` dans le nœud « Notifier par e-mail » (l'import ne devine pas l'identifiant d'une credential absente).
4. `make n8n-import`, puis vérifier `docker exec predicare-n8n n8n list:workflow` → **trois** lignes.
5. Prouver la chaîne : `make e2e-n8n`, puis un `curl` sur `/webhook/alerte-fraude-interne` avec la charge d'exemple ci-dessus (réponse **200**).

Une credential n8n appartient à un **utilisateur** : elle ne se synchronise
pas par Git. La sauvegarde/restauration chiffrée est décrite dans
[`credentials/README.md`](credentials/README.md).

## Nomenclature

| Préfixe | Rôle |
| --- | --- |
| `PK` | Production — s'exécute sur données réelles |
| `Stg` | Staging — jeu de test |
| `Dev` | Développement |

## Authentification et partage

**Il n'y a pas de mot de passe n8n dans le `.env`, et c'est normal.** n8n a
supprimé l'authentification basique en version 1.x : `N8N_BASIC_AUTH_USER` et
`N8N_BASIC_AUTH_PASSWORD` ne sont plus lues. Vérifié sur le binaire 2.37.10 :
zéro occurrence de `basicAuth` dans son schéma de configuration.

| Question | Réponse |
| --- | --- |
| Qui est le propriétaire ? | Le **premier visiteur** de l'URL : n8n affiche un formulaire de création de compte |
| Le mot de passe est-il dans le `.env` ? | Non. Il est choisi par le visiteur et n'est stocké nulle part |
| Deux postes ont-ils le même compte ? | Non, chacun a le sien |
| Le mot de passe est-il partageable ? | Non. C'est un mot de passe individuel, plus sûr |

État du compte sur un poste : `make n8n-compte`. Mot de passe oublié :
`docker compose exec n8n n8n user-management:reset` — cette commande
réinitialise **l'instance entière**, workflows compris.

Le partage interne de n8n n'est pas disponible en édition Community. Le
partage se fait **par Git** :

| Acteur | Commandes |
| --- | --- |
| Celui qui modifie un workflow | `make n8n-export`, puis `git add apps/n8n && git commit && git push` |
| Les autres | Après `git pull` : `make n8n-import` (ou `make up` / `make start` pour installer uniquement les workflows absents) |

À ne pas faire : pointer plusieurs machines vers le même PostgreSQL pour
« partager » les workflows. Les exécutions et leurs identifiants sont liés au
compte propriétaire.

## Import, mise à jour et amorçage

```bash
make n8n-export   # exporte les workflows de l'interface vers apps/n8n/workflows/
make n8n-import   # installe les absents, met à jour les existants, publie
```

`make n8n-import` met à jour un workflow existant **sur place** : la CLI
n8n n'a pas de commande « remplacer », mais `import:workflow` fait un upsert
sur l'`id`. Le script lit l'`id` existant avec `n8n list:workflow` et l'injecte
dans une copie temporaire ; les fichiers versionnés restent sans `id`, car cet
identifiant change d'une machine à l'autre. Le workflow est ensuite publié et
n8n est **redémarré** : la CLI écrit en base, mais un processus déjà démarré
garde ses anciens webhooks en mémoire (sans redémarrage, le nouveau chemin
répond 404).

Avec une `N8N_API_KEY` valide, le script passe par l'API : suppression puis
recréation, publication à chaud, sans redémarrage. La clé est optionnelle ;
elle se crée dans **Settings → n8n API**. Une clé présente dans `.env` mais
non enregistrée côté n8n est détectée (401) et le script bascule sur la CLI.

`make up`, `make up-light` et `make start` utilisent `--if-missing` : ils
installent uniquement les workflows absents et ne remplacent jamais une
modification locale. Après un `git pull` qui modifie un workflow existant,
lancer explicitement `make n8n-import`.

| Situation | Ce qui se passe |
| --- | --- |
| Machine avec compte déjà créé | Les absents sont installés, les existants mis à jour par `make n8n-import` |
| Machine vierge (aucun compte) | n8n crée un propriétaire « shell » ; l'import réussit, puis la première visite revendique ce shell |
| `make restart` | `--if-missing` : idempotent, rien n'est modifié |

## Persistance

Compte, session et workflows vivent dans **PostgreSQL** (base `n8n`, volume
des données), pas dans le volume `n8ndata` (config et logs seulement).

- `make down` / `make start` / redémarrage : tout est conservé.
- `make clean` (volumes supprimés) : tout est effacé ; la première visite
  recrée le compte. Seul cas « repartir de zéro ».

## TODO

- [x] Workflow d'alerte complet, versionné et importable
- [x] Troisième workflow `PK-Alerte-Fraude-Interne` (cible d'api-core, sans re-score)
- [x] Rapport SHAP dans le message Slack et dans l'e-mail
- [x] Variante e-mail via Mailpit (`make up-email`)
- [x] Branche d'erreur et journalisation dans `execution_entity`
- [x] Webhook de rappel pour la bascule de modèle (Phase 8.2)
- [x] Preuve de bout en bout automatisée (`make e2e-n8n`)
- [x] Seuil de notification envoyé par api-core (`body.seuil_notification`),
      n8n le préfère à sa variable d'environnement
- [ ] Recréer la credential n8n `Mailpit (dev)` (et `SLACK_WEBHOOK_URL`) sur
      **chaque** poste, puis refaire `make e2e-n8n` et le `curl` du webhook
      interne sur le poste du jury

Propriétaire : Mirado
