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
- [ ] Verifier le declenchement reel du webhook avec une facture de test
- [ ] Reporter le rapport SHAP dans le message Slack (noeud deja cable)
- [ ] Variante e-mail via le SMTP de developpement (Mailpit, `make up-email`)
- [ ] Gestion d'erreur : noeud de secours et journalisation des echecs
- [ ] Webhook de rappel pour la bascule de modele (Phase 8.2)

Proprietaire : Mirado