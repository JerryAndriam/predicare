#!/usr/bin/env bash
# =============================================================================
# Generateur du fichier d'identifiants PrediCare
# -----------------------------------------------------------------------------
# Produit une fiche d'accès à jour, lisible le jour de la soutenance.
#
# Pourquoi un fichier HORS du dépôt : il contient les vrais mots de passe.
# Il est écrit à côté du CDC et du plan d'action, jamais dans le dépôt Git,
# ce qui évite d'avoir à ajouter une règle d'exclusion et protège l'historique.
#
# Usage :
#   make acces
#   make acces ACCES_FILE=/tmp/fichier.md
#
# Le script n'invente jamais de valeur : un secret encore au marqueur
# `CHANGER_MOI` est signalé « à remplir » plutôt que recopié tel quel.
#
# ---------------------------------------------------------------------------
# NOTE D'ECRITURE IMPORTANTE
#
# Le document est produit par un heredoc QUOTE (`<<'FIN'`), donc aucune
# substitution n'y a lieu. Toutes les valeurs dynamiques sont ensuite
# injectees par sed sur des jetons `{{NOM}}`.
#
# La premiere version utilisait un heredoc NON quote. Les fences markdown
# ``` etait alors interpretees comme des substitutions de commande : le texte
# entre accents graves etait EXECUTE, et sa sortie atterrissait dans le
# fichier. Le document contient des blocs de code Markdown par nature, cette
# ecriture etait donc une bombe a retardement.
# =============================================================================

set -uo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RACINE"

ACCES_DIR="${ACCES_DIR:-/home/jerry/Documents/predicare}"
ACCES_FILE="${ACCES_FILE:-${ACCES_DIR}/ACCES_PREDICARE.md}"

log() { printf '\033[36m[acces]\033[0m %s\n' "$*"; }
err() { printf '\033[31m[acces]\033[0m %s\n' "$*" >&2; }

[ -f .env ] || { err "Aucun .env. Lancez d'abord : make setup"; exit 1; }

# shellcheck disable=SC1091
set -a
source .env
set +a

# --- Valeurs dynamiques ----------------------------------------------------
declare -A V

# Un secret encore au marqueur s'affiche « à remplir », jamais recopié tel
# quel : afficher une valeur invalide ferait perdre du temps le jour J.
valeur() {
    local v="${!1:-}"
    if [ -z "$v" ]; then
        printf 'non défini'
    elif printf '%s' "$v" | grep -q 'CHANGER_MOI'; then
        printf 'À REMPLIR'
    else
        printf '%s' "$v"
    fi
}

marquant() {
    local v="${!1:-}"
    if [ -z "$v" ]; then printf 'absent'
    elif printf '%s' "$v" | grep -q 'CHANGER_MOI'; then printf 'À REMPLIR'
    else printf 'ok'
    fi
}

etat_service() {
    local conteneur="$1"
    if ! docker inspect "$conteneur" >/dev/null 2>&1; then
        printf 'non démarré'
        return
    fi
    local etat boucle
    etat=$(docker inspect -f '{{.State.Status}}' "$conteneur" 2>/dev/null || echo '?')
    boucle=$(docker inspect -f '{{.RestartCount}}' "$conteneur" 2>/dev/null || echo 0)
    if [ "$etat" = "running" ]; then
        if [ "${boucle:-0}" -ge 3 ]; then printf 'en boucle de redémarrage'; else printf 'démarré'; fi
    else
        printf '%s' "$etat"
    fi
}

# Compte n8n de CETTE machine. n8n >= 1.x a supprime l'authentification
# basique : il n'existe aucun mot de passe n8n, le compte se cree au premier
# lancement de l'interface avec l'email saisi par le visiteur.
#
# Trois etats sont distingues : aucun compte, un compte cree mais dont le
# setup n'a pas ete termine (email vide), un compte complet. Sur le dernier,
# le moteur n8n cree une ligne vide avant que l'internaute ne remplisse le
# formulaire : confondre les deux ferait afficher « tout va bien » alors
# que personne ne peut se connecter.
compte_n8n() {
    local lignes
    lignes=$(docker compose exec -T db psql -U "${POSTGRES_USER:-predicare}" -d n8n \
        -tAc "SELECT coalesce(email, '') FROM \"user\" ORDER BY email" 2>/dev/null \
        | tr -d '\r' | grep -v '^$' || true)

    if [ -z "$lignes" ]; then
        printf 'aucun compte'
    elif printf '%s' "$lignes" | grep -q '^$'; then
        printf '⚠ setup non termine — a creer'
    else
        printf '%s' "$lignes" | tr '\n' ' '
    fi
}

V[DATE]="$(date '+%Y-%m-%d à %H:%M')"
V[GATEWAY]="http://localhost:${GATEWAY_PORT:-8080}"
V[N8N]="http://localhost:${N8N_PORT:-5678}"
V[SUPERSET]="http://localhost:${SUPERSET_PORT:-8088}"
V[GRAFANA]="http://localhost:${GRAFANA_PORT:-3001}"
V[MLFLOW]="http://localhost:${MLFLOW_PORT:-5000}"
V[PROM]="http://localhost:${PROMETHEUS_PORT:-9090}"
V[MAILPIT]="http://localhost:${MAILPIT_UI_PORT:-8025}"

V[POSTGRES_PASSWORD]="$(valeur POSTGRES_PASSWORD)"
V[RO_PASSWORD]="$(valeur PREDICARE_DB_RO_PASSWORD)"
V[BI_PASSWORD]="$(valeur SUPERSET_DB_RO_PASSWORD)"
V[SUPERSET_ADMIN]="$(valeur SUPERSET_ADMIN_PASSWORD)"
V[GRAFANA_ADMIN]="$(valeur GRAFANA_ADMIN_PASSWORD)"
V[SUPERSET_USER]="${SUPERSET_ADMIN_USERNAME:-admin}"
V[GRAFANA_USER]="${GRAFANA_ADMIN_USER:-admin}"

V[N8N_COMPTE]="$(compte_n8n)"
V[ETAT_N8N]="$(etat_service predicare-n8n)"
V[ETAT_SUPERSET]="$(etat_service predicare-superset)"
V[ETAT_GRAFANA]="$(etat_service predicare-grafana)"
V[ETAT_MLFLOW]="$(etat_service predicare-mlflow)"
V[ETAT_PROM]="$(etat_service predicare-prometheus)"
V[ETAT_MAILPIT]="$(etat_service predicare-mailpit)"
V[ETAT_WEB]="$(etat_service predicare-web)"
V[ETAT_CORE]="$(etat_service predicare-api-core)"
V[ETAT_INF]="$(etat_service predicare-api-inference)"
V[ETAT_RAG]="$(etat_service predicare-api-rag)"

V[LLM_KEY]="$(marquant LLM_API_KEY)"
V[EMB_KEY]="$(marquant EMBEDDING_API_KEY)"
V[SLACK_HOOK]="$(marquant SLACK_WEBHOOK_URL)"
V[SLACK_CHAN]="$(marquant SLACK_CHANNEL_ID)"
V[LLM_MODEL]="${LLM_MODEL:-gpt-4o-mini}"
V[EMB_MODEL]="${EMBEDDING_MODEL:-text-embedding-3-small}"
V[EMB_DIM]="${EMBEDDING_DIMENSION:-1536}"
V[SEUIL]="${FRAUD_ALERT_THRESHOLD:-0.8}"
V[RAPPEL]="${FRAUD_MIN_RECALL:-0.90}"

# --- Document littéral -----------------------------------------------------
# Stocke dans une variable plutot que dans un fichier temporaire : la
# substitution se fait ensuite en bash natif.
CONTENU=$(cat <<'FIN'
# PrediCare TPA — fiche d'accès

> **Contient des secrets.** Ne pas diffuser, ne pas versionner, ne pas
> imprimer dans un document partagé. Ce fichier est écrit **hors** du dépôt
> Git, à côté du CDC et du plan d'action.

Généré le {{DATE}} par `make acces`.
Source des valeurs : le fichier `.env` de la plateforme.

---

## 1. Accès aux applications

| Application | URL | Utilisateur | Mot de passe | État |
| --- | --- | --- | --- | --- |
| **Interface PrediCare** | {{GATEWAY}} | ⚠ aucun compte créé | — | {{ETAT_WEB}} |
| Documentation API (Swagger) | {{GATEWAY}}/api/core/docs | libre | — | {{ETAT_CORE}} |
| Documentation API inference | {{GATEWAY}}/api/inference/docs | libre | — | {{ETAT_INF}} |
| Documentation API RAG | {{GATEWAY}}/api/rag/docs | libre | — | {{ETAT_RAG}} |
| **n8n** — workflows d'alerte | {{N8N}} | {{N8N_COMPTE}} | *(voir § 3)* | {{ETAT_N8N}} |
| **Superset** — tableau de bord | {{SUPERSET}} | `{{SUPERSET_USER}}` | `{{SUPERSET_ADMIN}}` | {{ETAT_SUPERSET}} |
| Grafana — supervision | {{GRAFANA}} | `{{GRAFANA_USER}}` | `{{GRAFANA_ADMIN}}` | {{ETAT_GRAFANA}} |
| MLflow — suivi ML | {{MLFLOW}} | libre | — | {{ETAT_MLFLOW}} |
| Prometheus — métriques | {{PROM}} | libre | — | {{ETAT_PROM}} |
| Mailpit — e-mails de dev | {{MAILPIT}} | libre | — | {{ETAT_MAILPIT}} |

Les services en « libre » n'ont pas d'authentification : ils sont hors du
réseau de données et n'exposent rien de sensible.

---

## 2. Accès aux bases de données

Serveur unique, trois comptes avec trois périmètres distincts.

| Compte | Base | Usage | Mot de passe |
| --- | --- | --- | --- |
| `predicare` | predicare | application, migrations, sauvegarde | `{{POSTGRES_PASSWORD}}` |
| `predicare_ro` | predicare | **agent RAG** — lecture seule, filtré sur l'assuré connecté | `{{RO_PASSWORD}}` |
| `superset_ro` | predicare | **tableau de bord BI** — lecture seule, aucun accès au schéma `audit` | `{{BI_PASSWORD}}` |

Connexion locale :

```bash
make shell-db
```

**Aucun port TCP n'est publié sur la machine.** Le réseau `core` du projet est
`internal: true`, et Docker n'active la publication d'un port que si le
conteneur est attaché à au moins un réseau **non** interne. Un `psql
localhost:55432` échoue donc en `Connection refused` — ce n'est pas une panne.

Pour parler au serveur SQL :

```bash
make shell-db                                  # psql dans le conteneur
docker compose exec -T db psql -U predicare -d predicare -c '\dt'
```

Pour un client graphique (DBeaver, pgAdmin), passer par un tunnel SSH vers le
conteneur plutôt que par un port direct.

Bases annexes créées automatiquement : `n8n`, `superset`, `mlflow`.

Bases annexes créées automatiquement : `n8n`, `superset`, `mlflow`.

---

## 3. Compte n8n

n8n a **supprimé l'authentification basique** en version 1.x : il n'existe
aucun mot de passe n8n dans le `.env`, et c'est normal. Le compte
propriétaire se crée au premier lancement de l'interface, avec l'email
saisi par le visiteur.

- **Chaque machine a son propre compte.** Il n'est pas synchronisé entre
  postes, et le mot de passe n'est stocké nulle part : notez-le.
- **Mot de passe oublié ?**

  ```bash
  docker compose exec n8n n8n user-management:reset
  ```

  Cette commande réinitialise l'instance entière : workflows compris.

- **État sur cette machine :** `make n8n-compte`

Les workflows se partagent entre machines **par Git**, pas dans
n8n : l'édition Community n'a pas de partage de projet.

```bash
make n8n-export    # exporte les workflows
git add apps/n8n && git commit -m "n8n : synchronise les workflows" && git push
make n8n-import    # installe et publie sur l'autre poste
```

---

## 4. Clés externes à renseigner

Elles ne sont **pas** dans le dépôt et ne peuvent pas l'être.

| Service | Variable | État |
| --- | --- | --- |
| Fournisseur LLM | `LLM_API_KEY` | {{LLM_KEY}} |
| Embeddings | `EMBEDDING_API_KEY` | {{EMB_KEY}} |
| Slack — alerte fraude | `SLACK_WEBHOOK_URL` | {{SLACK_HOOK}} |
| Slack — canal | `SLACK_CHANNEL_ID` | {{SLACK_CHAN}} |

Sans clé LLM, l'assistant RAG démarre mais répond
« service temporairement indisponible ». Sans webhook Slack, le workflow
n8n s'exécute mais n'alerte personne : les credentials se créent **dans
l'interface n8n**, pas dans un fichier.

---

## 5. À compléter avant la démonstration

- [ ] **Comptes utilisateurs des 4 rôles.** La table `core.utilisateur` est
      vide : personne ne peut encore se connecter à l'interface.
- [ ] `LLM_API_KEY` et `EMBEDDING_API_KEY` — sans eux, pas de démonstration
      de l'assistant conversationnel.
- [ ] Credentials Slack dans l'interface n8n (Settings → Credentials).
- [ ] Modèle de fraude entraîné — sans lui, `api-inference` reste
      `degraded` et ne note aucune facture.
- [ ] Jeu de données dans `./data/raw` — la base est vide.
- [ ] Workflow n8n importé : `make n8n-import`.

---

## 6. Configuration courante

| Réglage | Valeur | Où le changer |
| --- | --- | --- |
| Seuil d'alerte | {{SEUIL}} | écran d'administration, sans redémarrage |
| Rappel minimal visé | {{RAPPEL}} | `.env`, justification du choix du seuil |
| Modèle d'embeddings | `{{EMB_MODEL}}` | `.env` |
| Modèle LLM | `{{LLM_MODEL}}` | `.env` |
| Dimension des vecteurs | {{EMB_DIM}} | `.env` — **doit rester alignée sur `EMBEDDING_MODEL`** |

---

## 7. Commandes du jour J

```bash
make doctor           # la machine est-elle prête ?
make up               # démarre la plateforme
make start            # redémarre sans reconstruire
make ps               # état des conteneurs
make health           # santé et métriques
make smoke            # parcours de vérification complet
make logs             # journaux en direct
make logs-service S=n8n
make n8n-compte       # compte n8n de cette machine
make n8n-import       # installe et publie les workflows
make threshold VALEUR=0.75   # change le seuil à chaud
make backup           # sauvegarde PostgreSQL immédiate
make restore          # restauration (demande confirmation)
make down             # arrêt, les données sont conservées
```

---

## 8. Deux pièges à connaître

1. **Changer `POSTGRES_PASSWORD` casse la base existante.** L'image
   PostgreSQL n'applique ce mot de passe qu'à la première initialisation
   du volume. Sur une installation qui tourne, il faut soit
   `make clean && make up`, soit un `ALTER ROLE` suivi de la mise à jour
   des URL dans le `.env`.
2. **`n8n` redémarre en boucle si sa base n'existe pas.** Le job
   `migrate` la crée ; s'il n'a pas abouti, le correctif est
   `make migrate` puis `docker compose restart n8n`.

---

*Régénérer ce fichier : `make acces`.*
FIN
)

# --- Injection des valeurs -------------------------------------------------
# Substitution bash native plutot que `sed`.
#
# La premiere version utilisait `sed -e "s|{{CLE}}|valeur|g"`. C'est fragile :
# si une valeur contient le delimiteur `|`, sed echoue sur « commande s
# inachevée » et le fichier sort VIDE, sans erreur visible puisque le script
# ne verifiait pas le code de sortie. Une valeur contenant `&` ou `\` aurait
# produit le meme resultat, de maniere encore plus discrete.
# `${var//motif/valeur}` n'a aucun de ces defauts.
for cle in "${!V[@]}"; do
    # Motif SANS guillemets : entre guillemets, les antislash seraient
    # pris litteralement et aucun remplacement n'aurait lieu.
    CONTENU=${CONTENU//\{\{${cle}\}\}/${V[$cle]}}
done

# Une variable restee en place signale un jeton mal nomme : mieux vaut le
# voir dans le fichier que le deviner.
if printf '%s' "$CONTENU" | grep -q '{{'; then
    err "Jeton non remplace dans le document. Fichier incomplet : $ACCES_FILE"
    exit 1
fi

mkdir -p "$(dirname "$ACCES_FILE")"
printf '%s\n' "$CONTENU" > "$ACCES_FILE"
chmod 600 "$ACCES_FILE"

log "Fiche d'accès écrite :"
log "  $ACCES_FILE"
log ""
log "Elle est hors du dépôt Git : aucun secret n'entre dans l'historique."

# Contrôle : aucun de ces secrets ne doit avoir fui dans le dépôt.
if command -v git >/dev/null 2>&1 && [ -d .git ]; then
    APERCU="${POSTGRES_PASSWORD:0:12}"
    if [ -n "$APERCU" ] && git grep -q -- "$APERCU" 2>/dev/null; then
        err "ATTENTION : un mot de passe de base figure dans un fichier versionné."
        exit 1
    fi
fi