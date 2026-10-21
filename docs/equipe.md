# Repartition du travail

Ce document suit le **projet**, pas la plateforme. Il est perime par nature :
les tableaux ci-dessous decrivent qui fait quoi aujourd'hui, et seront
obsoletes a la fin du projet. Pour le fonctionnement technique, voir le
[`README.md`](../README.md) racine.

Il a quitte le README racine pour cette raison : melanger la documentation
d'usage d'une plateforme et le suivi d'un projet fait disparaitre les deux.

## Qui fait quoi

|                       | Jerry                                                   | Cherica                                               | Mirado                                    |
| --------------------- | ------------------------------------------------------- | ----------------------------------------------------- | ----------------------------------------- |
| **Socle partagé**     | `packages/predicare-core/`                              |                                                       |                                           |
| **Flux 1 — fraude**   | Versionnement MLflow, métriques de latence et de dérive | Robustesse sur factures mal formées                   | Entraînement, seuil, SHAP, dérive         |
| **Flux 2 — RAG**      | Supervision, dérive                                     | Tests d'attaque injection                             | Agent ReAct, indexation, cache sémantique |
| **Flux 3 — pilotage** | Ecran d'administration, métriques, rollback             | Authentification, quatre rôles, parcours gestionnaire | —                                         |
| **Interface**         | —                                                       | React, quatre parcours de rôle                        | Vue assured (chat RAG)                    |
| **Données**           | Requêtes d'analyse pour la BI                           | Migrations, chargement initial, nettoyage             | Chargement des factures d'entraînement    |
| **Orchestration**     | —                                                       | —                                                     | Workflow n8n, alerte Slack + rapport SHAP |
| **Exploitation**      | Passerelle, sauvegarde, CI, scripts, docs               | Guide utilisateur                                     | Dossier de cadrage FinOps et conformité   |

## Rattachement aux phases

| Phase              | Jerry                                              | Cherica                                  | Mirado                                                |
| ------------------ | -------------------------------------------------- | ---------------------------------------- | ----------------------------------------------------- |
| 0 — cadrage        | Dépôt, CI, README, ADR                             | —                                        | —                                                     |
| 1 — données        | Requêtes BI, sauvegarde                            | Migrations, chargement, pseudonymisation | —                                                     |
| 2 — modèle         | MLflow                                             | Robustesse                               | EDA, feature engineering, entraînement, seuil, SHAP   |
| 3 — API            | Logs, métriques, dérive, Docker                    | Endpoints, Pydantic, tests               | —                                                     |
| 4 — n8n            | —                                                  | —                                        | Workflow, erreurs, export                             |
| 5 — RAG            | —                                                  | —                                        | Indexation, outils, sécurité, cache, jeu de questions |
| 6 — interface      | Administration                                     | Auth, rôles, parcours                    | Vue assuré                                            |
| 7 — BI             | Indicateurs, tableaux de bord                      | —                                        | —                                                     |
| 8 — exploitation   | Supervision, rollback, persistance, machine vierge | Seuil en direct                          | —                                                     |
| 9 — conformité     | Cartographie, conservation, sécurité               | Recherche de PII résiduelles             | AI Act, audit d'équité                                |
| 10 — documentation | Exploitation, README                               | Guide utilisateur                        | Dossier de cadrage                                    |
| 11 — soutenance    | Lot de 20 factures, démo                           | Slides                                   | Réponses aux objections                               |

## Points de coordination

- **Figer les contrats d'interface avant la Phase 3** : format des prédictions
  et des explications SHAP. C'est le point de dépendance entre les trois.
- Réunion hebdomadaire courte pour synchroniser les dépendances.
- Le seuil d'alerte et le format du rapport SHAP touchent les trois membres :
  à décider ensemble.

## Contributions vérifiables

Cette section ne remplace pas le tableau ci-dessus : elle liste les **artefacts réellement présents dans le dépôt** et la trace qui permet de les rattacher à un membre. Elle est vérifiable le 21/10/2026 avec `git log -- <chemin>` (ou `ls` pour les fichiers locaux non versionnés). Les auteurs Git sont repris tels quels : les commits de `BradAkemi`/`AkemiFF` correspondent à la part de Mirado — à confirmer par l'intéressé si son identité Git diffère.

| Membre | Artefact | Chemin | Trace |
| --- | --- | --- | --- |
| **Mirado** | Support de soutenance et fiches mémo | `local/SOUTENANCE_MIRADO.md`, `local/FICHE_MEMO_MIRADO.pdf`, `local/FICHE_MEMO_MIRADO_2P.pdf` | fichiers locaux (non versionnés) |
| **Mirado** | Dossier de cadrage (TCO, ROI, RGPD, AI Act, équité) | `docs/cadrage/dossier_cadrage.md` + `.pdf` | commits `BradAkemi` |
| **Mirado** | Rapports modèle et stratégies de déséquilibre | `reports/modele_v1.md`, `reports/modele_v2.md`, `reports/strategies_v1.md` | commits `BradAkemi` et `jerry` |
| **Mirado** | Audit d'équité | `reports/equite_v2.md` | commits `BradAkemi` et `jerry` |
| **Mirado** | Workflows n8n (alerte de fraude, bascule de modèle) | `apps/n8n/workflows/PK-Alerte-Fraude.json`, `apps/n8n/workflows/PK-Bascule-Modele.json` | commits `BradAkemi` (et `jerry` sur le premier) |
| **Cherica** | Guide utilisateur | `docs/utilisateur/guide-utilisateur.md` | commit `Cherica` |
| **Cherica** | Migrations de base | `db/migrations/` | commits `Cherica`, `jerry` et `BradAkemi` |
| **Cherica** | Workflow n8n interne | `apps/n8n/workflows/PK-Alerte-Fraude-Interne.json` | commits `Cherica` et `jerry` |
| **Jerry** | Guides d'exploitation | `docs/exploitation/README.md`, `docs/exploitation/demarrage-equipe.md`, `docs/exploitation/creer_tableau_bord_superset.md` | commits `jerry` (et `BradAkemi` sur le README) |
| **Jerry** | CI et décisions d'architecture | `.github/workflows/ci.yml`, `docs/adr/README.md` | commits `jerry` |
| **Jerry** | Migrations de base et audit d'équité | `db/migrations/`, `reports/equite_v2.md` | commits `jerry`, `Cherica` et `BradAkemi` (migrations) ; `jerry` et `BradAkemi` (équité) |

Deux précautions de lecture :

- **Le nombre de commits n'est pas une mesure de contribution.** Plusieurs fichiers portent des commits de deux ou trois membres (`README.md`, `db/migrations/`, `reports/equite_v2.md`, les workflows n8n) : c'est le résultat de l'intégration, pas un partage de paternité.
- **Ce tableau ne couvre que ce qui laisse une trace.** Le code applicatif (auth, rôles, endpoints, BI) est décrit dans le tableau « Qui fait quoi » ci-dessus ; son attribution fine se lit dans `git log --author=<nom>`, pas dans ce document qui reste, par construction, un suivi de projet.
