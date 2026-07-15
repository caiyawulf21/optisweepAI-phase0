# Cosmos query cheat sheet

All queries use partition key / filter: `c.publish_version_id = @PUBLISH_VERSION_ID`

---

## Bootstrap at startup

### Playbook embeddings (Prompt A)

```sql
SELECT c.id, c.source_record_id, c.embedded_text, c.vector,
       c.embedding_model, c.filter_metadata
FROM c
WHERE c.publish_version_id = @version
  AND c.doc_type = 'embedding'
  AND c.record_type = 'playbook_prompt_a'
```

Container: `COSMOS_CONTAINER_PLAYBOOKS_A`

### Playbook embeddings (Prompt B)

Same query with `record_type = 'playbook_prompt_b'`  
Container: `COSMOS_CONTAINER_PLAYBOOKS_B`

### Runbook embeddings (fallback retrieval)

```sql
SELECT c.id, c.source_record_id, c.embedded_text, c.vector,
       c.filter_metadata
FROM c
WHERE c.publish_version_id = @version
  AND c.doc_type = 'embedding'
  AND c.record_type = 'canonical_runbook'
```

Container: `COSMOS_CONTAINER_RUNBOOKS`

### Relationship graph (all shards)

```sql
SELECT c.id, c.shard_index, c.shard_count, c.links
FROM c
WHERE c.publish_version_id = @version
  AND c.doc_type = 'relationship_graph'
```

Container: `COSMOS_CONTAINER_RELATIONSHIP_LINKS`

Merge: `all_links = [link for shard in shards for link in shard.links]`

---

## Per-request lookups (turn 2+)

### Playbook document

```sql
SELECT c.payload
FROM c
WHERE c.publish_version_id = @version
  AND c.doc_type = 'playbook'
  AND c.record_id = @playbook_id
```

### Runbook document

```sql
SELECT c.payload
FROM c
WHERE c.publish_version_id = @version
  AND c.doc_type = 'runbook'
  AND c.record_id = @procedure_id
```

### Source artifact (screenshot metadata)

```sql
SELECT c.retrieval_text, c.filter_metadata, c.source_refs
FROM c
WHERE c.publish_version_id = @version
  AND c.doc_type = 'rag_record'
  AND c.record_type = 'source_artifact'
  AND c.source_record_id = @artifact_id
```

Container: `COSMOS_CONTAINER_SOURCE_ARTIFACTS`

---

## In-memory indexes to build at startup

```python
# embeddings_by_type: record_type -> list[EmbeddingDoc]
# playbooks_by_id: playbook_id -> payload (lazy load OK)
# runbooks_by_id: procedure_id -> payload (lazy load OK)
# links_by_source: (link_type, source_record_id) -> list[target_record_id]
```

### Link index example

```python
for link in all_links:
    key = (link["link_type"], link["source_record_id"])
    links_by_source.setdefault(key, []).append(link["target_record_id"])

# Resolve node runbook:
procedure_id = links_by_source.get(
    ("playbook_runbook", f"{playbook_id}:{node_id}"), []
)[0]
```

---

## Document ID patterns

| doc_type | id format |
|----------|-----------|
| runbook | `runbook_{procedure_id}` |
| playbook | `playbook_{playbook_id}` |
| embedding | `{record_type}:{source_record_id}` or Stage 10 `record_id` |
| relationship_graph | `relationship_graph_{version}_{shard:03d}` |

---

## Python SDK sketch

```python
from azure.cosmos import CosmosClient

client = CosmosClient(endpoint, credential=key)
db = client.get_database_client(database)

def query_container(container_name: str, sql: str, params: list[dict]):
    container = db.get_container_client(container_name)
    return list(container.query_items(
        query=sql,
        parameters=params,
        partition_key=publish_version_id,  # when using partition key
    ))
```

Use partition key `publish_version_id` on point reads when document id is known.

---

## Version refresh

When ingestion publishes a new corpus:

1. Update `PUBLISH_VERSION_ID` in app config.
2. Reload embedding index + relationship shards.
3. Invalidate sessions pinned to old version.

Compare `session.publish_version_id` vs env on each request; reset session if mismatch.
