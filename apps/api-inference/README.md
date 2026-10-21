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
| `derive.py` | Calcul du rapport de derive et ecriture dans `ml.rapport_derive` |
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

## Rapport de derive

Le worker `worker-ingest` calcule un rapport au demarrage, puis au plus une
fois par heure. Il l'ecrit dans `ml.rapport_derive` ; l'API et le worker etant
deux processus, un etat en memoire du worker ne serait jamais visible depuis
`GET /api/inference/derive`. La lecture en base rend aussi le rapport
consultable apres un redemarrage.

Faute de feature store, le calcul compare ce que `ml.prediction` conserve
reellement, sur la version de modele active :

| Variable | Source |
| --- | --- |
| `score_fraude` | `ml.prediction` |
| `montant_total` | `core.facture` |
| `nb_lignes` | `count(core.ligne_facture)` |
| `montant_moyen_ligne` | `avg(montant_unitaire * quantite)` |

La reference est la notation retrospective (`statut = 'archive'`) ; la fenetre
courante exclut ces archives et se limite aux `DRIFT_WINDOW_DAYS` derniers
jours. Le PSI suit les seuils conventionnels : stable sous 0,10, derive
moderee de 0,10 a 0,25, forte au-dela. Les effectifs des deux echantillons
sont stockes avec le rapport : un PSI calcule sur 18 lignes n'a pas la meme
portee que sur 5 000.

```bash
curl -s http://localhost:8002/api/inference/derive | python3 -m json.tool
```

```json
{
  "status": "ok",
  "id": 1,
  "calcule_le": "2026-10-20T12:11:15.591786+02:00",
  "fenetre_jours": 30,
  "psi_global": 6.5287,
  "variables_concernees": {
    "concernees": ["score_fraude", "montant_moyen_ligne", "montant_total", "nb_lignes"],
    "psi_par_variable": {"score_fraude": 6.5287, "montant_moyen_ligne": 5.1184},
    "observations_reference": 5510,
    "observations_courantes": 18,
    "version_modele": "1"
  },
  "score_moyen_reference": 0.1359,
  "score_moyen_courant": 0.5567,
  "alerte": true
}
```

La mesure du 20/10/2026 est volontairement extreme : la fenetre courante
contient le lot de 20 factures F17 (7 alertes) et les rejeux e2e, pas un
echantillon de production. Le rapport fait donc son travail — il signale que
la population servie ne ressemble plus a l'historique — et l'effectif
`observations_courantes: 18` permet de l'interpreter. Le front ne consomme pas
encore cet endpoint (voir `docs/livrables/04_securite.md`).

## Points de securite et de robustesse

- Une facture invalide produit **422 avec le nom du champ**, jamais une 500.
  C'est le cas que le jury soumet le jour J.
- Le seuil est relu a chaque appel : un changement depuis l'ecran
  d'administration s'applique a la facture suivante.
- Le conteneur execute l'utilisateur `predicare`, pas root.

## Reste à faire

- [ ] Agrégations SQL d'historique pour la featurisation — **ce n'est pas un
  bug** : le modèle servi a 32 variables, aucune n'est une agrégation. Les
  ajouter impose un ré-entraînement v3 et la requête d'historique qui va avec.
