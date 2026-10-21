# Livrables

**Analyse des coûts, conformité RGPD, EU AI Act et équité, sécurité, guide d'exploitation et d'utilisation**

| | |
| --- | --- |
| Version | 1.1 |
| Date | 21 octobre 2026 |
| Statut | Version de travail, revue métier et juridique à compléter |
| Périmètre | La plateforme de démonstration : API cœur, détection de fraude, assistant documentaire (RAG), interface web, BI, exploitation |
| Public | Jury, direction, DPO, RSSI, équipe d'exploitation, équipe produit |
| Nature | Documentation produit et dossier de preuves ; ce n'est ni une certification, ni un avis juridique |

## 1. Objet et périmètre du dossier

Il rassemble cinq documents qui répondent à cinq questions : **combien ça
coûte**, **sommes-nous conformes sur les données**, **quelles obligations
l'IA Act nous impose**, **la plateforme est-elle sécurisée**, **comment
l'exploiter et l'utiliser au quotidien**.

Chaque document se lit seul : le document 03 peut être transmis à un juriste sans le document 01.
L'index sert à trois choses : retrouver vite une preuve, éviter que deux
documents ne se contredisent sur un chiffre, et proposer à chaque lecteur un
parcours de lecture adapté à son métier.

Le dossier de cadrage reste la synthèse exécutive ; les présents livrables en
sont la version détaillée et à jour. **En cas de désaccord sur un fait
technique, le code, les tests et les scripts font foi. En cas de désaccord sur
un chiffre métier, le tableau de référence du § 4 fait foi** jusqu'au prochain
audit.

## 2. Documents du dossier

| Document | Objet | Public principal | Volume indicatif |
| --- | --- | --- | ---: |
| [`Analyse_TCO_ROI.pdf`](Analyse_TCO_ROI.pdf) | Coût total, retour sur investissement, coût des tokens, tableau FinOps | Direction, finance, jury | 17–19 pages |
| [`Conformite_RGPD.pdf`](Conformite_RGPD.pdf) | Registre des traitements, bases légales, droits des personnes, conservation, AIPD, sous-traitants | DPO, juriste, direction | 17–19 pages |
| [`EU_AI_Act_Equite.pdf`](EU_AI_Act_Equite.pdf) | Classement AI Act, grille des obligations, audit d'équité, plan de surveillance | Jury, conformité, data science | 19–22 pages |
| [`Mecanismes_Securite.pdf`](Mecanismes_Securite.pdf) | Modèle de menace, contrôles, preuves, risques résiduels, feuille de route | RSSI, exploitation, jury | 19–22 pages |
| [`Guide_Exploitation_Utilisateur.pdf`](Guide_Exploitation_Utilisateur.pdf) | Installation, configuration, runbooks, incidents, puis le guide d'utilisation par rôle | Exploitation, support, utilisateurs | 30–34 pages |

Les volumes sont indicatifs : ils correspondent à une mise en page A4 sobre,
hors annexes exceptionnellement longues.

## 3. Parcours de lecture par public

| Lecteur | Parcours recommandé | La question à laquelle il répond |
| --- | --- | --- |
| Jury | Index → 01 → 03 → 04 → 05 | Le projet est-il utile, mesuré, conforme et démontrable ? |
| Direction | Index → 01 (résumé et ROI) → 02 (risques) → 03 (classement) | Combien ça coûte, que rapporte la plateforme, que risque-t-on ? |
| DPO / juriste | 02 → 03 (partie AI Act) → 04 (sécurité) | Quelles données, quelles bases légales, quels droits, quels sous-traitants ? |
| RSSI | 04 → 05 (runbooks) → 02 (violations) | Quels contrôles sont réellement en place, et quels écarts restent ouverts ? |
| Exploitation | 05 → 04 (sauvegarde, TLS, rotation) → 01 (coûts) | Comment installer, superviser, sauvegarder, restaurer et dépanner ? |
| Produit / data | 03 (équité) → 01 (coût par requête) → 05 (BI) | Quelles performances, quels biais, quels coûts par usage ? |

## 4. Chiffres de référence

Tous les documents doivent reprendre ces valeurs, sauf mention explicite
d'une autre convention. La date de constat est le 21 octobre 2026.

### 4.1 Modèle de détection de fraude

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

### 4.2 Coûts et retour sur investissement

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

**Deux conventions coexistent, et il faut savoir laquelle on cite.** La
première ne compte que le coût des erreurs ; la seconde compare deux
organisations complètes du contrôle. Le dossier de cadrage et le document 01
n'emploient pas la même, donc leurs chiffres ne se superposent pas :

| | Convention historique | Convention recommandée |
| --- | ---: | ---: |
| Ce qui sert de référence | 9 208 non-fraudes contrôlées | 10 086 factures contrôlées |
| Coût du modèle | 4 968 000 MGA | 7 260 000 MGA |
| Économie | 22 656 000 MGA | 22 998 000 MGA |
| Ratio économie/TCO | 41,58× | 42,21× |
| Gain net | 22 111 150 MGA | 22 453 150 MGA |
| ROI net | 40,58× | 41,21× |
| Volume annuel retenu | 84 608 factures (dont 15 de démonstration) | 84 593 factures (jeu de données) |
| Économie annuelle projetée | 190,05 M MGA | 192,89 M MGA |
| Ratio annuel | 348,8× | 354,0× |
| Scénario prudent (50 % de l'économie, TCO stress) | 95,03 M MGA, 88,5× | 96,44 M MGA, 89,8× |

Le document 01 présente les deux et recommande la seconde : elle compte la
revue des 764 alertes, donc elle décrit une organisation de contrôle
réaliste. Un chiffre de l'une n'est jamais comparable à un chiffre de
l'autre.

> **Le terme « ROI » est souvent employé pour désigner le ratio
> `économie / TCO`. Ce n'est pas un ROI net.** Le document 01 sépare les trois
> notions — ratio de couverture, gain net, ROI net — et explique la
> différence.

### 4.3 Assistant documentaire et FinOps

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
| --- | ---: | --- |
| Conservation des prédictions | 3 ans | `rgpd/conservation.py` |
| Conservation des factures | 10 ans | `rgpd/conservation.py` |
| Conservation du journal d'audit | 5 ans | `rgpd/conservation.py` |
| Purge des données hors délai | Planifiée toutes les 24 h, tracée, désactivable par `PURGE_PLANIFIEE=0` | `apps/api-core/.../rgpd/purge.py` |
| Rétention des sauvegardes | 14 jours | `db/backup/pg_dump.sh` |
| Chiffrement des sauvegardes | AES-256-CBC, PBKDF2 200 000 itérations, clé fichier (si fournie) | `db/backup/pg_dump.sh` |
| Tests automatisés | 784 passés, 18 ignorés | `make test`, 21/10/2026 |
| Attaques RAG déclarées bloquées | 97 tests, 100 % des attaques déclarées | dossier de cadrage, à recouper |
| Garde-fous | 78 tests | dossier de cadrage, à recouper |
| SQL | 57 tests | dossier de cadrage, à recouper |
| RBAC | 22 tests | dossier de cadrage, à recouper |
| Chaîne n8n | 13/13 vérifications | dossier de cadrage, à recouper |
| Règles d'alerte Prometheus | 9 alertes versionnées | `ops/prometheus/rules/predicare.yml` |
| Vues Grafana provisionnées | 2 (service, modèle) | `ops/grafana/provisioning/dashboards/` |
| Registre des risques AI Act | 11 risques, art. 9 à 73 | `docs/cadrage/registre_risques.md` |
| Comparaison aux bases de décision | 3 baselines, même découpage | `reports/baselines_v2.md` |

## 5. Conventions de lecture

### 5.1 Statut d'une affirmation

Chaque chiffre porte une étiquette. Elle dit d'où il vient.

| Statut | Signification |
| --- | --- |
| **Mesuré** | Sortie réelle d'une commande, d'un test ou d'un rapport daté. |
| **Calculé** | Dérivé de mesures par une formule écrite. |
| **Estimé** | Fondé sur une hypothèse de coût, de volume ou de prix. |
| **Hypothèse** | Valeur posée par le métier, à valider avant production. |
| **Écart** | Fonction absente, partielle ou non prouvée. |

### 5.2 Vocabulaire de la conformité

Cinq mots reviennent partout. Les employer avec le même sens, c'est ce qui
permet de dire sans ambiguïté ce qui est fait et ce qui reste à faire.

- **conforme par conception** : la mesure existe dans l'architecture et dans
  les tests ; elle n'a pas été certifiée par un tiers ;
- **partiel** : une partie de l'obligation est couverte, une autre reste à
  faire ;
- **écart ouvert** : l'obligation n'est pas couverte, ou pas prouvée ;
- **non applicable** : l'obligation ne concerne pas le périmètre, avec
  justification ;
- **non certifié** : l'évaluation formelle, le marquage ou l'homologation ne
  sont pas prononcés.

Aucun document n'écrit « conforme », « certifié » ou « homologué » sans preuve
formelle.

### 5.3 Unités et dates

- Les montants métier sont en **ariary (MGA)**, ceux de l'infrastructure en
  **euro (EUR)**, ceux des tokens en **dollar (USD)**.
- Conversion de référence : **1 EUR = 5 000 MGA**. Elle doit être actualisée
  le jour d'une présentation officielle.
- Les dates des tableaux sont au format `2026-10-21` ; dans les paragraphes,
  elles s'écrivent en toutes lettres.
- Les prix d'hébergement sont des hypothèses datées, pas des devis.

### 5.4 Preuves attendues

Toute affirmation importante renvoie à une preuve : un fichier du dépôt avec
son chemin, une commande et sa sortie, un rapport daté, un test nommé, ou une
décision datée et attribuée. Les documents peuvent citer des documents
historiques, à condition d'en indiquer la date et de vérifier ce qui a changé
depuis.

## 6. Matrice de correspondance avec les exigences

| Exigence | Document principal | Sections |
| --- | --- | --- |
| TCO et ROI | 01 | Méthode, TCO consolidé, ROI, FinOps |
| Coût des tokens et cache | 01 | Économie des tokens, leviers FinOps |
| RGPD : cartographie et bases légales | 02 | Registre, bases légales, AIPD |
| RGPD : droits et conservation | 02 | Droits, conservation, purge |
| EU AI Act : classement | 03 | Fiche système, classification |
| EU AI Act : obligations haut risque | 03 | Grille articles 9 à 15, 17, 43, 48, 49, 72, 73 |
| Audit d'équité | 03 | Méthode, résultats, limites, mitigations |
| Sécurité | 04 | STRIDE, RBAC, chiffrement, réseau, assistant documentaire |
| Sauvegarde et restauration | 04 et 05 | Chiffrement, runbook, RPO/RTO |
| Supervision | 04 et 05 | Métriques, logs, dérive, tableaux de bord |
| Exploitation | 05 | Installation, configuration, incidents |
| Guide utilisateur | 05 | Parcours par rôle, FAQ, glossaire |

## 7. Sources de vérité par sujet

| Sujet | Source principale | Complément |
| --- | --- | --- |
| Modèle et métriques | `reports/modele_v2.md` | `reports/strategies_v1.md` |
| Comparaison aux bases de décision | `reports/baselines_v2.md` | `reports/baselines_v2.json` |
| Équité | `reports/equite_v2.md` | `reports/qualite_donnees_phase1_4.md` |
| Coûts et ROI | `docs/cadrage/dossier_cadrage.md` | `reports/modele_v2.md`, `apps/api-rag/README.md` |
| RGPD | `apps/api-core/src/predicare_core_api/rgpd/` | `docs/cadrage/dossier_cadrage.md` |
| Sécurité | `packages/predicare-core/src/predicare/rbac.py`, `audit.py`, `crypto.py` | `scripts/test-intrusion.sh`, `docs/cadrage/dossier_cadrage.md` |
| AI Act et risques | `docs/cadrage/registre_risques.md` | `docs/livrables/EU_AI_Act_Equite.pdf` |
| Exploitation | `docs/livrables/Guide_Exploitation_Utilisateur.pdf` | `.env.example`, `Makefile`, `db/backup/pg_dump.sh` |
| Utilisateur | `docs/livrables/Guide_Exploitation_Utilisateur.pdf` | interface web et tests Playwright |
| BI | `ops/superset/` | `ops/superset/creer_tableau_bord.md` |
| Supervision | `ops/prometheus/rules/predicare.yml` | `ops/grafana/provisioning/` |
| Tests | `make check` | rapports datés |

## 8. Avertissements

- Les données du modèle sont **synthétiques**. Les performances et le ROI ne
  sont pas une mesure de production.
- Le classement AI Act « haut risque » est une **lecture prudente**. Il doit
  être confirmé par un avis juridique avant mise sur le marché.
- Le rôle RGPD de l'éditeur de la plateforme dépend du contrat de
  déploiement : selon le cas, il est sous-traitant ou responsable de
  traitement.
- Les prix d'infrastructure sont des **hypothèses**, pas des devis.
- Le PDF `docs/cadrage/dossier_cadrage.pdf` reste daté du 20 octobre 2026. Le
  Markdown est la source à jour ; le PDF doit être régénéré après validation.
- Aucun secret réel ne doit être copié dans ces documents.

## 9. Maintenance du dossier

| Événement | Document à mettre à jour | Vérification |
| --- | --- | --- |
| Nouveau modèle ou nouveau seuil | 01, 03, index | `reports/modele_v2.md`, `/api/inference/modele` |
| Changement de coût ou de volume | 01, index | `apps/api-rag/README.md`, Prometheus |
| Nouvelle obligation ou nouveau pays | 02, 03 | avis DPO/juriste |
| Nouvelle mesure de sécurité | 04, 05 | test, script, revue |
| Nouveau service ou nouvelle commande | 05 | `make help`, README |
| Nouvelle version de l'interface | 05 | tests Playwright du parcours |
| Nouvelle campagne de tests | index, 04 | `make test`, rapport daté |
| Nouveau risque identifié | 03, `docs/cadrage/registre_risques.md` | revue du registre |

## 10. Historique des versions

| Version | Date | Changement |
| --- | --- | --- |
| 1.0 | 2026-10-21 | Création des cinq livrables, index, chiffres de référence et conventions. |
| 1.1 | 2026-10-21 | Guide utilisateur fusionné dans le document 05 ; purge planifiée, règles d'alerte Prometheus, vues Grafana, registre des risques AI Act, comparaison aux bases de décision et import PDF ajoutés ; nombre de tests revenu à 784 ; tableau de correspondance des deux conventions de ROI. |
