# Livrables PrediCare

**Analyse TCO/ROI, conformité RGPD, EU AI Act et équité, sécurité, guide d'exploitation et d'utilisation**

| | |
| --- | --- |
| Version | 1.0 |
| Date | 21 octobre 2026 |
| Statut | Version de travail, revue métier et juridique à compléter |
| Périmètre | Plateforme PrediCare : API coeur, scoring de fraude, assistant RAG, interface web, BI Superset, exploitation |
| Public | Jury, direction, DPO, RSSI, équipe d'exploitation, équipe produit |
| Nature | Documentation produit et dossier de preuves ; ce n'est ni une certification, ni un avis juridique |

## 1. Objet du dossier

Ce dossier rassemble cinq documents autonomes qui expliquent les choix économiques, juridiques, techniques et opérationnels de PrediCare. Chaque document peut être lu seul. L'index sert à trois choses : retrouver rapidement une preuve, éviter les chiffres contradictoires entre documents, et donner à chaque public un parcours de lecture adapté.

Le dossier de cadrage historique reste la synthèse exécutive. Les présents livrables en sont la version détaillée et actualisée. En cas de divergence sur un fait technique, le code, les tests et les scripts du dépôt font foi. En cas de divergence sur un chiffre métier, la table de référence ci-dessous fait foi jusqu'à nouvel audit.

## 2. Les cinq documents

| Document | Objet | Public principal | Volume indicatif |
| --- | --- | --- | ---: |
| [`01_analyse_tco_roi.md`](01_analyse_tco_roi.md) | TCO, ROI, coût des tokens, sauvegarde, tableau FinOps et leviers d'optimisation | Direction, finance, jury | 15–17 pages |
| [`02_conformite_rgpd.md`](02_conformite_rgpd.md) | Registre des traitements, bases légales, droits, conservation, AIPD, sous-traitants | DPO, juriste, direction | 15–17 pages |
| [`03_ai_act_equite.md`](03_ai_act_equite.md) | Classement AI Act, grille des obligations, audit d'équité et plan de surveillance | Jury, conformité, data science | 17–20 pages |
| [`04_securite.md`](04_securite.md) | Modèle de menace, contrôles, preuves, risques résiduels et feuille de route | RSSI, exploitation, jury | 17–20 pages |
| [`05_guide_exploitation_utilisateur.md`](05_guide_exploitation_utilisateur.md) | Installation, configuration, runbooks, incidents, prise en main par rôle | Exploitation, support, utilisateurs | 18–20 pages |

Les volumes sont indicatifs : ils correspondent à une mise en page A4 sobre, hors annexes exceptionnellement longues.

## 3. Parcours de lecture

| Lecteur | Parcours recommandé | Question à laquelle le dossier répond |
| --- | --- | --- |
| Jury | Index → 01 → 03 → 04 → 05 | Le projet est-il utile, mesuré, conforme et démontrable ? |
| Direction | Index → 01 (résumé et ROI) → 02 (risques) → 03 (classement) | Combien coûte la plateforme, que rapporte-t-elle, que risque-t-on ? |
| DPO / juriste | 02 → 03 (partie AI Act) → 04 (sécurité) | Quelles données, quelles bases légales, quels droits, quels sous-traitants ? |
| RSSI | 04 → 05 (runbooks) → 02 (violations) | Quels contrôles sont réellement en place, et quels écarts restent ouverts ? |
| Exploitation | 05 → 04 (sauvegarde, TLS, rotation) → 01 (coûts) | Comment installer, superviser, sauvegarder, restaurer et dépanner ? |
| Produit / data | 03 (équité) → 01 (coût par requête) → 05 (BI) | Quelles performances, quels biais, quels coûts par usage ? |

## 4. Chiffres de référence

Tous les documents doivent utiliser ces valeurs, sauf mention explicite d'une autre convention. La date de constat est le 21 octobre 2026.

### 4.1 Modèle de fraude

| Indicateur | Valeur | Source |
| --- | ---: | --- |
| Jeu d'entraînement | 84 593 factures | `reports/modele_v2.md` |
| Jeu de test | 10 086 factures | `reports/modele_v2.md` |
| Fraudes réelles dans le test | 878 (8,7 %) | `reports/modele_v2.md` |
| ROC-AUC | 0,9500 | `reports/modele_v2.md` |
| PR-AUC | 0,8913 | `reports/modele_v2.md` |
| Rappel au seuil 0,2876 | 0,8702 | `reports/modele_v2.md` |
| Précision | 0,5969 | `reports/modele_v2.md` |
| F1 | 0,7081 | `reports/modele_v2.md` |
| Spécificité | 0,9440 | `reports/modele_v2.md` |
| Vrais positifs | 764 | `reports/modele_v2.md` |
| Faux positifs | 516 | `reports/modele_v2.md` |
| Faux négatifs | 114 | `reports/modele_v2.md` |
| Vrais négatifs | 8 692 | `reports/modele_v2.md` |

### 4.2 Coûts et ROI

| Indicateur | Valeur | Statut |
| --- | ---: | --- |
| Coût d'un faux positif | 3 000 MGA | Hypothèse métier |
| Coût d'un faux négatif | 30 000 MGA | Hypothèse métier |
| Coût des erreurs au seuil | 4 968 000 MGA | Calcul |
| Référence « erreurs FP/FN » du dossier | 27 624 000 MGA | Convention historique |
| Économie selon la convention historique | 22 656 000 MGA | Calcul |
| Référence « contrôle exhaustif » | 30 258 000 MGA | Calcul recommandé |
| Coût modèle avec revue des alertes | 7 260 000 MGA | Calcul recommandé |
| Économie selon la convention recommandée | 22 998 000 MGA | Calcul recommandé |
| TCO de base | 108,97 €/an | Mesuré + hypothèse |
| TCO stress | 214,78 €/an | Mesuré + hypothèse |
| TCO conservateur | 390,86 €/an | Mesuré + hypothèse |
| Ratio économie/TCO de base | 41,6× (historique) ; 42,2× (recommandé) | Calcul |
| Économie annuelle projetée, convention recommandée | 192,89 M MGA | Extrapolation |
| Ratio économie/TCO annuel | 354,0× | Extrapolation |
| Ratio économie/TCO prudent | 89,8× | Extrapolation |

Le terme « ROI » est souvent employé dans le dossier pour désigner le ratio `économie / TCO`. Ce n'est pas un ROI net. Le document 01 définit les trois notions séparément : ratio de couverture, gain net et ROI net. Il présente aussi la différence entre le coût des erreurs et le coût complet d'un contrôle exhaustif.

### 4.3 Assistant RAG et FinOps

| Indicateur | Valeur | Source |
| --- | ---: | --- |
| Tokens par question | 3 725 | `reports/eval_rag_2026-10-19_5.json` |
| Coût par requête | 0,00064 USD (~0,00059 EUR) | `apps/api-rag/README.md` |
| Évaluation fidélité | 30/30 | même rapport |
| Évaluation citation | 20/20 | même rapport |
| Évaluation exactitude | 26/26 | même rapport |
| Cache sémantique, hits mesurés | 2 | dossier de cadrage |
| Latence évitée sur ces hits | 10,48 s | dossier de cadrage |
| Coût évité sur ces hits | 0,00064 € | dossier de cadrage |

### 4.4 Conformité et sécurité

| Indicateur | Valeur | Source |
| --- | --- | --- |
| Conservation des prédictions | 3 ans | `rgpd/conservation.py` |
| Conservation des factures | 10 ans | `rgpd/conservation.py` |
| Conservation du journal d'audit | 5 ans | `rgpd/conservation.py` |
| Rétention des sauvegardes | 14 jours | `db/backup/pg_dump.sh` |
| Chiffrement des sauvegardes | AES-256-CBC, PBKDF2 200 000 itérations, clé fichier (si fournie) | `db/backup/pg_dump.sh` |
| Tests automatisés | 696 passés, 18 ignorés | `make check`, 21/10/2026 |
| Attaques RAG déclarées bloquées | 97 tests, 100 % des attaques déclarées | dossier de cadrage, à recouper |
| Garde-fous | 78 tests | dossier de cadrage, à recouper |
| SQL | 57 tests | dossier de cadrage, à recouper |
| RBAC | 22 tests | dossier de cadrage, à recouper |
| Chaîne n8n | 13/13 vérifications | dossier de cadrage, à recouper |

## 5. Conventions de rédaction

### 5.1 Statut d'une affirmation

| Statut | Signification |
| --- | --- |
| **Mesuré** | Résultat produit par une commande, un test ou un rapport daté. |
| **Calculé** | Résultat dérivé de mesures par une formule explicite. |
| **Estimé** | Résultat fondé sur une hypothèse de coût, de volume ou de prix. |
| **Hypothèse** | Valeur posée par le métier, à valider avant production. |
| **Écart** | Fonction absente, partielle ou non prouvée. |

### 5.2 Vocabulaire de conformité

Les documents distinguent systématiquement :

- **conforme par conception** : les mesures sont présentes dans l'architecture et les tests ;
- **partiel** : une partie de l'obligation est couverte, une autre reste à faire ;
- **écart ouvert** : l'obligation n'est pas couverte ou n'est pas prouvée ;
- **non applicable** : l'obligation ne concerne pas le périmètre, avec justification ;
- **non certifié** : l'évaluation formelle, le marquage ou l'homologation ne sont pas prononcés.

Aucun document ne doit écrire « conforme », « certifié » ou « homologué » sans preuve formelle.

### 5.3 Unités et dates

- Montants en **ariary (MGA)** pour le métier, en **euro (EUR)** pour l'infrastructure, en **dollar (USD)** pour les tokens.
- Conversion de référence : **1 EUR = 5 000 MGA**. Elle doit être actualisée le jour d'une présentation officielle.
- Dates techniques au format `2026-10-21` dans les tableaux, dates en toutes lettres dans les paragraphes.
- Les prix d'hébergement sont des hypothèses datées, pas des devis.

### 5.4 Preuves

Chaque affirmation importante doit renvoyer à une preuve :

- un fichier du dépôt, avec chemin et section ;
- une commande et sa sortie ;
- un rapport daté ;
- un test nommé ;
- une décision explicite, datée et attribuée.

Les documents peuvent citer les documents historiques, mais ils doivent indiquer leur date et vérifier les faits qui ont changé depuis.

## 6. Matrice de correspondance avec le cahier des charges

| Exigence | Document principal | Sections |
| --- | --- | --- |
| TCO et ROI | 01 | Méthode, TCO consolidé, ROI, FinOps |
| Coût des tokens et cache | 01 | Économie des tokens, leviers FinOps |
| RGPD : cartographie et bases légales | 02 | Registre, bases légales, AIPD |
| RGPD : droits et conservation | 02 | Droits, conservation, purge |
| EU AI Act : classement | 03 | Fiche système, classification |
| EU AI Act : obligations haut risque | 03 | Grille articles 9 à 15, 17, 43, 48, 49, 72, 73 |
| Audit d'équité | 03 | Méthode, résultats, limites, mitigations |
| Sécurité | 04 | STRIDE, RBAC, chiffrement, réseau, RAG |
| Sauvegarde et restauration | 04 et 05 | Chiffrement, runbook, RPO/RTO |
| Supervision | 04 et 05 | Métriques, logs, dérive, dashboards |
| Exploitation | 05 | Installation, configuration, incidents |
| Guide utilisateur | 05 | Parcours par rôle, FAQ, glossaire |

## 7. Sources de vérité

| Sujet | Source principale | Complément |
| --- | --- | --- |
| Modèle et métriques | `reports/modele_v2.md` | `reports/strategies_v1.md` |
| Équité | `reports/equite_v2.md` | `reports/equite_v1.md` |
| Coûts et ROI | `docs/cadrage/dossier_cadrage.md` | `reports/modele_v2.md`, `apps/api-rag/README.md` |
| RGPD | `apps/api-core/src/predicare_core_api/rgpd/` | `docs/cadrage/dossier_cadrage.md` |
| Sécurité | `packages/predicare-core/src/predicare/rbac.py`, `audit.py`, `crypto.py` | `scripts/test-intrusion.sh`, `docs/cadrage/dossier_cadrage.md` |
| Exploitation | `docs/exploitation/` | `.env.example`, `Makefile`, `db/backup/` |
| Utilisateur | `docs/utilisateur/guide-utilisateur.md` | interface web et tests Playwright |
| BI | `ops/superset/` | `docs/exploitation/README.md` |
| Tests | `make check` | rapports datés |

## 8. Avertissements

- Les données du modèle sont **synthétiques**. Les performances et le ROI ne sont pas une mesure de production.
- Le classement AI Act « haut risque » est une **lecture prudente**. Il doit être confirmé par un avis juridique avant mise sur le marché.
- Le rôle RGPD de PrediCare dépend du contrat de déploiement. Selon le cas, PrediCare est sous-traitant ou responsable de traitement.
- Les prix d'infrastructure sont des **hypothèses**, pas des devis.
- Le PDF `docs/cadrage/dossier_cadrage.pdf` reste daté du 20 octobre 2026. Le Markdown est la source à jour ; le PDF doit être régénéré après validation.
- Aucun secret réel ne doit être copié dans ces documents.

## 9. Maintenance

| Événement | Document à mettre à jour | Vérification |
| --- | --- | --- |
| Nouveau modèle ou nouveau seuil | 01, 03, index | `reports/modele_v2.md`, `/api/inference/modele` |
| Changement de coût ou de volume | 01, index | `apps/api-rag/README.md`, Prometheus |
| Nouvelle obligation ou nouveau pays | 02, 03 | avis DPO/juriste |
| Nouvelle mesure de sécurité | 04, 05 | test, script, revue |
| Nouveau service ou nouvelle commande | 05 | `make help`, README |
| Nouvelle version de l'interface | 05 | `docs/utilisateur/guide-utilisateur.md` |
| Nouvelle campagne de tests | index, 04 | `make check`, rapport daté |

## 10. Changelog

| Version | Date | Changement |
| --- | --- | --- |
| 1.0 | 2026-10-21 | Création des cinq livrables, index, chiffres de référence et conventions. |
