# Rapport de conformité RGPD

**PrediCare — données de santé, pseudonymisation, droits des personnes et gouvernance**

|             |                                                                                                                        |
| ----------- | ---------------------------------------------------------------------------------------------------------------------- |
|             |
| Périmètre   | Traitements de la plateforme PrediCare : identité, facturation, détection de fraude, assistant RAG, audit, sauvegardes |
| Référentiel | Règlement (UE) 2016/679 (RGPD), lignes directrices CNIL, droit national applicable                                     |

## 1. Résumé exécutif

PrediCare traite des données personnelles sensibles : identité des assurés, actes de santé, montants, dates, prestataires, scores de fraude et explications SHAP. Le traitement est donc soumis à une vigilance renforcée : minimisation, pseudonymisation, chiffrement, cloisonnement des accès, durée de conservation bornée et droits des personnes.

La plateforme est **conforme par conception** sur plusieurs points démontrables :

- les noms et coordonnées sont isolés dans une table chiffrée ;
- les factures ne portent qu'un pseudonyme stable ;
- les accès sont filtrés côté serveur par rôle et par dossier ;
- les droits d'export, de rectification, d'opposition et d'effacement sont implémentés ;
- les durées de conservation sont codées : **3 ans** pour les prédictions, **10 ans** pour les factures, **5 ans** pour le journal d'audit ;
- les sauvegardes sont chiffrées lorsque la clé est fournie ;
- la connexion et les actions sensibles sont journalisées.

La plateforme n'est **pas certifiée** et plusieurs écarts restent ouverts :

- la purge est **manuelle**, pas planifiée ;
- l'effacement ne purge pas immédiatement les sauvegardes ;
- le droit à la limitation n'est pas implémenté ;
- la rectification, l'opposition et l'effacement passent par un administrateur, sans interface self-service ;
- le registre des traitements formel, la désignation du DPO, les contrats de sous-traitance et l'AIPD restent à finaliser ;
- la procédure de notification de violation sous 72 heures n'est pas écrite ;
- les transferts hors UE et les clauses contractuelles types doivent être documentés.

## 2. Rôles et gouvernance

### 2.1 Rôles

| Acteur          | Rôle RGPD                      | Commentaire                                                               |
| --------------- | ------------------------------ | ------------------------------------------------------------------------- |
| Assureur client | Responsable de traitement      | Détermine les finalités, les moyens et les durées                         |
| PrediCare       | Sous-traitant                  | Héberge, maintient et exploite la plateforme pour le compte de l'assureur |
| OpenAI          | Sous-traitant ultérieur        | Reçoit les questions, les extraits de contrats et l'historique minimisé   |
| Slack           | Sous-traitants de notification | Reçoivent une référence de facture, un score et un rapport SHAP           |
| Hébergeur       | Sous-traitant                  | Héberge la base, les sauvegardes et les artefacts                         |
| DPO             | À désigner                     | Point de contact, registre, AIPD, conseil                                 |
| Gestionnaire    | Personne habilitée             | Décide après examen humain, dans le périmètre de son rôle                 |
| Administrateur  | Personne habilitée             | Gère les comptes, les droits RGPD, les seuils et les secrets              |

Cette répartition doit être confirmée par le contrat de déploiement. Si PrediCare détermine lui-même les finalités ou les moyens, il devient responsable de traitement et les obligations changent. Le document ne présume pas la qualification contractuelle.

### 2.2 Gouvernance à mettre en place

| Élément                    | État                              | Action                                              |
| -------------------------- | --------------------------------- | --------------------------------------------------- |
| Registre des traitements   | Première version dans ce document | Reprendre dans l'outil du DPO                       |
| Désignation du DPO         | Non formalisée                    | Désigner et publier le contact                      |
| Politique de conservation  | Codée, pas encore approuvée       | Faire valider les durées                            |
| AIPD                       | Matière fournie, non réalisée     | Réaliser et consulter le DPO                        |
| Contrats de sous-traitance | Connus, non signés                | Signer les DPA et clauses de transfert              |
| Procédure de violation     | Non écrite                        | Rédiger le runbook 72 h                             |
| Formation des utilisateurs | Non formalisée                    | Former au score, à l'humain et à la confidentialité |
| Revue annuelle             | Non planifiée                     | Fixer une revue de conformité                       |

## 3. Registre des traitements

Le tableau ci-dessous est une proposition de registre. Les bases légales et les durées doivent être validées par le DPO.

| Traitement                   | Personnes                      | Données                                              | Finalité                  | Base légale proposée                                    | Conservation                    |
| ---------------------------- | ------------------------------ | ---------------------------------------------------- | ------------------------- | ------------------------------------------------------- | ------------------------------- |
| Identité assuré              | Assurés                        | Nom, coordonnées, date de naissance, référence       | Gestion du contrat        | Exécution du contrat, art. 6.1.b                        | Durée du contrat + prescription |
| Facturation et remboursement | Assurés, prestataires          | Actes, montants, dates, diagnostic, ordonnance       | Prise en charge           | Exécution du contrat ; obligation légale                | 10 ans pour les factures        |
| Détection de fraude          | Assurés, prestataires          | Factures pseudonymisées, score, SHAP, décision       | Prévention de la fraude   | Intérêt légitime, art. 6.1.f ; art. 9.2.f pour la santé | 3 ans pour les prédictions      |
| Assistant RAG                | Assurés                        | Question, historique de session, extraits de contrat | Information contractuelle | Exécution du contrat, art. 6.1.b                        | Session 1 h ; logs 30 jours     |
| Audit et décisions           | Gestionnaires, administrateurs | Acteur, rôle, action, cible, décision, commentaire   | Traçabilité et conformité | Obligation légale, art. 6.1.c ; intérêt légitime        | 5 ans                           |
| Sauvegardes                  | Tous                           | Copie de la base                                     | Continuité et reprise     | Intérêt légitime                                        | 14 jours                        |
| Notifications                | Assurés, gestionnaires         | Référence, score, SHAP                               | Alerte opérationnelle     | Exécution du contrat ; intérêt légitime                 | Selon le canal, à documenter    |
| Formation du modèle          | Assurés (si données réelles)   | Factures, étiquettes                                 | Amélioration du modèle    | À définir ; données synthétiques aujourd'hui            | Durée du projet                 |

Deux points sont structurants :

- **Les données de santé** sont présentes dans les actes, les diagnostics et les ordonnances. L'article 9 du RGPD exige une base spécifique. L'article 9.2.f (constatation, exercice ou défense d'un droit en justice) ou l'article 9.2.h (médecine) doivent être retenus selon le montage ; l'intérêt légitime de l'article 6 ne suffit pas à lui seul.
- **Le scoring de fraude** ne doit pas produire un effet juridique automatique. La décision est humaine, tracée et contestable. C'est une mesure de conformité, pas seulement un choix produit.

## 4. Bases légales et finalités

### 4.1 Gestion du contrat et remboursement

La base principale est l'exécution du contrat d'assurance. Les données de santé sont nécessaires à la prise en charge. La minimisation impose de ne collecter que les actes et pièces nécessaires, et de ne pas exposer les noms dans les écrans de contrôle qui n'en ont pas besoin.

### 4.2 Détection de fraude

L'intérêt légitime est plausible : l'assureur a un intérêt à prévenir la fraude et à maîtriser ses coûts. Mais il exige une mise en balance :

- nécessité : le score aide à prioriser les contrôles, il ne remplace pas la décision ;
- proportionnalité : les faux positifs ne doivent pas retarder indûment un remboursement ;
- transparence : la personne doit être informée du traitement et de ses droits ;
- garanties : pseudonymisation, accès restreint, audit, décision humaine.

La décision négative doit pouvoir être contestée. Le score n'est pas une preuve de fraude ; c'est un signal de priorisation.

### 4.3 Assistant RAG

L'assistant répond à des questions contractuelles. La base est l'exécution du contrat. Les questions peuvent contenir des données de santé ou des éléments de dossier ; la minimisation consiste à ne pas demander de nom, à limiter la longueur, à cloisonner la session et à ne pas conserver l'historique au-delà d'une heure.

Le fournisseur LLM reçoit la question, les extraits de contrats et l'historique. Il ne reçoit pas les noms si l'utilisateur ne les saisit pas. Le prompt système et les sources sont séparés de la question pour limiter l'injection.

### 4.4 Audit et sécurité

Le journal d'audit est nécessaire pour prouver les décisions, détecter les accès anormaux et répondre à une violation. Il est conservé 5 ans, mais il est anonymisé en cas d'effacement d'un dossier. La tension entre obligation de traçabilité et droit à l'effacement est traitée explicitement : l'action et l'horodatage restent, le pseudonyme disparaît.

## 5. Minimisation et pseudonymisation

### 5.1 Mesures en place

| Mesure                      | Implémentation                                        | Preuve                                                   |
| --------------------------- | ----------------------------------------------------- | -------------------------------------------------------- |
| Identités chiffrées         | Fernet (AES-128-CBC + HMAC), clé dans l'environnement | `packages/predicare-core/src/predicare/crypto.py`        |
| Pseudonyme stable           | HMAC-SHA256 avec `APP_SECRET_KEY`                     | même fichier                                             |
| Aucun nom dans les factures | `core.facture` ne porte que `assure_id`               | migrations                                               |
| Cloisonnement du cache RAG  | clé `assure_id` ou `user:{subject}`                   | `apps/api-rag/src/predicare_rag_api/main.py`             |
| Filtre SQL par assuré       | compte lecture seule + paramètre lié                  | `apps/api-rag/src/predicare_rag_api/sql_tool.py`         |
| Filtre prestataire          | `facture.prestataire_id = prestataire du compte`      | `apps/api-core/src/predicare_core_api/billing/router.py` |
| Journal d'audit             | acteur, rôle, action, cible, détails                  | `audit.journal`                                          |
| Connexion tracée            | action `connexion`                                    | `identity/router.py`                                     |

### 5.2 Limites

Le pseudonyme est stable : il permet de relier les factures d'une même personne, ce qui est nécessaire au contrôle. Il ne rend donc pas la personne anonyme. La ré-identification reste possible si l'attaquant obtient la clé Fernet et la table des identités. C'est pourquoi la clé est séparée, chiffrée par l'environnement et rotative.

Les logs applicatifs peuvent contenir des références de factures, des scores et des identifiants pseudonymisés. Ils ne doivent pas contenir de noms, de coordonnées, de diagnostic en clair ni de jeton. Une revue des logs est nécessaire avant production.

## 6. Conservation et purge

### 6.1 Durées

| Donnée              |                           Durée | État                     |
| ------------------- | ------------------------------: | ------------------------ |
| Identités chiffrées | Durée du contrat + prescription | À valider                |
| Factures            |                          10 ans | Codé                     |
| Prédictions         |                           3 ans | Codé                     |
| Journal d'audit     |                           5 ans | Codé                     |
| Sessions RAG        |                         1 heure | Codé dans Redis          |
| Logs applicatifs    |                        30 jours | Configuration à vérifier |
| Sauvegardes         |                        14 jours | Codé                     |
| Cache sémantique    |              Durée du processus | En mémoire               |

Les durées sont surchargeables par `audit.parametre` pour les clés `duree_conservation_*`. La purge utilise une année de 365 jours, volontairement indépendante du calendrier bissextile.

### 6.2 Sauvegardes

Les sauvegardes sont conservées 14 jours. Une demande d'effacement ne les purge pas immédiatement : les archives peuvent contenir le dossier jusqu'à leur rotation. Ce délai doit être expliqué dans la procédure de réponse à la personne. Si une restitution immédiate est exigée, il faut soit exclure le dossier des sauvegardes, soit restaurer et re-purcer, soit réduire la rétention. Chaque option a un coût de continuité.

## 7. Droits des personnes

### 7.1 Vue d'ensemble

| Droit                | État     | Modalité                                     | Limite                                           |
| -------------------- | -------- | -------------------------------------------- | ------------------------------------------------ |
| Accès                | Démontré | Export JSON du dossier                       | Admin ou assuré connecté                         |
| Portabilité          | Démontré | Même export JSON                             | Format lisible, pas de schéma standard           |
| Rectification        | Démontré | `PUT /rgpd/assures/{pseudonyme}/identite`    | Admin uniquement                                 |
| Opposition           | Démontré | `POST /rgpd/assures/{pseudonyme}/opposition` | Arrête la fourniture du service, ne supprime pas |
| Effacement           | Démontré | `DELETE /rgpd/assures/{pseudonyme}`          | Admin uniquement ; sauvegardes différées         |
| Limitation           | Écart    | Non implémenté                               | À définir                                        |
| Décision automatisée | Partiel  | Décision humaine, audit                      | Pas de contestation self-service                 |

### 7.2 Export et portabilité

L'assuré connecté peut appeler `GET /api/core/rgpd/moi/export`. Le pseudonyme vient du jeton, jamais de l'URL : un assuré ne peut pas exporter le dossier d'un autre. L'administrateur peut exporter n'importe quel dossier avec `GET /api/core/rgpd/assures/{pseudonyme}/export`.

L'export contient l'identité déchiffrée, les factures, les ordonnances, les prédictions, l'état d'opposition et la date de génération. Il est servi en JSON, avec un en-tête de téléchargement côté interface. C'est une base de portabilité, mais pas un format standardisé RGPD ; il faudra le documenter.

### 7.3 Rectification

L'administrateur peut corriger le nom, les coordonnées et la date de naissance. La valeur est rechiffrée immédiatement ; elle n'est jamais stockée en clair. L'action est journalisée. Il n'y a pas d'écran self-service pour l'assuré : la demande passe par le support ou le DPO.

### 7.4 Opposition

L'opposition met un drapeau sur le dossier. Les factures ne sont plus servies à l'assuré, mais elles ne sont pas supprimées. L'opposition ne s'applique pas à la prospection, qui n'est pas dans le périmètre. Il faut définir ce que l'opposition signifie pour les traitements obligatoires : elle ne peut pas faire obstacle à une obligation légale.

### 7.5 Effacement

L'effacement supprime :

- l'identité chiffrée ;
- les factures et leurs lignes ;
- les ordonnances et leurs lignes ;
- les prédictions et les explications SHAP ;
- les étiquettes d'entraînement liées aux factures ;
- les contrats, garanties et bénéficiaires ;
- le lien entre le compte et le dossier.

Il conserve le journal d'audit, mais remplace le pseudonyme par `[EFFACE]` dans les détails et les cibles. Il journalise l'effacement sans pseudonyme. C'est une décision explicite : la traçabilité de l'effacement prime, mais elle ne permet plus de ré-identifier la personne.

### 7.6 Limitation

Le droit à la limitation n'est pas implémenté. Un client qui conteste un traitement ne peut pas demander le gel de ses données par une API. C'est un écart à traiter avant production. La limitation peut être approchée par un statut de dossier et une exclusion temporaire des traitements, mais elle doit être conçue, testée et auditée.

### 7.7 Procédure de réponse

| Étape                      | Contenu                                                  | Délai     |
| -------------------------- | -------------------------------------------------------- | --------- |
| 1. Réception               | Canal support, DPO ou formulaire                         | Jour 0    |
| 2. Vérification d'identité | Ne pas divulguer à un tiers                              | Jour 0–2  |
| 3. Qualification           | Accès, rectification, opposition, effacement, limitation | Jour 2    |
| 4. Exécution               | Export, mise à jour, drapeau, suppression                | Jour 2–20 |
| 5. Réponse                 | Confirmation, limites, sauvegardes                       | Jour 30   |
| 6. Archivage               | Preuve de la demande et de la réponse                    | 5 ans     |

Le délai légal est d'un mois, prolongeable de deux mois pour les demandes complexes. L'identité doit être vérifiée avant tout export. Une demande d'effacement ne doit pas supprimer les données nécessaires à une obligation légale sans analyse.

## 8. AIPD

### 8.1 Pourquoi une AIPD

Le traitement combine données de santé, scoring, décision financière et population potentiellement vulnérable. Ces caractéristiques sont susceptibles d'engendrer un risque élevé. Une analyse d'impact est donc requise avant production.

### 8.2 Risques et mesures

| Risque                                 | Gravité | Mesures existantes                         | Risque résiduel |
| -------------------------------------- | ------- | ------------------------------------------ | --------------- |
| Faux positif : retard de remboursement | Moyenne | Décision humaine, commentaire, audit       | Moyen           |
| Biais défavorable à un segment         | Moyenne | Audit d'équité, supervision                | Moyen           |
| Ré-identification                      | Élevée  | Chiffrement, pseudonymisation, clé séparée | Faible          |
| Fuite vers le LLM                      | Élevée  | Minimisation, pas de noms, DPA à signer    | Moyen           |
| Injection de prompt                    | Moyenne | Filtre, séparation, SQL lecture seule      | Faible          |
| Accès indu d'un professionnel          | Moyenne | Filtre `prestataire_id` corrigé            | Faible          |
| Sauvegarde compromise                  | Moyenne | Chiffrement AES-256, clé fichier           | Faible          |
| Perte de clé                           | Moyenne | Sauvegarde de clé, rotation                | Moyen           |
| Journal non purgé                      | Moyenne | Purge manuelle                             | Moyen           |
| Sous-traitant hors UE                  | Élevée  | DPA, clauses, minimisation                 | Moyen           |

### 8.3 Consultation

Si l'AIPD conclut à un risque résiduel élevé malgré les mesures, le DPO doit consulter l'autorité de contrôle avant le traitement. Ce n'est pas le cas aujourd'hui dans la documentation, mais la conclusion doit être écrite.

## 9. Sous-traitants et transferts

| Destinataire | Données reçues                             | Localisation             | Mesure                                          |
| ------------ | ------------------------------------------ | ------------------------ | ----------------------------------------------- |
| OpenAI       | Question, extraits de contrats, historique | États-Unis (à confirmer) | DPA, clauses contractuelles types, minimisation |
| Slack        | Référence facture, score, SHAP             | États-Unis               | Workspace privé, DPA                            |
| E-mail       | Référence, score, lien                     | Selon fournisseur        | DPA, chiffrement                                |
| Hébergeur    | Base, sauvegardes, artefacts               | À choisir                | DPA, localisation UE, chiffrement               |
| Superset     | Données agrégées, pas de noms              | Même serveur             | Accès restreint, guest token                    |

Les transferts hors UE ne sont pas encore documentés. Avant production, il faut :

- vérifier la localisation réelle du fournisseur LLM ;
- signer les clauses contractuelles types et réaliser une analyse d'impact du transfert ;
- mettre à jour le registre ;
- prévoir un repli si le fournisseur change ;
- ne pas envoyer de données non minimisées.

## 10. Violations de données

### 10.1 Procédure cible

1. **Détecter** : alerte, logs, signalement interne, audit.
2. **Qualifier** : nature, volume, personnes, données concernées, gravité.
3. **Confiner** : révoquer les accès, isoler le service, préserver les preuves.
4. **Notifier** : autorité sous 72 heures si risque ; personnes si risque élevé.
5. **Corriger** : correctif, rotation, restauration.
6. **Documenter** : registre des violations, retour d'expérience.

### 10.2 État

La procédure n'est pas encore écrite. Les journaux et l'audit fournissent la matière, mais il manque un runbook, un annuaire d'escalade et un modèle de notification. C'est un écart P1 avant production.

## 11. Sécurité et conformité

Le document 04 couvre les mécanismes techniques. Pour le RGPD, les contrôles clés sont :

- chiffrement des identités et des sauvegardes ;
- pseudonymisation et cloisonnement ;
- RBAC et filtres serveur ;
- journalisation des connexions, décisions et actions RGPD ;
- rotation des clés ;
- sauvegarde et restauration ;
- test d'intrusion ;
- minimisation des données envoyées au LLM.

La sécurité n'est pas une conformité à elle seule : un contrôle technique sans procédure, sans preuve et sans responsable ne suffit pas. Le tableau de conformité ci-dessous relie chaque obligation à une preuve.

## 12. Matrice de conformité

| Obligation               | Preuve                    | Statut   | Écart / action                   |
| ------------------------ | ------------------------- | -------- | -------------------------------- |
| Registre des traitements | Ce document               | Partiel  | Reprendre dans l'outil DPO       |
| Bases légales            | Ce document               | Partiel  | Validation DPO/juriste           |
| Minimisation             | Pseudonymisation, filtres | Démontré | Revue des logs                   |
| Durées de conservation   | `conservation.py`         | Démontré | Planifier la purge               |
| Droit d'accès            | Export JSON               | Démontré | Documentation utilisateur        |
| Droit de rectification   | API admin                 | Démontré | Interface self-service à décider |
| Droit d'opposition       | API admin                 | Démontré | Définir les effets               |
| Droit d'effacement       | API admin                 | Démontré | Sauvegardes différées            |
| Droit à la limitation    | Absent                    | Écart    | Concevoir et tester              |
| AIPD                     | Matière fournie           | Écart    | Réaliser                         |
| DPO                      | Non désigné               | Écart    | Désigner                         |
| Contrats sous-traitants  | Non signés                | Écart    | Signer                           |
| Transferts hors UE       | Non documentés            | Écart    | DPA + TIA                        |
| Violation 72 h           | Non écrite                | Écart    | Runbook                          |
| Formation                | Non formalisée            | Écart    | Former                           |
| Revue annuelle           | Non planifiée             | Écart    | Planifier                        |

## 13. Plan d'action

| Action                               | Priorité | Responsable  | Échéance         | Preuve attendue       |
| ------------------------------------ | -------- | ------------ | ---------------- | --------------------- |
| Désigner le DPO                      | P0       | Direction    | Avant production | Lettre de désignation |
| Valider les bases légales            | P0       | DPO/juriste  | Avant production | Avis écrit            |
| Réaliser l'AIPD                      | P0       | DPO + RSSI   | Avant production | AIPD signée           |
| Planifier la purge                   | P1       | Exploitation | Avant production | Job + journal         |
| Implémenter la limitation            | P1       | Produit      | Avant production | API + test            |
| Écrire la procédure 72 h             | P1       | RSSI         | Avant production | Runbook               |
| Signer les DPA                       | P1       | Direction    | Avant production | Contrats              |
| Documenter les transferts            | P1       | DPO          | Avant production | TIA                   |
| Ajouter l'écran de demande de droits | P2       | Produit      | Après production | Parcours testé        |
| Former les utilisateurs              | P2       | Direction    | Lancement        | Support de formation  |

## 14. Conclusion

PrediCare dispose de fondations techniques sérieuses : pseudonymisation, chiffrement, filtres serveur, droits RGPD, conservation codée, audit. Ces fondations ne suffisent pas à déclarer une conformité complète. La différence entre « le code fait ce qu'il faut » et « l'organisation peut le prouver » reste à combler : DPO, AIPD, registre, contrats, procédure de violation, purge planifiée et droit à la limitation.

La feuille de route est donc claire : sécuriser les preuves documentaires, planifier les opérations, puis faire valider l'ensemble par le DPO et le juriste. Tant que ces étapes ne sont pas faites, le statut correct est **conformité par conception, conformité organisationnelle partielle, pas de certification**.

## 15. Annexes

### 15.1 Cartographie simplifiée

```text
Assuré
  ├── identité chiffrée (nom, coordonnées, date de naissance)
  ├── pseudonyme stable
  ├── factures / lignes / ordonnances
  ├── prédictions / SHAP
  ├── export RGPD
  └── opposition / effacement

Gestionnaire
  ├── file d'alertes
  ├── décision + commentaire
  └── audit

Administrateur
  ├── comptes et rôles
  ├── seuil et modèle
  ├── droits RGPD
  └── secrets / rotation

Sous-traitants
  ├── OpenAI : question, extraits, historique
  ├── Slack : référence, score, SHAP
  └── hébergeur : base, sauvegardes
```
