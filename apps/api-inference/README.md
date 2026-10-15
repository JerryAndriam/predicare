# Flux 1 - chaine de detection de fraude

Service FastAPI qui transforme une facture en score de fraude **explicable**.
Il est separe des deux autres flux parce qu'il a ses propres dependances
(XGBoost, SHAP), sa propre latence et son propre cycle de vie : un modele
peut etre remplace sans redemarrer le reste de la plateforme.

## Modules

| Module | Contenu |
| --- | --- |
| `validation.py` | Validation stricte d'entree, messages nommant le champ fautif |
| `features.py` | Featurisation : fonction PURE, aucun acces base |
| `registry.py` | Versions de modele, bascule a chaud, retour arriere |
| `explainability.py` | Valeurs SHAP traduites en francais lisible |
| `drift.py` | PSI par variable, detection de derive |
| `router.py` | Endpoints : predire, seuil, modele, derive |

## Points de securite et de robustesse

- Une facture invalide produit **422 avec le nom du champ**, jamais une 500.
  C'est le cas que le jury soumet le jour J.
- Le seuil est relu a chaque appel : un changement depuis l'ecran
  d'administration s'applique a la facture suivante.
- Le conteneur execute l'utilisateur `predicare`, pas root.

## Brouillon / TODO

- [ ] Persister predictions et explications SHAP dans `ml.prediction`
- [ ] Agregations SQL d'historique pour la featurisation
- [ ] Persistance du rapport de derive calcule par le worker
- [ ] Test de robustesse sur 20 factures inedites (Phase 8.1)
- [ ] Tests unitaires sur la validation (priorite haute)

Proprietaire : Mirado
