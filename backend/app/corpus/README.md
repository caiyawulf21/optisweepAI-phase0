# Corpus Module

Primary runtime knowledge source for playbook orchestration and `/retrieve`.
Loads a Stage 11 Cosmos publish into an in-memory `CorpusIndex` at startup.
When Cosmos creds are missing, falls back to a tiny in-process `sample` corpus
(`corpus_source=sample`). Optional Brain HTTP excerpts may also feed `/retrieve`
synthesis when feature flags are on — they do not replace this index.

There is **no** local `data/` corpus and **no** Azure AI Search retrieval path.

## Files

| File | Role |
|------|------|
| `settings.py` | Container env vars, `PUBLISH_VERSION_ID`, thresholds |
| `models.py` | `EmbeddingRecord`, `RelationshipLink`, `CorpusIndex` |
| `cosmos_client.py` | Query/load playbooks, runbooks, embeddings, links |
| `bootstrap.py` | Process-wide index singleton + reload |

## Env

See repo `.env.example`. With `AUTO_PUBLISH_VERSION=true`, startup resolves the
newest publish that has embeddings; otherwise pin `PUBLISH_VERSION_ID`.

## Consumers

Agents (`backend/app/agents/runtime.py`), `GET /corpus/*`, and hybrid retrieval.
UI talks to corpus only via the FastAPI routes.
