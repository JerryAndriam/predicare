# Phase 0.4 - Reconnaissance des donnees (proprietaire : Cherica)

- Tables analysees : 14
- Lignes totales : 436,710
- Periode couverte : 2024-10-01 -> 2026-10-01 (24 mois pleins + 1 mois entame)
- Factures : 84,593 | Fraudes : 7,347 (8.69%)
- Types de fraude : 14
- Desequilibre : ~1 fraude pour 10.5 factures saines -> metriques rappel/precision, SMOTE sur train seulement
- Colonnes de fuite a exclure : statut, motif_rejet, montant_pris_en_charge, date_traitement
- Factures invalides etiquetees : 0 -> rejet par regles deterministes (Phase 3)

## Prochaines etapes
- Phase 1.1 : migrations Alembic (schema cible)
- Phase 1.2 : script de chargement initial
- Phase 1.3 : pseudonymisation + table d'identites chiffree
- Phase 1.4 : nettoyage et validation (doublons, dates, conventions)
