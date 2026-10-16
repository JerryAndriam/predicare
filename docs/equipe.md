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
