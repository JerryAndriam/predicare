# Créer les tuiles du tableau de bord dans l'interface Superset

Ce guide décrit la procédure **par l'interface**, celle qui est devenue la
voie normale depuis que le code a cessé d'écrire les graphiques.

> **Pourquoi l'interface plutôt que le code ?** Un `form_data` écrit à la
> main doit correspondre exactement à ce qu'attend le *plugin* du graphique
> dans Superset 6.1. Ces règles ne sont pas devinables : `dist_bar` n'existe
> plus, la colonne temporelle doit être dans X-Axis et pas dans Dimension,
> le filtre de temps est ajouté par l'interface. Une description en Python
> de la forme « `groupby` + `metrics` » a produit des tuiles que le serveur
> refusait (« Empty query », « Duplicate column/metric labels ») alors que
> la vérification annonçait 200. **L'interface, elle, produit toujours une
> forme valide.**

## Le cycle

```
interface  ──(make bi-export)──▶  dépôt (archive JSON)  ──(make bi-dashboard)──▶  interface
```

| Étape | Commande | Effet |
| --- | --- | --- |
| Modifier une tuile | — | dans Superset, avec le compte `admin` |
| Archiver | `make bi-export` | écrit `ops/superset/dashboards/pilotage-mensuel.json` |
| Vérifier | `make bi-graphiques` | interroge chaque tuile **comme le navigateur** et compare à l'archive |
| Restaurer | `make bi-dashboard` | rejoue l'archive : le tableau redevient celui du dépôt |

Le compte `demo` est **en lecture seule** : il ouvre le tableau, mais le
serveur refuse toute sauvegarde (`403`). Pour créer ou modifier une tuile,
utiliser `admin`.

## Les quatre règles qui font échouer les créations

1. **X-Axis et Dimension ne sont pas le même contrôle.** La colonne
   temporelle va dans **X-Axis**. Si elle est aussi dans **Dimension**, le
   navigateur envoie deux colonnes du même nom et le serveur refuse :
   *« Duplicate column/metric labels: "mois" »*.
2. **Le type de graphique doit exister en Superset 6.** `dist_bar` a
   disparu (remplacé par `echarts_timeseries_bar`). Un type inconnu n'a
   aucun plugin : *« Data error: Empty query »*.
3. **Ne jamais recopier le filtre de temps à la main.** Quand X-Axis est une
   colonne de date, l'interface ajoute un filtre `TEMPORAL_RANGE` /
   *No filter*. Le recopier tel quel produit un filtre que le serveur
   refuse (*« Missing data for required field »*).
4. **Le tri se choisit explicitement.** Sans métrique de tri (*Sort by*), un
   tableau revient à l'ordre alphabétique, sans lever d'erreur.

## La fiche des douze tuiles

Les datasets sont those de la couche sémantique (`bi.*`), enregistrés par
`make up-bi`. Pour un graphique, l'interface propose un dataset par vue.

### Bandeau — indicateurs globaux (dataset **Indicateurs globaux**)

Type **Big Number** (une tuile « nombre » : un libellé, un chiffre, un
sous-titre — pas de courbe).

| Tuile | Metric | Format | Sous-titre |
| --- | --- | --- | --- |
| Factures traitees | `SUM(nb_factures)` | `,d` | Sur 24 mois |
| Montant presente (MGA) | `SUM(montant_total_mga)` | `~s` | Ariary |
| Taux de fraude observe (%) | `SUM(taux_fraude_pct)` | `.2f` | Prevalence terrain |
| Delai moyen de traitement (jours) | `SUM(delai_moyen_jours)` | `.1f` | Pondere par facture |

### Bandeau — boucle de decision

| Tuile | Dataset | Metric | Sous-titre |
| --- | --- | --- | --- |
| Montants economises confirmes (MGA) | Boucle de decision | `SUM(montant_economise_mga)` | En attente : aucune decision gestionnaire enregistree |
| Taux de detection du modele (%) | Performance du modele | `SUM(rappel_test_pct)` | Test temporel v2 : 3 derniers mois (10 086 factures) |
| Taux de faux positifs du modele (%) | Performance du modele | `SUM(faux_positifs_test_pct)` | Test temporel v2 (precision 59,77 %) |

### Tendances (dataset **Pilotage mensuel**)

Type **Time-series Line** (l'interface : *Line*).

| Tuile | X-Axis | Dimension | Metric | Row limit | Format |
| --- | --- | --- | --- | --- | --- |
| Montant present par mois (MGA) | `mois` | *(vide)* | `SUM(montant_total_mga)` | 24 | `~s` |
| Evolution du delai de traitement | `mois` | *(vide)* | `SUM(delai_traitement_jours)` | 24 | `.1f` |

**Dimension vide, toujours** : le mois est déjà X-Axis. Le grain (*Time
grain*) se met sur `P1M` si le contrôle apparaît.

### Décompositions

| Tuile | Dataset | Type | X-Axis | Dimension | Metric | Row limit |
| --- | --- | --- | --- | --- | --- | --- |
| Fraude par mecanisme (24 mois) | Fraude par mecanisme | Bar (stacked) | `type_fraude` | *(vide)* | `SUM(nb_fraudes)` | 20 |
| Motifs de non-paiement par mois | Points de controle | Bar (stacked) | `mois` | `motif` | `SUM(nb_factures)` | 10 000 |
| Cinq prestataires les plus exposes (MGA) | Top 5 prestataires | Table | *(colonnes : `prestataire_nom`)* | — | `SUM(montant_expose_mga)`, `SUM(taux_fraude_pct)` | 5 |

* **Cinq prestataires** : le *« 5 » est dans la vue* (`bi.v_top5_prestataires`),
  pas dans un contrôle. La tuile affiche donc cinq lignes quel que soit le
  type de graphique choisi, et le tri se fait sur le montant exposé
  (*Sort by* → Montant expose).
* **Motifs de non-paiement** : les mois en X-Axis, les motifs en Dimension →
  une barre par mois, empilée par motif.

## Créer une tuile, pas à pas

1. **Superset → Datasets** : choisir le dataset (une vue `bi.*`).
2. **Create chart** : choisir le type (Big Number, Line, Bar, Table).
3. **Controls** :
   - *X-Axis* : la colonne de date ou de catégorie ;
   - *Dimension* : les autres colonnes, **jamais** la colonne de X-Axis ;
   - *Metrics* : les mesures, avec leur format ;
   - *Row limit* : le nombre de lignes ;
   - *Sort by* : la métrique de tri, si l'ordre importe.
4. **Enregistrer**, puis **Ajouter au dashboard** « Pilotage mensuel ».
5. **Archiver** : `make bi-export`.
6. **Vérifier** : `make bi-graphiques` — 12/12, aucune dérive.

## Diagnostiquer une tuile qui affiche « Data error »

| Message | Cause | Remède |
| --- | --- | --- |
| `Empty query` | le type de graphique n'existe pas en v6 (`dist_bar`, `mixed_timeseries` obsolète…) ou X-Axis/Dimension/Metrics sont vides | vérifier le type dans la liste de Superset 6 ; renseigner X-Axis **et** au moins une métrique |
| `Duplicate column/metric labels: "X"` | la colonne temporelle est à la fois en X-Axis et en Dimension | vider Dimension, ou sortir la colonne temporelle de Dimension |
| `Missing data for required field` | un filtre `TEMPORAL_RANGE` / *No filter* a été recopié à la main | le supprimer de *Filters* : l'interface l'ajoute quand il faut |
| une tuile « nombre » sans courbe | une tuile Big Number n'a pas de graphique | la courbe est la tuile voisine (*Evolution du delai de traitement*) |
| le tableau n'affiche pas les 12 tuiles | une tuile a été supprimée, ou le `position_json` a été altéré | `make bi-dashboard` restaure l'archive |

## L'archive

`ops/superset/dashboards/pilotage-mensuel.json` contient tout l'état :

```jsonc
{
  "slug": "pilotage-mensuel",
  "tuiles": [
    {"titre": "…", "viz_type": "echarts_timeseries", "vue": "v_kpi_mensuel",
     "params": {…}, "cache_timeout": null}      // le form_data écrit par l'interface
  ],
  "position_json": {…},                          // la mise en page
  "json_metadata": {…}                           // les filtres natifs
}
```

L'archive est **versionnée** : c'est elle qui fait foi. Une tuile modifiée
dans l'interface sans `make bi-export` est signalée par `make bi-graphiques`
comme une dérive, et remise en place par `make bi-dashboard`.
