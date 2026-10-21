# Interface web

Application unique pour les quatre roles (CDC, condition « Utilisable »).
Build Vite + TypeScript, servie par nginx. Le navigateur ne voit qu'une seule
origine : la passerelle route `/api/*` vers les trois services.

## Adresse a ouvrir

| Adresse | Usage |
| --- | --- |
| `http://localhost:8080` | **Adresse de demonstration** : la passerelle Traefik sert l'interface ET les trois API sur la meme origine. |
| `http://localhost:8081` | Acces direct au conteneur web. Les appels `/api/core` passent, mais `/api/inference` et `/api/rag` **non** : le nginx du conteneur ne proxifie que vers api-core. |

En developpement, `npm run dev` reproduit le routage de la passerelle avec
trois proxys (`/api/core` -> 8001, `/api/inference` -> 8002,
`/api/rag` -> 8003).

## Comptes de demonstration

La table `core.utilisateur` est vide apres les migrations : aucun mot de passe
n'est code en dur dans le depot. Creer les quatre comptes :

```bash
# mot de passe genere et affiche une fois
make comptes

# ou mot de passe impose (au moins 12 caracteres)
DEMO_PASSWORD='PrediCare2026!' make comptes
```

| Compte | Role |
| --- | --- |
| `assure@predicare.local` | assure |
| `pro@predicare.local` | professionnel de sante |
| `gestionnaire@predicare.local` | gestionnaire |
| `admin@predicare.local` | administrateur |

Le compte assure est rattache au premier dossier de `core.assure` : lancez le
seed des donnees avant `make comptes`, sinon l'historique sera vide.

Le script sert a amorcer la plateforme ; ensuite, un administrateur cree et
desactive les comptes depuis l'onglet **Comptes** de l'administration. Le mot
de passe est hache (Argon2id) a l'ecriture et n'est jamais renvoye par l'API.
Deux garde-fous empechent de se desactiver soi-meme et de retirer le dernier
administrateur actif. La desactivation bloque la prochaine connexion ; un jeton
deja emis reste valide jusqu'a son expiration.

## Structure

```
src/
  main.tsx              montage React + Router + AuthProvider
  App.tsx               routes et gardes par role
  api/client.ts         fetch unique, jeton, erreurs typées
  api/types.ts          contrats recopies des schemas Pydantic
  auth/AuthContext.tsx  connexion, profil, deconnexion
  components/           coquille, gardes, briques d'interface, barres SHAP
  pages/                un espace par role
  styles.css            feuille unique, sans police ni icone externe (CSP)
```

## Contrats consommes

| Ecran | Endpoints |
| --- | --- |
| Connexion | `POST /api/core/auth/login`, `GET /api/core/auth/me` |
| Assure | `GET /api/core/factures`, `POST /api/rag/question` |
| Professionnel | `GET /api/core/factures/references`, `POST /api/core/factures/soumettre`, `POST /api/core/factures/ordonnances`, `GET /api/core/factures` |
| Gestionnaire | `GET /api/core/alertes/file`, `GET /api/core/alertes/detail/{id}`, `POST /api/core/alertes/decision`, `GET /api/core/alertes/historique` |
| Administrateur | `GET/PUT /api/core/admin/seuil`, `GET /api/core/admin/modele`, `POST /api/core/admin/modele/candidat`, `/bascule`, `/retour-arriere`, `GET /api/core/admin/sante`, `GET /api/core/admin/canaux`, `GET /api/core/audit/journal` |

## Assistant RAG (espace assure)

L'onglet **Assistant** de `AssurePage` est porte par
`components/RagAssistant.tsx` ; il consomme `POST /api/rag/question`.

- **Conversation** : un `session_id` UUID est genere au montage et rejoue a
  chaque question. Le serveur le cloisonne par assure (`assure_id`) et garde
  six tours pendant une heure. **Nouvelle conversation** vide l'ecran et
  genere un nouvel identifiant.
- **Citations** : chaque source affiche contrat, article, garantie, extrait
  contractuel replie, score de pertinence et fichier. Le composant
  `RagSourceCard` ne rend que du texte, jamais de HTML.
- **Agent** : la trace repliee montre les outils (`rechercher_contrats`,
  `consulter_historique_assure`), leur statut et leur duree.
- **FinOps** : les details techniques affichent latence, tokens d'entree et de
  sortie, coût USD/EUR et indicateur de cache.
- **Erreurs** : 400, 401, 403, 422, 429, 500/502/503 et panne reseau ont des
  messages distincts ; une reponse `succes = false` est marquee « Réponse
  dégradée ».
- **Accessibilite** : conversation en `role="log"`, `aria-live="polite"`,
  `aria-busy`, focus rendu au champ apres reponse.

Le backend accepte deja `session_id` ; aucune route supplementaire n'est
necessaire. Les tests de la chaine restent
`tests/e2e/test_rag_parcours.py` et `scripts/e2e_rag.sh`.

## Regles respectees

- **Le controle d'acces est cote API** : les gardes de routes ne sont qu'une
  aide a la navigation. Un assure qui appelle `/alertes/file` recoit un 403,
  meme s'il connait l'URL.
- **Jeton en `sessionStorage`** : il disparait a la fermeture de l'onglet.
- **Aucun secret dans le bundle** : seules des URL relatives `/api/...` sont
  injectees a la construction.
- **Aucune ressource externe** : la CSP de Traefik interdit les CDN, donc pas
  de police distante ni de bibliotheque chargee depuis un domaine tiers.
- **Les montants et seuils viennent de l'API**, jamais d'une valeur codee en
  dur dans l'ecran.

## Ce qui reste a fournir pour une demonstration complete

1. Un modele entraine (`make train VERSION=2`, puis `make model-promote`) :
   sans lui, `/predire` repond 503 et l'ecran professionnel affiche l'erreur
   metier correspondante.
2. `LLM_API_KEY` et `EMBEDDING_API_KEY` dans `.env` : sans eux, l'assistant
   repond « momentanement indisponible ».
3. Les donnees brutes dans `data/raw` puis le seed (`make reload-data`).
