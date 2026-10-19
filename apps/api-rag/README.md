# Flux 2 - assistant conversationnel agentique

Service FastAPI qui repond aux questions des assures a partir des contrats
PDF (pgvector) et de leur historique de remboursement. La note de securite
porte sur ce service : 15 % du bareme.

## Modules

| Module | Contenu |
| --- | --- |
| `guardrails.py` | Detection d'injection de prompt, prompt systeme, separation instruction/donnee |
| `sql_tool.py` | Outil SQL du compte en lecture seule, filtre sur l'assure connecte |
| `retriever.py` | Recherche pgvector, sources citees obligatoire |
| `agent.py` | Agent ReAct LangChain, assemblage et tracabilite des etapes |
| `semantic_cache.py` | Cache semantique et mesure du gain FinOps |

## Les trois barrieres de securite

1. Le compte SQL est en lecture seule **declare dans PostgreSQL**. Un bug
   applicatif ne peut pas le transformer en compte d'ecriture.
2. Les requetes passent par une liste blanche de formes SQL.
3. Le filtre sur l'assure connecte est injecte par le code, jamais demande au
   LLM : l'identifiant n'existe pas dans le schema de l'outil.

## Brouillon / TODO

- [x] Decoupage des contrats PDF en segments avec metadonnees (Phase 5.1)
- [x] Indexation pgvector et generation des embeddings (script `ingest_rag`)
- [x] Boucle ReAct complete : outils et trace (Phase 5.4)
- [ ] Injection du contexte de dialogue court (memoire de session)
- [ ] Jeu de questions de reference pour mesurer la fidelite (Phase 5.8)
- [x] Tests d'attaque : lot de prompts d'injection (Phase 5.6 - a completer)

Proprietaire : Mirado
