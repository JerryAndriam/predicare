# Plan de pitch et figures de la soutenance

Ce document est le conducteur de la présentation : il suit la structure du
pitch, indique qui parle, et liste les images à projeter avec le message
qu'elles portent.

**Les images** sont dans le dossier `pic-pitch` de la machine de travail :
`/home/jerry/Documents/pic-pitch/`, classées par partie du pitch. Elles ne sont
pas versionnées dans le dépôt (ce sont des captures d'écran de la pile de
démonstration, avec des données de démonstration) ; elles sont reproductibles
avec deux commandes :

```bash
make figures SORTIE=/home/jerry/Documents/pic-pitch   # figures générées
make captures N8N_MDP=<mot de passe>                  # captures d'écran
```

Le tableau des sources de chaque figure est dans `LEGENDE.md`, à côté des
images.

## 1. Introduction — Cherica

| Image | Ce qu'elle montre | Le message |
| --- | --- | --- |
| `1-introduction/p1_accueil_professionnel.png` | L'espace d'un professionnel de santé | Un seul écran, quatre rôles : le dépôt d'une facture, sa notation, son explication, le suivi. |
| `1-introduction/p1_pilotage_application.png` | Le tableau de bord embarqué dans l'application | La plateforme n'est pas une boîte noire : le pilotage est dans le produit, sans seconde connexion. |
| `3-ia/p3_matrice_confusion.png` | La matrice de confusion au seuil 0,2876 | Le problème chiffré : 27,6 M MGA de contrôle exhaustif contre 4,97 M MGA avec le modèle, soit 22,66 M MGA économisés. |
| `2-architecture/p2_architecture_globale.png` | L'architecture de la plateforme | Une pile Docker, un réseau interne, une seule porte d'entrée. |

## 2. Architecture et socle d'exploitation — Jerry

| Image | Ce qu'elle montre | Le message |
| --- | --- | --- |
| `2-architecture/p2_architecture_globale.png` | Passerelle, trois API, base, Redis, BI, supervision | Le socle : ce qui tourne, où, et ce qui n'est pas exposé. |
| `2-architecture/p2_observabilite.png` | L'écran d'observabilité de l'administration | La supervision est dans le produit, pas dans un outil à côté. |
| `2-architecture/p2_grafana_vue_service.png` | La vue service de Grafana | Les métriques applicatives, provisionnées dans le dépôt. |
| `2-architecture/p2_prometheus_regles.png` | Les neuf règles d'alerte Prometheus | L'alerte existe avant l'incident, et son seuil est écrit dans le dépôt. |

## 3. Intelligence artificielle et explicabilité — Mirado

| Image | Ce qu'elle montre | Le message |
| --- | --- | --- |
| `3-ia/p3_cycle_vie_modele.png` | Le cycle de vie du modèle en huit étapes | De la donnée brute à la décision : chaque étape a une preuve. |
| `3-ia/p3_importance_variables.png` | **L'importance des 32 variables**, moyenne des contributions SHAP sur 55 575 explications réelles | Le choix des variables n'est pas une intuition : il est mesuré, variable par variable, sur la production. |
| `3-ia/p3_courbes_roc_pr.png` | Courbes ROC et précision-rappel | La performance est recalculée sur le jeu de test, lu une seule fois. |
| `3-ia/p3_matrice_confusion.png` | La matrice de confusion | Rappel 87,02 %, précision 59,69 % : le modèle priorise, il ne décide pas. |
| `3-ia/p3_comparaison_baselines.png` | Modèle contre règles métier et régression logistique | Pourquoi un modèle appris : la comparaison est chiffrée, pas affirmée. |
| `3-ia/p3_equite_segments.png` | Le rappel par segment | L'inégalité de détection est mesurée et publiée, pas cachée. |
| `3-ia/p3_derive_psi.png` | La surveillance de la dérive et son état réel | Le dispositif de surveillance est écrit, et son manque actuel est dit. |
| `3-ia/p3_mlflow_experiences.png` | Les expériences MLflow | Chaque entraînement est journalisé : la reproductibilité est une preuve, pas une intention. |
| `3-ia/p3_mlflow_run.png` | Un run MLflow et ses métriques | Les métriques sont attachées au run, pas recopiées dans un document. |
| `3-ia/p3_seuil_modele.png` | Le registre des modèles et le seuil en service | Le seuil se change à chaud, il est tracé, et il est le même partout. |
| `3-ia/p3_seuil_valeur.png` | L'écran de réglage du seuil | Chaque changement porte un motif et une date. |
| `3-ia/p3_n8n_canvas.png` | Le workflow d'alerte de fraude | La chaîne d'alerte : webhook, seuil, e-mail, Slack, et ce qui se passe en cas d'échec. |
| `3-ia/p3_n8n_executions.png` | L'historique d'exécutions | 86 exécutions réelles : la chaîne tourne, et on peut le prouver. |
| `3-ia/p3_assistant_rag.png` | L'assistant et ses sources citées | L'IA cite ses sources et le dit : aucune réponse sans origine. |

## 4. Démonstration du produit — Cherica, Mirado, Jerry

Scénario joué en direct, captures prises pendant la démonstration :

| Image | Ce qu'elle montre | Le message |
| --- | --- | --- |
| `4-demo/p4_file_alertes.png` | La file d'alertes du gestionnaire | 26 alertes au-dessus du seuil, triées de la plus suspecte à la moins suspecte. |
| `4-demo/p4_detail_alerte.png` | Le détail d'une alerte : lignes, ordonnance, contributions | Le gestionnaire voit pourquoi, pas seulement combien. |
| `4-demo/p4_pilotage_bi.png` | Le tableau de bord dans l'application | Le pilotage sans seconde connexion. |
| `4-demo/p4_superset_tableau.png` | Le tableau de bord BI en plein écran | Le compte de démonstration est en lecture seule : aucune tuile modifiable. |
| `4-demo/p4_superset_view_as_table.png` | La modale « View as table » | Le rôle invité ouvre les interfaces de consultation, pas l'édition. |
| `1-introduction/p1_accueil_professionnel.png` | Le dépôt d'une facture | L'entrée de la démonstration : une facture, une note, une explication. |

## 5. Gouvernance, impact business et conclusion — Jerry

| Image | Ce qu'elle montre | Le message |
| --- | --- | --- |
| `5-gouvernance/p5_tco_scenarios.png` | Le TCO en trois scénarios | 108,97 € par an en base : l'infrastructure domine, le modèle de langage est minoritaire. |
| `5-gouvernance/p5_roi_conventions.png` | L'économie de contrôle et le seuil de rentabilité | 22,66 M MGA économisés, et 239 factures par an pour rentabiliser la plateforme. |
| `5-gouvernance/p5_sensibilite_fraude.png` | La sensibilité au coût d'une fraude manquée | L'hypothèse la plus influente, testée : le résultat reste favorable. |
| `5-gouvernance/p5_conformite_ai_act.png` | L'état de conformité par article de l'AI Act | Ce qui est couvert, ce qui ne l'est pas : les écarts sont écrits noir sur blanc. |
| `5-gouvernance/p5_grafana_vue_modele.png` | La vue modèle de Grafana | La dérive, les tokens et le coût du modèle, supervisés. |
| `5-gouvernance/p5_journal_actions.png` | Le journal des actions | Chaque décision, chaque changement de seuil : la preuve est horodatée et attribuée. |
| `5-gouvernance/p5_securite_canaux.png` | Les canaux de notification | Un canal actif mais non configuré n'envoie rien : le statut est visible. |

## Deux chiffres à connaître avant de passer

- **Seuil en service : 0,2876.** Il a été aligné sur la valeur du rapport de
  référence le 21 octobre 2026 (`audit.parametre.seuil_alerte`, changement
  tracé). L'artefact `models/2` porte encore son seuil d'origine (0,2766) :
  c'est le point de fonctionnement par défaut du modèle, pas celui de la
  plateforme en service.
- **MLflow** conserve le run du 21 octobre, calculé sur le seuil par défaut de
  l'artefact. Les métriques du run (rappel 0,8747) ne sont donc pas celles du
  seuil en service (rappel 0,8702 au seuil 0,2876) : même modèle, deux points
  de fonctionnement.

Propriétaire : Jerry
