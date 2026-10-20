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
| `scoring.py` | Score XGBoost + contributions SHAP, partages par l'API et le lot |
| `registry.py` | Versions de modele, bascule a chaud, retour arriere |
| `explainability.py` | Valeurs SHAP traduites en francais lisible |
| `drift.py` | PSI par variable, detection de derive |
| `router.py` | Endpoints : predire, seuil, modele, derive |
| `noter.py` | Job de notation en lot de l'historique (`make noter`) |

## Notation en lot (`make noter`)

Le chargement initial ecrit 84 000 factures, aucune prediction. `noter.py`
rejoue l'historique pour peupler `ml.prediction` : sans lui, la file d'alertes
reste vide et la boucle de decision n'a aucune cle.

```bash
make noter DRY_RUN=1 LIMITE=50          # calcule et affiche, sans ecrire
make noter LIMITE=500                   # note 500 factures (statut `archive`)
make noter LIMITE=200 STATUT=nouvelle   # entre dans la file du gestionnaire
make noter REFERENCE=FAC-00001234 RESCORER=1   # diagnostic d'une facture
```

**Le job tourne en process, pas via HTTP.** Une facture stockee porte son
`ordonnance_id` et son `heure_soin` ; la payload de soumission ne les transporte
pas, et le service les devine (ordonnance la plus recente, heure a 00:00).
Passer par `/predire` produirait donc un score different de l'entrainement :
`FAC-00063774` passe de 0,06 a 0,998. Le job importe `calculer_features` et
`Scorer`, exactement comme le service, et lit le contexte exact en base.

Deux choix structurants :

- **`statut = 'archive'` par defaut.** Une prediction retrospective documente
  la qualite du modele mais n'a jamais ete soumise a un gestionnaire. La
  compter dans les faux positifs ferait afficher 100 % sur un historique que
  personne n'a eu a traiter. Les vues `bi.v_faux_positifs` et `bi.v_cdc_global`
  excluent ce statut ; `bi.v_detection_mensuel` le conserve, parce qu'il mesure
  le volume d'inferences du modele.
- **Idempotence par exclusion.** Le job ne selectionne que les factures sans
  prediction. Relancer sur le meme lot ne renote rien et ne cree aucun
  doublon. `RESCORER=1` leve le filtre et met a jour la prediction existante.

## Points de securite et de robustesse

- Une facture invalide produit **422 avec le nom du champ**, jamais une 500.
  C'est le cas que le jury soumet le jour J.
- Le seuil est relu a chaque appel : un changement depuis l'ecran
  d'administration s'applique a la facture suivante.
- Le conteneur execute l'utilisateur `predicare`, pas root.

## Brouillon / TODO

- [x] Persister predictions et explications SHAP dans `ml.prediction`
  (`router.py` ; le peuplement de l'historique est le job `make noter`)
- [ ] Agregations SQL d'historique pour la featurisation — **pas un bug** :
  le modele servi a 32 variables, aucune n'est une agregation. Les ajouter
  impose un re-entrainement v3 et la requete d'historique qui va avec.
- [ ] Persistance du rapport de derive calcule par le worker
- [ ] Test de robustesse sur 20 factures inedites (Phase 8.1)
- [ ] Tests unitaires sur la validation (priorite haute)

Proprietaire : Mirado
