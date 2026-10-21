# Analyse TCO, ROI et FinOps

**PrediCare — coût total de possession, économie de contrôle et pilotage des coûts**

|           |                                                                                        |
| --------- | -------------------------------------------------------------------------------------- |
| Périmètre | Infrastructure, tokens LLM, sauvegarde, exploitation de la plateforme de démonstration |
| Devise    | EUR pour l'infrastructure, USD pour les tokens, MGA pour le métier                     |

## 1. Résumé

PrediCare coûte **108,97 € par an** dans son scénario de base : un serveur virtuel de 4 vCPU et 8 Go, une sauvegarde quotidienne chiffrée lorsque la clé est configurée et 1 000 questions RAG par mois. Ce montant reste inférieur à **10 € par mois**. Dans le scénario de stress, avec 10 000 questions par mois et un serveur plus cher, le TCO monte à **214,78 € par an**. Dans le scénario conservateur, qui applique le tarif LLM le plus défavorable et 10 000 questions par mois, il atteint **390,86 € par an**.

Le poste dominant n'est pas le LLM. En base, l'infrastructure représente **93,5 %** du TCO et les tokens **6,5 %**. À 10 000 questions par mois, les tokens montent à **33 %**. En conservateur, ils deviennent majoritaires à **63 %**. La conséquence est simple : le premier levier FinOps est le dimensionnement de l'infrastructure ; le second est la maîtrise du prompt et du cache.

Le modèle de fraude produit, sur le jeu de test, une économie de coûts de contrôle de **22,66 millions MGA** selon la convention historique du dossier, ou **22,998 millions MGA** si l'on compare à un contrôle exhaustif incluant la revue des alertes. Le ratio économie/TCO est de **41,6×** dans la convention historique et de **42,2×** dans la convention recommandée. Ce n'est pas un ROI net : le gain net est de l'ordre de **22,1 à 22,5 millions MGA**, et le ROI net de l'ordre de **40,6× à 41,2×**.

Ces chiffres sont des **mesures sur données synthétiques** et des **hypothèses de coût**. Ils ne constituent ni une promesse de recouvrement, ni une économie comptable certaine. Ils montrent qu'à volume constant, le coût de la plateforme est très inférieur au coût des contrôles qu'elle permet d'éviter. La décision de production doit encore valider le taux de fraude réel, le coût d'un contrôle et la capacité à réaffecter les heures libérées.

## 2. Méthode et périmètre

### 2.1 Ce que mesure le TCO

Le TCO couvre les coûts nécessaires pour faire tourner la plateforme :

- l'hébergement : serveur, système, reverse proxy, volumes ;
- la sauvegarde : stockage des archives et rétention ;
- les tokens LLM : entrée et sortie du modèle `gpt-4o-mini` ;
- les services inclus dans le même serveur : API, interface, Superset, Prometheus, Grafana, n8n ;
- l'exploitation de base : scripts, supervision, sauvegarde, mises à jour.

Le TCO ne couvre pas :

- le temps de développement et de maintenance évolutive ;
- le temps des gestionnaires qui traitent les alertes ;
- les licences tierces, l'assurance, le support éditeur ;
- les coûts juridiques, DPO, audit externe ;
- les coûts de mise en production, de migration et de formation ;
- les coûts de sortie de production et de réversibilité.

Cette frontière est volontaire : le TCO répond à la question « combien coûte la plateforme ? », pas à la question « combien coûte l'organisation de contrôle ? ». Le ROI, lui, compare la plateforme à un mode de contrôle de référence. Les deux périmètres sont donc différents et doivent être lus ensemble, jamais confondus.

### 2.2 Ce que mesure le ROI

Le ROI compare le coût du contrôle avec et sans modèle :

- **Coût de référence** : contrôle exhaustif des factures, avec un coût unitaire de contrôle ;
- **Coût avec modèle** : traitement des alertes par un gestionnaire, plus le coût des fraudes manquées ;
- **Économie** : différence entre les deux ;
- **TCO** : coût de la plateforme ;
- **Gain net** : économie moins TCO ;
- **ROI net** : gain net divisé par TCO.

Le coût d'un faux positif est fixé à **3 000 MGA** : c'est le coût d'un contrôle inutile. Le coût d'un faux négatif est fixé à **30 000 MGA** : c'est le coût d'une fraude non détectée. Ces valeurs sont des **hypothèses métier** du projet, pas des mesures comptables. Elles sont justifiées par un rapport de 1 à 10 entre le contrôle et la fraude, et elles doivent être validées par le métier avant production.

### 2.3 Conventions

| Élément                   |                    Valeur | Nature                     |
| ------------------------- | ------------------------: | -------------------------- |
| Conversion EUR → MGA      |         1 EUR = 5 000 MGA | Convention de présentation |
| Conversion USD → EUR      |          1 USD ≈ 0,92 EUR | Convention de présentation |
| Volume de base            |  1 000 questions RAG/mois | Hypothèse                  |
| Volume de stress          | 10 000 questions RAG/mois | Hypothèse                  |
| Volume annuel de factures |                    84 593 | Taille du jeu de données   |
| Taux de fraude du test    |                     8,7 % | Mesure                     |
| Coût d'un contrôle        |                 3 000 MGA | Hypothèse                  |
| Coût d'une fraude manquée |                30 000 MGA | Hypothèse                  |

Les prix d'hébergement sont des prix publics indicatifs d'octobre 2026, pas des devis. Le taux de conversion et les prix doivent être actualisés le jour d'une présentation officielle.

## 3. Architecture de coûts

La plateforme tient dans un seul serveur de démonstration. Cette simplicité est un choix économique : elle évite de multiplier les services managés, les licences et les coûts de coordination. Elle a aussi une limite : le serveur est un point unique de défaillance et la marge mémoire est étroite.

| Poste         | Ce qu'il inclut                              | Nature          | Déterminant                          |
| ------------- | -------------------------------------------- | --------------- | ------------------------------------ |
| Serveur       | 4 vCPU, 8 Go, 80 Go, OS, Docker, Traefik     | Fixe            | Dimensionnement                      |
| Sauvegarde    | Archive chiffrée, 14 jours, stockage objet   | Variable faible | Taille de la base                    |
| Tokens LLM    | Entrée, sortie, système, sources, historique | Variable        | Nombre de questions, top-k, sessions |
| Superset      | Un conteneur, métadonnées, dashboards        | Inclus          | Mémoire                              |
| Observabilité | Prometheus, Grafana, logs                    | Inclus          | Rétention, cardinalité               |
| n8n           | Workflows de notification                    | Inclus          | Exécutions                           |
| Exploitation  | Scripts, sauvegarde, supervision             | Fixe            | Temps humain non chiffré             |

Le socle applicatif consomme environ **4,5 Go** de mémoire ; la pile complète avec les overlays atteint environ **6,5 Go**. Un serveur de 8 Go suffit pour la démonstration, mais la marge est faible. Le scénario de base retient ce dimensionnement. Le scénario de stress retient un serveur à 12 €/mois, ce qui laisse une marge pour les pics et les rebuilds.

## 4. TCO détaillé

### 4.1 Infrastructure

| Poste                         |            Base |          Stress | Commentaire                     |
| ----------------------------- | --------------: | --------------: | ------------------------------- |
| VPS 4 vCPU / 8 Go / 80 Go     |     8,49 €/mois |    12,00 €/mois | Prix public indicatif           |
| Coût annuel                   |    **101,88 €** |    **144,00 €** | 12 mois                         |
| Sauvegarde, 177 Mo en base    |       0,02 €/an |       0,12 €/an | Stockage objet à 0,01 €/Go/mois |
| Sauvegarde, 1 Go en stress    |               — |          inclus | 14 jours de rétention           |
| **Sous-total infrastructure** | **101,90 €/an** | **144,12 €/an** | Hors tokens                     |

La machine de démonstration de l'équipe coûte **0 €** : le scénario ci-dessus est le coût de l'hébergement si la plateforme quitte le poste de développement. Il inclut l'OS, le reverse proxy, les volumes et les services internes. Il n'inclut pas les postes de travail des utilisateurs.

### 4.2 Tokens

Le RAG utilise `gpt-4o-mini`. Sur les 30 questions de référence, la consommation mesurée est de **111 742 tokens** : 108 501 en entrée et 3 241 en sortie. Cela représente **3 725 tokens par question**, dont 97 % en entrée. Le prompt, les sources et l'historique dominent donc le coût.

| Mesure                        |                     Valeur | Source                               |
| ----------------------------- | -------------------------: | ------------------------------------ |
| Tokens par question           |                      3 725 | `reports/eval_rag_2026-10-19_5.json` |
| Coût au tarif du service      | 0,00064 USD (~0,00059 EUR) | `apps/api-rag/README.md`             |
| Coût conservateur             |                0,00223 USD | même rapport                         |
| Coût de l'évaluation complète |                 0,0670 USD | même rapport                         |

Le tarif conservateur surestime le coût d'environ 3,5 fois, mais il ne dépend d'aucune hypothèse de répartition entrée/sortie. Il est utilisé pour le scénario le plus défavorable.

| Volume                |     Base, 0,00064 USD/q | Conservateur, 0,00223 USD/q |
| --------------------- | ----------------------: | --------------------------: |
| 1 000 questions/mois  |   7,68 USD/an (~7,07 €) |     26,82 USD/an (~24,67 €) |
| 10 000 questions/mois | 76,80 USD/an (~70,66 €) |   268,20 USD/an (~246,74 €) |

### 4.3 TCO consolidé

| Poste                    |            Base |            Stress |      Conservateur |
| ------------------------ | --------------: | ----------------: | ----------------: |
| Infrastructure           |        101,88 € |          144,00 € |          144,00 € |
| Sauvegarde               |          0,02 € |            0,12 € |            0,12 € |
| Tokens RAG               |          7,07 € |           70,66 € |          246,74 € |
| **Total annuel**         |    **108,97 €** |      **214,78 €** |      **390,86 €** |
| **Total mensuel moyen**  |      **9,08 €** |       **17,90 €** |       **32,57 €** |
| **Total en MGA**         | **544 850 MGA** | **1 073 900 MGA** | **1 954 300 MGA** |
| Part de l'infrastructure |          93,5 % |            67,0 % |            36,8 % |
| Part des tokens          |           6,5 % |            33,0 % |            63,1 % |

Le coût par facture, à volume annuel constant et hors temps humain, est de **6,44 MGA** (environ **0,00129 €**) en base. Ce chiffre est un coût de plateforme, pas un coût complet de traitement. Il ne doit pas être présenté comme le coût d'une facture pour l'assureur.

### 4.4 Sauvegarde et restauration

La sauvegarde est un `pg_dump` compressé, exécuté quotidiennement, conservé **14 jours**. Une sauvegarde de la base de démonstration pèse **12,66 Mo**. La base pèse environ **110 Mo**. Les 14 archives représentent environ **177 Mo**.

| Élément                            |      Valeur |
| ---------------------------------- | ----------: |
| Taille de la base                  |      110 Mo |
| Taille d'une sauvegarde compressée |    12,66 Mo |
| Rétention                          |    14 jours |
| Volume conservé                    |     ~177 Mo |
| Coût de stockage                   | < 0,12 €/an |

Depuis la mise à jour du script, l'archive est chiffrée lorsque la clé est présente : **AES-256-CBC**, dérivation **PBKDF2 200 000 itérations**, clé lue depuis un fichier. La restauration est une commande explicite, avec confirmation et sauvegarde de sécurité préalable. Le test de restauration complet reste une action de recette avant production ; il n'est pas encore automatisé dans la CI.

## 5. ROI

### 5.1 Matrice de confusion

Le modèle v2, au seuil **0,2876**, produit sur le jeu de test :

|                  | Fraude réelle | Non-fraude réelle |
| ---------------- | ------------: | ----------------: |
| **Alerte**       |      764 (VP) |          516 (FP) |
| **Pas d'alerte** |      114 (FN) |        8 692 (VN) |

Le jeu contient **10 086 factures** et **878 fraudes**, soit **8,7 %**. Le rappel est de **87,0 %**, la précision de **59,7 %**. Le modèle laisse donc passer 114 fraudes et déclenche 516 contrôles inutiles. Ces deux erreurs ont un coût, mais elles ne sont pas symétriques.

### 5.2 Convention historique du dossier

La convention historique compte :

- les faux positifs à 3 000 MGA ;
- les faux négatifs à 30 000 MGA ;
- les vrais positifs à 0 MGA dans le coût du modèle ;
- la référence comme « toutes les non-fraudes contrôlées », soit 9 208 × 3 000.

| Scénario                    | Calcul                     |               Coût |
| --------------------------- | -------------------------- | -----------------: |
| Au seuil 0,2876             | 516 × 3 000 + 114 × 30 000 |  **4 968 000 MGA** |
| Référence « erreurs FP/FN » | 9 208 × 3 000              |     27 624 000 MGA |
| **Économie**                | 27 624 000 − 4 968 000     | **22 656 000 MGA** |

Cette convention est utile pour comparer des seuils entre eux, mais elle ne représente pas un contrôle exhaustif : elle ne compte pas la revue des 764 vrais positifs. Elle doit donc être appelée **coût des erreurs**, pas **coût complet du contrôle**.

### 5.3 Convention recommandée : contrôle exhaustif

La convention recommandée compare deux organisations complètes :

- **Référence** : toutes les factures sont contrôlées, soit 10 086 × 3 000 = **30 258 000 MGA** ; l'hypothèse est que le contrôle exhaustif détecte toute fraude ;
- **Modèle** : les 1 280 alertes sont revues, soit 1 280 × 3 000 = 3 840 000 MGA, et les 114 fraudes manquées coûtent 114 × 30 000 = 3 420 000 MGA, soit **7 260 000 MGA** ;
- **Économie** : 30 258 000 − 7 260 000 = **22 998 000 MGA**.

| Scénario                      | Calcul                       |               Coût |
| ----------------------------- | ---------------------------- | -----------------: |
| Contrôle exhaustif            | 10 086 × 3 000               | **30 258 000 MGA** |
| Modèle avec revue des alertes | 1 280 × 3 000 + 114 × 30 000 |  **7 260 000 MGA** |
| **Économie**                  | 30 258 000 − 7 260 000       | **22 998 000 MGA** |

L'écart avec la convention historique est de **342 000 MGA**, soit **1,5 %**. Il est faible, mais il change la lecture : l'économie n'est pas « 22,66 M » par miracle, elle est « environ 23 M » dans les deux conventions, avec une définition différente de la référence.

### 5.4 Ratios et gain net

| Convention         |       Économie | TCO de base | Ratio économie/TCO |       Gain net |    ROI net |
| ------------------ | -------------: | ----------: | -----------------: | -------------: | ---------: |
| Historique         | 22 656 000 MGA | 544 850 MGA |         **41,58×** | 22 111 150 MGA | **40,58×** |
| Contrôle exhaustif | 22 998 000 MGA | 544 850 MGA |         **42,21×** | 22 453 150 MGA | **41,21×** |

Le ratio de **41,6×** souvent cité est donc le rapport entre l'économie et le TCO, pas le retour net. Le ROI net est légèrement inférieur, autour de **40,6×**. La différence est faible à cette échelle, mais le vocabulaire doit être exact.

### 5.5 Projection annuelle

Le jeu de données contient **84 593 factures** ; le test en contient 10 086, soit un facteur **8,387**. À taux de fraude et coût unitaire constants :

| Scénario                                     | Factures/an |     Économie |         TCO | Ratio économie/TCO | ROI net |
| -------------------------------------------- | ----------: | -----------: | ----------: | -----------------: | ------: |
| Test mesuré, convention historique           |      10 086 |  22,66 M MGA | 0,545 M MGA |              41,6× |   40,6× |
| Test mesuré, contrôle exhaustif              |      10 086 |  23,00 M MGA | 0,545 M MGA |              42,2× |   41,2× |
| Annuel à volume constant, contrôle exhaustif |      84 593 | 192,89 M MGA | 0,545 M MGA |             354,0× |  353,0× |
| Prudent : 50 % de l'économie, TCO stress     |      84 593 |  96,44 M MGA | 1,074 M MGA |              89,8× |   88,8× |

L'économie par facture est d'environ **2 280 MGA** dans la convention recommandée. Le seuil de rentabilité de la plateforme, hors temps humain, est donc d'environ **239 factures par an** : au-delà, l'économie de contrôle dépasse le TCO de base. Ce calcul suppose que le modèle conserve ses performances et que le coût du contrôle reste à 3 000 MGA.

### 5.6 Sensibilité au coût d'une fraude manquée

Le coût d'un faux négatif est l'hypothèse la plus influente. À seuil et performances constants :

| Coût d'un FN |    Coût modèle |       Économie | Ratio économie/TCO |
| -----------: | -------------: | -------------: | -----------------: |
|   15 000 MGA |  5 550 000 MGA | 24 708 000 MGA |             45,35× |
|   30 000 MGA |  7 260 000 MGA | 22 998 000 MGA |             42,21× |
|   60 000 MGA | 10 680 000 MGA | 19 578 000 MGA |             35,93× |

Le modèle reste économiquement favorable dans les trois cas. La conclusion serait différente si le coût d'un contrôle augmentait fortement ou si le taux de fraude réelle s'effondrait. C'est pourquoi le scénario prudent ne retient que 50 % de l'économie.

## 6. Tableau FinOps

### 6.1 Allocation des coûts

| Domaine                 |        Base |      Stress | Propriétaire   | Fréquence de revue |
| ----------------------- | ----------: | ----------: | -------------- | ------------------ |
| Infrastructure          |    101,88 € |    144,00 € | Exploitation   | Mensuelle          |
| Sauvegarde              |      0,02 € |      0,12 € | Exploitation   | Mensuelle          |
| Tokens RAG              |      7,07 € |     70,66 € | Produit / data | Hebdomadaire       |
| Observabilité           |      inclus |      inclus | Exploitation   | Mensuelle          |
| BI Superset             |      inclus |      inclus | Produit        | Mensuelle          |
| Support et exploitation | non chiffré | non chiffré | Direction      | Trimestrielle      |

### 6.2 Indicateurs de pilotage

| Indicateur               | Formule                                   | Cible                  | Alerte      |
| ------------------------ | ----------------------------------------- | ---------------------- | ----------- |
| Coût par requête         | `predicare_llm_cost_usd_total / requêtes` | ≤ 0,00064 USD          | > 0,001 USD |
| Tokens par requête       | tokens prompt + completion / requêtes     | ≤ 3 725                | > 4 500     |
| Taux de cache            | hits / (hits + miss)                      | > 10 % à volume stable | < 5 %       |
| Coût par alerte          | coût plateforme / alertes                 | < 10 €                 | > 25 €      |
| Taux d'occupation disque | disque utilisé / disque                   | < 70 %                 | > 80 %      |
| Taille des sauvegardes   | somme des archives                        | < 1 Go                 | > 2 Go      |
| Écart budget             | dépense / budget                          | ≤ 100 %                | > 120 %     |

### 6.3 Leviers

| Levier                                | Effet attendu                     | Coût         | Décision                      |
| ------------------------------------- | --------------------------------- | ------------ | ----------------------------- |
| Cache sémantique                      | 0 token et 0 ms de LLM sur un hit | Déjà actif   | Conserver, surveiller le taux |
| Réduire `RAG_TOP_K`                   | Moins de tokens d'entrée          | Réglage      | À arbitrer avec la fidélité   |
| Réduire `SESSION_MAX_TURNS`           | Moins d'historique rejoué         | Réglage      | À arbitrer avec le suivi      |
| Modèle `gpt-4o-mini`                  | Coût maîtrisé                     | Déjà actif   | Ne pas changer sans mesure    |
| Plafond de débit Traefik              | Protège le quota LLM              | Déjà actif   | Maintenir                     |
| Alerte `predicare_llm_cost_usd_total` | Détecte une dérive                | À configurer | Priorité P1                   |
| Dimensionnement serveur               | Premier poste de coût             | À revoir     | Revoir avant montée en charge |

Le cache sémantique a été mesuré sur deux hits : **10,48 s** et **0,00064 €** évités. C'est une preuve de fonctionnement, pas une prévision de taux de réutilisation. En production, le taux dépendra de la répétition réelle des questions. Un taux faible n'est pas une anomalie : il indique simplement que les utilisateurs posent des questions variées.

### 6.4 Gouvernance FinOps

La boucle de pilotage est simple :

1. **Informer** : collecter les métriques Prometheus et les coûts fournisseur.
2. **Allouer** : rattacher les coûts à un domaine (infrastructure, RAG, BI, exploitation).
3. **Optimiser** : agir sur le levier qui a le meilleur rapport effet/risque.
4. **Gouverner** : fixer un budget, un seuil d'alerte et un propriétaire.

La revue mensuelle doit tenir sur une page : TCO réel, écart au budget, coût par requête, taux de cache, nombre d'alertes, incidents. Une dérive de tokens sans dérive de trafic est un signal de prompt ou de cache, pas un signal de croissance.

## 7. Limites

- Le TCO n'inclut pas le temps de développement, de support, de formation, de DPO ou d'audit.
- Le TCO n'inclut pas le coût des gestionnaires qui traitent les alertes.
- Le ROI est un **coût de contrôle évité**, pas une fraude recouvrée ni une économie comptable certaine.
- Les coûts unitaires de 3 000 et 30 000 MGA sont des hypothèses métier.
- L'extrapolation annuelle suppose un taux de fraude et une performance identiques à ceux du test.
- Le modèle est entraîné sur des données synthétiques ; le rappel de 87,0 % n'est pas une mesure de production.
- Les prix d'hébergement et le taux de conversion sont datés et doivent être actualisés.
- Le scénario prudent ne constitue pas une borne inférieure garantie.

## 8. Décisions recommandées

| Décision                                                         | Justification                       | Échéance               |
| ---------------------------------------------------------------- | ----------------------------------- | ---------------------- |
| Conserver le TCO de base comme référence de communication        | Il est mesuré et stable             | Immédiat               |
| Présenter le 41,6× comme ratio économie/TCO                      | Éviter la confusion avec le ROI net | Immédiat               |
| Utiliser la convention « contrôle exhaustif » pour les décisions | Elle inclut la revue des alertes    | Avant production       |
| Valider les coûts 3 000 / 30 000 MGA avec le métier              | Ils déterminent le seuil et le ROI  | Avant production       |
| Configurer l'alerte de coût LLM                                  | Détecter une dérive                 | P1                     |
| Tester une restauration complète                                 | Prouver la sauvegarde               | Avant production       |
| Revoir le dimensionnement à 10 000 questions/mois                | Les tokens deviennent 33 % du TCO   | Avant montée en charge |

## 9. Annexes

### 9.1 Formules

```text
TCO = infrastructure + sauvegarde + tokens
Coût modèle = alertes revues × coût de contrôle + FN × coût d'une fraude manquée
Référence contrôle exhaustif = factures × coût de contrôle
Économie = référence - coût modèle
Gain net = économie - TCO
Ratio économie/TCO = économie / TCO
ROI net = (économie - TCO) / TCO
Projection annuelle = économie du test × (84 593 / 10 086)
```

### 9.2 Registre des hypothèses

| Hypothèse                 |                  Valeur | Sensibilité | Validation   |
| ------------------------- | ----------------------: | ----------- | ------------ |
| Coût d'un contrôle        |               3 000 MGA | Forte       | Métier       |
| Coût d'une fraude manquée |              30 000 MGA | Très forte  | Métier       |
| Volume de questions       | 1 000 / 10 000 par mois | Moyenne     | Produit      |
| Prix du VPS               |     8,49 / 12,00 €/mois | Faible      | Devis        |
| Taux de conversion        |           5 000 MGA/EUR | Moyenne     | Jour J       |
| Taux de fraude            |                   8,7 % | Très forte  | Production   |
| Performance du modèle     |           Rappel 87,0 % | Très forte  | Surveillance |
