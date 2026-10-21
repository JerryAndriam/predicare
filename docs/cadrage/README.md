# Dossier de cadrage stratégique

Phase 10.3 du plan d'action. Le dossier PDF remis au jury, qui pèse 20 % sur
la partie business et 15 % sur la conformité. Les livrables détaillés et à jour
sont dans [`docs/livrables/`](../livrables/README.md) ; le PDF versionné reste
daté du 20/10/2026 tant qu'il n'est pas régénéré.

## Livrable

| Fichier | Rôle |
| --- | --- |
| `dossier_cadrage.md` | Source rédigée, versionnée |
| `dossier_cadrage.pdf` | PDF remis au jury, 26 pages |
| `dossier.css` | Mise en page A4 (couverture, tableaux, sauts de page) |
| `export_pdf.js` | Régénération locale du PDF via Playwright |

Le dossier couvre les six parties exigées, plus une synthèse et quatre annexes
(index des preuves, hypothèses, glossaire, checklist jury).

## Contenu exigé par le CDC

| Partie | Ce qu'il faut démontrer | Où le dossier le traite |
| --- | --- | --- |
| **TCO et ROI** | Coût total d'infrastructure et de tokens, face aux coûts de contrôle évités | Partie 1 : TCO à 109 €/an en base, ratio économie/TCO de 41,6× à 348,8× |
| **RGPD** | Cartographie, bases légales, pseudonymisation, chiffrement, droits | Partie 2 : cartographie, AIPD, écarts de conservation |
| **EU AI Act** | Classement, obligations haut risque, mesures de maîtrise | Partie 3 : grille articles 9 à 15, 17, 43, 48, 49, 72, 73 |
| **Audit d'équité** | Performance par segment : âge, tarif, prestataire, formule, type de fraude | Partie 4 : rappels et précisions par segment |
| **Sécurité** | Authentification, chiffrement, contrôle d'accès, protection du RAG | Partie 5 : STRIDE, RBAC, SQL lecture seule, réseau, supply chain |
| **Semantic caching** | Gain mesuré, pas annoncé | Partie 6 : 2 hits, 10,48 s et 0,00064 € évités |

## Chiffres clés

| Indicateur | Valeur | Source |
| --- | ---: | --- |
| ROC-AUC du modèle v2 | 0,9500 | `reports/modele_v2.md` |
| Rappel au seuil 0,2876 | 87,0 % | `reports/modele_v2.md` |
| Économie sur le jeu de test | 22 656 000 MGA | `reports/modele_v2.md` |
| Fidélité / citation / exactitude RAG | 30/30, 20/20, 26/26 | `reports/eval_rag_2026-10-19_5.json` |
| Coût LLM par requête | 0,00064 USD | `apps/api-rag/README.md` |
| Tests | 696 passés, 18 ignorés | `make check`, 21/10/2026 |

## Note sur le FinOps

20 % de la note, et le plan d'action le dit : « il ne peut pas être traité en
fin de projet ». Les métriques nécessaires existent déjà
(`predicare_llm_tokens_total`, `predicare_semantic_cache_total`,
`predicare_llm_call_duration_seconds`) : le dossier les exploite, et la partie
6 mesure le cache au lieu de l'annoncer.

## Régénérer le PDF

Le PDF versionné est le livrable. Pour le régénérer après une modification du
Markdown :

```bash
cd docs/cadrage

# 1. Markdown -> HTML
pandoc dossier_cadrage.md -f markdown+pipe_tables+raw_html -t html5 -s \
  --toc --toc-depth=2 --css dossier.css --metadata lang=fr \
  -o dossier_cadrage.html

# 2. HTML -> PDF (outil local, non versionné)
npm install --no-save --no-package-lock playwright
npx playwright install chromium
node export_pdf.js
```

Vérification rapide : `pdfinfo dossier_cadrage.pdf` doit annoncer 26 pages, et
`pdftotext dossier_cadrage.pdf -` doit contenir « Synthèse pour le jury » et
« Checklist pour le jury ».

## Points de vigilance

- Les prix d'hébergement sont des hypothèses datées, pas des devis.
- Le taux de conversion 1 EUR = 5 000 MGA doit être actualisé le jour J.
- Le classement AI Act « haut risque » est une lecture prudente, à confirmer
  par un avis juridique.
- Le dossier nomme les écarts (purge non planifiée, TLS non actif par défaut,
  MFA absent, dashboards Grafana absents) au lieu de les masquer.
- Les chiffres ont été actualisés au 21/10/2026 ; le PDF, lui, date du 20/10.

Propriétaire : Mirado et Jerry
