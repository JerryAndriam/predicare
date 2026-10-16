# Export / import des credentials n8n

Ce dossier est **volontairement gitignore** (`.gitignore` du depot). Un
export de credentials contient le webhook Slack, l'identifiant SMTP et la
cle LLM : le commiter reviendrait a mettre ces secrets dans l'historique
Git, definitivement.

## Ce qui se versionne

Seuls les **workflows** sont commites, dans `apps/n8n/workflows/`. Ils ne
contiennent aucun secret : les credentials y sont referencees par nom.

## Attention : une credential par poste, par compte

Une credential n8n appartient a un **utilisateur**, pas a une instance.
Trois consequences concretes :

- Chaque poste doit recreer ses credentials dans l'interface apres
  `make n8n-import`. L'import du workflow echoue proprement s'il manque le
  credential, mais il ne peut pas le deviner.
- Un `n8n import:credentials` sur le compte de Jerry ne rendra rien
  visible sur le poste de Cherica : les credentials d'un compte ne sont pas
  visibles par les autres. L'export/import ci-dessous sert a migrer un
  compte vers un autre compte, pas a synchroniser une equipe.
- Si le mot de passe du compte est perdu, `n8n user-management:reset`
  reinitialise l'instance entiere — **y compris les credentials** qui y
  etaient stockees.

Etat du compte sur le poste courant : `make n8n-compte`.

## Sauvegarder les credentials (a faire avant le jour J)

Dans l'interface n8n :

1. **Credentials** (menu de gauche)
2. Cocher toutes les credentials
3. **Export** en bas a droite
4. Telecharger le fichier `.json`

n8n chiffre ce fichier avec `N8N_ENCRYPTION_KEY`. Conservez les deux ensemble
dans un coffre-fort, jamais dans Git.

## Restaurer les credentials

Dans l'interface n8n :

1. **Credentials** > **Import**
2. Televerser le fichier `.json` exporte

Le dechiffrement ne fonctionne que si `N8N_ENCRYPTION_KEY` est **identique**
a celle utilisee a l'export. C'est pour cela que cette cle est epinglee dans
`.env.example` et non generee aleatoirement a chaque demarrage.

## Verification

- [ ] Les credentials attendues existent dans l'interface apres restauration
- [ ] Le workflow d'alerte se declenche bien et le message Slack part
- [ ] `N8N_ENCRYPTION_KEY` du `.env` correspond a celle du fichier exporte

## Reinitialisation complete

Si les credentials sont perdus, il suffit de les recreer dans l'interface :
un webhook Slack et une cle LLM se regenerent en quelques minutes. C'est
volontaire : un credential n'est pas un artefact de deploiement, c'est un
parametre d'environnement de l'installation.