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
