# Dossier de cadrage stratégique

Phase 10.3 du plan d'action. Le dossier PDF remis au jury, qui pèse 20 % sur
la partie business et 15 % sur la conformité.

> **État au 21 octobre 2026.** Le PDF versionné (`dossier_cadrage.pdf`,
> 26 pages) date du 20 octobre 2026 et n'a pas été régénéré après les
> corrections du 21 octobre. La source Markdown, elle, est à jour : elle
> contient le poste GPU du TCO, la distinction des deux ROI, le filtre
> prestataire corrigé et les chiffres remis en cohérence.

## Livrable

| Fichier | Rôle |
| --- | --- |
| `dossier_cadrage.md` | Source rédigée, versionnée |
| `dossier_cadrage.pdf` | PDF remis au jury, 26 pages (version du 20/10/2026) |
| `dossier.css` | Mise en page A4 (couverture, tableaux, sauts de page) |
| `export_pdf.js` | Régénération locale du PDF via Playwright |

Le dossier couvre les six parties exigées, plus une synthèse et quatre annexes
(index des preuves, hypothèses, glossaire, checklist jury).

## Contenu exigé par le CDC

| Partie | Ce qu'il faut démontrer | Où le dossier le traite |
| --- | --- | --- |
| **TCO et ROI** | Coût total d'infrastructure et de tokens (Cloud/GPU), face aux coûts de contrôle évités et aux fraudes évitées | Partie 1 : TCO à 108,97 €/an en base (214,78 € en stress, 390,86 € en conservateur), scénario GPU à 256 €/an hors total, ROI coût de contrôle de 41,6× à 348,8× et ROI fraude évitée sous hypothèse (12,5×) |
| **RGPD** | Cartographie, bases légales, pseudonymisation, chiffrement, droits | Partie 2 : cartographie, AIPD, écarts de conservation |
| **EU AI Act** | Classement, obligations haut risque, mesures de maîtrise | Partie 3 : grille articles 9 à 15, 17, 43, 48, 49, 72, 73 |
| **Audit d'équité** | Performance par segment : âge, tarif, prestataire, formule, type de fraude | Partie 4 : rappels et précisions par segment |
| **Sécurité** | Authentification, chiffrement, contrôle d'accès, protection du RAG | Partie 5 : STRIDE, RBAC, SQL lecture seule, réseau, supply chain |
| **Semantic caching** | Gain mesuré, pas annoncé | Partie 6 : 2 hits, 10,48 s et 0,00064 € évités |

## Chiffres clés

| Indicateur | Valeur | Source |
| --- | ---: | --- |
| ROC-AUC du modèle v2 | 0,9500 | `reports/modele_v2.md` |
| Seuil appliqué | 0,2876 | `models/2/metadata.json` |
| Rappel au seuil 0,2876 | 87,02 % | `reports/modele_v2.md` |
| Économie sur le jeu de test | 22 656 000 MGA | `reports/modele_v2.md` |
| TCO base / stress / conservateur | 108,97 / 214,78 / 390,86 €/an | Partie 1, `dossier_cadrage.md` |
| ROI coût de contrôle / fraude évitée (hypothèse 30 %) | 41,6×–348,8× / 12,5× | Partie 1, `dossier_cadrage.md` |
| Fidélité / citation / exactitude RAG | 30/30, 20/20, 26/26 | `reports/eval_rag_2026-10-19_5.json` |
| Coût LLM par requête | 0,00064 USD | `apps/api-rag/README.md` |
| Datasets BI | 13 | `ops/superset/register_datasets.py` |
| Tests | 693 passés, 18 ignorés | `make test`, 21/10/2026 |

## Note sur le FinOps

20 % de la note, et le plan d'action le dit : « il ne peut pas être traité en
fin de projet ». Les métriques nécessaires existent déjà
(`predicare_llm_tokens_total`, `predicare_semantic_cache_total`,
`predicare_llm_call_duration_seconds`) : le dossier les exploite, et la partie
6 mesure le cache au lieu de l'annoncer.

La partie 1 chiffre aussi le poste GPU demandé par le CDC (hypothèse de
256 €/an, hors total, avec point d'équilibre face à l'API LLM) et justifie
l'instance PostgreSQL+pgvector unique plutôt qu'une base vectorielle dédiée.
La partie 1.6 sépare explicitement le **ROI coût de contrôle évité (mesuré)**
du **ROI fraude évitée (hypothèse de recouvrement)**.

## Régénérer le PDF

Le PDF versionné est le livrable. Il n'y a **pas de `package.json`** dans ce
dossier : `export_pdf.js` réutilise le Playwright déjà installé pour les tests
du front, dans `apps/web/node_modules`. La chaîne ci-dessous a été exécutée le
21 octobre 2026 avec pandoc 3.8 et Node 22 ; elle produit un PDF à partir de
la source courante.

```bash
# 1. Dépendances du front et navigateur de test
cd apps/web && npm ci && npx playwright install chromium && cd ../..

# 2. Markdown -> HTML
cd docs/cadrage
pandoc dossier_cadrage.md -f markdown+pipe_tables+raw_html -t html5 -s \
  --toc --toc-depth=2 --css dossier.css --metadata lang=fr \
  -o dossier_cadrage.html

# 3. HTML -> PDF, avec le Playwright de apps/web
NODE_PATH=../../apps/web/node_modules node export_pdf.js
```

`dossier_cadrage.html` est un intermédiaire non versionné : il peut être
supprimé après l'export.

Vérification : `pdfinfo dossier_cadrage.pdf` donne le nombre de pages, et
`pdftotext dossier_cadrage.pdf -` doit contenir « Synthèse pour le jury » et
« Checklist pour le jury ». Le nombre de pages dépend du contenu et de la
version de pandoc : le PDF versionné du 20/10/2026 en compte 26, tandis que la
source actuelle, régénérée le 21/10/2026, en produit 22. Régénérer le PDF
avant remise et vérifier ce total.

## Points de vigilance

- Les prix d'hébergement sont des hypothèses datées, pas des devis.
- Le poste GPU (0,35 €/h, 256 €/an) est une hypothèse de tarif public, tenue
  hors des trois scénarios du TCO : il ne correspond à aucune dépense engagée.
- Le taux de conversion 1 EUR = 5 000 MGA doit être actualisé le jour J.
- Le classement AI Act « haut risque » est une lecture prudente, à confirmer
  par un avis juridique.
- Le dossier nomme les écarts (conservation, TLS, sauvegardes chiffrées) au
  lieu de les masquer.

Propriétaire : Mirado et Jerry
