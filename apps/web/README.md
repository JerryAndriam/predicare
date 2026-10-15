# Interface web

Application unique pour les quatre roles (CDC, condition Utilisable). Build
Vite + TypeScript, servie par nginx. Le navigateur ne voit qu'une seule
origine : la passerelle route `/api/*` vers les trois services.

## Roles et parcours

| Role | Parcours attendu |
| --- | --- |
| Assure | Chat RAG, historique de ses remboursements |
| Professionnel de sante | Depot de factures et ordonnances, suivi des dossiers |
| Gestionnaire | File d'alertes, rapport SHAP, decision valider ou rejeter |
| Administrateur | Seuil, canaux, secrets, metriques, sante, rollback modele |

## Structure

```
src/
  main.tsx        point de montage
  App.tsx         coquille : les quatre roles, etats de sante
  vite-env.d.ts   types des variables VITE_*
Dockerfile        build Node 22 puis service nginx non root
nginx.conf        routage /api et regles de cache
```

## Brouillon / TODO

- [ ] Ecran de connexion (JWT stocke en memoire session)
- [ ] Garde de routes par role, derivee du JWT
- [ ] Formulaire de depot de facture avec validation cote client
- [ ] Vue gestionnaire : file d'alertes et lecture du rapport SHAP
- [ ] Vue administrateur : seuil, canaux, metriques, rollback
- [ ] Vue assure : chat RAG avec affichage des sources citees
- [ ] Tests de parcours de bout en bout (Playwright)

Proprietaire : Cherica
