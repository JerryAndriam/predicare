# Pilotage decisionnel

Couche semantique du tableau de bord Superset, et documentation des
indicateurs (Phase 7.3 du plan d'action : « Documenter chaque indicateur :
definition, source, frequence de mise a jour »).

## Principe : des vues, pas des graphiques construits a la main

Les vues vivent dans `db/bi/views/*.sql` et sont appliquees par
`db/bi/load.sh`. Un tableau de bord construit dans l'interface n'est ni
auditable, ni reproductible sur une machine vierge : il faut le refaire a la
main, et personne ne peut dire d'ou vient un chiffre.

Ce qui est dans le depot :

| Element | Ou |
| --- | --- |
| Schema et droits | `db/migrations/versions/0005_schema_bi.py` |
| Vues | `db/bi/views/*.sql` |
| Chargement | `db/bi/load.sh` |
| Datasets Superset | `ops/superset/register_datasets.py` |
| Graphiques et dashboard | `ops/superset/register_dashboard.py` |

Les VUES ne sont pas des migrations, volontairement : un indicateur change
dix fois plus souvent qu'un schema, et l'obliger a ecrire une migration a
chaque retouche de libelle decourage de corriger, donc les indicateurs
vieillissent. Elles restent versionnees dans Git et rejouables sur une
machine vierge.

## Les dix vues

| Vue | Grain | Role |
| --- | --- | --- |
| `v_kpi_mensuel` | 1 ligne / mois | la tendance : volume, montants, prevalence, delai |
| `v_kpi_global` | 1 ligne | le bandeau : les memes indicateurs, sur toute la periode |
| `v_factures_detail` | 1 ligne / facture | socle d'exploration, dimensions denormalisees |
| `v_fraude_par_type` | type x mois | les mecanismes de fraude et leur montant expose |
| `v_prestataires_risque` | 1 ligne / prestataire | classe par montant expose |
| `v_controle_points` | motif x mois | motifs de non-paiement |
| `v_detection_mensuel` | 1 ligne / mois | volume de predictions du modele |
| `v_delai_decision` | 1 ligne / mois | alerte -> decision gestionnaire |
| `v_montants_economises` | 1 ligne / mois | fraude confirmee par un gestionnaire |
| `v_faux_positifs` | prediction x decision | matrice de confusion metier |
| `v_cdc_global` | 1 ligne | la boucle de decision : rappel, faux positifs, economises, delai |

## Les cinq indicateurs du CDC

La Phase 7 exige volumes, montants economises, taux de detection, delai de
traitement et taux de faux positifs. Deux d'entre eux n'existent pas encore
dans les donnees : `ml.prediction` et `audit.decision_gestionnaire` sont
vides.

Les vues correspondantes sont **livrees quand meme, et vides**. Une brique
absente est invisible ; une brique vide avec son etat affiche est un
indicateur de donnees manquant, que le jury peut constater et discusser. Le
tableau se remplira seul a la premiere execution du modele.

| Indicateur CDC | Vue | Etat | Source |
| --- | --- | --- | --- |
| Volumes | `v_kpi_mensuel` | **peuple** | `core.facture` |
| Delai de traitement | `v_kpi_mensuel` | **peuple** — 8,5 jours reels | `core.facture.date_reception` -> `date_traitement` |
| Montants economises | `v_kpi_mensuel.montant_fraude_mga` | **peuple** — fraude identifiee sur le jeu | `core.facture` x `ml.label_fraude` |
| Taux de detection | `v_detection_mensuel` | vide | `ml.prediction` |
| Taux de faux positifs | `v_faux_positifs` | vide | `ml.prediction` + `audit.decision_gestionnaire` |

## Unite : ariary, jamais euros

Le jeu de l'encadrement est en **MGA**. Une colonne nommee `montant_eur`
serait fausse d'un facteur d'environ 57 000. Toutes les colonnes portent
`mga` dans leur nom, et les titres de graphiques le rappelent.

## Quatre pieges que les tests ne voient pas

Ils ont chacun a fait afficher « there was an issue » sur des graphiques dont la
requete etait pourtant correcte. Les deux meritaient d'etre ecrits.

### 1. Une colonne existe dans la vue, pas dans Superset

`information_schema` dit que `nb_factures` existe. Le graphique echoue
malgre tout, avec « Columns missing in dataset ».

Les datasets sont ecrits en SQL direct par `register_datasets.py`, ce qui cree
la ligne sans jamais appeler `fetch_metadata()`. La ligne existe, l'interface
l'affiche, et ses colonnes sont vides. **Verifier la colonne dans la base ne
prouve rien : il faut verifier ce que Superset a dans `table_columns`.** Le
script appelle donc `fetch_metadata()` a chaque execution, et `make bi`
compte les colonnes.

### 2. Un taux ne se somme pas, une moyenne de moyennes n'est pas une moyenne

Le bandeau voulait la valeur sur les 24 mois. Sommer `v_kpi_mensuel` :

```
SOMME des taux mensuels        219,29 %   <- absurde
taux GLOBAL recalcule             8,69 %   <- juste
MOYENNE des delais mensuels        8,50 j
delai GLOBAL pondere                8,49 j
```

`v_kpi_global` recalcule donc chaque indicateur depuis son numerateur et son
denominateur. Les tuiles y agrègent une vue qui ne contient qu'**une ligne**.

### 3. `groupby` porte des NOMS DE COLONNES, pas des objets

La forme enrichie est tentante, parce qu'elle decrit mieux :

```json
"groupby": [{"column_name": "prestataire_nom", "label": "Prestataire", "type": "STRING"}]
```

Elle est fausse. Le champ attendu est une liste de chaines :

```json
"groupby": ["prestataire_nom", "prestataire_ville"]
```

Et elle casse **trois choses a la fois**, sans qu'aucune ne parle de
`groupby` -- c'est ce qui rend le diagnostic long :

| Ce qu'on voit | Pourquoi |
| --- | --- |
| `GET /dashboard/<slug>/datasets` -> **422** `unhashable type: 'dict'` | `data_for_slices` range la valeur dans un `set` : un dictionnaire n'est pas hachable |
| `POST /chart/data` -> **400** `Columns missing in dataset: [{...}]` | `get_column_names_from_columns` recopie le dictionnaire tel quel, et compare un objet a des noms |
| `POST /chart/data` -> **400** `Empty query?` | la fabrique de requetes ne trouve plus rien a grouper |

Les metriques, elles, SONT des objets : `is_adhoc_metric` les reconnait et en
extrait `column_name`. C'est la difference entre les deux champs, et elle
n'est ecrite nulle part.

Effet collateral : `PUT /api/v1/dashboard/<id>` echouait aussi en
`unhashable type: 'dict'`, **sans jamais nommer le coupable**. La cause etait
ici, pas dans la mise en page.

### 4. La mise en page v2 est une CARTE PLATE

Un arbre imbrique parait naturel :

```json
{"ROOT_ID": {"children": [{"type": "CHART", "id": "1"}]}}
```

Superset attend une carte indexee par identifiant, ou `children` est une
liste de **chaines** :

```json
{"ROOT_ID": {"children": ["GRID_ID"]},
 "GRID_ID": {"children": ["ROW-0"], "parents": ["ROOT_ID"]},
 "ROW-0":   {"children": ["COLUMN-0-7"], "parents": ["ROOT_ID", "GRID_ID"]},
 "COLUMN-0-7": {"children": ["CHART-7"], "parents": [...]},
 "CHART-7": {"children": [], "meta": {"chartId": 7, ...}}}
```

Le frontal fait `position[enfant]` : un enfant qui est un objet n'est ni un
identifiant ni indexable, et **le tableau s'ouvre vide sans lever d'erreur**.

Les positions `x`/`y` ne sont pas ecrites : c'est la structure
ROOT > GRID > ROW > COLUMN qui definit la mise en page. References dans la
version installee : `superset/examples/world_bank.py` et
`superset/mcp_service/dashboard/tool/generate_dashboard.py`.

Corollaire : une mise a jour du tableau commence par relire la position
DEJA stockee pour construire l'arbre des onglets. Un document invalide
empoisonne donc sa propre correction -- il faut l'ecraser une fois en direct
avant que l'API reaccepte quoi que ce soit.

### Les cinq indicateurs du CDC, tous affiches

Les trois derniers sont des tuiles sur `v_cdc_global`, qui renvoie toujours
une ligne. Tant que le modele n'a pas tourne, elles affichent « en attente »
avec le sous-titre qui dit pourquoi -- plutot que d'etre absentes du tableau.
Une brique vide se constate ; une brique manquante passe pour un oubli.

## Securite : la frontiere `audit`

La migration 0002 retire a `superset_ro` tout acces au schema `audit` :
« le tableau de bord doit pouvoir mesurer la performance, pas consulter qui a
fait quoi ».

Deux anciens datasets violaient cette regle et echouaient en production avec
« permission denied for schema audit ». Les vues `v_montants_economises` et
`v_faux_positifs` sont creees `security_invoker = false`, c'est-a-dire avec
les privileges du proprietaire : `superset_ro` lit l'**agregat** sans
jamais pouvoir lire `audit`.

Ce que cela expose : un nombre de dossiers et un montant, par mois.
Ce que cela n'expose pas : `decided_by`, aucun nominatif. La colonne
`decided_by` n'apparait dans aucune vue.

Verifier que la frontiere tient :

```bash
make db-sql Q="SELECT count(*) FROM audit.decision_gestionnaire"        # doit echouer
make db-sql Q="SELECT count(*) FROM bi.v_montants_economises"          # doit repondre
make db-sql Q="SELECT * FROM bi.v_cdc_global"                           # doit repondre
```

`v_cdc_global` est `security_invoker = false` comme ses soeurs, et pour la
meme raison : elle agrege `audit` sans jamais en exposer le detail.

## Regles de conception appliquees

1. **Une graine par vue.** Une vue au grain facture ne doit pas recalculer
   une moyenne deja calculee ailleurs.
2. **Un indicateur par graphique.** Un graphique qui melange volume et taux
   impose deux axes, et le lecteur doit en choisir un.
3. **Unite dans le titre**, pas seulement dans l'axe.
4. **Pas de camembert au-dela de sept parts.** La comparaison angulaire
   devient illisible ; les barres horizontales se comparent par la longueur.
5. **Lecture verticale** : indicateurs, puis tendance, puis decomposition,
   puis controle.
6. **Les NULL ne sont pas des defauts.** 44 % des factures n'ont pas
   d'ordonnance parce que beaucoup d'actes n'en exigent pas : les vider
   detruirait le signal.
7. **Fuite de donnees.** `statut` et `motif_rejet` sont correles a la fraude
   — 70 % des factures rejetees sont frauduleuses contre 7 % des payees.
   Ils restent dans `core`, la validite derivee est dans `ml`.

## Recharger

```bash
bash db/bi/load.sh      # ou make reload-data, qui l'enchaîne
```

`CREATE OR REPLACE VIEW` rend l'operation idempotente. Les droits sont
rejoues apres chaque creation : une vue remplacee est recreee avec les
privileges de son createur, pas avec ceux de l'ancienne.

## Brouillon / TODO

- [ ] Ingerer le `rag_corpus/` dans `core.document_vectorise`
- [ ] Remplir `ml.prediction` a la premiere execution du modele
- [ ] Enregistrer des decisions gestionnaire d'interface pour la boucle
- [ ] Vue de tendance sur douze mois glissants, pour l'usage en reunion

Proprietaire : Jerry
