# Dependencies on the ingestion codebase

This app (**optisweepAI-phase0** / appcode) does **not** ingest incidents,
build playbooks, embed the corpus, or host Brain. Those capabilities live in
the separate **ingestion** repository (often referred to as
`optisweepAI-ingestion` / incidence + operational pipelines + Brain).

If ingestion is missing, misconfigured, or pointed at a different Azure
account, this app cannot deliver a useful demo — even when the Container App
and Streamlit UI are healthy.

```text
┌─────────────────────────────┐         ┌──────────────────────────────┐
│  Ingestion repo             │         │  This app (appcode)          │
│                             │         │                              │
│  Pipelines (incidence +     │         │  FastAPI + LangGraph         │
│  operational)               │         │  Streamlit UI                │
│       │                     │         │       │                      │
│  Stages 4–8 draft           │         │  POST /troubleshoot          │
│  Stage 10 embed             │────────▶│  POST /retrieve              │
│  Stage 11 Cosmos publish    │  Cosmos │  sessions / logs / feedback  │
│                             │  publish│                              │
│  Brain service + HTTP API   │────────▶│  BrainHttpClient (optional)  │
│  (brain_* containers)       │  HTTP   │  SME Review UI               │
└─────────────────────────────┘         └──────────────────────────────┘
```

**Boundary rule:** this app **reads** the Stage 11 publish corpus and may call
Brain HTTP as a **client**. It never runs pipeline stages and never upserts
`brain_*` containers.

---

## What we depend on (checklist)

| Dependency | Produced by ingestion | Consumed by this app | Without it |
|------------|----------------------|----------------------|------------|
| Published playbooks / runbooks / embeddings / links / gate phrases / operational context | Stage 11 Cosmos publish | `corpus/` load + hybrid retrieval + playbook execute | Empty Search; no pin/candidates; `embedding_total=0` |
| `publish_version_id` + container names | `publish_manifest.json` | `.env` / Container App env / `AUTO_PUBLISH_VERSION` | Wrong or empty corpus version |
| Embedding model identity | Stage 10 (`text-embedding-3-small`, 1536-d typical) | Query embeddings at retrieve/troubleshoot time | Nonsense ranks / dim mismatch errors |
| Playbook entry `embedded_text` shape | Stage 8 → 10 card text | Hybrid + symptom scoring | Sparse queries like “AGVs stopped” miss playbooks |
| Gate phrase table | Stage 11 `gate_phrase_tables` (`id=gate_phrases`) | First-turn keyword symptom extraction | Weak/empty symptom gate (YAML fallback only in tests) |
| Canonical image blobs + `publish_canonical_images` | Stage 11 + Blob | `/images`, runbook step screens | Broken or missing screenshots |
| Brain HTTP service | Ingestion-hosted Container App | Optional retrieve/troubleshoot excerpt overlay, feedback forward, SME reviews | SME Review disabled; no continuous-learning loop |
| Brain OpenAPI shapes | Live `/openapi.json` on Brain host | `brain_http_client.py` adapters (`query_text`, optional `entity_ids`) | Client parse / 4xx failures |

Contracts for the Brain side:
[`brain/HTTP_BOUNDARY.md`](brain/HTTP_BOUNDARY.md) ·
[`brain/FEEDBACK_CAPTURE.md`](brain/FEEDBACK_CAPTURE.md).

Corpus shapes:
[`cosmos_data_map.md`](cosmos_data_map.md) ·
[`retrieval_algorithms.md`](retrieval_algorithms.md).

---

## 1. Publish corpus (required for core product)

### Pipeline stages that matter to this app

| Stage (ingestion) | Output this app cares about |
|-------------------|-----------------------------|
| ~5–8 | Playbook/runbook JSON quality: entry symptoms, `support_user_language_examples`, node branches, runbook links |
| 10 | Vectors written with a known `embedding_model` + dimensions |
| 11 | Cosmos upsert into the **publish** containers + Blob image upload + `publish_manifest.json` |

Typical Stage 11 containers (names configurable via env; defaults in
`.env.example`):

| Cosmos container | App env |
|------------------|---------|
| `runbooks` | `COSMOS_CONTAINER_RUNBOOKS` |
| `playbooks_prompt_a` / `playbooks_prompt_b` | `COSMOS_CONTAINER_PLAYBOOKS_A` / `_B` |
| `operational_context` | `COSMOS_CONTAINER_OPERATIONAL_CONTEXT` |
| `relationship_links` | `COSMOS_CONTAINER_RELATIONSHIP_LINKS` |
| `source_artifacts` | `COSMOS_CONTAINER_SOURCE_ARTIFACTS` |
| `publish_canonical_images` | `COSMOS_CONTAINER_CANONICAL_IMAGES` |
| `gate_phrase_tables` | `COSMOS_CONTAINER_GATE_PHRASE_TABLES` |

Partition key for publish docs: `/publish_version_id`.

### How this app loads it

1. Startup: `corpus/bootstrap.py` loads the index for one publish version
   (`AUTO_PUBLISH_VERSION=true` → newest with embeddings, else pin
   `PUBLISH_VERSION_ID`).
2. Turn 1 retrieve/pin: in-memory hybrid search over those embeddings
   (`retrieval/hybrid_retriever.py`) — **not** Azure AI Search.
3. Turn 2+: playbook/runbook **ID lookups** + relationship links — no vector
   search for node execution.

### Cutover / new Azure account

You cannot “finish” moving this app without either:

- Re-running ingestion Stage 11 into the new Cosmos account, **or**
- Copying the published containers + blobs from the old account

See [`../AZURE_ACCOUNT_HANDOFF.md`](../AZURE_ACCOUNT_HANDOFF.md) §5.

Verify:

```powershell
python -m backend.app.scripts.verify_cosmos_corpus
# Expect embeddings > 0 and a resolved publish_version_id
```

---

## 2. Embedding contract (Stage 10 ↔ query time)

| Rule | Detail |
|------|--------|
| Same model | App `AZURE_EMBEDDINGS_DEPLOYMENT` must match Stage 10 (usually `text-embedding-3-small`) |
| Same dims | `AZURE_EMBEDDING_DIMENSIONS=1536` (or whatever Stage 10 used) |
| Playbook card text | Entry-scoped: title + entry symptoms + support language examples — see [`retrieval_algorithms.md`](retrieval_algorithms.md) |

If ingestion re-embeds with a new model, **republish** and restart this app so
the in-memory index and query encoder stay aligned.

---

## 3. Brain HTTP (optional overlay + learning loop)

Hosted **only** by ingestion. This app enables it with `BRAIN_HTTP_*` flags
(defaults **off** in `.env.example`; live Container App YAML may turn them on).

| Brain route | App use |
|-------------|---------|
| `POST /brain/v1/context/retrieve` | Extra approved excerpts on Search (flag `BRAIN_HTTP_RETRIEVE`) |
| `POST /brain/v1/context/troubleshoot` | Supplemental context / routing-learning signals (flag `BRAIN_HTTP_TROUBLESHOOT`) |
| `POST /brain/v1/feedback` | Forward operator feedback after local `feedback_events` write |
| `GET/POST /brain/v1/reviews...` | SME Review page |

### Continuous learning (who does what)

```text
Operator (UI)
  → POST /feedback or attachments  (this app)
  → feedback_events + interaction_logs in app Cosmos
  → optional POST /brain/v1/feedback  (ingestion Brain)
       → may write operational_unreviewed / conflicting
       → may open BrainReview
SME (UI SME Review)
  → GET/POST /reviews* via this app proxy
  → Brain resolve (MERGE applies; RETYPE may apply on v4; RECLASSIFY may not)
  → approved knowledge only then becomes citable guidance
```

**Playbook step machine stays in this app.** Brain does not replace Guided
Troubleshoot orchestration.

UI-oriented explanation: [`../ui/README.md`](../ui/README.md) (Brain & continuous learning).
API contract: [`brain/HTTP_BOUNDARY.md`](brain/HTTP_BOUNDARY.md).

Against Brain HTTP **v4**, prefer `BRAIN_HTTP_TIMEOUT_SECONDS=90` (cold ~40–50s,
warm ~2s). Update `BRAIN_HTTP_BASE_URL` when Brain moves to a new Azure account.

---

## 4. What lives only in this app (not ingestion)

| Concern | Where |
|---------|--------|
| LangGraph playbook / retrieve graphs | `backend/app/graph`, `agents` |
| Hybrid scorer implementation | `backend/app/retrieval` |
| `workflow_sessions`, `interaction_logs`, `feedback_events` | App Cosmos containers |
| Streamlit UX | `ui/` |
| Container App for troubleshooting UI+API | `deploy/`, this repo’s Dockerfile |

Ingestion should not be expected to ship these.

---

## 5. Coordination checklist (handoff)

Give the next owner **both** repos (or clear access) and named contacts.

- [ ] Ingestion repo URL + default branch documented
- [ ] Who runs Stage 11 publish after corpus/content changes
- [ ] Shared Cosmos DB name + which subscription owns it
- [ ] Current `publish_version_id` (or `AUTO_PUBLISH_VERSION=true`)
- [ ] Embedding deployment name + dims confirmed identical app ↔ Stage 10
- [ ] Brain HTTP base URL + whether flags are on in demo
- [ ] Agreement: app never gets Brain Cosmos write keys
- [ ] Azure move: ingest publish **before** deleting old Cosmos (see Azure handoff)

---

## 6. Failure modes that are usually “ingestion-side”

| Symptom in this app | Likely ingestion / publish issue |
|---------------------|----------------------------------|
| `embedding_total = 0` | No Stage 11 publish, wrong DB, or empty version |
| Gate never fires | Missing `gate_phrases` doc for that publish version |
| “AGVs stopped” misses stoppage playbook | Stage 8 card text / examples not in embed; need republish |
| Images 404 | Blob not uploaded or `storage_uri` still on old account |
| SME Review warning / empty | Brain down, wrong `BRAIN_HTTP_BASE_URL`, or review flags off |
| Feedback saved but “not in Brain” | `BRAIN_HTTP_FEEDBACK=false` or Brain reject/timeout |

Do not debug these only inside Streamlit — check ingestion publish + Brain
`/health` or `/docs` first.
