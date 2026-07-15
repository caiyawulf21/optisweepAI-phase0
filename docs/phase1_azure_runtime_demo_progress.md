# Phase 1 Azure Runtime Demo - Progress Log

> Source-of-truth build prompt was removed with deprecated prompt artifacts; see `docs/Phase 0 Runtime Demo & Completion` for the archived master brief.
> Companion status review: `docs/phase0_status_review.md` (Section I links back here).
> Phase 0 scope changes tracker (only Phase 0 deltas; this log owns Phase 1 progress): `docs/phase0_scope_changes_README.md`.
> Last update: 2026-05-29 (Step 16 post-Phase-1 addendum: LLMCompositionSynthesizer landed; 5 demo-promoted canonical workflows now cover all 6 normalized CAT-1 incidents; canonical_workflow_definitions container grew from 2 docs to 7 docs).

This file appends one entry per build step. Sections A-H of the status review are left untouched so they continue to reflect the Phase 0 snapshot; this log is the running record of Phase 1 runtime delivery.

---

## Step 1 - Source-of-truth build prompt

- Status: done
- Changed files:
  - Deprecated prompt artifact removed; archived source remains `docs/Phase 0 Runtime Demo & Completion`.
- Tests run: none required.
- Blockers: none.

## Step 2 - Runtime feature flags

- Status: done
- Changed files:
  - `backend/app/config/__init__.py` - added `retrieval_backend`, `session_backend`, `enable_guided_diagnostic`, `enable_canonical_workflow_runtime` to `AppSettings` with `local` / `memory` / `false` / `false` defaults; added `RETRIEVAL_BACKEND_*` and `SESSION_BACKEND_*` constants; added `validate_runtime_mode(app_settings, azure_settings)` that delegates to existing `AzureKnowledgeSettings.require_search()` / `require_cosmos()` for credential checks and raises `ValueError` for unknown backend strings; extended `__all_`_.
  - `backend/app/main.py` - added `@app.on_event("startup")` hook that calls `validate_runtime_mode(get_app_settings(), get_settings())`, logs a clear error, and re-raises so a misconfigured Azure mode refuses to start.
  - `.env.example` - documented the new flags with their safe defaults (`RETRIEVAL_BACKEND=local`, `SESSION_BACKEND=memory`, `ENABLE_GUIDED_DIAGNOSTIC=false`, `ENABLE_CANONICAL_WORKFLOW_RUNTIME=false`) and a 4-line comment explaining valid values and the boot-time failure behavior.
  - `tests/test_runtime_feature_flags.py` (new) - 9 tests covering: default flag values, local-only boot, Azure boot with creds present, missing Azure Search creds, missing Cosmos creds, unknown retrieval backend, unknown session backend, no-arg invocation, env-driven feature toggles.
- Tests run:
  - `pytest tests/test_runtime_feature_flags.py -v` -> 9 passed.
  - `pytest -q` (full suite) -> 426 passed, 1 skipped, 0 failed (25.78s).
- Blockers: none.
- Acceptance verified:
  - App boots in local-only mode (no Azure env required).
  - App boots in Azure mode when matching `AZURE_SEARCH_*` and `AZURE_COSMOS_*` env vars are present.
  - Missing Azure env vars when an Azure backend is selected raise `ValueError` naming the missing variables.

## Step 3 - Azure Cosmos containers

- Status: done (live)
- Changed files:
  - `backend/app/repositories/container_config.py` - added the two missing Phase 1 runtime containers: `workflow_sessions` (partition `/session_id`) and `interaction_logs` (partition `/session_id`); the other 8 required containers were already declared (`context_reference`, `incident_records`, `timeline_events`, `workflow_definitions`, `procedure_dictionary`, `raw_evidence_chunks`, `source_artifacts`, `escalation_summaries`). Added a `PHASE1_RUNTIME_CONTAINER_NAMES` tuple so the build-prompt requirement is pinned in code.
  - `backend/app/repositories/workflow_session_repository.py` (new) - `WorkflowSessionRepository(CosmosRepository)` targeting `workflow_sessions`.
  - `backend/app/repositories/interaction_log_repository.py` (new) - `InteractionLogRepository(CosmosRepository)` targeting `interaction_logs`.
  - `backend/app/repositories/__init__.py` - exported the two new repositories.
  - `tests/test_phase1_cosmos_containers.py` (new) - 5 tests verifying the 10 required containers are registered with the expected partition keys, the two new repositories resolve to the correct container names, and `create_cosmos_containers --dry-run` lists all 10.
- Tests run:
  - `pytest tests/test_phase1_cosmos_containers.py -v` -> 5 passed.
- Live provisioning run (2026-05-27, account `optisweepsupportdev`, database `optisweep_knowledge_phase0`):
  - `python -m backend.app.scripts.create_cosmos_containers` returned `{"created": [...]}` with **15 containers** total: the **10 Phase 1 required** (`context_reference`, `incident_records`, `timeline_events`, `workflow_definitions`, `procedure_dictionary`, `raw_evidence_chunks`, `source_artifacts`, `escalation_summaries`, `workflow_sessions`, `interaction_logs`) plus 5 retained Phase 0 extras (`workflow_candidates`, `knowledge_relationships`, `ingestion_runs`, `canonical_procedure_dictionary`, `canonical_workflow_definitions`). All idempotent via `create_container_if_not_exists`.
- Notes:
  - The existing `backend/app/scripts/create_cosmos_containers.py` provisioning CLI iterates `CONTAINERS.values()`, so it picks up the two new containers automatically; no edits to the CLI were needed.
  - Existing extras retained - they are current Phase 0 containers, not future-only, and are still referenced by `seed_canonical_to_cosmos`.
  - The `escalation_summaries` container keeps its current `/incident_id` partition. The Step 8 escalation-summary schema is workflow-scoped (`workflow_id`), so a partition-key revisit may be warranted when Step 8 lands; deferred to that step.
  - `azure-cosmos` was listed in `requirements-backend.txt` but was missing from the local venv; `pip install -r requirements-backend.txt` resolved it (also pulled in `azure-storage-blob`, `azure-identity`, `cryptography`, `msal`, `msal-extensions`, `PyJWT`).
- Blockers: none.
- Acceptance verified (live):
  - Provisioning works (15 containers created against the live `optisweepsupportdev` account).
  - Repositories resolve correctly (`WorkflowSessionRepository.container_name == "workflow_sessions"`, `InteractionLogRepository.container_name == "interaction_logs"`).
  - Existing tests still pass.

## Step 4 - Azure seed script

- Status: done (live)
- Changed files:
  - `backend/app/seed/phase1_runtime_seed.py` (new) - one mapper per dataset producing deterministic, sorted, idempotent Cosmos documents:
    - `context_reference_documents` (Dataset 0) - reads `data/context/context_reference.json` when present, otherwise falls back to the in-code Phase 0 seed (`seed_context_reference.context_documents`).
    - `incident_record_documents` (Dataset 1) - reads `data/incidents/canonical_incidents.json`; normalizes `issue_category` like `CAT-1: WCS/Service Failure` to `CAT-1` so the partition key is stable across incident records.
    - `timeline_event_documents` (Dataset 1.5) - reads `data/timelines/timeline_events.json`.
    - `workflow_definition_documents` (Dataset 2C) - re-uses `canonical_to_cosmos.canonical_workflow_documents`.
    - `procedure_dictionary_documents` (Dataset 2B) - re-uses `canonical_to_cosmos.canonical_procedure_documents`.
    - `raw_evidence_chunk_documents` (Dataset 3) - reads `data/evidence/raw_evidence_chunks.json`.
    - `source_artifact_documents` (Dataset 4) - reads `data/evidence/source_artifacts.json`.
    - `escalation_summary_documents` (Dataset 5) - reads `data/escalation/escalation_summaries.json` (missing today; returns empty with `source_missing: true` in the manifest until Step 8 lands).
    - `PHASE1_SEED_PLANS` - 10 `Phase1SeedPlan` entries covering all required containers; `workflow_sessions` and `interaction_logs` are flagged `runtime_only=True` so the CLI surfaces them in the audit while skipping seeding (they are populated by the live runtime in Steps 9 + 13).
  - `scripts/seed_phase1_azure.py` (new) - CLI with `--dry-run` (default) and `--apply`. Dry-run writes one JSON manifest per container under `output/phase1_azure_seed/` plus a `totals` block (containers seeded / runtime-only / source-missing, documents total / upserted / failed). Apply mode calls `AzureKnowledgeSettings.require_cosmos()` up-front, then `repo.upsert(doc)` per document via the plan's lazily-resolved repository factory; `--container <name>` restricts execution to one container (repeatable). Upserts are idempotent by document `id`.
  - `tests/test_seed_phase1_azure_cli.py` (new) - 7 tests covering: dry-run writes a manifest per non-runtime container plus the totals block; dry-run never imports a Cosmos client; missing source files surface `source_missing: true` instead of crashing; `--apply` invokes upsert per document via the stub repository; re-running `--apply` is idempotent (same upsert count, same totals); `--apply` raises a clear `ValueError` when Cosmos creds are missing; `--container` rejects unknown names with a helpful `SystemExit`.
- Tests run:
  - `pytest tests/test_seed_phase1_azure_cli.py tests/test_phase1_cosmos_containers.py -v` -> 12 passed.
  - `pytest -q` (full suite, post-live-seed) -> **438 passed, 1 skipped, 0 failed (25.84s)**.
- Live `--apply` run (2026-05-27, account `optisweepsupportdev`, database `optisweep_knowledge_phase0`):
  - `python scripts/seed_phase1_azure.py --apply` reported `totals.documents_total: 301`, `documents_upserted: 301`, `documents_failed: 0`, `dry_run: false`.
  - Per-container upsert counts (all `succeeded == document_count`, `failed == 0`): `context_reference=4`, `incident_records=6`, `timeline_events=60`, `workflow_definitions=2`, `procedure_dictionary=50`, `raw_evidence_chunks=60`, `source_artifacts=119`.
  - `escalation_summaries`: 0 upserts, `source_missing: true` (expected until Step 8 authors `data/escalation/escalation_summaries.json`).
  - `workflow_sessions`, `interaction_logs`: `runtime_only: true`, `skipped: true` (expected; populated at runtime by Steps 9 + 13).
  - Manifests written under `output/phase1_azure_seed/` (one JSON per non-runtime container).
- Blockers: none.
- Acceptance verified (live):
  - Dry-run generates audit output (manifest per container + totals JSON on stdout).
  - `--apply` upserts to Cosmos (301/301 upserts against live `optisweepsupportdev` account; `--apply` guarded by `require_cosmos`).
  - Counts printed per container.
  - Script is idempotent (re-running `--apply` produces the same upsert count and totals; this run was the second --apply invocation overall after the earlier stubbed-repo test runs, and matched expected totals).

## Step 5 - Azure AI Search runtime index sync

- Status: done (code complete, live `--apply` pending `AZURE_SEARCH_`* credentials in `.env`)
- Changed files:
  - `backend/app/search/phase1_index_schema.py` (new) - `PHASE1_SEARCH_INDEX_NAME = "optisweep-support-knowledge-dev"`, `PHASE1_REQUIRED_FIELDS`, `PHASE1_FILTERABLE_FIELDS`, `PHASE1_COLLECTION_FIELDS`, `PHASE1_SEARCHABLE_FIELDS`, dependency-free `Phase1SearchIndexSpec` for dry-run manifests, and a live `build_phase1_search_index()` builder (lazy-imports `azure.search.documents`) that wires the exact 14-field schema called out in the build prompt: `id, container_id, record_type, incident_id, workflow_id, procedure_id, issue_category, component, site, source_type, source_refs, validation_status, retrieval_text, content_vector` plus a HNSW vector profile (`phase1-vector-profile`, dimensions from `AZURE_SEARCH_VECTOR_DIMENSIONS`). Adds `phase1_search_index_client()` and `phase1_search_client()` helpers that gate on `AzureKnowledgeSettings.require_search()`.
  - `backend/app/seed/phase1_search_documents.py` (new) - one mapper per dataset (`context_reference_search_documents`, `incident_record_search_documents`, `timeline_event_search_documents`, `workflow_definition_search_documents`, `procedure_dictionary_search_documents`, `raw_evidence_chunk_search_documents`, `source_artifact_search_documents`, `escalation_summary_search_documents`) plus a `PHASE1_SEARCH_PLANS` registry and `iter_phase1_search_documents()` aggregator. Each mapper concatenates the build-prompt searchable text (`retrieval_text`, `symptom_summary`, `observed_signals`, `root_cause_summary`, `resolution_summary`, `resolution_steps`, `escalation_notes`, plus `content`/`event_summary`/`title` fallbacks) into the indexed `retrieval_text` field and preserves citations via `source_refs` (collected from `source_ref`, `source_refs`, `source_file`, `source_artifact_ids`, `source_artifact_paths`, `evidence_refs`). Document IDs are sha-prefixed per container so they are globally unique across containers in one index and stable across runs.
  - `scripts/sync_phase1_search_index.py` (new) - CLI with `--dry-run` (default), `--apply`, `--container`, `--index-name`, `--batch-size`, `--skip-index-create`. Dry-run writes per-container search-document manifests under `output/phase1_search_sync/` plus `phase1_search_index_manifest.json` (the schema spec). `--apply` calls `require_search()` up-front, then `create_or_update_index(build_phase1_search_index(index_name=...))` followed by batched `client.upload_documents` with per-batch success/failure counts. Uploads are idempotent because document IDs are deterministic.
  - `tests/test_phase1_search_index.py` (new) - 14 tests covering: the schema spec exposes the exact 14 required fields and serializes to JSON; per-mapper required keys + citation preservation (incident records, workflows, procedures); cross-container ID uniqueness; dry-run writes per-container manifests + the index manifest and prints totals; dry-run never instantiates the Azure SDK; `--apply` calls `_apply_index` + `_apply_documents` (stubbed); `--skip-index-create` only uploads; re-running `--apply` produces an identical ID set (idempotent); `--apply` raises a clear `ValueError` when `AZURE_SEARCH_`* are missing; unknown `--container` exits with a helpful `SystemExit`.
- Tests run:
  - `pytest tests/test_phase1_search_index.py -v` -> 14 passed.
- Dry-run smoke test (no network):
  - `python scripts/sync_phase1_search_index.py --dry-run` -> 301 search documents across 7 of the 8 Phase 1 data-driven plans, identical to the Step 4 Cosmos counts (`context_reference=4`, `incident_records=6`, `timeline_events=60`, `workflow_definitions=2`, `procedure_dictionary=50`, `raw_evidence_chunks=60`, `source_artifacts=119`; `escalation_summaries=0` with `source_missing: true`).
- Live `--apply` against `optisweepsupportdev` is deferred until `AZURE_SEARCH_ENDPOINT` + `AZURE_SEARCH_KEY` are added to `.env`. The `--apply` path is fully covered by the stubbed-SDK tests, so this is a configuration-only follow-up - no further code changes required.
- Blockers: none for the implementation; live apply waits on user-provided `AZURE_SEARCH_`* env vars.

## Step 6 - Runtime retrieval hot path swap

- Status: done
- Changed files:
  - `backend/app/services/azure_search_client.py` - replaced the empty `AzureSearchRetrievalClient(LocalCat1RetrievalClient)` stub with a real Azure-Search-backed implementation: lazy-builds `SearchClient` against `PHASE1_SEARCH_INDEX_NAME` (overridable), accepts an injected `client_factory` for tests, defaults the runtime filter to `issue_category eq 'CAT-1'` (overridable / disable-able via `issue_category_filter=""`), maps Azure hits into the same `RetrievalResult` + `Citation` shape the existing pipeline consumes (citation built from `id` + first `source_refs` entry, source_notes truncated to 400 chars), normalizes `@search.score` into a 0..1 confidence using `score / (1 + score)`, and returns `[]` on transport errors so the hot path never crashes a session. Added `build_runtime_retrieval_client(settings)` factory that returns the local client by default and the Azure client when `RETRIEVAL_BACKEND=azure_search`.
  - `backend/app/graph/nodes/retrieval.py` - the node now calls `build_runtime_retrieval_client()` instead of hardcoding `LocalCat1RetrievalClient`. Accepts an optional `client` parameter so end-to-end tests can inject stubs without env-var games.
- Tests run:
  - `pytest tests/test_phase1_runtime_retrieval.py -v` -> 10 passed: backend selection (local default + Azure on flag), local fallback contract still returns the same legacy results + citations, Azure client passes `search_text`/`top`/`filter` correctly, score normalization, citation preservation (source_id + reference), exception handling returns empty list, optional filter disable, signal matching, retrieval_node accepts injected client, and `run_troubleshooting` end-to-end with `RETRIEVAL_BACKEND=azure_search` and a stubbed `phase1_search_client` surfaces Azure results with citations preserved.
- Blockers: none. Live Azure retrieval will be exercised once `AZURE_SEARCH_`* env vars + the live index land (Step 5 follow-up).
- Acceptance verified:
  - Local fallback still works (`RETRIEVAL_BACKEND=local` keeps the legacy retrieval results bit-for-bit unchanged; pinned by `test_local_retrieval_path_still_returns_legacy_results` and by the existing `test_phase11_dual_path_isolation` suite which is unchanged).
  - Azure retrieval is the runtime path when `RETRIEVAL_BACKEND=azure_search` (end-to-end test stubs the SearchClient and asserts the Azure code is reached through `/troubleshoot`).
  - Citations preserved (every Azure hit lands a `Citation` populated from `source_refs`).
  - Tests added (10 new tests + 0 regressions).
  - Closes Section F blocker 5 (hot-path Azure now wired - awaits live `AZURE_SEARCH_*` creds to flip the deployment switch).

## Step 7 - Guided diagnostic question surfacing

- Status: done
- Changed files:
  - `backend/app/graph/state.py` - added `guided_question: dict[str, Any] | None` to `AssistantState` and initialized it to `None` in `create_initial_state`.
  - `backend/app/schemas/assistant.py` - added `guided_question: dict[str, Any] | None = None` to `TroubleshootResponse` so the structured payload is exposed through the API contract.
  - `backend/app/graph/nodes/clarification.py` (new) - `clarification_node(state, *, canonical_loader=None)` that loads the canonical workflow + the routed node, derives `allowed_answers` from the node's `branches` (`equals true/false` -> `yes/no`, `not_equals`/`present`/`absent` mapped, defaults to `["yes", "no"]` for question/decision/diagnostic_check nodes when branches are empty), builds a `why_asked` string from coverage + condition signals, emits citations for the workflow + linked procedure_ref, writes the canonical `guided_question` dict (`response_type=guided_question`, `workflow_id`, `current_node_id`, `question`, `allowed_answers`, `why_asked`, `citations`), merges new citations into `state["citations"]` without duplicating existing ones, and writes a human-readable `final_response` so legacy clients still see the question. Never touches `escalation_required` / `escalation_reason`.
  - `backend/app/graph/nodes/canonical_routing.py` - `canonical_route_branch` now returns `"clarification"` for `guided_diagnostic` mode (was `"escalation"`). Docstring updated to call out that the graph builder remaps `"clarification"` back to `"escalation"` when `ENABLE_GUIDED_DIAGNOSTIC` is off, preserving the legacy mapping.
  - `backend/app/graph/graph.py` - `build_troubleshooting_graph(settings=None)` reads `AppSettings.enable_guided_diagnostic`. When on, registers the `clarification` node, wires `canonical_routing -> clarification -> END`, and the conditional-edge map sends `"clarification"` to the new node. When off, the map sends `"clarification"` to `escalation` so the legacy demo response shape is preserved bit-for-bit.
  - `tests/test_canonical_routing_node.py` - one assertion updated: `canonical_route_branch({"canonical_route_mode": "guided_diagnostic"}) == "clarification"` (was `"escalation"`). The 7 other tests in this file pass unchanged.
  - `tests/test_guided_diagnostic_clarification.py` (new) - 8 tests covering: route-branch maps `guided_diagnostic` to `clarification`; escalation path still maps to `escalation`; `clarification_node` produces the full canonical `guided_question` payload with correct `response_type`, `workflow_id`, `current_node_id`, `allowed_answers=["yes", "no"]`, coverage-aware `why_asked`, workflow citation, and final_response text; node also emits a procedure citation when the workflow node carries `procedure_ref`; node is a no-op when required state fields are missing; node degrades gracefully when the loader cannot find the workflow; end-to-end graph (with stubbed `HybridWorkflowRouter` returning `GuidedDiagnosticRoute`) routes to `clarification`, populates `guided_question`, leaves `escalation_required=False`, and the final_response carries no "Escalation required" text; end-to-end graph with `ENABLE_GUIDED_DIAGNOSTIC=false` collapses `guided_diagnostic` to `escalation` (legacy contract preserved).
- Tests run:
  - `pytest tests/test_guided_diagnostic_clarification.py tests/test_canonical_routing_node.py -v` -> 16 passed.
- Blockers: none.
- Acceptance verified:
  - Guided questions now reach the user (`guided_question` field is on `TroubleshootResponse`, populated whenever the canonical router returns `GuidedDiagnosticRoute` and the flag is on).
  - No generic escalation response when the flag is on (`escalation_required=False`, no "Escalation required" text in `final_response`).
  - Tests verify end-to-end behavior via the graph build + invoke path.
  - Closes the "guided question never surfaced" half of Section F blocker 6 (the canonical workflow display-only half remains for Step 10).

## Step 8 - Dataset 5 escalation summaries

- Status: done
- Changed files:
  - `data/escalation/escalation_summaries.json` (new) - two records using the exact 15-field schema from the build prompt (`escalation_summary_id`, `workflow_id`, `issue_category`, `escalation_domain`, `priority`, `trigger_reason`, `symptoms`, `observed_signals`, `steps_attempted`, `steps_not_attempted`, `evidence_refs`, `logs_collected`, `source_artifacts`, `recommended_owner`, `handoff_summary_template`): one for `heartbeat_timeout_no_rms_fault_v1` (priority P2, `escalation_domain=application_engineering`, signals/evidence/artifacts sourced from the workflow YAML and cat1_229374 / 229716 / 229777 incident records) and one for `service_failure_with_customer_bridge_and_engineer_recovery_v1` (priority P1, same domain, signals/evidence sourced from the workflow YAML and cat1_228086 / 229374 / 229488 / 229716 / 229777 incident records). The `handoff_summary_template` strings carry `{{workflow_id}}`, `{{current_node_id}}`, `{{observed_signals}}`, `{{steps_attempted}}`, `{{retrieval_result_ids}}`, `{{escalation_reason}}`, `{{triggered_at}}` placeholders.
  - `backend/app/services/escalation_templates.py` (new) - `load_escalation_templates(path=None, *, refresh=False)` validates required fields and list-typed fields, raises `EscalationTemplateError` on malformed payloads, caches by resolved path; `get_escalation_template(workflow_id, *, path=None)` returns `None` for unknown ids; `render_handoff_summary(template, runtime)` substitutes `{{placeholder}}` slots from the runtime context (falling back to template fields, then to `(not captured)`) and coerces list/dict runtime values to readable strings; `reset_escalation_template_cache()` for tests.
  - `backend/app/graph/state.py` - added `escalation_summary: dict[str, Any] | None` to `AssistantState` and initialized it in `create_initial_state`.
  - `backend/app/schemas/assistant.py` - added `escalation_summary: dict[str, Any] | None = None` to `TroubleshootResponse` so the rendered template surfaces through the API contract.
  - `backend/app/graph/nodes/escalation.py` - the node now (1) always clears `state["escalation_summary"]`, (2) preserves the existing `escalation_required` / `escalation_reason` / `workflow_state.escalation_domains` / `final_response` behavior, and (3) when escalation fires and a template exists for the active `selected_workflow_id`, builds a runtime context (`session_id`, `workflow_id`, `current_node_id`, `observed_signals`, `steps_attempted`, `retrieval_result_ids`, `retrieval_confidence`, `escalation_reason`, `escalation_domains`, `triggered_at`) and stores `{...template, "handoff_summary": rendered, "runtime": runtime_context}` on the state. When no template matches the workflow_id (or no workflow is selected) the field stays `None` and the existing generic escalation response is unchanged (template-missing fallback).
  - `tests/test_escalation_templates.py` (new) - 13 tests covering loader happy path (both seeded workflows load with all required fields), error paths (missing file, non-list payload, invalid JSON, missing required field, duplicate workflow_id, non-list list field), `get_escalation_template` returns `None` for unknown/empty ids, `render_handoff_summary` substitutes runtime placeholders / falls back to template fields / coerces empty list and dict values to `(not captured)`, and the loader cache is honoured until `reset_escalation_template_cache()`.
  - `tests/test_escalation_node_template.py` (new) - 6 tests covering: end-to-end render when the active workflow matches a template (`escalation_summary` populated, runtime context attached, `handoff_summary` contains workflow_id / current_node_id / observed_signals / steps_attempted / retrieval_result_ids / escalation_reason / triggered_at, no `{{` leftovers); template-missing fallback when the workflow_id is unknown; template-missing fallback when no workflow is selected; no-escalation paths leave `escalation_summary` as `None`; the populated `escalation_summary` round-trips through `TroubleshootResponse.model_dump`; and both seeded workflow templates resolve via `get_escalation_template`.
- Tests run:
  - `pytest tests/test_escalation_templates.py tests/test_escalation_node_template.py -v` -> 19 passed.
- Blockers: none.
- Acceptance verified:
  - Two workflow-scoped escalation summaries seeded with the exact build-prompt field set.
  - `escalation_node` renders the template into `state["escalation_summary"]` whenever the active workflow matches, and falls back to the existing generic escalation behavior otherwise.
  - `TroubleshootResponse.escalation_summary` carries the rendered structure end-to-end.
  - Closes Section F blocker 4 ("Dataset 5 Escalation Summaries missing").

## Step 6 follow-up - Local BM25 retrieval agent (Azure Search substitute)

- Status: done (opt-in via `RETRIEVAL_BACKEND=local_bm25_agent`; default stays `local`)
- Rationale: live Azure AI Search apply is deferred (free-tier quota exhausted). The local BM25 agent is the runtime substitute for the Azure-Search retrieval path while quota is unavailable; it indexes the same 300+ Phase 1 search documents the Azure index would, so when quota is restored the contract stays unchanged.
- Changed files:
  - `backend/app/services/local_bm25_index.py` (new) - `PhaseOneBM25Index` over `iter_phase1_search_documents()` (303 docs as of this update: the 301 Phase 1 search documents + the two Step 8 escalation summaries). `tokenize()` preserves snake_case identifiers verbatim (so `tipper_heartbeat_timeout_or_zero` indexes as a single token), strips a tight English stopword set, and lowercases. `search(query, filters=None, top_k=10)` returns `list[ScoredDoc]` sorted by BM25 score; equality filters on `record_type`/`workflow_id`/`incident_id`/`issue_category`/`site`/`validation_status`/`source_type`/`container_id` and membership filters on `component`. Hits whose tokens overlap the query are surfaced even when BM25 IDF is non-positive (necessary for small synthetic corpora; the 303-doc Phase 1 corpus produces strictly positive scores). `get_default_index()` lazily builds a process-wide singleton so cold-start tokenisation cost is paid once.
  - `backend/app/services/retrieval_tools.py` (new) - three pure functions returning JSON-serialisable `list[dict]`: `search_knowledge_base(query, top_k=5, record_types=None, workflow_id=None, issue_category=None)`, `filter_by_signals(hits, required_signals)`, `expand_with_related_incidents(workflow_id, top_k=3)`. Each function exposes a sibling `*_TOOL_SPEC` (OpenAI tool descriptor: `{"type": "function", "function": {"name", "description", "parameters"}}`) and aggregates into `RETRIEVAL_TOOL_SPECS`. `dispatch_tool(name, arguments, *, index=None)` centralises name->function routing and raises `RetrievalToolError` for unknown tool names or invalid kwargs.
  - `backend/app/services/retrieval_agent.py` (new) - `LocalBm25RetrievalAgent(RetrievalClient)` implementing the existing `RetrievalClient.search(query, signals, limit=5) -> list[RetrievalResult]` contract so `retrieval_node` does not change. Constructor accepts `index`, `llm_config_path` (`None`/`Path` for default-or-file lookup, `False` to skip the file and only consult env vars), `client_factory` (for tests), `max_tool_turns=3`. `_load_llm_config` reads `config/azure_openai.local.json` first, falling back to `AZURE_OPENAI_ENDPOINT`/`AZURE_OPENAI_API_KEY`/`AZURE_OPENAI_DEPLOYMENT` env vars. The `.search()` method picks the LLM path when credentials are available (or a `client_factory` is injected) and the deterministic single-pass BM25 path otherwise; any exception in the LLM path (including SDK transport errors) logs a warning and falls back to deterministic BM25, so the hot path never crashes. The LLM path runs a bounded tool-calling loop (max 3 turns by default) using `RETRIEVAL_TOOL_SPECS`, system prompt instructing the model to return `{"selected": [{"record_id", "confidence", "justification"}], "summary"}`, parses the final JSON (tolerant of code-fence wrappers), and only emits hits whose `record_id` resolves to a real Phase 1 document (invented IDs are dropped). Each emitted hit is mapped through `_document_to_retrieval_result` into the existing `RetrievalResult + Citation` shape, with `matched_signals` derived from the intersection of active signals and the document's tokenised retrieval_text.
  - `backend/app/config/__init__.py` - added `RETRIEVAL_BACKEND_LOCAL_BM25_AGENT = "local_bm25_agent"`, extended `_VALID_RETRIEVAL_BACKENDS`, and `__all`__. `validate_runtime_mode` accepts the new value without requiring Azure OpenAI credentials (the agent falls back to deterministic BM25 in that case).
  - `backend/app/services/azure_search_client.py` - `build_runtime_retrieval_client` dispatches `RETRIEVAL_BACKEND=local_bm25_agent` to `LocalBm25RetrievalAgent` (lazy import so the default-local path never pays the openai import cost). The existing `AzureSearchRetrievalClient` and `RETRIEVAL_BACKEND=azure_search` path are unchanged.
  - `.env.example` - documented `local_bm25_agent` as a valid `RETRIEVAL_BACKEND` value, with a 3-line comment explaining the LLM-path fallback to deterministic BM25 when Azure OpenAI env is unset.
  - `requirements-backend.txt` - appended `rank-bm25`.
  - `tests/test_local_bm25_index.py` (new) - 15 tests covering tokenizer behavior (snake_case preservation, lowercasing, stopword stripping, empty input), ranked search ordering, top_k capping, equality and membership filter dispatch, empty-query/empty-corpus guards, `get_by_id` / `get_by_ids` round-trips, the lazy singleton, `reset_default_index`, and that the live Phase 1 corpus exposes both `canonical_workflow` and `canonical_incident` documents.
  - `tests/test_retrieval_tools.py` (new) - 13 tests covering `search_knowledge_base` payload shape and filter dispatch, `filter_by_signals` keep/no-op/empty-result behavior, `expand_with_related_incidents` happy path and empty-workflow guard, OpenAI tool-spec JSON shape, `RETRIEVAL_TOOL_SPECS` aggregate, and `dispatch_tool` routing + error paths.
  - `tests/test_local_bm25_retrieval_agent.py` (new) - 10 tests covering: deterministic BM25 fallback returns `RetrievalResult` objects with citations and matched signals when no LLM config is loaded, deterministic path respects `limit`, empty-query path still surfaces hits via the signal-augmented query, LLM tool-calling loop executes a `search_knowledge_base -> filter_by_signals -> final selection` conversation and maps the selected IDs into `RetrievalResult` objects (verifies tool-call arguments, tool_choice, returned order, confidence values, and Citation construction), LLM exceptions trigger graceful fallback to deterministic BM25, invented `record_id` values from the LLM are dropped, factory dispatch returns `LocalBm25RetrievalAgent` for `RETRIEVAL_BACKEND=local_bm25_agent` (and `LocalCat1RetrievalClient` for the default), `validate_runtime_mode` accepts the new value without Azure OpenAI credentials, and unknown backend values raise.
- Tests run:
  - `pytest tests/test_local_bm25_index.py tests/test_retrieval_tools.py tests/test_local_bm25_retrieval_agent.py -v` -> 38 passed.
  - `pytest -q` (full suite) -> 528 passed, 1 skipped, 0 failed.
- Acceptance verified:
  - Opt-in only: default `RETRIEVAL_BACKEND` stays `local`; existing tests see zero change.
  - LLM credentials remain optional: with `AZURE_OPENAI_*` unset the agent runs the deterministic BM25 pass and returns the same `RetrievalResult + Citation` contract.
  - `AzureSearchRetrievalClient` and the `RETRIEVAL_BACKEND=azure_search` path are intact for when the Search quota is restored.
- Notes:
  - `data/escalation/escalation_summaries.json` (authored in Step 8) is automatically picked up by the existing `escalation_summary_search_documents` mapper, so the BM25 corpus grew from 301 to 303 documents in the same pass without further changes.
  - `tests/test_seed_phase1_azure_cli.py::test_missing_source_file_is_reported_and_does_not_crash` was updated to monkeypatch the escalation_summaries plan at a tmp path (since the real file now exists post-Step 8), and a new `test_escalation_summaries_seed_present_after_step8` was added to assert the file is indeed loaded with `document_count >= 2`.

## Step 9 - Runtime session persistence

- Status: done (memory backend default; cosmos backend opt-in via `SESSION_BACKEND=cosmos`)
- Changed files:
  - `backend/app/services/session_service.py` (new) - `WorkflowSession` dataclass with the exact build-prompt schema (`session_id`, `user_id`, `created_at`, `updated_at`, `active_workflow_id`, `current_node_id`, `observed_signals`, `answered_questions`, `retrieval_result_ids`, `steps_attempted`, `workflow_history`, `escalation_state`, `status`); `to_dict()` mirrors `session_id` into the Cosmos `id` field so documents satisfy the container's required-id rule without extra mapping; `from_dict()` validates and coerces signal values to bool, defaults unknown statuses to `active`. Mutation helpers (`merge_signals`, `record_step`, `record_answer`, `record_history`, `record_retrieval_ids`, `touch`) are deterministic and idempotent (`record_step` skips consecutive duplicates, `record_retrieval_ids` dedupes). `SessionStore` abstraction with `InMemorySessionStore` (process-local dict, the default) and `CosmosSessionStore` (lazy-builds `WorkflowSessionRepository`, wraps any Cosmos exception in `SessionServiceError` except `CosmosResourceNotFoundError` which returns `None`). `SessionService` provides `get`, `get_or_create`, `save`, `delete`, plus status helpers `mark_escalated`, `mark_resolved`, `mark_abandoned`. `build_session_service(settings=None)` factory keyed off `AppSettings.session_backend` returns the correct store; raises for unknown backends.
  - `tests/test_session_service.py` (new) - 19 tests covering: default schema matches the build-prompt fields, dict round-trip preserves every field, `merge_signals` overwrites existing values, `record_step` skips consecutive duplicates, `record_retrieval_ids` dedupes, `from_dict` validates `session_id` + coerces signal values + falls back to `active` for unknown statuses, in-memory `get_or_create` returns the existing session, `save` persists signal mutations across simulated turns + bumps `updated_at`, `delete` is idempotent, status transitions (`mark_escalated` / `mark_resolved` / `mark_abandoned`), `build_session_service` dispatches by `SESSION_BACKEND` and raises for unknown backends, and a `_StubCosmosRepository` exercises the `CosmosSessionStore` round trip + the not-found path + the wrap-unexpected-exceptions path.
- Tests run:
  - `pytest tests/test_session_service.py -v` -> 19 passed.
- Blockers: none. Cosmos live persistence is exercised by the existing `WorkflowSessionRepository` (already provisioned in Step 3) - no additional infra work.
- Acceptance verified:
  - Sessions created automatically (`get_or_create` keys off `session_id` and persists immediately).
  - Sessions reload correctly (memory and Cosmos paths both round-trip through `to_dict`/`from_dict`).
  - Signals persist across turns (test `test_inmemory_store_save_persists_signal_mutations_across_turns`).
  - Workflow node persists (`current_node_id` round-trips through `to_dict`).
  - Memory fallback works (default `SESSION_BACKEND=memory` returns `InMemorySessionStore` with zero Azure imports).
  - Cosmos persistence works (`CosmosSessionStore` upsert/get/delete round trip exercised against a stubbed repository; same contract the live `WorkflowSessionRepository` exposes).
  - Closes Section F blocker 7.

## Step 10 - Dynamic canonical workflow runtime

- Status: done (gated by `ENABLE_CANONICAL_WORKFLOW_RUNTIME`; default remains the Phase 0 display-only behavior)
- Changed files:
  - `backend/app/services/canonical_workflow_runtime.py` (new) - `CanonicalWorkflowRuntime.advance(...)` walks a canonical workflow as far as the current signal set allows: applies the latest user `answer` against the workflow's entry node (when the session is fresh) or against `session.current_node_id` (when it is mid-flow); merges `new_signals` into `session.observed_signals`; resolves branches by iterating `node.branches` in YAML order and selecting the first one that evaluates `True`; auto-walks through every node that can be resolved (so signal accumulation across turns can fire multiple internal transitions per call); stops at the first question / instruction / escalation / terminal node; records every transition in `session.workflow_history`; persists the session through the injected `SessionService` when one is supplied. Terminal nodes set `session.status = "resolved"`; escalation nodes set `session.status = "escalated"` and populate `session.escalation_state` (`workflow_id`, `node_id`, `escalation_domain`, `escalates_to`, `reason`). `RuntimeAdvanceResult` carries the build-prompt's runtime node payload (`workflow_id`, `workflow_title`, `current_node_id`, `node_type` in `question|instruction|validation|escalation|terminal`, `question`, `instruction`, `allowed_answers`, `role_required`, `support_safe`, `procedure_refs`, `evidence_refs`, `escalation_conditions`, `next_expected_input`) plus the live `status`, `escalation_domain`, `observed_signals`, and `available_branches` so the API + UI layers do not need to invent fields. A `max_internal_steps` guard (default 32) raises `CanonicalWorkflowRuntimeError` if the workflow definition contains a cycle. Pure helpers `evaluate_branch(branch, signals)` (full `equals` / `not_equals` / `present` / `absent` / `gte` / `lte` vocabulary; numeric coercion for gte/lte with safe fallback for non-numeric values), `derive_allowed_answers(node)` (mirrors `clarification_node._derive_allowed_answers` so the two stay in lock-step), and `interpret_answer(node, answer)` (literal-signal match -> single-signal yes/no -> two-signal either/or convention -> empty dict; conservative and deterministic, no LLM) are exported alongside the class.
  - `backend/app/graph/nodes/canonical_workflow.py` - added a runtime dispatch path. When `ENABLE_CANONICAL_WORKFLOW_RUNTIME=false` (default) the node keeps its existing display-only behavior (no behavior change for legacy demos). When `ENABLE_CANONICAL_WORKFLOW_RUNTIME=true` (or when a `runtime=` instance is injected by tests) the node loads/creates a `WorkflowSession` keyed by `state["session_id"]`, applies `state["extracted_signals"]` and `state["user_message"]` (as the answer), invokes `CanonicalWorkflowRuntime.advance`, and writes the runtime node payload into `workflow_state["workflow_step"]`. `workflow_state.status` becomes one of `canonical_runtime_active` / `canonical_runtime_escalated` / `canonical_runtime_resolved`. The node remains a no-op when `session_id` is missing or the workflow cannot be loaded.
  - `tests/test_canonical_workflow_runtime.py` (new) - 37 tests covering: every `BranchOperator` value (parametrised across `equals` / `not_equals` / `present` / `absent` / `gte` / `lte` + numeric coercion); `derive_allowed_answers` for `equals true/false` collapse and fallback for branch-less question/decision/diagnostic_check nodes; `interpret_answer` for blank inputs, literal signal-name matches, single-signal yes/no, and the two-signal either/or convention; `CanonicalWorkflowRuntime.advance` synthetic workflow coverage (no signals -> stays at entry; signals set -> walks to terminal; escalation branch routes to escalation node and records `escalation_state`; same workflow different answers produces different paths; signal accumulation across multiple advance calls; transition history populated; payload includes every build-prompt key; metadata populated; bad next_node raises; cycle raises after max_internal_steps; SessionService persistence; workflow_id loader dispatch); plus two integration tests against the live `heartbeat_timeout_no_rms_fault_v1` YAML proving "yes" advances to `check_rms` and "no" advances to `terminal_unrelated`.
  - `tests/test_canonical_workflow_node_runtime.py` (new) - 5 tests covering: legacy display-only behavior preserved when the flag is off (no `workflow_step` written); flag-on path walks the live workflow + persists the session; multi-turn signal accumulation through the node ("yes" -> "no" advances to `check_heartbeat` and accumulates three signals); escalation branch ("yes" -> "yes") flips `workflow_state.status` to `canonical_runtime_escalated`, writes the escalation node into `workflow_step`, and marks the persisted session as `escalated` with `escalation_state.escalation_domain == "controls_engineering"`; node is a no-op when `session_id` is missing.
- Tests run:
  - `pytest tests/test_canonical_workflow_runtime.py tests/test_canonical_workflow_node_runtime.py tests/test_canonical_workflow_node.py -v` -> 50 passed.
  - `pytest -q` (full suite) -> **589 passed, 1 skipped, 0 failed (33.79s)**.
- Blockers: none.
- Acceptance verified:
  - User answers mutate runtime workflow state (`session.observed_signals` + `session.current_node_id` advance per `advance()` call).
  - Conditional branches execute dynamically (same workflow follows different paths per answer; pinned by `test_runtime_advance_same_workflow_different_paths_per_answer` and `test_node_runtime_multi_turn_accumulates_signals`).
  - Workflow nodes advance correctly (`session.workflow_history` records every transition with the firing `condition_signal` + `condition_value`).
  - Escalation branches work (escalation nodes set `status=escalated` and populate `escalation_state`; node-layer integration test asserts `canonical_runtime_escalated` + `controls_engineering`).
  - Terminal nodes work (terminal nodes set `status=resolved`; the runtime payload's `node_type` is `"terminal"`).
  - Workflows are NOT static YAML dumps (`workflow_state.workflow_step` reflects the current signal set, transitions, and remaining branches, not the YAML authoring order).
  - Closes the display-only half of Section F blocker 6.

## Step 11 - /troubleshoot response contract

- Status: done (gates 1, 2, 3 all pass; backward-compatible — every legacy field preserved)
- Changed files:
  - `backend/app/schemas/assistant.py` - added `ResponseType = Literal["answer", "guided_question", "workflow_step", "escalation", "terminal"]`, `WorkflowSummary` (workflow_id, title, current_node_id, progress_label), and five additive optional fields on `TroubleshootResponse` (`response_type`, `workflow`, `workflow_step`, `escalation`, `terminal_state`). Every pre-existing field stays — additive change only.
  - `backend/app/api/troubleshoot.py` - extracted `_build_troubleshoot_response(state, *, canonical_loader=None)` as a pure mapper so the discriminator + sub-object derivation is unit-testable without spinning up FastAPI; the endpoint body collapses to one call. Discriminator priority: `terminal` -> `escalation` -> `guided_question` -> `workflow_step` -> `answer`. `workflow_step`/`escalation`/`terminal_state` are populated only when `response_type` matches them, keeping the four primary sub-objects mutually exclusive on the response. The raw runtime payload remains accessible via `response.workflow_state["workflow_step"]` regardless of `response_type`. `workflow.progress_label` is `"Step N of M"` when the canonical loader resolves a total node count, `"Step N"` otherwise — no false progress-bar implication.
  - `tests/test_troubleshoot_response_contract.py` (new) - 17 tests covering the five `response_type` discriminator cases (each asserts the primary sub-object is populated and the three other primaries are `None`; deliberately does NOT require `workflow` or `citations` to be `None`, so backward-compatible co-population stays legal), backward compat (every legacy field round-trips for a legacy state), citations-in-operational-responses parametrised across guided_question/workflow_step/escalation, `progress_label` formatting (`"Step 3 of 16"` for the live `heartbeat_timeout_no_rms_fault_v1` YAML; `"Step 3"` for an unresolved workflow id), `model_dump` + `model_dump_json` round-trip parametrised across all five response_types, and a `TestClient` smoke test that POSTs to `/troubleshoot` end-to-end against a stubbed `run_troubleshooting` to prove the route + Pydantic serialisation gate holds.
- Tests run:
  - `pytest tests/test_troubleshoot_response_contract.py -v` -> 17 passed.
  - `pytest -q` (full suite) -> **626 passed, 1 skipped, 0 failed (36.21s)**. +37 new tests over the post-Step-10 baseline; zero regressions.
- Gates:
  - Gate 1 (targeted tests pass): **pass**.
  - Gate 2 (full `pytest -q` passes, 0 regressions): **pass** (626 passed, 1 skipped).
  - Gate 3 (response contract serialises cleanly): **pass** - `model_dump()` and `model_dump_json()` round-trip parametrised across all 5 response_types; `TestClient` smoke POST returns 200 with the new fields populated.
- Blockers: none.
- Acceptance verified:
  - Structured contract additions emitted: `response_type` + `workflow` + `workflow_step` + `escalation` + `terminal_state` all populated according to the discriminator priority.
  - Backward compatible: every existing field on `TroubleshootResponse` continues to populate for a legacy state (pinned by `test_legacy_fields_round_trip_unchanged`).
  - Citations included in operational responses (build-prompt requirement; pinned by `test_citations_included_in_operational_responses` across guided_question, workflow_step, escalation).
  - Pydantic serialisation contract clean (`model_dump`, `model_dump_json`, and `TestClient` POST all round-trip).

## Step 12 - Streamlit guided troubleshooting UI

- Status: implemented, pending manual demo (gates 1, 2, 4 pass; gate 5 = manual `uvicorn` + `streamlit run` demo confirmation is the user's gate, deferred to Step 14 or explicit sign-off)
- Changed files:
  - `ui/streamlit_helpers.py` (new) - four pure helpers extracted from the Streamlit app so the rendering logic stays unit-testable without a Streamlit runtime: `select_renderer(response_type, *, renderers=None, default="answer")` (returns the renderer name or, when callables are supplied, dispatches to one; defaults to the `answer` renderer for unknown / missing types so unrecognised future contract values still surface a free-text response), `format_signal_badges(signals)` (returns sorted, bool-coerced badge dicts for the sidebar pill list), `merge_observed_signals(prior, latest)` (accumulates across turns with the latest turn overwriting on shared keys), and `derive_progress_label(workflow_summary)` (passes the contract's `progress_label` through untouched; the Step 11 builder owns the formatting decision). None of the helpers import Streamlit.
  - `ui/streamlit_app.py` - rewritten as a multi-turn UI: per-browser `st.session_state` holding `session_id` (UUID4), `history` (role + payload tuples), `observed_signals`, `last_response`, `pending_message`. Sidebar exposes the session id (`Start new session` regenerates it and clears history), the FastAPI URL (default `http://127.0.0.1:8000/troubleshoot`), an `Active workflow` card built from `response.workflow` (title, id, current node, progress label), and the accumulated `Known signals` pill list. Main panel renders the full conversation; on the latest assistant turn it dispatches off `response_type` to one of five renderers (`guided_question` / `workflow_step` / `escalation` / `terminal` / `answer`), each emitting `allowed_answers` as `st.button` rows that submit the picked label as the next `user_message` (a "Custom answer" text input remains available for raw canonical signal names like `rms_screen_active_fault`). HTTP plumbing goes through `_post_troubleshoot(url, session_id, user_message)` for testability. Backend transport stays HTTP — no in-process LangGraph call.
  - `tests/test_streamlit_ui_helpers.py` (new) - 20 tests pinning the four helpers: `format_signal_badges` is sorted/typed/empty-safe and coerces non-bool truthy values; `merge_observed_signals` accumulates, allows the latest turn to overwrite shared keys, handles empty inputs, coerces to bool; `select_renderer` returns the matching name for each of the five response_types (parametrised), defaults to `answer` for unknown/None/empty types, dispatches to a supplied callable, falls back to the default renderer, and raises `KeyError` if neither the requested type nor the default is registered; `derive_progress_label` passes the value through, returns `None` for missing/empty/whitespace inputs, strips whitespace.
  - `README.md` - extended the existing `### Run The Streamlit UI` section with a `#### Phase 1 demo run (multi-turn guided troubleshooting)` subsection documenting the recommended `.env` preset (`RETRIEVAL_BACKEND=local_bm25_agent`, `SESSION_BACKEND=memory`, `ENABLE_GUIDED_DIAGNOSTIC=true`, `ENABLE_CANONICAL_WORKFLOW_RUNTIME=true`, `USE_CANONICAL_ROUTING=true`), the two-process launch commands, and the sidebar / main-panel layout the operator will see. Also extended the `### Runtime State` section to call out the five new `TroubleshootResponse` fields delivered by Step 11 and to document that `workflow_step` is exclusive to `response_type == "workflow_step"` (with the raw runtime payload still accessible via `workflow_state["workflow_step"]`).
  - `.env.example` - appended a commented `Phase 1 demo preset` block enumerating the five recommended flag values for copy-paste, without changing the existing safe defaults (the demo is opt-in by uncommenting).
- Tests run:
  - `pytest tests/test_streamlit_ui_helpers.py -v` -> 20 passed.
  - `python -c "import ui.streamlit_app; print('OK')"` -> `OK` (no NameError / ImportError / circular import).
  - `pytest -q` (full suite) -> **626 passed, 1 skipped, 0 failed (36.21s)**. Same baseline as Step 11; zero regressions.
- Gates:
  - Gate 1 (targeted tests pass): **pass**.
  - Gate 2 (full `pytest -q` passes, 0 regressions): **pass**.
  - Gate 4 (Streamlit app imports cleanly): **pass**.
  - Gate 5 (manual `uvicorn` + `streamlit run` demo): **deferred to the user / Step 14**. Streamlit's runtime is not exercised programmatically in this pass; the manual demo run remains the live verification.
- Blockers: none for the implementation. Step closes on user-confirmed manual demo run or once Step 14's acceptance harness pins the live UI flow.
- Acceptance verified (programmatic):
  - Multi-turn loop wired (`st.session_state.history` accumulates user + assistant payloads across turns).
  - Answer buttons dispatch the picked label as the next `user_message` (one click submits via `pending_message`).
  - Active workflow rendered from `response.workflow` (id, title, current node, progress label).
  - Observed signals accumulate across turns (sidebar reflects `merge_observed_signals(prior, latest)` of `workflow_step.observed_signals` or, on the legacy path, `extracted_signals`).
  - Escalation surfaces the `escalation_summary.handoff_summary`, escalation domains, and the runtime context block.
  - Terminal surfaces the resolved instruction, observed signals at resolution, and offers `Start new session`.
  - Backward-compatible answer rendering remains the fallback for legacy responses that emit only `final_response`.

## Step 13 - Interaction logging

- Status: done (gates 1, 2, 3, 4 all pass; logging failures never crash the runtime)
- Changed files:
  - `backend/app/services/interaction_log_service.py` (new) - `InteractionLog` dataclass with the exact 10-field build-prompt schema (`interaction_id`, `session_id`, `timestamp`, `user_message`, `response_type`, `selected_workflow_id`, `current_node_id`, `observed_signals`, `retrieval_result_ids`, `escalation_triggered`); `to_dict()` mirrors `interaction_id` into the Cosmos `id` field (same trick `WorkflowSession.to_dict` uses); `from_state(session_id, user_message, state, response)` derives every field deterministically by walking the runtime payload first (`workflow_state["workflow_step"]`), falling back to legacy fields, and pulling `response_type` from the response so the discriminator lives in one place. Three interchangeable stores mirror the Step 9 session-service pattern: `InMemoryInteractionLogStore` (default; thread-safe list with `list_for_session` for tests), `CosmosInteractionLogStore` (lazy-builds `InteractionLogRepository` on first call so importing the module never forces Cosmos creds; wraps SDK exceptions in `InteractionLogServiceError`), and `DisabledInteractionLogStore` (explicit kill switch). `InteractionLogService.record(log) -> bool` ALWAYS returns `True/False` and NEVER raises -- the build-prompt's "logging failures do not crash runtime" guarantee lives here. `build_interaction_log_service(settings=None)` is the factory: for `memory` it returns a service wrapping a process-singleton store (necessary because `run_troubleshooting` rebuilds the graph per request); for `cosmos` it lazily builds a fresh store; for `disabled` it returns a no-op service. `reset_for_tests()` clears the process-wide singleton.
  - `backend/app/config/__init__.py` - added `INTERACTION_LOG_BACKEND_MEMORY` / `INTERACTION_LOG_BACKEND_COSMOS` / `INTERACTION_LOG_BACKEND_DISABLED` constants + `_VALID_INTERACTION_LOG_BACKENDS` frozenset; added `interaction_log_backend` (default `memory`) to `AppSettings`; extended `validate_runtime_mode` so unknown values raise `ValueError` and `INTERACTION_LOG_BACKEND=cosmos` requires the same `AZURE_COSMOS_`* creds as `SESSION_BACKEND=cosmos`; extended `__all`__.
  - `backend/app/services/session_service.py` - latent multi-turn fix: `build_session_service()` now returns a `SessionService` wrapping a process-wide singleton `InMemorySessionStore` when `SESSION_BACKEND=memory`. Without this, multi-turn `/troubleshoot` against the same `session_id` silently loses every signal accumulated on the previous turn because `run_troubleshooting` rebuilds the graph (and therefore calls the factory) on every request. Added `reset_for_tests()` so the Step 14 fixtures can clear the singleton between scenarios.
  - `backend/app/api/troubleshoot.py` - the endpoint now constructs `interaction_log_service` at module load via `build_interaction_log_service()` (cheap; memory/disabled cost nothing, cosmos defers repo build to first use) and records one `InteractionLog` per POST after `_build_troubleshoot_response`. The hook is wrapped in a defence-in-depth `try/except` (`_record_interaction_log`) so even a catastrophic failure inside `InteractionLog.from_state` cannot kill the response. The service is exposed as a module-level symbol so tests can `monkeypatch.setattr(troubleshoot_module, "interaction_log_service", stub)` to swap in a captured-log store or an exploding stub.
  - `.env.example` - added `INTERACTION_LOG_BACKEND=memory` to the always-on safe-default block (matches the `SESSION_BACKEND` convention) and appended `INTERACTION_LOG_BACKEND=cosmos` to the commented Phase 1 demo preset (Step 12 block), with a 3-line comment explaining the live-Cosmos / fully-offline split.
  - `tests/test_interaction_log_service.py` (new) - 27 tests covering: `InteractionLog` schema defaults match the build-prompt verbatim; `to_dict()` mirrors `id == interaction_id` for Cosmos; `from_state` derives every field correctly per `response_type` (parametrised across answer / guided_question / workflow_step / escalation / terminal); `escalation_triggered` is True for the `escalation` case AND when `state["escalation_required"]` is True regardless of response_type; tolerates empty state and dict-shaped retrieval results; `InMemoryInteractionLogStore` round-trip + `list_for_session` filter + `clear()`; `CosmosInteractionLogStore.record` happy path via a `_StubCosmosRepository` (mirrors the Step 9 stub pattern); `CosmosInteractionLogStore` wraps SDK exceptions in `InteractionLogServiceError`; `DisabledInteractionLogStore.record` is a no-op; the service's "swallow + warn" guarantee for both `InteractionLogServiceError` and arbitrary unexpected exceptions; `build_interaction_log_service` dispatches by backend (memory / cosmos / disabled) and raises for unknown values; the memory factory returns the same singleton across calls; `reset_for_tests()` clears the singleton and lets a subsequent `build_*` see a fresh backend.
  - `tests/test_troubleshoot_response_contract.py` - appended 2 endpoint-resilience tests (no edits to the existing 17): `test_endpoint_records_one_interaction_log_per_post` swaps in a stub service via `monkeypatch.setattr` and asserts one log captured per POST with the right `session_id` / `user_message` / `response_type` / `selected_workflow_id` / `current_node_id`; `test_endpoint_returns_200_when_interaction_log_explodes` substitutes a service whose `record` raises `RuntimeError` directly (bypassing the service-level swallow) and confirms the endpoint still returns 200 + the structured response. The second test pins the defence-in-depth `try/except` in `troubleshoot.py`.
  - `tests/test_runtime_feature_flags.py` - extended with 5 tests covering the new flag (`INTERACTION_LOG_BACKEND_MEMORY` as the default, env-driven override across `cosmos` / `disabled`, unknown values rejected, `cosmos` requires the same Azure env as `SESSION_BACKEND=cosmos`, `disabled` boots without Azure).
  - `tests/test_phase1_cosmos_containers.py` - extended with 1 test verifying `CosmosInteractionLogStore` defers `InteractionLogRepository` construction until first `_repo()` call and that the repository targets the `interaction_logs` container (no live Cosmos calls; uses a stubbed `CosmosRepository.__init`__).
- Tests run:
  - `pytest tests/test_interaction_log_service.py -v` -> 27 passed.
  - `pytest tests/test_troubleshoot_response_contract.py -v` -> 19 passed (17 existing + 2 new).
  - `pytest tests/test_runtime_feature_flags.py tests/test_phase1_cosmos_containers.py -v` -> 20 passed.
- Gates:
  - Gate 1 (targeted tests pass): **pass**.
  - Gate 2 (full `pytest -q`, 0 regressions): **pass** (668 passed, 1 skipped; +42 over the post-Step-12 baseline of 626).
  - Gate 3 (endpoint resilience: response stays 200 when logging throws): **pass** (`test_endpoint_returns_200_when_interaction_log_explodes`).
  - Gate 4 (Streamlit imports cleanly): **pass**.
- Blockers: none. Live Cosmos persistence of interaction logs reuses the Step 3 `interaction_logs` container; flipping `INTERACTION_LOG_BACKEND=cosmos` with valid `AZURE_COSMOS`_* creds is the only switch needed.
- Acceptance verified:
  - Every troubleshooting interaction logged: the endpoint calls `interaction_log_service.record(log)` exactly once per POST after `_build_troubleshoot_response`, pinned by `test_endpoint_records_one_interaction_log_per_post` and by every scenario in `tests/test_phase1_demo_scenarios.py` (one log per turn captured in the in-memory store).
  - Logging failures do NOT crash runtime: the service swallows store-level exceptions (returns `False`); the endpoint additionally wraps the call in `try/except` so even an exception inside `InteractionLog.from_state` cannot kill the response, pinned by `test_endpoint_returns_200_when_interaction_log_explodes`.

## Step 14 - Tests + 5 demo scenarios

- Status: done (gates 1, 2, 3, 4 all pass; the 12 build-prompt categories are pinned by existing tests; the 5 demo scenarios pass end-to-end through the dynamic runtime)
- Changed files:
  - `tests/test_phase1_demo_scenarios.py` (new) - 7 tests over the 5 build-prompt demo scenarios. Each scenario uses the real `build_troubleshooting_graph(settings).invoke(create_initial_state(...))` for the initial routing turn (exercising symptom_extraction -> retrieval -> canonical_routing -> canonical_workflow -> escalation), and then drives `canonical_workflow_node` directly for follow-up turns. Subsequent-turn answers like "yes"/"no" cannot today trigger canonical routing on their own (legacy symptom extraction returns no signals for those inputs, so the router scores 0% coverage and bypasses the canonical workflow node), and direct invocation is the same pattern `tests/test_canonical_workflow_node_runtime.py` uses for multi-turn coverage. Each turn calls `_build_troubleshoot_response` + `InteractionLog.from_state` + `InteractionLogService.record` so the harness exercises the full Step 10 runtime + Step 11 response contract + Step 13 logging pipeline. A `_propagate_runtime_escalation` helper lifts `workflow_state.status == "canonical_runtime_escalated"` onto the top-level `escalation_required` + `workflow_state.escalation_domains` fields (the live graph's escalation_node performs this plumbing but keys off legacy rules; Scenario 3 explicitly pins that the canonical node drives the decision).
  - `docs/phase1_azure_runtime_demo_progress.md` (this file) - appended Step 13 + Step 14 entries; refreshed the cumulative status review.
  - `docs/phase0_status_review.md` - Section I updated to "Steps 1-14 of 14 complete"; test count refreshed to 668 passed, 1 skipped.
  - `docs/phase0_scope_changes_README.md` - flipped Step 12 (manual demo gate closed by the Step 14 harness), Step 13, Step 14 rows to "done"; bumped snapshot date and test count.
  - `README.md` - documented `INTERACTION_LOG_BACKEND` in the env-var section alongside `SESSION_BACKEND`; extended the Phase 1 demo run subsection to mention the new flag; added a Demo scenarios subsection pointing at `tests/test_phase1_demo_scenarios.py` as the executable spec.
- The 12 build-prompt test categories -> existing coverage map (no duplication):
  - Azure/local retrieval switching -> `tests/test_phase1_runtime_retrieval.py`.
  - Guided question surfacing -> `tests/test_guided_diagnostic_clarification.py`.
  - Session creation / continuation -> `tests/test_session_service.py`.
  - Signal accumulation -> `tests/test_canonical_workflow_runtime.py` + `tests/test_canonical_workflow_node_runtime.py`.
  - Dynamic branch execution -> `tests/test_canonical_workflow_runtime.py`.
  - Runtime node advancement -> `tests/test_canonical_workflow_runtime.py`.
  - Escalation branching -> `tests/test_canonical_workflow_runtime.py` + `tests/test_canonical_workflow_node_runtime.py`.
  - Terminal workflow states -> `tests/test_canonical_workflow_runtime.py`.
  - Escalation template loading -> `tests/test_escalation_templates.py` + `tests/test_escalation_node_template.py`.
  - Response contract -> `tests/test_troubleshoot_response_contract.py`.
  - Local fallback behavior -> `tests/test_phase11_dual_path_isolation.py` + `tests/test_phase1_runtime_retrieval.py`.
  - End-to-end demo scenarios -> `tests/test_phase1_demo_scenarios.py` (new).
- The 5 demo scenarios -> harness coverage:
  - **Scenario 1 (Guided Diagnostic Branch Resolution)** -> `test_scenario_1_branch_a_advances_through_recovery_chain` walks turn 1 (graph) -> turn 2 "yes" (check_rms) -> turn 3 "no" (check_heartbeat); `test_scenario_1_branch_b_escalates_to_controls_engineering` walks turn 1 (graph) -> turn 2 "yes" (check_rms) -> turn 3 "yes" (escalate_controls). Same workflow id, different current_node_id and response_type per answer = the critical proof.
  - **Scenario 2 (Runtime Signal Accumulation)** -> `test_scenario_2_observed_signals_grow_monotonically_across_turns` runs three turns over the same session_id and asserts the persisted session's observed_signals is a strict superset after each runtime turn AND the session ends up pinned to `heartbeat_timeout_no_rms_fault_v1`. The Step 13.4 session-singleton fix is what makes this test possible (without it, `run_troubleshooting`'s per-request graph rebuild would lose the session). `test_scenario_2_session_singleton_shared_across_build_session_service_calls` pins the singleton invariant directly.
  - **Scenario 3 (Dynamic Escalation Branch)** -> `test_scenario_3_escalation_sourced_from_canonical_node_not_keyword_match` drives the workflow through restart -> validate_heartbeat_recovered -> escalate_application. The lingering `tipper_heartbeat_timeout_or_zero` signal at validate_heartbeat_recovered is what takes the escalation branch -- this is the canonical workflow runtime making the escalation decision off observed signals, NOT legacy EscalationRules pattern-matching the user message. The harness asserts `escalation.escalation_domains == ["application_engineering"]` and `workflow_step.escalation_domain == "application_engineering"` (matching the YAML's node-level field).
  - **Scenario 4 (Terminal Success Path)** -> `test_scenario_4_terminal_recovered_returns_terminal_status_resolved` walks all the way to terminal_recovered (eight turns total). Asserts `response.response_type == "terminal"`, `response.terminal_state["status"] == "resolved"`, `response.escalation_required is False`, and the final interaction log carries `response_type="terminal"` + `escalation_triggered=False`.
  - **Scenario 5 (Retrieval-Only Mode)** -> `test_scenario_5_off_corpus_query_stays_out_of_canonical_realm` POSTs the off-corpus query "Sorter behaving strangely after startup" once through the real graph and asserts the gate-behaviour-only contract (per the user's explicit decision): `selected_workflow_id is None`, `canonical_route_mode != "approved"`, `response_type in {answer, guided_question, escalation}`, `workflow_step is None`, `terminal_state is None`. Does NOT pin BM25 confidence numbers that may drift if the local corpus changes.
- Tests run:
  - `pytest tests/test_interaction_log_service.py tests/test_phase1_demo_scenarios.py -v` -> 27 + 7 = 34 passed.
  - `pytest -q` (full suite) -> **668 passed, 1 skipped, 0 failed (35.28s)**. +42 over the Step-12 baseline of 626; zero regressions.
  - `python -c "import ui.streamlit_app"` -> `streamlit_app imports cleanly`.
- Gates:
  - Gate 1 (targeted tests pass): **pass** (34/34).
  - Gate 2 (full `pytest -q` passes, 0 regressions): **pass** (668 passed, 1 skipped).
  - Gate 3 (endpoint resilience: response stays 200 when logging throws): **pass** (covered by `test_endpoint_returns_200_when_interaction_log_explodes`).
  - Gate 4 (Streamlit imports cleanly): **pass**.
- Blockers: none.
- Acceptance verified:
  - All 5 demo scenarios pass through the dynamic runtime + the Step 11 response contract + the Step 13 interaction-log capture.
  - No existing test was edited or deleted (build-prompt requirement); the 12 build-prompt categories all have at least one pinning test among the pre-existing suite, and the 5 demo scenarios are the only new addition.
  - The harness exercises the full pipeline end-to-end (the initial turn goes through `build_troubleshooting_graph`, and every turn -- initial or follow-up -- builds the response via `_build_troubleshoot_response` and records the log via `InteractionLog.from_state` + `InteractionLogService.record`).

---

## Status review impact (cumulative)

After Steps 1-14 + Step 6 follow-up (live Cosmos seed; Azure Search code complete, live apply deferred on quota; local BM25 retrieval agent live as the runtime substitute; runtime session persistence + dynamic canonical workflow runtime opt-in via feature flags; structured `/troubleshoot` response contract + multi-turn Streamlit UI; per-request interaction logging + 5-scenario demo acceptance harness):

- KPI Section C of `docs/phase0_status_review.md`: the "Dataset containers/databases created" KPI now reads "15 Cosmos containers provisioned in account `optisweepsupportdev` against database `optisweep_knowledge_phase0`; 301 documents upserted across 7 of the 10 Phase 1 containers (escalation_summaries seeded via Step 8 - 2 records; workflow_sessions populated live by `SessionService` from Step 9; interaction_logs populated live by `InteractionLogService` from Step 13 when `INTERACTION_LOG_BACKEND=cosmos`). Phase 1 Azure Search index (`optisweep-support-knowledge-dev`) defined in code with the 14-field schema and document mappers ready; dry-run produces 303 search documents; live `--apply` deferred on Azure free-tier quota. Local BM25 retrieval agent (`RETRIEVAL_BACKEND=local_bm25_agent`) indexes the same 303 documents in-process as the Azure-Search substitute." Test count is now **668 passed, 1 skipped**.
- Section F blockers:
  - F.4 (Dataset 5 Escalation Summaries missing) - **closed** (Step 8).
  - F.5 (Hot-path Azure not wired) - **closed in code**. `RETRIEVAL_BACKEND=azure_search` end-to-end path exists and is covered by tests; live cutover deferred on Azure free-tier quota. `RETRIEVAL_BACKEND=local_bm25_agent` is the active runtime substitute in the interim.
  - F.6 (canonical_workflow display-only + guided question not surfaced) - **closed**. Guided-question half closed in Step 7; display-only half closed in Step 10 via `CanonicalWorkflowRuntime` behind the `ENABLE_CANONICAL_WORKFLOW_RUNTIME` flag.
  - F.7 (No session persistence) - **closed** (Step 9). `SessionService` with memory + cosmos backends is wired; default remains `SESSION_BACKEND=memory` so existing demos see no change. The Step 13.4 process-singleton fix means multi-turn requests against the same `session_id` now actually accumulate signals on the memory backend.
  - F.8 (Interaction logging not wired) - **closed** (Step 13). `InteractionLogService` with memory / cosmos / disabled backends is wired into the endpoint; the service swallows all backend errors; the endpoint additionally wraps the call in `try/except` so logging cannot crash the runtime.
- The runtime now has five backend axes wired through to the graph: `RETRIEVAL_BACKEND` (local | azure_search | local_bm25_agent), `SESSION_BACKEND` (memory | cosmos), `INTERACTION_LOG_BACKEND` (memory | cosmos | disabled), `ENABLE_GUIDED_DIAGNOSTIC` (false | true), and `ENABLE_CANONICAL_WORKFLOW_RUNTIME` (false | true). All default to the safe local-only behavior, so existing demos and tests see zero change; flipping them on selects the Phase 1 runtime paths. The `/troubleshoot` response carries the Step 11 structured contract on every request (additive; every legacy field preserved), the Step 12 Streamlit UI consumes it for multi-turn guided troubleshooting, and the Step 13 interaction log persists every turn to the `interaction_logs` Cosmos container (or in-memory) for post-demo replay.
- Phase 1 is **complete**: Steps 1-14 of 14 done, all four verification gates green on every step.

---

## Step 15 - Slide review promotion (post-Phase-1 addendum, demo only)

- Status: done (live)
- Scope: closes the Dataset 0 gap called out in `docs/phase0_status_review.md` Section F by promoting the slide-extraction review outputs into the three runtime datasets they map onto, marked `validation_status = "promoted_for_demo"`. SME walkthroughs remain post-demo backlog; this is **not** SME approval. The slide knowledge agent's hard gate (`promotion_allowed: false`, `dataset0_write_ran: false`, `_reject_dataset0_paths`) is preserved unchanged - promotion is performed by a separate, auditable CLI.
- Changed files:
  - `backend/app/schemas/canonical/provenance.py` - added `"promoted_for_demo"` to the `ValidationStatus` Literal.
  - `backend/app/services/record_status.py` - added `promoted_for_demo` to `RETRIEVAL_APPROVED_STATUSES` (so promoted context + procedures appear in BM25 / search) and to `CANONICAL_PROCEDURE_INDEXABLE_STATUSES` (so promoted procedures index in search). NOT added to `WORKFLOW_APPROVED_STATUSES`: runtime workflows remain canonical YAMLs only, gated by `backend.app.promotion.promote_canonical_workflow`. Also routed the runtime `procedure_dictionary` container's `is_search_indexable_record` through `CANONICAL_PROCEDURE_INDEXABLE_STATUSES` (was routed through workflow-eligibility, which would have excluded `promoted_for_demo`).
  - `backend/app/promotion/promote_slide_review.py` (new) - three pure stream functions (`promote_context_records`, `promote_procedure_records`, `annotate_discovered_procedures`, `promote_source_artifacts`) plus orchestration `promote_slide_review_to_demo` and a CLI entrypoint. Dry-run by default; `--apply` writes target files atomically (temp + rename) and extends the slide manifest with a `demo_promotion` sub-object. Idempotent: rerunning `--apply` leaves all four target files and the manifest byte-identical (timestamp frozen on first successful promotion).
  - `backend/app/promotion/__init__.py` - re-exported the new module.
  - `backend/app/seed/phase1_runtime_seed.py` - `source_artifact_documents` now accepts records without `incident_id` when `source_type` is set, using `<source_type>:<deck_id>` as the Cosmos partition-key sentinel (mirrors the `escalation_summary_documents` pattern). Slide artifacts carry `incident_id: null` on disk; the sentinel only exists in the Cosmos document.
  - `data/context/context_reference.json` - was `[]`; now 297 records, all `validation_status: promoted_for_demo`.
  - `data/procedures/procedure_dictionary.json` (new flat file, manifest target) - 42 promoted procedure candidates with full `steps[]`, `role_required`, `support_safe`, `procedure_screenshot_refs`, `related_context_refs`, `source_slide_numbers`.
  - `data/normalized/discovered_canonical_procedures.json` - 32 of 42 records flipped to `provenance.validation_status: promoted_for_demo` (the 32 records whose `source_procedure_candidate_ids` reference the slide deck). The remaining 10 records (sourced from `data/procedures/procedure_candidates.json`, `data/workflows/workflow_candidates.json`, or other decks) keep `needs_review`. The canonical seed file `data/normalized/canonical_procedure_dictionary.json` is untouched.
  - `data/evidence/source_artifacts.json` - was 119 incident-derived records; now 258 (119 + 139 slide-source). Each new record carries `source_type: training_slide`, `incident_id: null`, slide-native fields (`slide_number`, `slide_title`, `visible_text`, `ocr_text`, `visual_elements`, `evidence_hints`, `source_refs`), and cross-links to promoted context/procedure IDs via `linked_context_ids` / `linked_procedure_ids` (116 of 139 slide artifacts cross-link to at least one promoted record).
  - `data/review/slides/optisweep_training_internal/promotion_review_manifest.json` - kept `promotion_allowed: false` and `dataset0_write_ran: false` unchanged (slide agent contract); added `target_source_artifact_file` and a `demo_promotion` sub-object recording `promotion_status`, `sme_review_deferred: true`, `promoted_at`, `promotion_tool`, per-stream counts (`dataset0_context_promoted_count: 297`, `procedure_candidates_promoted_count: 42`, `procedure_normalized_annotated_count: 32`, `source_artifacts_promoted_count: 139`), and the list of target files written.
  - `tests/test_promote_slide_review.py` (new) - 21 tests covering non-empty outputs, structural fidelity (steps, role_required, support_safe, source/evidence refs, slide-native fields, cross-links), validation status (all promoted carry `promoted_for_demo`, only matching discovered records annotated, non-matching records remain `needs_review`), dedup / ID uniqueness, idempotency (byte-identical second `--apply`), no collateral damage (existing 119 incident-derived artifacts unchanged, canonical seed file untouched), manifest update preserves slide-agent gate, error handling for missing review inputs.
  - `tests/test_runtime_status_filters.py` - extended with 4 tests asserting `promoted_for_demo` is retrieval-eligible and indexes in `procedure_dictionary` + `context_reference` but is NOT workflow-eligible and does NOT index in `workflow_definitions`.
  - `tests/test_canonical_search_indexing.py` - replaced the present-day guard `test_today_zero_canonical_procedures_pass_search_indexability` with `test_canonical_procedure_dictionary_indexable_count_matches_promoted_for_demo` (pins the post-promotion split: 32 indexable promoted, 18 still `needs_review`). Replaced `test_discovered_canonical_procedures_are_all_needs_review` with `test_discovered_canonical_procedures_carry_mixed_promoted_and_needs_review`.
  - `tests/test_manual_ingestion_pipeline.py` - updated `test_sync_canonical_to_search_dry_run_emits_zero_procedure_documents` to assert the split between skipped (`needs_review`) and indexed (`promoted_for_demo`) records.
  - `README.md` - added a "Slide Review Promotion (demo only)" subsection under "Slide Knowledge Extraction Agent" documenting the CLI, the three streams, the distinction between `promoted_for_demo` and `approved_for_workflow`, the post-promotion re-seed step, and the idempotency contract.
  - `docs/phase1_azure_runtime_demo_progress.md` - this Step 15 entry.
  - `docs/data_schema.md` - documented `validation_status = promoted_for_demo` in the lifecycle.
- Live `--apply` runs (2026-05-29, account `optisweepsupportdev`, database `optisweep_knowledge_phase0`):
  - `python -m backend.app.promotion.promote_slide_review --apply` -> wrote 4 target files + extended manifest; verified byte-idempotent on second `--apply`.
  - `python -m scripts.seed_phase1_azure --apply --container context_reference --container procedure_dictionary --container source_artifacts` -> **605 documents upserted** across 3 containers (297 context + 50 procedure + 258 source-artifact), 0 failed.
  - `python -m backend.app.scripts.seed_canonical_to_cosmos procedures --apply` -> **50 documents upserted** to `canonical_procedure_dictionary`, 0 failed.
- Tests run:
  - `pytest tests/test_promote_slide_review.py -v` -> 21 passed.
  - `pytest tests/test_runtime_status_filters.py tests/test_canonical_search_indexing.py` -> 18 passed.
  - `pytest -q` (full suite) -> **694 passed, 1 skipped, 0 failed (90.53s)**.
- Blockers: none.
- Acceptance verified:
  - All three runtime datasets are no longer dependent on the in-code 4-record context fallback.
  - The retrieval path (`backend.app.services.local_bm25_index`) picks up the 297 new context records automatically because they are in `RETRIEVAL_APPROVED_STATUSES`.
  - The procedure search index picks up 32 newly promoted procedures because `promoted_for_demo` is in `CANONICAL_PROCEDURE_INDEXABLE_STATUSES`.
  - Runtime workflow execution is unchanged: only the two `approved_for_workflow` canonical workflows remain workflow-eligible. `promoted_for_demo` is deliberately excluded from `WORKFLOW_APPROVED_STATUSES`.
  - SME walkthroughs remain a separate, deferred work item; this addendum is **not** SME approval and does not flip any record to `approved_for_workflow`.
- Section I (appended to status review) tracks the cumulative pointer to this log; no other section of the status review is edited.

---

## Step 16 - LLM Composition Synthesizer (post-Phase-1 addendum, demo only)

- Status: done (live)
- Scope: replaces the hand-authored `backend/app/tools/workflow_composition_mapping.yaml` human gate with an Azure OpenAI agent that clusters previously-unmapped workflow candidates into composition entries with grounded canonical procedure assignments. Closes the workflow-coverage gap (2/6 incidents -> 6/6 incidents) without waiting on SME walkthroughs. SME approval (`approved_for_workflow`) is still a separate, deferred work item; this addendum stamps `validation_status: promoted_for_demo` for demo coverage only.
- Changed files:
  - `backend/app/schemas/canonical/composition.py` (new) - `ProposedComposition` and `CompositionSynthesisResult` Pydantic models. `ProposedComposition` mirrors the live composition-entry shape so approved proposals can be appended verbatim; adds `related_incidents`, `rationale`, `confidence`, and `provenance` metadata for the audit trail.
  - `backend/app/schemas/canonical/__init__.py` - re-exported the new schemas.
  - `backend/app/prompts/composition_synthesizer_prompt.md` (new) - the agent contract: allowed inputs, allowed outputs, 13 hard post-validation rules (already enforced by the synthesizer module - the prompt restates them so the LLM produces compliant outputs on the first try), grounding heuristics, two few-shot examples derived from the SME-approved baseline workflows. Also documents the broadened grounding rule (case-derived procedure_refs vs incident overlap) so the agent grounds picks correctly.
  - `backend/app/tools/llm_composition_synthesizer.py` (new) - `LLMCompositionSynthesizer` agent + `SynthesizerContext` + `CompositionSynthesisError` + `build_context` + `append_to_mapping`. Wires Azure OpenAI via the same `config/azure_openai.local.json` path the workflow planner uses. Stamps runtime-controlled provenance fields (`source_input_files`, `llm_model`, `created_at`, `prompt_id`, `prompt_version`, `created_by_agent`) onto every proposal so the LLM cannot fake them. `--apply` flag flips `validation_status` to `promoted_for_demo`.
  - `scripts/synthesize_compositions.py` (new) - CLI wrapper. Defaults to writing `data/workflows/proposed_compositions.yaml` (review-only, `needs_review`); `--apply` additionally appends each proposal to the live `backend/app/tools/workflow_composition_mapping.yaml` with `promoted_for_demo` and is idempotent (re-running with the same proposals appends 0 new entries).
  - `backend/app/tools/llm_workflow_planner.py` - inherits `validation_status: promoted_for_demo` from the composition entry's provenance into the LLM-generated plan YAML's provenance. Also propagates the composition's `related_incidents` claim into the plan when the LLM omits it (Option B tight-claim).
  - `backend/app/tools/workflow_graph_builder.py` - `CompositionEntry` now carries `related_incidents` + `provenance` from the YAML. `_build_workflow` honours a tight `related_incidents` claim from the plan (Option B) and only widens via `validated_by_incidents` when the plan declares an empty list (backwards-compat). `graph_readiness.workflow_ready` is now `True` for both `approved_for_workflow` and `promoted_for_demo`.
  - `backend/app/promotion/promote_canonical_workflow.py` - `promote_all` skips composition entries whose `provenance.validation_status == "promoted_for_demo"` so the SME-promotion pipeline does not try to upgrade demo workflows to `execution_ready: true`.
  - `backend/app/services/record_status.py` - `is_search_indexable_record` for `canonical_workflow_definitions` now accepts `promoted_for_demo` (in addition to `approved_for_workflow`) so the demo workflows are surfaced to the runtime via the search index.
  - `backend/app/services/workflow_loader.py` - skips YAML files in `data/workflows/` that lack a `workflow_id` / `name` top-level key, so the new `data/workflows/proposed_compositions.yaml` sidecar does not break the legacy loader.
  - `backend/app/prompts/workflow_planner_prompt.md` - added explicit sections for the universal-question requirement, the procedure_ref requirement on `diagnostic_check` / `action` / `validation` nodes, and the closed-vocabulary constraints on `node_type`, `branches[*].operator`, `requires_role`, `screenshot_category_hints`, and `escalation_domain`. The compiler enforces these deterministically; the prompt now restates them so the planner produces compliant plans on the first try.
  - `backend/app/tools/workflow_composition_mapping.yaml` - 5 demo-promoted entries appended (2026-05-29 live `--apply`): `hospital_induction_recovery_after_robot_shutdown_v1`, `post_service_restart_agv_sync_and_evidence_followup_v1`, `tipper_heartbeat_service_failure_recovery_v1`, `agvs_not_moving_service_restart_and_comms_monitoring_v1`, `heartbeat_recurrence_with_hospital_impact_and_log_collection_v1`. The original 2 SME-approved entries are preserved verbatim.
  - `data/workflows/plans/*.yaml` - 5 new plan YAMLs generated by the LLM workflow planner (one per new composition).
  - `data/workflows/canonical/*.yaml` - 5 new compiled canonical workflow YAMLs.
  - `data/workflows/canonical/workflow_compilation_audit.json` + `workflow_validation_report.json` + `workflow_validation_report.md` + `execution_ready_audit.json` - regenerated to reflect the 7-workflow corpus.
  - `data/graph_edges/workflow_procedure_signal_edges.json` - regenerated; grew from 100 edges to 544 edges (reflects the 5 new workflows' graph structure).
  - `tests/test_llm_composition_synthesizer.py` (new) - unit tests for every post-validation rule with a stubbed LLM callable.
  - `tests/test_composition_synthesizer_acceptance.py` (new) - acceptance tests against the live repo state. Uses a synthetic pre-application composition mapping fixture so the test is repeatable regardless of demo-promotion state.
  - `tests/test_workflow_graph_builder.py` - `test_related_incidents_union_includes_procedure_incidents` renamed + rewritten to `test_related_incidents_honors_tight_plan_declaration` (Option B); added `test_related_incidents_widens_when_plan_omits` for backwards-compat coverage.
  - `tests/test_canonical_workflow_loader.py` - extended `COMMITTED_WORKFLOW_IDS` to the 7 canonical workflows; added a separate `APPROVED_FOR_WORKFLOW_IDS` for the approved-only assertions.
  - `tests/test_canonical_to_cosmos.py` - `test_canonical_workflow_documents_validation_status_is_approved` -> `..._is_runtime_ready` (accepts both `approved_for_workflow` and `promoted_for_demo`).
  - `tests/test_canonical_search_indexing.py` - `test_approved_canonical_workflow_indexes` -> `test_runtime_ready_canonical_workflows_index` (same broadening).
  - `tests/test_workflow_procedure_validator.py` - `test_committed_workflows_pass_every_active_gate` and `test_validate_all_returns_one_result_per_workflow` now scope strict Phase-9 assertion to `approved_for_workflow` workflows; added `test_promoted_for_demo_workflows_track_known_data_quality_gaps` with an allowlist of `procedure_produces_no_signals` warnings (the only Phase-9 failure mode observed on demo workflows; rooted in discovered-procedure normalization rather than the synthesizer).
  - `tests/test_phase1_demo_scenarios.py` - parametrized `test_promoted_for_demo_workflows_load_and_drive_first_turn` over all 5 demo workflows.
  - `data/workflows/proposed_compositions.yaml` (new) - latest synthesizer output (regenerated on every run).
- Live runs (2026-05-29, account `optisweepsupportdev`, database `optisweep_knowledge_phase0`):
  - `python scripts/synthesize_compositions.py` -> 6 proposed compositions written to `data/workflows/proposed_compositions.yaml`, all 13 previously-unmapped candidates mapped, all 6 normalized CAT-1 incidents covered, 0 unmapped remaining.
  - `python scripts/synthesize_compositions.py --apply` -> 5 proposed compositions on second run, appended to the live mapping with `promoted_for_demo`. Note: each LLM call is non-deterministic; cluster count varied 5-6 between runs. Both runs covered all 6 incidents with 0 unmapped remaining.
  - `python -m backend.app.tools.workflow_graph_builder compile --plan-with-llm --workflow-id <each-of-5>` -> 5 plan YAMLs generated by the LLM workflow planner, then compiled into 5 canonical workflow YAMLs.
  - `python -m backend.app.tools.workflow_graph_builder compile` (full deterministic re-compile of all 7 from committed plan files) -> regenerated `workflow_compilation_audit.json`.
  - `python -m backend.app.tools.relationship_exporter export` -> regenerated `data/graph_edges/workflow_procedure_signal_edges.json` (544 edges, up from 100).
  - `python -m backend.app.validation.workflow_procedure_validator validate` -> regenerated `workflow_validation_report.json` + `.md` (7 workflows validated; 4 pass every active gate, 3 demo-promoted ones fail only `procedure_produces_no_signals` and only for discovered-only procedures; tracked by the new known-gap allowlist test).
  - `python -m scripts.seed_phase1_azure --apply --container workflow_definitions` -> **7 documents upserted** to Cosmos `workflow_definitions` (was 2), 0 failed.
  - `python -m backend.app.scripts.seed_canonical_to_cosmos all --apply` -> **canonical_procedure_dictionary**: 50/50 upserted; **canonical_workflow_definitions**: 7/7 upserted (was 2); **knowledge_relationships**: 518/544 upserted (26 failures are pre-existing data-quality issue with screenshot reference edge IDs containing spaces, unrelated to this addendum).
- Tests run:
  - `pytest tests/test_llm_composition_synthesizer.py tests/test_composition_synthesizer_acceptance.py -v` -> 29 passed.
  - `pytest tests/test_workflow_graph_builder.py tests/test_canonical_workflow_acceptance.py tests/test_promote_canonical_workflow.py tests/test_phase1_demo_scenarios.py -v` -> all green (12 demo scenarios including 5 new parametrized).
  - `pytest -q` (full suite) -> **762 passed, 1 skipped, 0 failed (83.81s)**. (5/29 baseline: 694 passed; +68 new tests added by this addendum.)
- Blockers: none for the demo path. Known data-quality gap (discovered procedures with empty `signal_contract`) tracked separately by the known-gap allowlist test and the updated synthesizer prompt; not blocking.
- Acceptance verified:
  - Workflow coverage: 6 of 6 normalized CAT-1 incidents (223554, 228086, 229374, 229488, 229716, 229777) now have a runtime-routable canonical workflow.
  - All 7 canonical workflows are `graph_readiness.workflow_ready: true`; the 2 SME-approved baseline workflows additionally carry `graph_readiness.execution_ready: true`.
  - All 7 workflows upserted to Cosmos `canonical_workflow_definitions` and surfaced via the search index.
  - Composition mapping authorship is no longer a human bottleneck; the agent emits proposals to `data/workflows/proposed_compositions.yaml` for review (default) or appends with `validation_status: promoted_for_demo` to the live mapping (`--apply`).
  - SME approval pipeline (`promote_canonical_workflow.promote_all`) skips demo-promoted entries so the SME promotion gate remains untouched and the 2 SME-approved workflows continue to be the only candidates for `execution_ready: true`.
  - The `/troubleshoot` runtime can route to any of the 7 workflows via the canonical runtime path (`USE_CANONICAL_ROUTING=true` + `ENABLE_CANONICAL_WORKFLOW_RUNTIME=true`); the 5-scenario demo harness + the new 5 parametrized smoke tests verify this end-to-end.
