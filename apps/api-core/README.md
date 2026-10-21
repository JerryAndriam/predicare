# Flux 3 et socle d'exploitation

Service FastAPI qui porte l'identite, les factures, les decisions du
gestionnaire et l'ecran d'administration. Il ne calcule aucun score : c'est
le role de `api-inference`.

## Modules

| Module | Contenu |
| --- | --- |
| `identity/` | Connexion, profil, changement de mot de passe |
| `billing/` | Depot de factures et ordonnances, historique par assure |
| `decisions/` | File d'alertes, rapport SHAP, decision gestionnaire |
| `admin/` | Seuil a chaud, canaux, etat du modele, sante |
| `audit/` | Journal d'audit, reserve gestionnaire et administrateur |

## Points de securite

- Le filtre sur l'assure connecte est pose DANS la requete SQL, a partir du
  pseudonyme du jeton. Il n'est jamais renvoye au client pour qu'il filtre.
- `/admin/*` exige la permission `seuil:modifier`, donc le role administrateur.
- Les routes d'ecriture tracent un evenement dans `audit.journal`.

## Brouillon / TODO

- [ ] Persistance des sessions (refresh token)
- [ ] CRUD complet des factures et des ordonnances
- [ ] Endpoint de soumission relayant reellement vers `api-inference`
- [ ] Tests d'integration par role (Phase 6.6)
- [ ] Ecran de restitution du rapport SHAP complet

Proprietaire : Cherica
