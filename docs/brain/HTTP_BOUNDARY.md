# OptiSweep App — Brain HTTP Boundary (locked)

Contract between **appcode** (this repo) and **ingestion Brain HTTP**.  
MCP remains for Codex / internal agents only — not the Streamlit/runtime path.

Related (this repo): [`FEEDBACK_CAPTURE.md`](FEEDBACK_CAPTURE.md), [`.env.example`](../../.env.example).
Brain implementation lives in the **ingestion** repo; this app is HTTP client only.

---

## Locked decisions

1. **Brain hosts the HTTP API.** Appcode is an HTTP client. Appcode never holds Brain write credentials and never upserts `brain_*` containers.
2. **Dual retrieval during transition.** Keep publish-corpus `/retrieve` and playbook runtime. Feature-flag Brain HTTP in (`BRAIN_HTTP_ENABLED` or similar). Do not delete the publish path until Brain context is validated in UI.
3. **Hydrated runtime responses.** Brain HTTP returns `ContextPacket` **plus** hydrated approved excerpts (not ID lists alone). App must not N+1-read `brain_*` to render a turn.
4. **Auth later.** Same Entra story for app and Brain HTTP when needed. Do not special-case MCP for the UI.
5. **MCP ≠ product runtime.** MCP stays ingestion/Codex tooling. Product surfaces use HTTP only.
6. **Brain owns mutation.** Feedback interpretation, validation, `BrainReview` creation, and approved writes to `brain_*` happen only inside Brain. App may keep `interaction_logs` / `feedback_events` / attachments as **app audit**, then hand off via Brain feedback HTTP.
7. **SME notification = pull queue first.** Appcode hosts an SME Review page that lists open `BrainReview`s via Brain HTTP; nav badge when count > 0. Technicians are not approvers. Teams/email digest is Phase B only (see §5).

### Confirmed with ingestion (through 2026-09-10 / Brain HTTP **v4**)

| Item | Confirmation |
|---|---|
| Hosting | Brain builds real HTTP alongside MCP; both call same `brain_service/` — not an MCP proxy in appcode. |
| Feedback writes | **Sync** Create-path + `apply_reconciliation`; same as pipeline. Writes immediately as `operational_unreviewed` / `conflicting` (except GAP). `brain_review_id` is audit trail, not an approval gate. |
| Hydration | **Implemented:** truncated (~2000 chars), status-labeled excerpts (`approved` / `working` / `conflict`); approved prioritized under 10–15 cap. Never bare ids. |
| Resolve / MERGE | **Implemented:** MERGE applies for real (merge into winner, deprecate losers — no delete). |
| Resolve / RETYPE | **Implemented on v4:** SME approve renames entity, corpus-wide id cascade, validates before write, deprecates old id. Returns `applied: true` + `mutated_record_ids`. Refusal → HTTP 400 with specific reason (never silent success). Re-resolve of same id fails loudly (idempotency). |
| Resolve / RECLASSIFY | **Still `applied: false` on purpose** — different-kind-of-record problem, not type-correction; own explanation (not the old shared RETYPE message). |
| Cosmos / embeddings | **Closed:** 19,766 / 19,766 embeddings; live retrieve E2E verified. |
| Retrieve latency (v4) | **Not an ANN gap.** Root cause was per-request provider rebuild (killed cache), triple query re-embed, and uncached `load_brain_context` full Cosmos scan. Fixed on **optisweep-brain-http:v4**. Live measured: **cold ~40–50s**, **warm ~1.5–2s**; known AGV query still `excerpt_count: 15`. App default timeout **90s** (was 300s for the old 3–4 min bug). |
| Base URL / OpenAPI | **Live:** `https://optisweep-brain-http.nicetree-2326f6da.eastus.azurecontainerapps.io` — OpenAPI at `/docs` + `/openapi.json`. Auth: none for v1. App client adapts live schema. |
| Human review notify | Phase A pull queue in app SME Review UI; Phase B Teams/email digest still deferred. |

App UI copy must distinguish: feedback was **accepted and may already be in Brain as unreviewed** vs **approved guidance**. Do not tell users “saved as trusted OptiSweep knowledge” on feedback alone.

### Appcode ask vs what shipped (v4)

| Appcode asked | Ingestion delivered |
|---|---|
| ANN / low-latency retrieve | **Latency fixed without ANN** (cache + provider reuse + single embed). ANN not required at current corpus size. |
| RETYPE + RECLASSIFY apply | **RETYPE applies**; **RECLASSIFY** remains explicit non-apply with clearer reason. |

SME UI continues to treat **`applied`** as corpus-change source of truth.

---

## Surface split

| App surface | App route (today) | Brain HTTP (new) | Brain responsibility |
|---|---|---|---|
| Search / retrieve | `POST /retrieve` | `POST /brain/v1/context/retrieve` | Semantic + graph context for Q&A |
| Guided troubleshoot | `POST /troubleshoot` | `POST /brain/v1/context/troubleshoot` | Session-aware approved context |
| Feedback | `POST /feedback` (app Cosmos) | `POST /brain/v1/feedback` | Create-path → review / unreviewed writes |
| SME review | Streamlit **SME Review** (`ui/pages/3_SME_Review.py`) + `GET/POST /reviews*` | `GET/POST /brain/v1/reviews/...` | List / resolve `BrainReview`; mutate corpus |

App orchestration stays in appcode. Brain never runs the playbook step machine.

---

## Shared types

### ValidationStatus (runtime cite filter)

Only hydrate into `approved_excerpts` / cite as guidance when:

```text
catalog_authoritative | sme_approved
```

Other statuses may appear under `working_material` / `conflicts` for transparency — never as approved guidance.

### ContextPacket (IDs — unchanged contract)

```json
{
  "task": "string",
  "current_state": {},
  "entities": ["entity:..."],
  "approved_knowledge": ["claim:..."],
  "evidence_excerpts": ["evidence:..."],
  "relevant_incidents": ["..."],
  "policies": ["..."],
  "conflicts": ["claim:..."],
  "required_output_schema": null
}
```

### HydratedExcerpt (app-facing addition)

```json
{
  "record_id": "claim:...",
  "record_type": "claim|entity|evidence_unit|capability|procedure|playbook|relationship",
  "validation_status": "sme_approved",
  "title": "optional short label",
  "text": "short citeable text",
  "source_refs": ["evidence:..."]
}
```

### BrainContextResponse

```json
{
  "packet": { "...ContextPacket..." },
  "approved_excerpts": ["...HydratedExcerpt..."],
  "working_material": ["...HydratedExcerpt..."],
  "conflicts": ["...HydratedExcerpt..."],
  "query_echo": "string",
  "brain_backend": "azure|local",
  "trace": {}
}
```

---

## Route contracts

Base URL: Brain service (ingestion-hosted), e.g. `BRAIN_HTTP_BASE_URL`.

### 1. `POST /brain/v1/context/retrieve`

**Purpose:** Search/Chat and any free-text Q&A grounding.

**Request**

```json
{
  "query": "string (required)",
  "session_id": "string|null",
  "limit": 12,
  "entity_ids": [],
  "include_working_material": false
}
```

**Response:** `BrainContextResponse`  
`task` typically `"retrieve"`. `approved_excerpts` populated from runtime-eligible hits.

**App usage:** Call when `BRAIN_HTTP_ENABLED` + `BRAIN_HTTP_RETRIEVE`. Live client
sends `query_text` (basic retrieve). Hydrated excerpts may merge into `/retrieve`
synthesis as cited evidence — not as a knowledge-graph walk. Approved excerpts
are preferred; **operational_unreviewed** working material may also be synthesized
when present (must be labeled unreviewed). Both feed citations alongside publish
hits until cutover.

---

### 2. `POST /brain/v1/context/troubleshoot`

**Purpose:** Guided troubleshoot turn grounding (symptoms, node, playbook hints).

**Request**

```json
{
  "query": "string (user message or enriched message)",
  "session_id": "string (required)",
  "playbook_id": "string|null",
  "node_id": "string|null",
  "runbook_id": "string|null",
  "observed_signals": {},
  "entity_ids": [],
  "attachment_summaries": [],
  "limit": 12,
  "include_working_material": false,
  "playbook_resolution": "pinned|awaiting_candidate|unpinned|null",
  "awaiting_playbook_selection": false,
  "candidate_playbook_ids": [],
  "case_id": "string|null"
}
```

**Response:** `BrainContextResponse`  
`task` typically `"troubleshoot"`. May include procedure/capability excerpts relevant to the active node when approved.

**App usage:** Call from `/troubleshoot` after enrichment (incl. image summaries); merge approved citations. When the operator has **not** chosen a playbook/case (`unpinned` / `awaiting_candidate`), app sets those fields, requests working material, and (if `BRAIN_HTTP_FEEDBACK`) auto-forwards a routing-learning packet with `about=unresolved_playbook_selection` carrying the user message + candidates — so Brain can improve routing/coverage. Playbook step selection remains app/publish runtime unless a later flag says otherwise.

---

### 3. `POST /brain/v1/feedback`

**Purpose:** Hand off user feedback; Brain runs Create-path (and any write policy). App does not mutate `brain_*`.

**Request**

```json
{
  "session_id": "string",
  "interaction_id": "string",
  "surface": "troubleshoot|retrieve",
  "sentiment": "helpful|not_helpful|suggestion",
  "about": "string|null",
  "user_text": "string",
  "proposed_change": "string",
  "targets": {
    "playbook_id": null,
    "runbook_id": null,
    "node_id": null,
    "record_ids": []
  },
  "attachment_ids": [],
  "image_summaries": [],
  "context_snapshot": {},
  "app_feedback_id": "feedback:...|null"
}
```

**Response**

```json
{
  "accepted": true,
  "brain_review_id": "brain_review:...|null",
  "ingestion_run_id": "string|null",
  "status": "applied_unreviewed|conflicting|gap|rejected|error",
  "mutated_record_ids": [],
  "message": "human-readable; must not claim sme_approved / catalog truth from feedback alone",
  "errors": []
}
```

**Semantics (locked with ingestion):** feedback runs extract → classify → reconcile → `apply_reconciliation` **synchronously**. Records may land immediately as `operational_unreviewed` or `conflicting`. `brain_review_id` audits what changed; it is **not** a queue waiting on SME before write.

**App usage:** After local `POST /feedback` persists `feedback_events`, optionally (flag) forward to Brain. Store returned `brain_review_id` (and status) on the app `FeedbackEvent`. UI: “Recorded for Brain review / unreviewed knowledge” — never “saved as approved guidance.”

---

### 4. Review

#### `GET /brain/v1/reviews?status=open&limit=50`

List open `BrainReview` summaries for SME UI (app or ingestion console).

#### `GET /brain/v1/reviews/{review_id}`

Full review + affected record stubs.

#### `POST /brain/v1/reviews/{review_id}/resolve`

**Locked with ingestion (v4):** `resolve_audit_candidate` (Tool 6) may only *propose*. HTTP `POST .../resolve` must execute what it can:

- **`MERGE` — apply for real:** mark losing `affected_record_ids` `DEPRECATED`, merge fields into `winner_record_id` via `merge_record`, return `mutated_record_ids`.
- **`RETYPE` — apply for real (v4):** rename entity id, cascade through referencing records (corpus-wide walk), validate post-cascade state before write, deprecate old id. Success → `applied: true` + `mutated_record_ids`. Refusal → HTTP **400** with specific reason (bad type, payload loss, id collision) — never silent success. Second apply on same id fails loudly (idempotency).
- **`RECLASSIFY` — still not auto-applied:** returns `applied: false` with a **RECLASSIFY-specific** explanation (different kind of record, not a type correction). Do not treat as RETYPE.

Do not ship a review-only path that pretends `MERGE`/`RETYPE` applied when they did not.

**Request**

```json
{
  "resolution": "approve|reject|edit",
  "resolved_by": "human",
  "reviewer_id": "string|null",
  "notes": "string|null",
  "edited_proposed_change": null
}
```

**Response**

```json
{
  "review_id": "brain_review:...",
  "status": "resolved",
  "resolution": "approve|reject|edit",
  "applied": true,
  "mutated_record_ids": [],
  "message": "string"
}
```

`applied` is the source of truth for whether the corpus changed. Appcode never applies the diff. SME UI: `applied=true` (often with `mutated_record_ids`) → real MERGE or RETYPE write; `applied=false` → do not claim corpus IDs changed (typical for RECLASSIFY or refused RETYPE).

---

## 5. Human notification & approval (locked)

This was previously undefined. Lock the following so app and ingestion share one SME path.

### 5.1 What needs a human

Not every feedback write waits on SME (sync Create-path may land `operational_unreviewed` / `conflicting` immediately). Humans are required when a durable **`BrainReview` is `open`** (or resolution returns accepted-but-not-executed), especially:

| Trigger | Why SME |
|---|---|
| Conflict / disputed claim | Prevent wrong guidance becoming `sme_approved` |
| Audit `MERGE` proposal | Execute collapse of duplicates |
| Audit `RETYPE` proposal | Execute id rename + cascade (v4) |
| Audit `RECLASSIFY` | Explicit non-apply until Brain supports kind change |
| GAP / unsafe-step / novel fix | Promote or reject working material |
| Pipeline / MCP-created open reviews | Same queue as runtime feedback |

Technicians using Guided Troubleshoot / Search are **not** the approvers. Approvers are **OptiSweep knowledge SMEs** (named Entra group / role).

### 5.2 How the human is notified (phased)

**Phase A — pull queue (ship with review HTTP; required)**

1. Brain persists `BrainReview` with `status=open` (and kind / priority if available).
2. **No email/Teams required for v1.** Notification = the review exists in the queue API.
3. Appcode hosts an **SME Review** Streamlit page (role-gated later; flag `BRAIN_HTTP_REVIEWS` / page visible to SME role):
   - Polls `GET /brain/v1/reviews?status=open&limit=50` on load / refresh.
   - Shows count badge (“N open reviews”) in nav when > 0.
   - Detail: `GET /brain/v1/reviews/{id}` → approve / reject / edit → `POST .../resolve`.
4. Optional operator habit: open the page at start of shift / after a known feedback spike. Product copy on feedback success stays “recorded / unreviewed,” and may add “SME queue updated” when `brain_review_id` is returned — **not** “an email was sent.”

**Phase B — push digest (deferred, same contract)**

- Brain or a small notifier job sends **Teams / email digest** to the SME Entra group when:
  - new `open` review created, and/or
  - daily/hourly summary of open count by kind.
- Payload: review_id, kind, short summary, deep link to app SME Review page (`?review_id=...`).
- Push never bypasses the queue UI; it only alerts humans to open the queue.

**Out of scope for now:** SMS, per-technician push, auto-assign to individual SMEs, SLA timers.

### 5.3 Who owns the UI vs mutation

| Concern | Owner |
|---|---|
| Open review store + resolve / MERGE apply | Brain (ingestion HTTP) |
| SME Review page, badge, deep links | **Appcode** (product UI) |
| Entra SME gate, Phase B Teams digest | Deferred (app + identity) |
| RECLASSIFY apply | Deferred (ingestion; still `applied: false`) |
| ANN index | **Not required** after v4 cache/provider fixes; revisit only if corpus scale regresses latency |
| App writing `brain_*` | **Rejected** (same handoff section) |

Runtime assistants and end users **never** call resolve. They only create feedback that may open a `BrainReview`.

### 5.4 Approval outcomes (what the human does)

1. Open queue → pick review → read proposed change + affected records.
2. **Approve / edit / reject** via `POST .../resolve`.
3. UI reflects Brain response:
   - MERGE / RETYPE with `applied=true` → show mutated ids.
   - RECLASSIFY or refused RETYPE (`applied=false` / HTTP 400) → show Brain `detail`; do not claim IDs changed.
   - Reject → trusted cite set unchanged.

### 5.5 App flags (add when building the page)

```text
BRAIN_HTTP_REVIEWS=false   # enable SME Review page + open-queue client calls
```

Deferred Entra gate and Phase B digest remain future. Latency (v4) and RETYPE
apply are **done on Brain**; RECLASSIFY apply is still Brain-side deferred.
This app never writes `brain_*`.

---

## App feature flags (proposed)

```text
BRAIN_HTTP_BASE_URL=https://optisweep-brain-http.nicetree-2326f6da.eastus.azurecontainerapps.io
BRAIN_HTTP_ENABLED=false
BRAIN_HTTP_RETRIEVE=false
BRAIN_HTTP_TROUBLESHOOT=false
BRAIN_HTTP_FEEDBACK=false
BRAIN_HTTP_REVIEWS=false
BRAIN_HTTP_TIMEOUT_SECONDS=90
```

Defaults off for local enable flags → today’s publish path unchanged until you flip them. Azure Container App templates set flags **on** with the live Brain URL. Timeout default **90s** covers v4 cold retrieve (~40–50s); warm is ~2s. With
`BRAIN_HTTP_WARMUP_ON_STARTUP=true` (default), the app schedules a background
probe retrieve on API startup so the cold load is less likely to hit the first
operator question. (Pre-v4 needed 300s for a 3–4 min provider/cache bug — fixed without ANN.) Scale-to-zero on the Brain Container App can still reintroduce cold starts after idle.

Appcode `BrainHttpClient` maps to the **live OpenAPI** shapes (e.g. `query`→`query_text`, `excerpts[]`→approved/working/conflict buckets, feedback `text`/`review_ids`, resolve `applied`/`detail`). `GET /reviews/{id}` is not on live OpenAPI — detail falls back to list lookup.


---

## What appcode will not do

- Upsert `brain_evidence` / `brain_entities` / `brain_claims` / etc.
- Treat MCP as the UI transport
- Cite `operational_unreviewed` / `needs_sme_review` / `conflicting` / `deprecated` as approved guidance
- Replace playbook step runtime with Brain drafts until explicitly flagged and SME-ready
- Notify technicians (end users) to approve BrainReviews
- Claim email/Teams was sent in Phase A

---

## Implementation order (appcode)

1. ~~Brain HTTP client + flag plumbing + retrieve dry-run~~ **done** (flags default off; client + cite filter + retrieve/troubleshoot merge + feedback forward).
2. Wire against live Brain OpenAPI when ingestion publishes base URL.
3. ~~**SME Review page (Phase A pull queue)**~~ **done**. Entra / Phase B still deferred. Brain v4: latency fixed + RETYPE apply live; RECLASSIFY still `applied: false`.
4. Cutover / demote publish retrieval only after quality sign-off.

---

## Open for ingestion to confirm

- ~~Exact host/path prefix and OpenAPI~~ — **live**.
- ~~Feedback sync / hydration / MERGE / embeddings~~ — confirmed.
- ~~Retrieve latency~~ — **fixed on v4** (cache/providers; not ANN); cold ~40–50s, warm ~2s.
- ~~RETYPE apply~~ — **done on v4** (`applied: true` + cascade).
- **RECLASSIFY apply** — still open (explicit `applied: false`).
- ~~Human notification Phase A~~ — locked in app; Phase B digest deferred.

Auth model for v1: unauthenticated or shared network + later Entra; no MCP-specific auth for UI.
