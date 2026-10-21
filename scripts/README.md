# Scripts d'exploitation

Ce que le jury execute, et ce qui casse quand une machine est vierge.

| Script | Declenche | Role |
| --- | --- | --- |
| `bootstrap.sh` | `make up` | Verifie les outils de la machine, cree le `.env`, genere les secrets, controle les ports |
| `doctor.sh` | `make doctor` | Audit complet de la machine et de la plateforme. Ne modifie rien |
| `wait-for-services.sh` | `make up`, `make up-all` | Attend la fin de la sequence de demarrage |
| `check-health.sh` | `make health` | Sonde `/health` et `/metrics` de chaque service |
| `smoke-test.sh` | `make smoke` | Parcours de verification de bout en bout |
| `n8n-export.sh` | `make n8n-export` | Copie les workflows de l'interface vers Git |
| `n8n-import.sh` | `make n8n-import` | Restaure, met a jour par ID et reactive les workflows |
| `e2e_n8n.sh` | `make e2e-n8n` | Prouve la chaine n8n reelle : Slack, e-mail Mailpit, echec journalise |
| `generate-access-file.sh` | `make acces` | Genere la fiche d'identifiants **hors du depot** |
| `split-workflows.py` | `make n8n-export` | Decoupe l'export n8n en un fichier par workflow |
| `check-commit-title.sh` | hook pre-commit | Normalise les titres de commit |
| `attendre-http.sh` | `make up-bi` | Attend qu'une URL reponde (Superset est lent au premier demarrage) |

## La fiche d'acces sort du depot

`generate-access-file.sh` ecrit `/home/jerry/Documents/predicare/ACCES_PREDICARE.md`,
en mode 600. Aucune valeur du `.env` n'entre donc dans l'historique Git, et
aucune regle d'exclusion n'a a etre maintenue dans le `.gitignore`.

## Outils appeles par chaque script

Hors conteneurs, `make up` n'utilise que `bash`, `make`, `curl`, `docker`
et les coreutils. Ni `openssl`, ni `python3`, ni `timeout` ne sont requis
pour demarrer la plateforme : les secrets viennent de `/dev/urandom` et les
boucles d'attente sont bornees a la main.

| Script | Outils externes |
| --- | --- |
| `bootstrap.sh` | `docker`, coreutils, `grep`, `sed`, `tr`, `cut`, `awk`, `touch`, `mkdir`. Optionnels : `ss` (controle des ports), `uv` (verrou a jour) |
| `doctor.sh` | `docker`, `git`, coreutils |
| `wait-for-services.sh` | `docker`, `curl`, `grep` |
| `check-health.sh` | `curl`, `python3` |
| `smoke-test.sh` | `docker`, `curl`, `python3` |
| `n8n-import.sh` / `n8n-export.sh` | `docker`, `curl`, `python3` |
| `e2e_n8n.sh` | `docker`, `curl`, `jq`, `python3` |
| `generate-access-file.sh` | `docker`, `git` (le controle de fuite se degrade si git est absent) |
| `attendre-http.sh` | `curl` |

## Proprietes communes

Tous les scripts sont **idempotents** : les relancer ne casse rien. C'est une
exigence d'exploitation, pas une commodite : un operateur relance une
commande qui a echoue sans craindre d'aggraver la situation.

## Brouillon / TODO

- [ ] Script de deploiement d'une version complete avec tag
- [ ] Verification du comportement sur machine vierge (Phase 8.5)
- [ ] Alerte de certification d'une sauvegarde de plus de 26 heures

Proprietaire : Jerry
