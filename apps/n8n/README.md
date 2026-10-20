# Workflows n8n

Phase 4 du plan d'action et chantier C4. Les workflows **versionnés** dans
`workflows/` sont la source de vérité : ils sont importables sur une machine
vierge, relus en pull request et restaurés par Git. L'interface n8n sert à les
éditer et à les exporter (`make n8n-export`), pas à les stocker.

## Les deux workflows

| Fichier | Webhook | Rôle |
| --- | --- | --- |
| `PK-Alerte-Fraude.json` | `POST /webhook/alerte-fraude` | Note une facture, répond le score et le rapport SHAP, puis notifie Slack et e-mail si le score dépasse le seuil de notification. |
| `PK-Bascule-Modele.json` | `POST /webhook/bascule-modele` | Prévient Slack et e-mail après une bascule de modèle réussie. Appelé par `api-inference`. |

## Chaîne d'alerte (Flux 1)

Le déclencheur est un appelant externe — écran de gestion, lot du jury, test
de recette — qui POSTe la facture brute sur le webhook n8n. Le workflow appelle
ensuite `POST /api/inference/predire` :

```text
appelant → webhook n8n → api-inference (validation, score, SHAP, persistance)
        → réponse au client (score + rapport_shap)
        → IF score >= SEUIL_NOTIFICATION_SLACK
              vrai  → Slack → e-mail
              faux  → aucune interruption humaine (la facture reste dans la file)
```

Deux seuils sont volontairement distincts :

- `FRAUD_ALERT_THRESHOLD` (0,2876) est le **seuil de détection** : il décide de
  l'entrée dans la file du gestionnaire et de l'écriture dans `ml.prediction`.
- `SEUIL_NOTIFICATION_SLACK` (0,8) est le **seuil de notification** : une alerte
  Slack est une interruption humaine, réservée aux cas très nets.

La réponse au client part **avant** Slack et l'e-mail (`Repondre au client`) :
le score et le rapport SHAP ne dépendent pas de la disponibilité de Slack ou
du SMTP. `responseMode: responseNode` rend cette réponse déterministe ; avec
`lastNode`, elle dépendait du dernier nœud exécuté.

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

Le workflow d'alerte a deux branches d'erreur explicites :

| Panne | Comportement | Trace |
| --- | --- | --- |
| API d'inférence en 4xx/5xx ou injoignable | `Repondre echec inference` répond **502** avec « aucune notification n'a été envoyée », puis `Inference indisponible` arrête l'exécution. Aucun nœud Slack/e-mail n'est atteint. | `execution_entity.status = 'error'` |
| Slack en échec | L'e-mail part quand même (`continueRegularOutput`). Après l'e-mail, `Notification en echec ?` inspecte les deux résultats et `Notification en echec` arrête l'exécution. | `execution_entity.status = 'error'` |
| E-mail en échec | Même contrôle final ; Slack a déjà été tenté. | `execution_entity.status = 'error'` |

C'est la garantie « pas de notification fantôme » : les notifications sont
**en aval** de la réponse de l'inférence et de la condition de seuil. Une
facture invalide (422) ne peut pas produire d'alerte.

Le journal d'exploitation est celui de n8n, dans sa propre base PostgreSQL
(base `n8n`) :

```bash
docker compose exec -T db psql -U predicare -d n8n -c \
"SELECT e.id, e.status, e.mode, e.\"startedAt\", e.\"stoppedAt\"
 FROM execution_entity e
 JOIN workflow_entity w ON w.id = e.\"workflowId\"
 WHERE w.name = 'PK-Alerte-Fraude'
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

## Credentials et exploitation sur chaque poste

Les workflows ne contiennent **aucun secret**. Ce qui doit exister sur chaque
poste :

| Élément | Où | Procédure |
| --- | --- | --- |
| Webhook Slack | `.env` → `SLACK_WEBHOOK_URL` | Créer un Incoming Webhook dans le Slack de l'équipe, coller l'URL, recréer n8n. |
| SMTP | Credential n8n `Mailpit (dev)` | Host `mailpit`, port `1025`, sans TLS ni authentification (Mailpit). En production, créer la credential du vrai SMTP et la sélectionner dans le nœud e-mail. |
| Bascule de modèle | `.env` → `N8N_BASCULE_WEBHOOK_URL` | `http://n8n:5678/webhook/bascule-modele`, puis recréer `api-inference`. |
| Clé LLM | Credential n8n | Uniquement si un nœud LLM est ajouté ; absente des deux workflows actuels. |

Une credential n8n appartient à un **utilisateur** : elle ne se synchronise
pas par Git. Après un import sur une nouvelle machine, ouvrir chaque workflow,
cliquer sur le nœud e-mail et sélectionner la credential SMTP (ou la créer).
La sauvegarde/restauration chiffrée est décrite dans
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
- [x] Rapport SHAP dans le message Slack et dans l'e-mail
- [x] Variante e-mail via Mailpit (`make up-email`)
- [x] Branche d'erreur et journalisation dans `execution_entity`
- [x] Webhook de rappel pour la bascule de modèle (Phase 8.2)
- [x] Preuve de bout en bout automatisée (`make e2e-n8n`)
- [ ] Créer les credentials Slack/SMTP sur **chaque** poste et refaire
      `make e2e-n8n` sur le poste du jury

Propriétaire : Mirado
