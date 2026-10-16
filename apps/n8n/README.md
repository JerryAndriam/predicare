# Workflows n8n

Phase 4 du plan d'action. Le workflow est **constitue dans l'interface n8n**,
pas ecrit a la main dans ce dossier : l'interface est la source de verite,
ce qui garantit qu'il est reellement importeable par le jury.

## Domaine 1 - Alerte de fraude (Flux 1)

Webhook declenche par `api-inference` des qu'une facture depasse le seuil
(0,8 par defaut). Le noeud HTTP de n8n appelle ensuite l'API et pose une
condition sur le score. Si elle est vraie, une notification Slack part avec
le rapport SHAP deja mis en forme, l'e-mail restant une option.

Les secrets (webhook Slack, identifiants SMTP, cle LLM) sont crees comme
**credentials n8n** dans l'interface, jamais ecrits dans un workflow.

## Nomenclature

| Prefix | Role |
| --- | --- |
| `PK` | Production - s'execute sur donnees reelles |
| `Stg` | Staging - jeu de test |
| `Dev` | Developpement |

## Authentification et partage

**Il n'y a pas de mot de passe n8n dans le `.env`, et c'est normal.**

n8n a supprimé l'authentification basique en version 1.x : les variables
`N8N_BASIC_AUTH_USER` et `N8N_BASIC_AUTH_PASSWORD` ne sont plus lues du
tout. Vérifié sur le binaire 2.37.10 installé ici : **zéro occurrence** de
`basicAuth` dans son schéma de configuration.

Le modèle réel est le suivant :

| Question | Réponse |
| --- | --- |
| Qui est le propriétaire ? | Le **premier visiteur** de l'URL : n8n affiche un formulaire de création de compte |
| Le mot de passe est-il dans le `.env` ? | Non. Il est choisi par le visiteur et n'est stocké nulle part |
| La création est-elle reproductible ? | Non. Elle dépend de qui ouvre l'URL en premier |
| Deux postes ont-ils le même compte ? | Non, chacun a le sien |
| Le mot de passe est-il partageable ? | Non. C'est un mot de passe individuel, ce qui est plus sûr |

État du compte sur un poste : `make n8n-compte`. Il distingue trois cas —
aucun compte, un compte dont le formulaire n'a pas été terminé (cas trompeur :
n8n crée une ligne vide avant que le visiteur ne remplisse le formulaire), et
un compte complet.

Mot de passe oublié :

```bash
docker compose exec n8n n8n user-management:reset
```

Cette commande réinitialise **l'instance entière** : workflows compris.

## Le partage des workflows

**Le partage interne de n8n n'est pas disponible ici.** La table
`shared_workflow` existe bien dans le schéma, mais le code qui la manipule
est dans des fichiers `.ee.js` — la convention de n8n pour l'Enterprise
Edition. Sans licence, l'instance est en **édition Community** et chaque
compte ne voit que ses propres workflows.

Le partage se fait donc **par Git**, ce qui est de toute façon ce que le CDC
demande comme livrable :

| Acteur | Commandes |
| --- | --- |
| Celui qui modifie un workflow | `make n8n-export` puis `git add apps/n8n && git commit && git push` |
| Jerry, Cherica, Mirado | `make n8n-import` |

L'échange via Git plutôt que via n8n apporte trois choses que le
partage interne n'aurait pas données : l'historique Git montre **qui** a
modifié quoi, une pull request permet la relecture, et le workflow est
restaurable si une machine est réinstallée.

À ne pas faire : pointer plusieurs machines vers le même PostgreSQL pour
« partager » les workflows. Les exécutions et leurs identifiants sont liés
au compte propriétaire — on créerait des conflits pour un gain nul.

## Workflow de reference

`workflows/PK-Alerte-Fraude.json` est livre pret a importer : webhook
d'entree, controle du montant, appel de l'API d'inference, comparaison au
seuil, rapport SHAP, notification Slack, journalisation.

## Synchronisation avec Git

```bash
make n8n-export   # exporte les workflows dans apps/n8n/workflows/ (a commiter)
make n8n-import   # restaure et publie les workflows apres un down/up
```

Les deux scripts passent par la **CLI n8n**, pas son API REST : l'API exige
une cle creee a la main dans l'interface, ce qui rend l'installation
impossible a automatiser sur une machine vierge.

Consequence assumee : sans cle API, `make n8n-import` ne **remplace** pas un
workflow deja present (n8n 2.x n'expose aucune suppression en CLI) et le
signale plutot que de creer un doublon. Avec `N8N_API_KEY` renseignee dans
le `.env`, le remplacement et l'activation se font par l'API.

- `workflows/` est **versionne** : c'est le livrable « workflows n8n
  importables (.json) » exige par le CDC.
- `credentials/` est **gitignore** : un export de credentials contient le
  webhook Slack et la cle LLM. La procedure d'export/import manuel, chiffree
  par `N8N_ENCRYPTION_KEY`, est decrite dans `credentials/README.md`.

## Brouillon / TODO

- [x] Workflow d'alerte complet, versionne et importable
- [ ] Creer les credentials Slack, SMTP et LLM sur CHAQUE poste : ils ne
      se synchronisent pas, seul le workflow est versionne
- [ ] Verifier le declenchement reel du webhook avec une facture de test
- [ ] Reporter le rapport SHAP dans le message Slack (noeud deja cable)
- [ ] Variante e-mail via le SMTP de developpement (Mailpit, `make up-email`)
- [ ] Gestion d'erreur : noeud de secours et journalisation des echecs
- [ ] Webhook de rappel pour la bascule de modele (Phase 8.2)

Proprietaire : Mirado