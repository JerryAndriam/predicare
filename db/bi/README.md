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

## Les huit vues

| Vue | Grain | Role |
| --- | --- | --- |
| `v_kpi_mensuel` | 1 ligne / mois | le tableau de bord : volume, montants, prevalence, delai |
| `v_factures_detail` | 1 ligne / facture | socle d'exploration, dimensions denormalisees |
| `v_fraude_par_type` | type x mois | les mecanismes de fraude et leur montant expose |
| `v_prestataires_risque` | 1 ligne / prestataire | classe par montant expose |
| `v_controle_points` | motif x mois | motifs de non-paiement |
| `v_detection_mensuel` | 1 ligne / mois | volume de predictions du modele |
| `v_delai_decision` | 1 ligne / mois | alerte -> decision gestionnaire |
| `v_montants_economises` | 1 ligne / mois | fraude confirmee par un gestionnaire |
| `v_faux_positifs` | prediction x decision | matrice de confusion metier |

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
```

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
