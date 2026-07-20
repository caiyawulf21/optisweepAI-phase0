# Corpus Module

Sole runtime data access layer for playbook orchestration. Cosmos is the only runtime corpus source.

## Files

| File | Role |
|------|------|
| `settings.py` | Env: Cosmos containers, `PUBLISH_VERSION_ID`, thresholds |
| `models.py` | `EmbeddingRecord`, `RelationshipLink`, `CorpusIndex` |
| `cosmos_client.py` | Query/load playbooks, runbooks, embeddings, links |
| `bootstrap.py` | Process singleton cache |

## Env Vars

```env
COSMOS_ENDPOINT=
COSMOS_KEY=
COSMOS_DATABASE=
COSMOS_CONTAINER_RUNBOOKS=
COSMOS_CONTAINER_PLAYBOOKS_A=
COSMOS_CONTAINER_PLAYBOOKS_B=
COSMOS_CONTAINER_RELATIONSHIP_LINKS=
PUBLISH_VERSION_ID=
AUTO_PUBLISH_VERSION=true
```

`AUTO_PUBLISH_VERSION=true` resolves the newest Cosmos publish with embeddings at startup / corpus reload. `PUBLISH_VERSION_ID` is the fallback (and the pin when auto is false).

## API Surface

Used by agents and `GET /corpus/*` routes; not called from UI directly.
