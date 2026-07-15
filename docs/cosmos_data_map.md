# Cosmos corpus — sole source of truth

**The published ingestion corpus lives in Azure Cosmos DB.** The app must read exclusively from Cosmos. Do not read from `data/`, `sample_data/`, filesystem YAML workflows, CAT-1 JSON, or root-cause datasets.

---

## Connection (env vars)

Set these in the app repo `.env` (values come from your Azure / ingestion publish):

```env
COSMOS_ENDPOINT=https://<account>.documents.azure.com:443/
COSMOS_KEY=<primary-or-read-key>
COSMOS_DATABASE=<database-name>

COSMOS_CONTAINER_RUNBOOKS=<container-name>
COSMOS_CONTAINER_PLAYBOOKS_A=<container-name>
COSMOS_CONTAINER_PLAYBOOKS_B=<container-name>
COSMOS_CONTAINER_OPERATIONAL_CONTEXT=<container-name>
COSMOS_CONTAINER_SOURCE_ARTIFACTS=<container-name>
COSMOS_CONTAINER_RELATIONSHIP_LINKS=<container-name>
COSMOS_CONTAINER_CANONICAL_IMAGES=publish_canonical_images

# Screenshot binaries (Stage 11 uploads during publish)
AZURE_STORAGE_CONNECTION_STRING=<storage-connection-string>
AZURE_CANONICAL_IMAGES_CONTAINER=canonical-images
AZURE_STORAGE_ACCOUNT_URL=https://<account>.blob.core.windows.net

# Active publish version — copy from publish_manifest.json after Stage 11
PUBLISH_VERSION_ID=<e.g. publish_20260712_143022_a1b2c3d4>

# Must match Stage 10 embedding model
AZURE_OPENAI_ENDPOINT=...
AZURE_OPENAI_API_KEY=...
AZURE_EMBEDDINGS_DEPLOYMENT=<same model used in Stage 10>
```

**Authoritative manifest:** `shared_pipeline_stages/data/output/shared/stage_11_cosmos_publish/publish_manifest.json` in the ingestion repo (or SME review sheet). Use `publish_version_id`, `embedding_model`, `record_counts`, and `containers` from that file.

---

## Container map

| Env var | Logical dataset | What is stored |
|---------|-----------------|----------------|
| `COSMOS_CONTAINER_RUNBOOKS` | Canonical procedures | `doc_type=runbook` documents + `doc_type=embedding` where `record_type=canonical_runbook` |
| `COSMOS_CONTAINER_PLAYBOOKS_A` | Prompt A playbooks | `doc_type=playbook` + embeddings `record_type=playbook_prompt_a` |
| `COSMOS_CONTAINER_PLAYBOOKS_B` | Prompt B playbooks | `doc_type=playbook` + embeddings `record_type=playbook_prompt_b` |
| `COSMOS_CONTAINER_OPERATIONAL_CONTEXT` | Manual context RAG | `doc_type=rag_record`, `record_type=operational_context` |
| `COSMOS_CONTAINER_SOURCE_ARTIFACTS` | Screenshot/evidence RAG | `doc_type=rag_record`, `record_type=source_artifact` |
| `COSMOS_CONTAINER_RELATIONSHIP_LINKS` | Link graph shards | `doc_type=relationship_graph` (sharded, up to 2000 links/doc) |
| `COSMOS_CONTAINER_CANONICAL_IMAGES` | Image metadata + Blob URI | `doc_type=canonical_image` with `storage_uri` (SAS HTTPS URL); default container `publish_canonical_images` |

---

## Partition key

All published documents use:

```text
partition key = publish_version_id
```

Every query **must** filter on `c.publish_version_id = @PUBLISH_VERSION_ID` so the app reads one corpus version at a time.

---

## Document shapes (Stage 11 publisher)

### Runbook document (`doc_type: "runbook"`)

```json
{
  "id": "runbook_proc_<slug>_canonical_v1",
  "doc_type": "runbook",
  "publish_version_id": "publish_...",
  "record_id": "proc_<slug>_canonical_v1",
  "payload": { "...full canonical runbook JSON..." }
}
```

Runtime reads `payload` — same schema as Stage 7 `canonical_runbooks.json`.

### Playbook document (`doc_type: "playbook"`)

```json
{
  "id": "playbook_playbook_incident_228086_...",
  "doc_type": "playbook",
  "publish_version_id": "publish_...",
  "record_id": "playbook_incident_228086_...",
  "payload": { "...full canonical playbook JSON with nodes, branches, resolved_runbook_ids..." }
}
```

### Embedding document (`doc_type: "embedding"`)

```json
{
  "id": "playbook_prompt_a:playbook_incident_228086_...",
  "doc_type": "embedding",
  "publish_version_id": "publish_...",
  "record_type": "playbook_prompt_a | playbook_prompt_b | canonical_runbook",
  "source_record_id": "<playbook_id or procedure_id>",
  "embedded_text": "<retrieval text>",
  "vector": [0.01, -0.02, ...],
  "embedding_model": "<azure deployment name>",
  "embedding_dimensions": 1536,
  "filter_metadata": { "case_id", "extraction_mode", "title", ... }
}
```

### Relationship graph shard (`doc_type: "relationship_graph"`)

```json
{
  "id": "relationship_graph_publish_..._000",
  "doc_type": "relationship_graph",
  "publish_version_id": "publish_...",
  "shard_index": 0,
  "shard_count": 3,
  "link_count": 1842,
  "links": [
    {
      "link_type": "playbook_runbook",
      "source_record_id": "playbook_incident_228086_...:node_1",
      "target_record_id": "proc_..._canonical_v1",
      "link_confidence": "high",
      "link_rank": 1
    }
  ]
}
```

Link types used at runtime: `playbook_runbook`, `artifact_runbook`, `context_runbook`, `incident_runbook`.

### Canonical image (`doc_type: "canonical_image"`)

**Container:** `COSMOS_CONTAINER_CANONICAL_IMAGES` (default `publish_canonical_images`)  
**Blob container:** `AZURE_CANONICAL_IMAGES_CONTAINER` (default `canonical-images`)

```json
{
  "id": "image_artifact_fig_3_1_operator_station_panels_removed_for_clarity",
  "doc_type": "canonical_image",
  "publish_version_id": "publish_...",
  "image_id": "artifact_fig_3_1_operator_station_panels_removed_for_clarity",
  "title": "...",
  "description": "...",
  "category": "manual_figure",
  "storage_uri": "https://<account>.blob.core.windows.net/canonical-images/publish_.../artifact_....jpeg?<sas>",
  "content_type": "image/jpeg",
  "linked_procedure_ids": ["proc_..._canonical_v1"],
  "linked_incident_ids": [],
  "case_id": "",
  "source_artifact_ids": ["artifact_fig_3_1_operator_station_panels_removed_for_clarity"]
}
```

Prefer `storage_uri` for rendering. Resolve procedure screenshots via `artifact_runbook` links, then load the matching `image_id`.

---

## Required queries

### 1. Bootstrap — load embedding index (startup, once per version)

Load all embedding docs into memory for brute-force hybrid search (no Azure AI Search):

**Container:** `COSMOS_CONTAINER_PLAYBOOKS_A` (and B, RUNBOOKS)

```sql
SELECT c.id, c.record_type, c.source_record_id, c.embedded_text, c.vector,
       c.embedding_model, c.filter_metadata
FROM c
WHERE c.publish_version_id = @version
  AND c.doc_type = 'embedding'
```

Split by `record_type`:
- `playbook_prompt_a` → turn-1 retrieval when A/B toggle = A
- `playbook_prompt_b` → turn-1 retrieval when A/B toggle = B
- `canonical_runbook` → fallback runbook retrieval

### 2. Load playbook by ID (after pin)

**Container:** `COSMOS_CONTAINER_PLAYBOOKS_A` or `_B`

```sql
SELECT c.payload
FROM c
WHERE c.publish_version_id = @version
  AND c.doc_type = 'playbook'
  AND c.record_id = @playbook_id
```

### 3. Load runbook by procedure ID (node execution)

**Container:** `COSMOS_CONTAINER_RUNBOOKS`

```sql
SELECT c.payload
FROM c
WHERE c.publish_version_id = @version
  AND c.doc_type = 'runbook'
  AND c.record_id = @procedure_id
```

### 4. Load relationship graph (startup or lazy)

**Container:** `COSMOS_CONTAINER_RELATIONSHIP_LINKS`

```sql
SELECT c.links, c.shard_index, c.shard_count
FROM c
WHERE c.publish_version_id = @version
  AND c.doc_type = 'relationship_graph'
```

Merge all shards into an in-memory adjacency index keyed by `(link_type, source_record_id)` → `target_record_id[]`.

### 5. Resolve playbook node → runbook (O(1), no search)

Prefer `payload.nodes[].resolved_runbook_ids[0]`. Fallback:

```text
link_type = playbook_runbook
source_record_id = "{playbook_id}:{node_id}"
→ target_record_id = procedure_id (lowest link_rank)
```

### 6. Resolve screenshots

```text
link_type = artifact_runbook
target_record_id = procedure_id
→ source_record_id = artifact_id / image_id
```

Then load from `COSMOS_CONTAINER_CANONICAL_IMAGES`:

```sql
SELECT c.image_id, c.title, c.description, c.storage_uri, c.content_type,
       c.linked_procedure_ids, c.case_id
FROM c
WHERE c.publish_version_id = @version
  AND c.doc_type = 'canonical_image'
  AND c.image_id = @artifact_id
```

Render via `storage_uri` (HTTPS Blob SAS). Fallback: artifact RAG metadata in `COSMOS_CONTAINER_SOURCE_ARTIFACTS` (text only — no pixels).

---

## A/B playbook toggle

Filter at retrieval time:

```text
record_type = playbook_prompt_a   → extraction_mode one_playbook_candidate_per_incident
record_type = playbook_prompt_b   → extraction_mode multi_flow
```

Do not swap filesystem directories — filter Cosmos embedding `record_type` and load playbooks from the matching container.

---

## Publish version lifecycle

1. Ingestion runs Stage 11 with `--publish` → new `publish_version_id` in Cosmos.
2. App sets `PUBLISH_VERSION_ID` env (or reads latest from a small config doc).
3. On version change: reload embedding index + relationship shards; invalidate pinned sessions.

---

## What is NOT in Cosmos (do not build loaders for)

| Artifact | Status |
|----------|--------|
| `root_cause_dataset.json` | Not published — use playbook `case_id` + retrieval |
| `data/workflows/canonical/*.yaml` | Not published — use playbook `payload.nodes` |
| `cat1_records.json` | Not published — use runbook embeddings |
| `canonical_procedure_dictionary.json` | Not published — use runbook documents |
| Per-source `canonical_incident_record.json` | Not published — optional future container |
| Azure AI Search index | Not used in this project |

---

## Ingestion repo cross-reference

Publisher implementation: `shared_pipeline_stages/stage_11/cosmos_publisher.py`  
Container config: `shared_pipeline_stages/stage_11/container_config.py`  
Schema mapping: `docs/cosmos_record_types.md`  
Retrieval algorithm: `docs/retrieval_algorithms.md`
