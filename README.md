# OptiSweep AI Support Assistant

Cosmos-backed **playbook troubleshooting** and **retrieval chat** for OptiSweep incidents.
FastAPI + LangGraph backend; Streamlit UI. Corpus is published by the separate
**ingestion** repo (Stage 11) — this app does not ingest or own Brain writes.

| | |
|--|--|
| UI | `streamlit run ui/Home.py` · full guide [`ui/README.md`](ui/README.md) |
| API | `uvicorn backend.app.main:app --reload` |
| Site ops | [UPS – Haslet TX](https://fortna.atlassian.net/wiki/spaces/DS/pages/3064266909/UPS+-+Haslet+TX) |
| **Azure ownership transfer** | [`AZURE_ACCOUNT_HANDOFF.md`](AZURE_ACCOUNT_HANDOFF.md) — step-by-step for moving off a personal subscription |
| **Ingestion dependencies** | [`docs/INGESTION_DEPENDENCIES.md`](docs/INGESTION_DEPENDENCIES.md) — Stage 11 publish, embeddings, Brain HTTP |

## What this repo is (and is not)

| This app (implemented) | Not this repo |
|------------------------|---------------|
| `POST /troubleshoot` — guided playbook steps | Live RMS / WCS / Ignition queries |
| `POST /retrieve` — hybrid search over Cosmos embeddings | Ingestion pipelines / Brain corpus mutation |
| Session + interaction logs (+ optional feedback) in Cosmos | YAML workflow / CAT-1 case-triage runtime (**removed**) |
| Optional **Brain HTTP client** (feature-flagged) | Hosting Brain HTTP (ingestion hosts it) |

**Primary knowledge path:** Azure Cosmos publish containers filled by the
**ingestion** repo (Stage 11). This app only loads and searches that publish.
When Cosmos creds are missing, `corpus_source` reports `sample` (tiny in-process
demo corpus) — never confuse that with live publish data.  
**Optional Brain path:** when `BRAIN_HTTP_ENABLED` + `BRAIN_HTTP_RETRIEVE` are on,
Brain HTTP returns hydrated excerpts that the app may merge into `/retrieve`
answer synthesis as **supplemental cited evidence** (not a knowledge graph).
Approved excerpts are preferred; **operational_unreviewed** working material is
allowed only when labeled unreviewed.  
See [`docs/brain/HTTP_BOUNDARY.md`](docs/brain/HTTP_BOUNDARY.md).

Publish playbook→runbook links live in Cosmos `relationship_links` and are used
by Guided Troubleshoot — that is separate from Brain retrieve.

**Two-repo dependency map:** [`docs/INGESTION_DEPENDENCIES.md`](docs/INGESTION_DEPENDENCIES.md).

## Quick start

```powershell
# From repo root, with .venv activated and .env filled from .env.example
uvicorn backend.app.main:app --reload
streamlit run ui/Home.py
```

Health: `GET http://127.0.0.1:8000/health`  
Settings dump: `GET http://127.0.0.1:8000/debug/settings`

## UI pages

Full UI handoff (tabs, backends, Brain learning loop, screenshots):
[`ui/README.md`](ui/README.md).

| Page | File | Backend |
|------|------|---------|
| Home | `ui/Home.py` | `/health` |
| Guided Troubleshoot | `ui/pages/1_Guided_Troubleshoot.py` | `POST /troubleshoot` (+ embedded retrieve) |
| Search / Chat | `ui/pages/2_Search_Chat.py` | `POST /retrieve` |
| SME Review | `ui/pages/3_SME_Review.py` | `GET/POST /reviews*` (Brain HTTP; flags required) |

Compat: `streamlit run ui/streamlit_app.py` forwards to `Home.py`.

## How the runtime works

1. **Turn 1** — keyword symptoms from Cosmos `gate_phrase_tables` (optional LLM overlay).
   Hybrid retrieval over published embeddings; candidate list or auto-pin by thresholds.
2. **Turn 2+** — pinned playbook node + linked runbooks by ID (no vector search).
3. **Branching** — exact button labels are deterministic; free text may use branch LLM.
4. **`/retrieve`** — multi-turn search chat; always includes `operational_context` when present.
   Answer synthesis uses richer hit excerpts (`compose_answer.md` v1.3) when
   `ENABLE_LLM_RETRIEVE_SYNTHESIS=true` and Azure chat is configured; otherwise a
   template fallback. Check `GET /debug/settings` for `corpus_source`,
   `llm_available`, and Brain flags.

Details: [`docs/PLAYBOOK_RUNTIME.md`](docs/PLAYBOOK_RUNTIME.md) ·
[`backend/app/agents/README.md`](backend/app/agents/README.md).

## Repository map

```text
backend/app/
  main.py                 FastAPI entry
  api/                    HTTP routes
  agents/                 Playbook agents (orchestrator + tools)
  graph/                  LangGraph playbook + retrieve graphs
  runtime/                run_playbook_troubleshoot / run_retrieve_chat
  corpus/                 Cosmos load + in-memory index (sole corpus source)
  retrieval/              Hybrid scorer (cosine + Jaccard + symptom)
  services/               Sessions, logs, embeddings, Brain HTTP client, feedback, …
  repositories/           Cosmos repos for sessions/logs/feedback/images (+ unused Phase-1 leftovers)
ui/                       Streamlit multi-page app
docs/                     Current architecture + Cosmos + Brain contracts
deploy/                   Container App YAML (live + preview)
scripts/                  Azure start + preflight
tests/                    Pytest
```

### Live vs leftover code

| Keep (live) | Leftover / safe to ignore for runtime |
|-------------|----------------------------------------|
| `api/`, `agents/`, `graph/playbook_*`, `runtime/`, `corpus/`, `retrieval/` | Empty `graph/nodes/` (legacy stub) |
| `services/` used by routes + agents (see module notes) | Unused Phase-1 `repositories/*` + `models/*` not on the playbook path |
| `schemas/assistant.py` | Older `schemas/incident|workflow|procedure*.py` |
| UI pages + `playbook_ui.py` / `feedback_ui.py` | — |

## Configuration

Copy [`.env.example`](.env.example) for a short template, or [`.env.mock`](.env.mock)
for an agent-oriented inventory of every key (required vs optional, aliases,
Key Vault `secretRef` names, where to get values). Important groups:

| Mode | Vars |
|------|------|
| Live Cosmos corpus | `RETRIEVAL_BACKEND=cosmos`, `AUTO_PUBLISH_VERSION=true`, `COSMOS_*` |
| Sessions / logs | `SESSION_BACKEND=cosmos`, `INTERACTION_LOG_BACKEND=cosmos` |
| LLM slots | `ENABLE_LLM_*=true`, `AZURE_OPENAI_*`, embeddings deployment must match Cosmos |
| Brain HTTP (optional) | `BRAIN_HTTP_BASE_URL`, `BRAIN_HTTP_ENABLED`, per-route `BRAIN_HTTP_RETRIEVE|TROUBLESHOOT|FEEDBACK|REVIEWS`, optional `BRAIN_HTTP_WARMUP_ON_STARTUP=true` (background cold probe so first user turn is more likely warm) |

With `AUTO_PUBLISH_VERSION=true`, startup picks the newest Cosmos publish that has
embeddings. Pin with `PUBLISH_VERSION_ID` when auto is off.

## Azure deploy

Root `Dockerfile` → `scripts/start_azure_container_app.py` (FastAPI `:8000` + Streamlit `:8501`).
Ingress target port **8501**. Templates: `deploy/container-app.yaml` (live),
`deploy/container-app-preview.yaml` (preview).

```powershell
python scripts/preflight_deployment.py
python -m backend.app.scripts.verify_cosmos_corpus
```

## Documentation index

| Doc | Use when |
|-----|----------|
| [`AZURE_ACCOUNT_HANDOFF.md`](AZURE_ACCOUNT_HANDOFF.md) | Move app to a new Azure subscription / owner |
| [`docs/INGESTION_DEPENDENCIES.md`](docs/INGESTION_DEPENDENCIES.md) | What this app needs from the ingestion repo |
| [`ui/README.md`](ui/README.md) | Streamlit pages, backends, Brain learning UX |
| [`docs/README.md`](docs/README.md) | Doc map |
| [`docs/PLAYBOOK_RUNTIME.md`](docs/PLAYBOOK_RUNTIME.md) | Graph, agents, routing |
| [`docs/cosmos_data_map.md`](docs/cosmos_data_map.md) | Containers + publish model |
| [`docs/cosmos_record_types.md`](docs/cosmos_record_types.md) | Payload shapes |
| [`docs/cosmos_corpus_queries.md`](docs/cosmos_corpus_queries.md) | SQL query cheat sheet |
| [`docs/retrieval_algorithms.md`](docs/retrieval_algorithms.md) | Hybrid scoring |
| [`docs/app_agent_scoring_handoff.md`](docs/app_agent_scoring_handoff.md) | Thresholds / smoke notes |
| [`docs/brain/HTTP_BOUNDARY.md`](docs/brain/HTTP_BOUNDARY.md) | App ↔ Brain HTTP contract |
| [`docs/brain/FEEDBACK_CAPTURE.md`](docs/brain/FEEDBACK_CAPTURE.md) | Feedback + attachments |

## Known maturity

| Area | Status |
|------|--------|
| Cosmos playbook + retrieve | **Implemented** |
| Streamlit Guided / Search / SME Review | **Implemented** (SME needs Brain flags) |
| Brain HTTP overlay | **Partial** — client + flags; default **off**; publish corpus remains primary. Retrieve may merge Brain hydrated excerpts into synthesis (not a knowledge graph); working material labeled unreviewed. Brain **v4**: cold ~40–50s / warm ~2s; MERGE+RETYPE apply; RECLASSIFY still `applied: false`. |
| Auth / Entra on app or Brain | **Deferred** |
| Dead Phase-1 repo/model modules | Present but **not** on hot path — cleanup candidate |

Do not treat removed YAML / CAT-1 / case-triage docs or `data/` workflows as current —
those paths were deleted from this repo.
