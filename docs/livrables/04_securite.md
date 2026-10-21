# Spécification des mécanismes de sécurité

**PrediCare — authentification, cloisonnement, chiffrement, audit et réponse à incident**

| | |
| --- | --- |
| Version | 1.0 |
| Date | 21 octobre 2026 |
| Statut | Version de travail |
| Public | RSSI, exploitation, jury, direction |
| Périmètre | API coeur, scoring, RAG, interface web, Superset, base, Redis, sauvegardes |
| Référentiels | STRIDE, OWASP ASVS, OWASP LLM Top 10, ISO/IEC 27001 (lecture), NIST CSF 2.0 (lecture) |

> **Avertissement.** Ce document décrit les contrôles présents et les écarts ouverts. Il ne constitue pas une certification ISO 27001 ni une attestation de conformité. Les contrôles non testés sont signalés comme tels.

## 1. Résumé exécutif

PrediCare est une plateforme multi-rôles qui manipule des données de santé pseudonymisées, des scores de fraude et des décisions financières. Sa sécurité repose sur cinq principes :

- **cloisonner** : chaque rôle ne voit que son périmètre, et le filtre est appliqué côté serveur ;
- **minimiser** : les noms sont chiffrés et isolés, les factures ne portent qu'un pseudonyme ;
- **tracer** : les connexions, décisions, changements de seuil et actions RGPD sont journalisés ;
- **chiffrer** : les identités sont chiffrées et les sauvegardes le sont lorsque la clé est fournie ; TLS est disponible mais doit être activé en production ;
- **limiter l'impact** : base et Redis non publiés, SQL lecture seule, rate limit, cache RAG cloisonné.

Les contrôles démontrés sont réels : RBAC, Argon2id, JWT, filtres serveur, audit, chiffrement des identités, sauvegarde chiffrée, test d'intrusion, tests RAG/SQL/RBAC. Les écarts principaux sont connus :

- TLS n'est pas activé par défaut ;
- MFA absent ;
- pas de quota LLM par utilisateur ;
- pas de test d'intrusion externe ;
- pas de dashboards ni de règles d'alerte Grafana provisionnés ;
- pas de test de restauration automatisé ;
- rotation des clés outillée mais peu testée ;
- état des dépendances et Dependabot à vérifier ;
- pas de SBOM ;
- procédure d'incident et de notification à formaliser.

La posture est donc **solide pour une démonstration**, **partielle pour une production**. Le document distingue les contrôles, les preuves et les risques résiduels.

## 2. Périmètre et actifs

### 2.1 Actifs

| Actif | Sensibilité | Localisation |
| --- | --- | --- |
| Identités chiffrées | Très élevée | PostgreSQL, table `core.identite_chiffree` |
| Factures et lignes | Élevée | PostgreSQL |
| Prédictions et SHAP | Élevée | PostgreSQL, `ml` |
| Journal d'audit | Élevée | PostgreSQL, `audit` |
| Sessions RAG | Élevée | Redis |
| Clés et secrets | Critique | `.env`, secrets Docker |
| Sauvegardes | Critique | Volume `backups` |
| Modèles | Moyenne | Volume `models` |
| Dashboards Superset | Moyenne | Métadonnées Superset |
| Logs | Moyenne | Docker, Prometheus |

### 2.2 Acteurs

| Acteur | Accès |
| --- | --- |
| Assuré | Ses factures, son assistant, son export |
| Professionnel de santé | Ses dépôts, ses dossiers, ses ordonnances |
| Gestionnaire | File d'alertes, détail, décision |
| Administrateur | Comptes, seuil, modèle, RGPD, observabilité |
| Exploitant | Conteneurs, logs, sauvegardes, métriques |
| Fournisseur LLM | Question, extraits, historique minimisé |
| Attaquant externe | Surface HTTP, Superset, API |

### 2.3 Frontières de confiance

```text
Internet
  │
  ▼
Traefik (HTTP/HTTPS, rate limit, en-têtes)
  │
  ├── web (interface)
  ├── api-core (métier, auth, RGPD, décisions)
  ├── api-inference (scoring)
  ├── api-rag (LLM, SQL lecture seule)
  ├── Superset (BI invitée)
  └── n8n (notifications)
        │
        ▼
Réseau interne : PostgreSQL, Redis, volumes
```

Les services internes ne doivent pas être exposés directement. Le navigateur ne doit jamais recevoir un secret de service.

## 3. Modèle de menace STRIDE

| Menace | Scénario | Contrôle | Écart |
| --- | --- | --- | --- |
| Usurpation | Vol de jeton, force brute | JWT signé, Argon2id, mot de passe 12 caractères, rate limit | Pas de MFA |
| Altération | Injection SQL, prompt injection | SQL lecture seule, liste blanche, séparation instruction/donnée | Filtre non exhaustif |
| Répudiation | Nier une décision | Audit décisions, audit connexion, logs JSON | Actions admin à compléter |
| Divulgation | Fuite de noms, cache partagé | Chiffrement, pseudonymes, scope assuré | Logs à revoir |
| Déni de service | Script sur le RAG | Rate limit, question 1 000 caractères, `LIMIT` SQL | Pas de quota par utilisateur |
| Élévation de privilèges | Admin via API | RBAC, permissions dédiées | MFA admin absent |

### 3.1 Scénarios prioritaires

1. **Vol d'un jeton de gestionnaire** : l'attaquant peut consulter la file et décider. Mitigation : expiration courte, TLS, MFA, révocation, journalisation.
2. **Injection de prompt** : l'attaquant demande au RAG d'ignorer les instructions ou d'exfiltrer un prompt. Mitigation : filtre, séparation, pas d'outil d'écriture, SQL lecture seule.
3. **Injection SQL via le RAG** : l'attaquant tente une requête destructive. Mitigation : compte `predicare_ro`, transaction read-only, liste blanche, paramètres liés.
4. **Fuite de sauvegarde** : un volume est copié. Mitigation : chiffrement AES-256, clé séparée, accès restreint.
5. **Accès indu d'un professionnel** : un professionnel voit les factures d'un autre. Mitigation : filtre `prestataire_id` côté serveur, corrigé et testé.
6. **Compromission d'un compte admin** : l'attaquant change le seuil ou les secrets. Mitigation : MFA, moindre privilège, audit, rotation.
7. **Déni de service LLM** : un utilisateur épuise le quota. Mitigation : rate limit, quota par sujet, alerte de coût.

## 4. Authentification et habilitations

### 4.1 Authentification

| Contrôle | Implémentation |
| --- | --- |
| Hachage | Argon2id |
| Longueur minimale | 12 caractères |
| Jeton | JWT signé, expiration, rôle, `assure_id`, session |
| Erreur de connexion | Message identique pour email inconnu et mot de passe faux |
| Rate limit | 60 requêtes/min, burst 120 |
| Audit | Action `connexion` dans `audit.journal` |
| MFA | Absent |

Le message d'erreur identique évite l'énumération des comptes. La connexion est journalisée dans la même transaction que la mise à jour de `last_login` : si l'écriture réussit, la trace existe.

### 4.2 Rôles

| Rôle | Périmètre | Interdictions |
| --- | --- | --- |
| Assuré | Ses factures, son export, son assistant | File d'alertes, admin, autres dossiers |
| Professionnel de santé | Ses dépôts, ses dossiers, ses ordonnances | File des autres praticiens, admin |
| Gestionnaire | File d'alertes, décision, SHAP | Administration, secrets |
| Administrateur | Comptes, seuil, modèle, RGPD, observabilité | Aucune, mais actions tracées |

Le contrôle d'accès est centralisé dans `packages/predicare-core/src/predicare/rbac.py` et appliqué par des dépendances FastAPI. Une route non annotée est refusée par défaut dans les tests RBAC.

### 4.3 Cloisonnement des données

| Donnée | Filtre | Preuve |
| --- | --- | --- |
| Factures assuré | `facture.assure_id = assure_id du jeton` | `billing/router.py` |
| Factures prestataire | `facture.prestataire_id = prestataire du compte` | `billing/router.py` |
| Export RGPD | Pseudonyme du jeton ou admin | `rgpd/router.py` |
| Cache RAG | `assure_id` ou `user:{subject}` | `semantic_cache.py` |
| SQL RAG | Compte lecture seule + paramètres | `sql_tool.py` |
| Superset | Guest token, rôle invité | `ops/superset/preparer_embed.py` |

Le filtre prestataire est un correctif important : auparavant, un professionnel pouvait voir toutes les factures pseudonymisées. Le code vérifie maintenant le prestataire du compte et l'applique dans la requête SQL. La soumission est également restreinte au prestataire du compte.

## 5. Chiffrement et gestion des clés

### 5.1 Au repos

- Les identités sont chiffrées avec **Fernet** (AES-128-CBC + HMAC).
- Le pseudonyme est un **HMAC-SHA256** avec `APP_SECRET_KEY`.
- Les sauvegardes sont chiffrées avec **AES-256-CBC**, **PBKDF2 200 000 itérations**, clé lue depuis un fichier, lorsque `BACKUP_CLE_FILE` est présent ; sinon elles restent en clair et le journal le signale.
- Les secrets ne sont pas versionnés ; `.env` est ignoré.
- Les factures et prédictions ne contiennent pas de noms.

### 5.2 En transit

- En local, HTTP sur le réseau Docker.
- TLS est disponible via `scripts/generer-traefik.sh` : si `PREDICARE_TLS_DOMAIN` est défini et si les certificats sont fournis, Traefik expose 443 et redirige HTTP.
- TLS n'est pas activé par défaut, car un certificat auto-signé sur `localhost` dégrade l'expérience et donne une fausse impression de sécurité.
- En production, TLS doit être obligatoire, avec certificats valides et HSTS.

### 5.3 Clés

| Clé | Usage | Rotation |
| --- | --- | --- |
| `APP_SECRET_KEY` | Pseudonymisation, signature interne | `scripts/rotater-cles.sh` |
| `JWT_SECRET_KEY` | Signature des jetons | `scripts/rotater-cles.sh` |
| `IDENTITY_ENCRYPTION_KEY` | Chiffrement Fernet | `scripts/rotater-cles.sh` |
| `BACKUP_CLE_FILE` | Chiffrement des sauvegardes | Procédure manuelle |
| `LLM_API_KEY` | Appels LLM | Fournisseur |
| `EMBEDDING_API_KEY` | Embeddings | Fournisseur |
| `PREDICARE_DB_RO_URL` | Lecture SQL RAG | `ALTER ROLE` |

La rotation des clés applicatives est outillée : le script simule par défaut, puis rechiffre les identités et les secrets dans une transaction avant de réécrire `.env`. Il impose un redémarrage. La rotation de la clé de sauvegarde n'est pas automatisée : une sauvegarde chiffrée avec une clé perdue est une sauvegarde perdue.

## 6. Réseau et passerelle

| Contrôle | État |
| --- | --- |
| PostgreSQL non publié sur l'hôte | Démontré |
| Redis non publié sur l'hôte | Démontré |
| Traefik sans socket Docker | Démontré |
| En-têtes CSP, nosniff, frame-deny | Configurés |
| HSTS | À activer avec TLS |
| Rate limit | 60/min, burst 120 |
| Journal d'accès | Activé |
| Superset accessible directement | Oui en local ; à restreindre en production |
| Mailpit | Développement uniquement |

Le réseau Docker isole les services internes. Le reverse proxy est le seul point d'entrée. En production, Superset et les outils d'observabilité doivent être protégés par authentification, VPN ou liste d'accès.

## 7. Sécurité applicative et RAG

### 7.1 Contrôles

| Contrôle | Détail |
| --- | --- |
| Validation d'entrée | Schémas Pydantic, bornes, types |
| SQL | Compte `predicare_ro`, transaction read-only, liste blanche, paramètres liés |
| Prompt injection | Motifs déclarés, refus explicite, journalisation |
| Séparation | Question dans un bloc `<question>`, instructions système séparées |
| Longueur | Question limitée à 1 000 caractères, historique borné |
| Périmètre | `assure_id` du jeton, jamais du texte |
| Cache | Cloisonné par assuré, pas de cache pour les questions de suivi |
| Réponse | Sources citées, extraits, scores |
| Écriture | Aucun outil d'écriture pour l'agent |

### 7.2 Limites

Le filtre d'injection est fondé sur des motifs : il ne couvre pas toutes les formulations. La barrière qui ne dépend pas du vocabulaire est le **compte SQL en lecture seule** et l'absence d'outil d'écriture. Le périmètre de lecture est tenu par l'injection du `assure_id` du jeton et la liste blanche, pas par le rôle SQL.

Le cache sémantique peut servir une réponse à une question proche. Le seuil de similarité (0,95 par défaut) doit être surveillé : trop bas, il mélange des questions ; trop haut, il ne sert à rien. Une réponse de cache ne doit jamais franchir un périmètre.

## 8. Audit et supervision

### 8.1 Journalisation

| Élément | Contenu | Preuve |
| --- | --- | --- |
| Journal d'audit | Acteur, rôle, action, cible, détails, date | `audit.journal` |
| Décisions | Prédiction, décision, commentaire, acteur | `audit.decision_gestionnaire` |
| Connexion | Action `connexion` | `identity/router.py` |
| Seuil | Ancienne et nouvelle valeur | `audit.parametre` |
| Modèle | Version, artefact, métriques, statut | `ml.modele_version` |
| Dérive | PSI, variables, alerte | `ml.rapport_derive` |
| RGPD | Export, rectification, opposition, effacement | `audit.journal` |

Les logs sont en JSON, sans noms. Les identifiants de facture et de prédiction restent des données pseudonymisées : ils doivent être traités comme des données personnelles.

### 8.2 Supervision

Prometheus collecte les métriques applicatives : latence, erreurs, tokens, coût, cache. Grafana est configuré avec une source Prometheus. **Aucun dashboard ni règle d'alerte n'est provisionné dans le dépôt** : c'est un écart d'exploitation à combler avant production.

Les signaux à surveiller :

- taux d'erreur 5xx ;
- latence p95 ;
- tokens et coût par requête ;
- taux de cache ;
- dérive PSI ;
- files d'alertes ;
- espace disque ;
- échecs de sauvegarde ;
- connexions échouées.

## 9. Sauvegarde, restauration et résilience

| Élément | Valeur |
| --- | --- |
| Fréquence | Quotidienne, 03 h 00 |
| Rétention | 14 jours |
| Format | `pg_dump` compressé, chiffré si clé présente |
| Chiffrement | AES-256-CBC, PBKDF2 200 000 itérations |
| Vérification | `gzip -t` ou déchiffrement + `gzip -t` |
| Restauration | `make restore`, confirmation obligatoire |
| Sauvegarde avant restauration | Oui |
| RPO | ≤ 24 h |
| RTO | Non mesuré |
| Test de restauration CI | Absent |

La restauration n'est jamais automatique : une erreur de script écraserait les données du jour. Le script vérifie qu'au moins 10 tables existent après restauration, ce qui détecte une restauration vide.

## 10. Chaîne d'approvisionnement

| Contrôle | État |
| --- | --- |
| Images Docker avec tags explicites | Oui |
| Lock Python `uv.lock` | Oui |
| CI GitHub Actions | Oui |
| Dépendances épinglées | Partiel |
| Dependabot | Aucun fichier de configuration dans le dépôt ; état GitHub à vérifier |
| SBOM | Absent |
| Scan d'images | À vérifier |
| Signature d'images | Absent |
| Revue des dépendances | Partielle |

Avant production, il faut activer Dependabot ou un équivalent, produire un SBOM, scanner les images et documenter la politique de mise à jour.

## 11. Preuves de test

| Suite | Résultat | Commande |
| --- | ---: | --- |
| Tests unitaires et d'intégration | **696 passés, 18 ignorés** | `make check` |
| Attaques RAG | 97 tests, 100 % des attaques déclarées bloquées | `pytest tests/test_rag_attacks.py` |
| Garde-fous | 78 tests | `pytest tests/test_guardrails.py` |
| SQL | 57 tests | `pytest tests/test_sql_tool.py` |
| RBAC | 22 tests | `pytest tests/test_rbac.py` |
| Chaîne n8n | 13/13 vérifications | `make e2e-n8n` |
| Intrusion | 7 familles de contrôles | `scripts/test-intrusion.sh` |
| Lint | OK | `make lint` |
| Types | OK | `make typecheck` |

Les 18 tests ignorés sont les tests e2e et PostgreSQL sans pile démarrée ; ils sont rejoués sur la plateforme de démonstration. Le test d'intrusion est une liste de contrôles nommés, pas un scanner de vulnérabilités.

## 12. Réponse à incident

### 12.1 Étapes

1. **Détecter** : alerte, log, signalement, audit.
2. **Qualifier** : gravité, périmètre, données, personnes.
3. **Confiner** : révoquer les jetons, isoler le service, bloquer l'accès.
4. **Préserver** : logs, horodatage, captures, base.
5. **Corriger** : correctif, rotation, restauration.
6. **Notifier** : autorité sous 72 h si violation RGPD ; autorité AI Act si incident grave.
7. **Apprendre** : retour d'expérience, test de non-régression.

### 12.2 Incidents types

| Incident | Première action | Vérification |
| --- | --- | --- |
| Jeton volé | Révoquer, changer le secret, auditer | Sessions fermées |
| Fuite de clé LLM | Révoquer chez le fournisseur, changer `.env`, redémarrer | Aucun appel non autorisé |
| Injection réussie | Bloquer l'utilisateur, analyser les logs, corriger le filtre | Test de non-régression |
| Sauvegarde corrompue | Garder l'archive, tester la précédente | Restauration sur base vide |
| Disque plein | Purger les logs, réduire la rétention, étendre le volume | Métriques stables |
| Base indisponible | Vérifier le conteneur, le volume, les logs | `/health` OK |
| Dérive modèle | Revenir à la version précédente | Métriques et alertes |
| Accès indu | Couper le compte, auditer, corriger le filtre | Test RBAC |

## 13. Risques et feuille de route

### 13.1 Registre des risques

| Risque | Probabilité | Impact | Contrôle | Résiduel |
| --- | --- | --- | --- | --- |
| Vol de jeton | Moyenne | Élevé | JWT, TLS, rate limit | Moyen |
| MFA absent | Moyenne | Élevé | À ajouter | Élevé |
| Fuite de sauvegarde | Faible | Élevé | Chiffrement | Faible |
| Perte de clé | Faible | Élevé | Sauvegarde de clé | Moyen |
| Injection RAG | Moyenne | Moyen | Filtre, SQL RO | Faible |
| Déni de service LLM | Moyenne | Moyen | Rate limit | Moyen |
| Dépendance vulnérable | Moyenne | Moyen | Dependabot à activer | Moyen |
| Dashboard non supervisé | Élevée | Moyen | Grafana à compléter | Élevé |
| Restauration non testée | Moyenne | Élevé | Test à automatiser | Élevé |
| TLS non activé | Élevée | Élevé | Activer en production | Élevé |

### 13.2 Priorités

| Priorité | Action | Échéance |
| --- | --- | --- |
| P0 | Activer TLS en production | Avant production |
| P0 | Ajouter MFA pour admin et gestionnaire | Avant production |
| P0 | Tester une restauration complète | Avant production |
| P1 | Créer dashboards et alertes Grafana | Avant production |
| P1 | Activer Dependabot et scanner les images | Avant production |
| P1 | Écrire la procédure d'incident 72 h | Avant production |
| P1 | Ajouter quota LLM par utilisateur | Avant production |
| P2 | Produire un SBOM | Après production |
| P2 | Test d'intrusion externe | Après production |
| P2 | Rotation de la clé de sauvegarde | Après production |

## 14. Conclusion

La sécurité de PrediCare est **démontrée sur les contrôles structurants** : RBAC, filtres serveur, chiffrement, audit, SQL lecture seule, sauvegarde chiffrée, tests. Elle reste **partielle pour la production** : TLS, MFA, supervision Grafana, test de restauration, gestion des dépendances et procédure d'incident.

La priorité n'est pas d'ajouter des outils, mais de fermer les écarts qui ont un impact direct sur la confidentialité, l'intégrité et la disponibilité. TLS et MFA protègent les comptes ; la restauration testée protège les données ; les alertes Grafana protègent la disponibilité ; Dependabot protège la chaîne d'approvisionnement.
