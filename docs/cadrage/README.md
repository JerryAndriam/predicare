# Dossier de cadrage stratégique

Phase 10.3 du plan d'action. Le dossier PDF remis au jury, qui pèse 20 % sur
la partie business et 15 % sur la conformité.

## Contenu exigé par le CDC

| Partie | Ce qu'il faut démontrer | Où trouver les éléments |
| --- | --- | --- |
| **TCO et ROI** | Coût total d'infrastructure et de tokens, face aux fraudes évitées | métriques `predicare_llm_tokens_total`, taux de détection |
| **RGPD** | Cartographie des données, traitement, pseudonymisation, chiffrement | `packages/predicare-core/crypto.py`, `db/migrations/versions/0001` |
| **EU AI Act** | Classement du système, obligations haut risque, mesures de maîtrise | `apps/api-rag/guardrails.py`, registre de modèles |
| **Audit d'équité** | Performance par segment : âge, acte, prestataire | à produire dans `apps/ml-training/` |
| **Sécurité** | Authentification, chiffrement, contrôle d'accès, protection du RAG | `packages/predicare-core/rbac.py`, `apps/api-rag/sql_tool.py` |
| **Semantic caching** | Gain mesuré, pas annoncé | `apps/api-rag/semantic_cache.py`, `/api/rag/cache/stats` |

## Note sur le FinOps

20 % de la note, et le plan d'action le dit : « il ne peut pas être traité en
fin de projet ». Les métriques nécessaires existent déjà
(`predicare_llm_tokens_total`, `predicare_semantic_cache_total`,
`predicare_llm_call_duration_seconds`) : elles se collectent en continu, il
n'y a plus qu'à les exploiter.

## Brouillon / TODO

- [ ] Trame du dossier PDF
- [ ] Tableau TCO : infrastructure, tokens, restauration
- [ ] Calcul du ROI à partir du taux de détection et du montant frauduleux évité
- [ ] Grille d'évaluation EU AI Act
- [ ] Rapport d'audit d'équité par segment
- [ ] Export PDF final

Propriétaire : Mirado et Jerry