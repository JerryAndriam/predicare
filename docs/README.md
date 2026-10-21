# Documentation

Structure previsionnelle pour les livrables documentaires du projet. Les
contenus seront rediges au fil des phases ; les repertoires existent des
maintenant pour que Git les suive.

| Dossier | Contenu | Phase |
| --- | --- | --- |
| `adr/` | Journaux de decision d'architecture | Phase 0 |
| `exploitation/` | Guide d'exploitation : installation, sauvegarde, incidents | Phase 10.2 |
| `utilisateur/` | [Guide utilisateur](utilisateur/guide-utilisateur.md), une section par rôle | Phase 10.1 |
| `cadrage/` | Dossier PDF : TCO, ROI, RGPD, AI Act, equite, securite | Phase 10.3 |
| `equipe.md` | Repartition du travail et rattachement aux phases | Evolue en continu |

## Decisions d'architecture deja figees

| Decision | Position |
| --- | --- |
| Base de donnees | PostgreSQL unique avec pgvector, pas de base vectorielle separee |
| API | Trois services FastAPI alignes sur les trois flux du CDC |
| RAG | LangChain, agent ReAct, LLM et embeddings par API |
| Interface | React + Vite + TypeScript, servie par nginx |
| Orchestration | n8n pilote depuis son interface, versionne par export |
| Dependances Python | uv, workspace, verrou commite |
| Modification du seuil | a chaud, sans redemarrage |

## Brouillon / TODO

- [ ] ADR-001 : une base unique plutot qu'une base vectorielle separee
- [ ] ADR-002 : trois services API plutot qu'un monolithe
- [ ] ADR-003 : MLflow hors du chemin d'inference
- [ ] Guide d'exploitation complet (procedure de reprise incluse)
- [x] [Dossier de cadrage](cadrage/README.md) : TCO et ROI chiffres, pas estimes (PDF 26 pages)

Proprietaire : Jerry
