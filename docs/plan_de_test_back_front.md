# Plan de test back / front — PrediCare

> Objectif : vérifier **endpoint par endpoint** que la base, l'API et l'interface
> affichent la même chose. Ce document sert aussi de support pour la démo jury.

---

## 0. Prérequis

```bash
# Dans WSL, à la racine du projet
docker compose -f docker-compose.yml ps
```

Tu dois voir `db`, `redis`, `api-core`, `api-inference`, `api-rag`, `web`, `gateway`
en `Up` (et `api-core`, `api-inference`, `api-rag`, `db`, `redis` en `healthy`).

Vérifier le modèle :

```bash
curl -s http://localhost:8002/api/inference/modele
```

Attendu : `"active_version"` vaut `"1"` ou `"2"` selon la version chargée (les
deux sont disponibles), et `"threshold":0.287569522857666`.

Créer les comptes si nécessaire :

```bash
DEMO_PASSWORD='PrediCare2026!' make comptes
```

> ⚠️ **Règle d'or** : après toute modification du front, reconstruis l'image web.
> Sinon le navigateur reçoit l'ancienne version :
>
> ```bash
> docker compose -f docker-compose.yml build web
> docker compose -f docker-compose.yml up -d web
> ```
>
> C'est la cause n°1 du symptôme « rien n'est dynamique ».

---

## 1. Se connecter et récupérer un jeton

### PowerShell

```powershell
$body = @{
  email    = "admin@predicare.local"
  password = "PrediCare2026!"
} | ConvertTo-Json

$reponse = Invoke-RestMethod `
  -Uri "http://localhost:8080/api/core/auth/login" `
  -Method Post `
  -Body $body `
  -ContentType "application/json"

$token = $reponse.access_token
$headers = @{ Authorization = "Bearer $token" }
```

### Réponse attendue

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

### Vérifier le profil

```powershell
Invoke-RestMethod -Uri "http://localhost:8080/api/core/auth/me" -Headers $headers
```

Attendu :

```json
{
  "subject": "4",
  "email": "admin@predicare.local",
  "role": "administrateur",
  "display_name": "Administrateur de demonstration"
}
```

### SQL de contrôle

```bash
docker compose -f docker-compose.yml exec -T db psql -U predicare -d predicare \
  -c "SELECT email, role, is_active FROM core.utilisateur ORDER BY role;"
```

Attendu : 4 lignes, `is_active = t`.

---

## 2. Carte des endpoints

| Écran | Méthode | Endpoint | Rôle | Attendu |
|---|---|---|---|---|
| Connexion | POST | `/api/core/auth/login` | public | 200 + token |
| Profil | GET | `/api/core/auth/me` | connecté | 200 |
| Assuré | GET | `/api/core/factures?limit=5` | assuré | 200 + `items` |
| Assuré | POST | `/api/rag/question` | assuré | **200** + sources (voir § 5.4 : session, extraits, cache, injection) |
| Pro | GET | `/api/core/factures/references` | pro | 200 + listes |
| Pro | POST | `/api/core/factures/soumettre` | pro | **202** + score + SHAP |
| Pro | POST | `/api/core/factures/ordonnances` | pro | 201 |
| Pro | GET | `/api/core/factures?limit=100` | pro | 200 |
| Gestionnaire | GET | `/api/core/alertes/file?statut=nouvelle&limit=100` | gestionnaire | 200 |
| Gestionnaire | GET | `/api/core/alertes/detail/{id}` | gestionnaire | 200 + SHAP |
| Gestionnaire | POST | `/api/core/alertes/decision` | gestionnaire | 200 |
| Gestionnaire | GET | `/api/core/alertes/historique?limit=200` | gestionnaire | 200 |
| Admin | GET | `/api/core/admin/seuil` | admin | 200 + seuil |
| Admin | PUT | `/api/core/admin/seuil` | admin | 200 |
| Admin | GET | `/api/core/admin/modele` | admin | 200 + version 2 |
| Admin | POST | `/api/core/admin/modele/candidat` | admin | 200 |
| Admin | POST | `/api/core/admin/modele/bascule` | admin | 200 |
| Admin | POST | `/api/core/admin/modele/retour-arriere` | admin | 200 |
| Admin | GET | `/api/core/admin/sante` | admin | 200 |
| Admin | GET | `/api/core/admin/canaux` | admin | 200 |
| Admin | GET | `/api/core/audit/journal?limit=5` | admin | 200 |
| Admin | POST | `/api/core/audit/evenement` | connecté | 200 |
| Admin | GET | `/api/core/admin/utilisateurs` | admin | 200 |
| Admin | POST | `/api/core/admin/utilisateurs` | admin | 201 |
| Admin | PATCH | `/api/core/admin/utilisateurs/{id}` | admin | 200 |
| Inférence | GET | `/api/inference/modele` | admin | 200 + version 2 |

> Les chemins passent par la passerelle `http://localhost:8080`. En direct :
> `api-core` = 8001, `api-inference` = 8002, `api-rag` = 8003.

---

## 3. Tests détaillés

### 3.1 Connexion

| Test | Commande | Attendu |
|---|---|---|
| Bon mot de passe | `POST /auth/login` | 200 + `access_token` |
| Mauvais mot de passe | `POST /auth/login` avec `faux` | 401 |
| Compte désactivé | désactiver via admin, puis login | 401 |
| Profil | `GET /auth/me` | 200 + `role` |

**SQL :**

```sql
SELECT email, role, is_active, last_login FROM core.utilisateur ORDER BY role;
```

**UI :** après connexion, tu dois être redirigé vers :
- `assure` → `/assure`
- `professionnel_sante` → `/professionnel`
- `gestionnaire` → `/gestionnaire`
- `administrateur` → `/administration`

---

### 3.2 Assuré

#### `GET /api/core/factures?limit=5`

```powershell
$body = @{email="assure@predicare.local"; password="PrediCare2026!"} | ConvertTo-Json
$r = Invoke-RestMethod -Uri "http://localhost:8080/api/core/auth/login" -Method Post -Body $body -ContentType "application/json"
$h = @{ Authorization = "Bearer $($r.access_token)" }
Invoke-RestMethod -Uri "http://localhost:8080/api/core/factures?limit=5" -Headers $h | ConvertTo-Json -Depth 4
```

Attendu :

```json
{
  "items": [
    {
      "facture_id": "FAC-...",
      "assure_pseudonyme": "assr_...",
      "prestataire_id": "PRE-00001",
      "montant_total": 224000,
      "montant_eligible": 224000,
      "montant_pris_en_charge": 150000,
      "reste_a_charge": 74000,
      "date_facture": "2026-07-22T01:00:00+02:00",
      "statut": "PAYEE"
    }
  ],
  "total": 27,
  "limit": 5,
  "offset": 0
}
```

> Le filtre est appliqué **côté serveur**. À la connexion, le jeton contient
> `ins = core.utilisateur.assured_id`. Pour le rôle `assure`, la requête ajoute
> `AND f.assure_id = :assure_id`. Aucun paramètre envoyé par le navigateur ne
> permet de changer de dossier.
>
> Preuve attendue : l'API renvoie le nombre de factures du dossier
> `assure@predicare.local` (27 au 20/10/2026), pas les 84 603 factures de la
> base. Tous les `assure_pseudonyme` renvoyés sont identiques.

**SQL :**

```sql
SELECT count(*) FROM core.facture f
JOIN core.assure a ON a.id = f.assure_id
WHERE a.id = (SELECT assured_id FROM core.utilisateur WHERE email='assure@predicare.local');
```

Le résultat doit être égal à `total`.

**UI :** onglet **Mes remboursements** → tableau avec **Facture**, **Pris en
charge**, **Reste à charge**, **Statut** et **Contrôle**.
Les factures `PAYEE` doivent afficher `Remboursee` et des montants ; les
factures `recue` affichent `—` tant qu'elles ne sont pas traitées.
Si le tableau est vide alors que le SQL renvoie des lignes, le front ne lit pas
la bonne réponse.

#### `POST /api/rag/question`

```powershell
$corps = @{
  question   = "Quel est le taux de remboursement d'une consultation en formule PREMIUM ?"
  session_id = "recette-rag-001"
} | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8080/api/rag/question" -Method Post -Headers $h -Body $corps -ContentType "application/json"
```

**Attendu** : 200 avec `reponse`, `sources`, `etapes_agent`, `latence_ms`,
`tokens`, `cache_semantique` et `succes = true`.

Vérifier ensuite dans l'interface :

1. la source affiche le contrat, l'article, la garantie et, après clic sur
   **Voir l'extrait**, le passage contractuel ;
2. la question de suivi « Et pour l'optique ? » réutilise le même
   `session_id` et reprend le contexte ;
3. **Nouvelle conversation** génère un autre `session_id` et vide l'écran ;
4. une tentative d'injection renvoie 400 et un message lisible, sans trace
   technique ;
5. le cache sémantique est signalé sur une question répétée dans une nouvelle
   conversation (une conversation avec historique n'utilise pas le cache).

---

### 3.3 Professionnel de santé

#### `GET /api/core/factures/references`

Attendu :

```json
{
  "assures": [{ "pseudonyme": "assr_..." }],
  "prestataires": [{ "code": "PRE-00001", "nom": "Pharmacie Vatolampy" }],
  "actes": [{ "code": "CONS-GEN", "libelle": "Consultation medecine generale", "prix_unitaire": 20000 }]
}
```

Les montants sont en **ariary (MGA)**, pas en euros. Une ligne est
acceptée jusqu'à **10 000 000 MGA** et le total jusqu'à **10 000 000 MGA**.

**UI :** le formulaire **Déposer une facture** doit avoir les listes déroulantes
remplies. Si elles sont vides, l'appel `/references` a échoué.

#### `POST /api/core/factures/soumettre`

Exemple de corps (les valeurs viennent de `/references`) :

```json
{
  "assure_pseudonyme": "assr_...",
  "prestataire_id": "PRE-00001",
  "date_facture": "2026-10-19T10:00:00",
  "montant_total": 20000,
  "lignes": [
    {
      "code_acte": "CONS-GEN",
      "quantite": 1,
      "montant_unitaire": 20000,
      "date_acte": "2026-10-19T10:00:00"
    }
  ]
}
```

Attendu : **202** avec :

```json
{
  "facture_id": "FAC-...",
  "score_fraude": 0.12,
  "is_fraud": false,
  "seuil_applique": 0.2876,
  "model_version": "2",
  "shap": [
    { "feature": "...", "shap_value": 0.03, "direction": "pousse_vers_fraude", "human_readable": "..." }
  ]
}
```

**SQL :**

```sql
SELECT count(*) FROM ml.prediction;          -- doit augmenter de 1
SELECT count(*) FROM ml.shap_explication;    -- doit augmenter
SELECT reference, montant_total FROM core.facture ORDER BY creee_le DESC LIMIT 1;
```

**UI :** carte **Résultat de la notation** → score, seuil, version 2, barres SHAP.
Onglet **Suivi des dossiers** → la facture apparaît.

#### Test d'invalidation

Envoie un `montant_unitaire` négatif, un `code_acte` inconnu, ou une date
de facture dans le futur.

Attendu : **422** avec un message qui nomme le champ, par exemple :

```json
{
  "code": "invalid_invoice",
  "message": "Facture invalide - lignes.0.montant_unitaire : Input should be greater than or equal to 0",
  "details": {}
}
```

Aucune ligne ne doit être créée dans `core.facture`.

---

### 3.4 Gestionnaire

> La file est **vide au départ**. Les 84 000 factures historiques ne sont pas
> notées. Il faut d'abord soumettre une facture (3.3). Si son score est sous
> 28,76 %, elle n'apparaît pas. Pour forcer une alerte, baisse temporairement le
> seuil à `0.05` via l'admin, soumets à nouveau, puis remets `0.2876`.

#### `GET /api/core/alertes/file?statut=nouvelle&limit=100`

Attendu : **200** + liste d'alertes :

```json
[
  {
    "prediction_id": "1",
    "facture_id": "FAC-...",
    "score_fraude": 0.91,
    "montant_total": 50000,
    "assure_pseudonyme": "ASS-...",
    "created_at": "2026-10-19T..."
  }
]
```

**SQL :**

```sql
SELECT p.id, p.facture_id, p.score_fraude, p.is_fraud, p.statut
FROM ml.prediction p
WHERE p.is_fraud = true AND p.statut = 'nouvelle'
ORDER BY p.created_at DESC;
```

Les `id` doivent correspondre à `prediction_id` dans l'API.

#### `GET /api/core/alertes/detail/{id}`

Attendu : 200 + `score_fraude`, `seuil_applique`, `shap`, `montant_total`.

**SQL :**

```sql
SELECT feature, shap_value, direction, human_readable
FROM ml.shap_explication WHERE prediction_id = 1;
```

#### `POST /api/core/alertes/decision`

Corps :

```json
{
  "prediction_id": "1",
  "decision": "valider_fraude",
  "commentaire": "Facture conforme après vérification.",
  "decided_at": "2026-10-19T10:15:00Z"
}
```

Valeurs possibles pour `decision` : `valider_fraude`, `rejeter`,
`demander_piece`. `decided_at` est **obligatoire**.

Attendu : 200 + `status: "ok"`.

**SQL :**

```sql
SELECT prediction_id, decision, commentaire, decided_by, decided_at
FROM audit.decision_gestionnaire ORDER BY decided_at DESC;
```

**UI :** l'alerte disparaît de la file, apparaît dans **Historique**.

---

### 3.5 Administrateur

#### `GET /api/core/admin/seuil`

Attendu : `{ "seuil": 0.287569522857666 }`.

#### `PUT /api/core/admin/seuil`

Corps :

```json
{ "seuil": 0.3, "motif": "Test de variation du seuil" }
```

Attendu : 200. **SQL :**

```sql
SELECT cle, valeur, modifie_par, modifie_at
FROM audit.parametre WHERE cle = 'seuil_alerte';
```

> Le `motif` est écrit dans les **logs** (`admin.seuil_change`), pas dans
> `audit.journal`. Le journal d'audit n'enregistre pour l'instant que les
> événements envoyés explicitement via `POST /api/core/audit/evenement`.

#### `GET /api/core/admin/modele`

Attendu :

```json
{
  "active_version": "2",
  "candidate_version": null,
  "threshold": 0.2876,
  "available_versions": ["2"],
  "metrics": { "roc_auc": 0.950033, "rappel": 0.870159 }
}
```

#### `GET /api/core/admin/sante`

Attendu : `status: "ok"`, `database: true`, versions des services.

#### `GET /api/core/admin/canaux`

Attendu : liste des canaux (Slack, e-mail) avec `configure: false` pour Slack.

#### `GET /api/core/admin/utilisateurs`

Attendu : 4 comptes (ou plus).

**SQL :**

```sql
SELECT id, email, role, is_active, display_name FROM core.utilisateur ORDER BY role;
```

#### Création / désactivation

```json
POST /api/core/admin/utilisateurs
{
  "email": "test@predicare.local",
  "password": "TestPrediCare2026!",
  "role": "gestionnaire",
  "display_name": "Compte de test"
}
```

Attendu : 201. Puis :

```json
PATCH /api/core/admin/utilisateurs/{id}
{ "is_active": false }
```

Attendu : 200. **SQL :** `is_active = f`.

**UI :** Administration → **Comptes** : le compte apparaît, puis passe à
**désactivé**. Le bouton de désactivation de son propre compte est grisé.

#### `POST /api/core/audit/evenement`

Corps :

```json
{
  "action": "test_plan",
  "cible": "documentation",
  "details": { "source": "plan_de_test_back_front" }
}
```

Attendu : `{ "status": "ok" }`. **SQL :**

```sql
SELECT acteur, role, action, cible, details, created_at
FROM audit.journal ORDER BY id DESC LIMIT 5;
```

**UI :** Administration → **Journal** doit afficher l'entrée après
rafraîchissement (bouton ou changement d'onglet).

> Les décisions du gestionnaire ne sont **pas** recopiées automatiquement dans
> `audit.journal` : elles vivent dans `audit.decision_gestionnaire`. Le journal
> ne contient que les événements postés explicitement.

---

### 3.6 Inférence

#### `GET /api/inference/modele`

Attendu : `"active_version":"2"`, `"threshold":0.2876`, `"metrics": {...}`.

#### `POST /api/inference/predire`

Corps : même structure que `soumettre`. Attendu : 200 + score + SHAP.

Si `models/` est vide : **503** `modele indisponible`.

---

## 4. Test de bout en bout (E2E)

Scénario à jouer dans l'ordre :

1. **Pro** : login → `/references` → `POST /soumettre`.
2. Noter le `facture_id` et le `score_fraude`.
3. **SQL** : `SELECT count(*) FROM ml.prediction;` → a augmenté.
4. **Gestionnaire** : login → `GET /alertes/file`.
5. Si l'alerte est présente : `GET /detail/{id}` → `POST /decision`.
6. **SQL** : `SELECT count(*) FROM audit.decision_gestionnaire;` → a augmenté.
7. **SQL** : la décision est lisible dans `audit.decision_gestionnaire` et
   `ml.prediction.statut` a changé (`valider_fraude`, `rejeter` ou
   `demander_piece`).
8. **UI** : la file du gestionnaire diminue, l'historique augmente.

> Le `audit.journal` n'est **pas** alimenté automatiquement par les décisions.
> Pour le tester, appelle explicitement `POST /api/core/audit/evenement`.

Script automatique fourni :

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verifier_back_front.ps1
```

### 4.1 Chaîne n8n (Slack et e-mail)

Prérequis : `SLACK_WEBHOOK_URL` renseigné, Mailpit démarré (`make up-email`),
workflows importés (`make n8n-import`).

```bash
make e2e-n8n
```

Vérifications :

1. `PK-Alerte-Fraude` est actif et `POST /webhook/alerte-fraude` est enregistré.
2. `FAC-JURY-001` (lot F17) répond **200** avec `score_fraude` ≥ 0,8 et
   `rapport_shap`.
3. L'e-mail arrive dans Mailpit (`http://localhost:8025`) avec le rapport SHAP.
4. `execution_entity.status = 'success'` : Slack a répondu 2xx.
5. Une facture invalide répond **502**, n'ajoute aucun e-mail et laisse
   l'exécution en `error` : l'échec est journalisé, sans notification fantôme.

La bascule de modèle se prouve avec `POST /webhook/bascule-modele` (payload
`version_avant` / `version_apres`) : réponse 200, puis Slack et e-mail. Le
détail et les credentials par poste sont dans `apps/n8n/README.md`.

### 4.2 Rapport de dérive persisté

Prérequis : `worker-ingest` démarré (`make up-workers` ou `make up`).

```bash
curl -s http://localhost:8002/api/inference/derive | python3 -m json.tool
```

Attendu :

1. `status: "ok"`, avec `id`, `calcule_le`, `fenetre_jours`, `psi_global`,
   `variables_concernees`, `score_moyen_reference`, `score_moyen_courant`,
   `alerte`.
2. `variables_concernees.observations_reference` et
   `observations_courantes` sont présents : sans eux, un PSI n'est pas
   interprétable.
3. `ml.rapport_derive` contient au moins une ligne :

   ```bash
   docker compose exec db psql -U predicare -d predicare \
     -c "SELECT id, calcule_le, psi_global, alerte FROM ml.rapport_derive ORDER BY id DESC LIMIT 3;"
   ```

4. Après `docker compose restart api-inference`, l'endpoint renvoie toujours
   le même rapport : il est lu en base, pas gardé en mémoire du worker.
5. Le worker ne calcule qu'une fois par heure ; pour forcer un calcul :

   ```bash
   docker compose exec worker-ingest /opt/venv/bin/python -c \
     "from predicare_inference_api.derive import calculer_et_persister_derive; print(calculer_et_persister_derive(force=True))"
   ```

Mesure du 20/10/2026 : rapport `id=1`, `5510` notations rétrospectives contre
`18` notations courantes, `psi_global=6,5287`, `alerte=true`. Le PSI est
extrême parce que la fenêtre courante contient le lot F17 et les rejeux e2e,
pas un échantillon de production ; c'est le comportement attendu d'un
détecteur de dérive, et l'effectif courant permet de le lire correctement.

---

## 5. Tests de sécurité (RBAC)

| Test | Requête | Attendu |
|---|---|---|
| Assuré → file d'alertes | `GET /api/core/alertes/file` | **403** |
| Assuré → admin seuil | `GET /api/core/admin/seuil` | **403** |
| Pro → file d'alertes | `GET /api/core/alertes/file` | **403** |
| Gestionnaire → admin seuil | `GET /api/core/admin/seuil` | **403** |
| Pro → RAG | `POST /api/rag/question` | **403** |
| Admin → tout | tous les GET | **200** |

Exemple :

```powershell
# avec le jeton d'un assuré
Invoke-WebRequest -Uri "http://localhost:8080/api/core/alertes/file" -Headers $hAssure
# Attendu : 403 Forbidden
```

> Côté UI, un assuré qui tape `/administration` est redirigé vers `/`.
> Un administrateur, lui, a accès à tous les écrans (héritage de droits).

---

## 6. Correspondance base → API → interface

| Donnée | Table | Endpoint | Écran |
|---|---|---|---|
| Comptes | `core.utilisateur` | `/api/core/admin/utilisateurs` | Admin → Comptes |
| Factures | `core.facture` | `/api/core/factures` | Assuré / Pro → Suivi |
| Prédictions | `ml.prediction` | `/api/core/alertes/file` | Gestionnaire → File |
| SHAP | `ml.shap_explication` | `/api/core/alertes/detail/{id}` | Gestionnaire → Détail |
| Décisions | `audit.decision_gestionnaire` | `/api/core/alertes/historique` | Gestionnaire → Historique |
| Seuil | `audit.parametre` + modèle | `/api/core/admin/seuil` | Admin → Seuil |
| Versions | `ml.modele_version` | `/api/core/admin/modele` | Admin → Modèle |
| Journal | `audit.journal` | `/api/core/audit/journal` | Admin → Journal |

---

## 7. Corrections déjà appliquées (19/10/2026)

Six écarts ont été trouvés en exécutant ce plan. Ils sont corrigés :

| # | Symptôme | Cause | Correctif |
|---|---|---|---|
| 1 | `POST /factures/soumettre` → **500** | api-core appelait `http://api-inference:8002/predire` alors que la route est `/api/inference/predire` | `main.py` expose `inference_api_url` ; billing et admin l'utilisent |
| 2 | **500** `can't compare offset-naive and offset-aware datetimes` | le front envoie une date sans fuseau, la validation la comparait à `datetime.now(UTC)` | normalisation des dates dans `validation.py` |
| 3 | `POST /alertes/decision` → **500** | `.scalar()` appelé sur un `UPDATE` (SQLAlchemy 2.1 refuse) | `rowcount` + contrôle « alerte introuvable » |
| 4 | **422** sur presque toutes les factures | plafond métier à 10 000 MGA alors que les actes vont jusqu'à 2 500 000 MGA | plafond porté à 10 000 000 MGA (schéma + validation) |
| 5 | `POST /audit/evenement` → **500** | psycopg n'adapte pas un `dict` Python à une colonne `jsonb` | sérialisation JSON + `CAST(:details AS jsonb)` |
| 6 | Onglet **Remboursements** sans montants, statuts `PAYEE`/`REJETEE` bruts, `is_fraud=null` affiché « Clair » | l'API ne renvoyait pas les montants de prise en charge ; le front ne normalisait pas la casse | ajout de `montant_eligible`, `montant_pris_en_charge`, `reste_a_charge` ; statuts normalisés ; badge « Non controle » si aucune prédiction |

Vérification après correction :

- script automatique : **24 OK / 0 KO** ;
- `CONS-GEN` à 20 000 MGA → **202**, score `0.149546`, `is_fraud=false` ;
- `ACC-CESAR` à 2 500 000 MGA → **202**, score `0.999947`, `is_fraud=true` ;
- `POST /audit/evenement` → `{"status":"ok"}`, puis `audit.journal` contient
  l'entrée `admin / test_plan / documentation` ;
- `GET /factures` avec le jeton de `assure@predicare.local` → **27 factures**
  sur **84 603** en base, toutes avec le même pseudonyme, et les montants
  `montant_pris_en_charge` / `reste_a_charge` renseignés pour les `PAYEE` ;
- UI assuré : colonnes **Facture / Pris en charge / Reste à charge**, statut
  `Remboursee` pour `PAYEE`, `—` pour les factures non traitées, badge
  `Non controle` quand aucune prédiction n'existe.

---

## 8. Points connus à ne pas confondre avec des bugs

| Symptôme | Cause | Statut |
|---|---|---|
| Assistant RAG → 500/503 | image `api-rag` obsolète, clés placeholder ou `document_vectorise` vide | reconstruire l'image, vérifier les clés et `count(*)` ; la chaîne est opérationnelle depuis le 20/10 au soir |
| Aucune alerte au départ | `ml.prediction` vide ; les factures historiques ne sont pas notées | normal |
| Journal vide au départ | aucune action admin effectuée | normal |
| Journal vide après une décision | seules les actions explicites `/api/core/audit/evenement` alimentent `audit.journal` | écart connu |
| Notification Slack absente | `SLACK_WEBHOOK_URL` vide | à configurer ; prouver avec `make e2e-n8n` |
| n8n répond 404 après un import | processus démarré avant la publication CLI | `make n8n-import` redémarre n8n ; sinon `docker compose restart n8n` |
| E-mail n8n en échec après un import | credential SMTP non reliée sur ce poste | rouvrir le nœud e-mail et sélectionner `Mailpit (dev)` |
| File d'alertes vide après une facture | score < 28,76 % | baisser le seuil pour tester |
| Front « pas dynamique » | image `web` non reconstruite | `docker compose build web` |
| Décision impossible | aucune alerte sélectionnée | soumettre une facture d'abord |
| Admin voit tous les écrans | `peut()` accorde tous les droits à `administrateur`, comme l'API | normal |

---

## 9. Ce qu'il faut voir dans le navigateur (F12 → Réseau)

Pour chaque page, ouvre **F12 → Réseau → Fetch/XHR** et vérifie :

| Page | Requêtes attendues | Statut |
|---|---|---|
| Connexion | `POST /api/core/auth/login`, `GET /api/core/auth/me` | 200 |
| Assuré | `GET /api/core/factures` | 200 |
| Pro | `GET /references`, `POST /soumettre`, `GET /factures` | 200 / 202 |
| Gestionnaire | `GET /alertes/file`, `GET /alertes/detail/...`, `POST /alertes/decision` | 200 |
| Admin | `GET /admin/seuil`, `/admin/modele`, `/admin/sante`, `/admin/canaux`, `/admin/utilisateurs`, `/audit/journal` | 200 |

Résultat du passage navigateur du **19/10/2026** :

- **Assuré** : 23 factures affichées, montants en `Ar`, statuts et colonne
  « Contrôle » remplis ;
- **Pro** : référentiel chargé (assurés, prestataires, actes), soumission
  `ACC-CESAR` → **202**, résultat affiché : `100.0 %`, « Au-dessus du seuil —
  alerte », seuil `28.8 %`, modèle `2`, puis 5 barres SHAP ;
- **Gestionnaire** : file de 5 alertes, ouverture du détail → SHAP, décision
  enregistrée → **200**, l'alerte quitte la file et passe dans l'historique ;
- **Admin** : seuil `28.8 %`, modèle actif `2` (`roc_auc 0.950033`), santé
  `ok` pour base / inférence / RAG, 4 comptes listés, journal d'audit affiché.

Si une requête est en **401** : le jeton a expiré ou le compte est désactivé.
Si elle est en **403** : mauvais rôle.
Si elle est en **500** : regarder les logs du service concerné.
