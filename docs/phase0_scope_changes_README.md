# Phase 0 Scope Changes README

> Purpose: a single, discoverable record of every Phase 0 deliverable that diverges from the original Phase 0 scope. Each row says **what changed**, **why it matters**, and **where the evidence lives**. Used to keep stakeholders aligned without re-reading the long status review or chasing it through `.docx` trackers.
>
> Snapshot date: 2026-05-28 (refreshed after Phase 1 Steps 13-14: interaction-log persistence + 5-scenario demo acceptance harness; Phase 1 Steps 1-14 complete).
>
> Scope baseline (the "should" side of every row):
>
> - `docs/Phase 0 Execution Tracker.docx`
> - `docs/Optisweep AI Support Assistant Phase 0 Plan.docx`
> - `docs/Optisweep-AI-Support-Assistant-Phase-0-SOW.txt`
> - `docs/phase0_scope.md`
>
> Repository reality (the "is" side of every row):
>
> - `docs/phase0_status_review.md` (Sections A-H)
> - `docs/phase0_status_review_kpis.md` (paste-back-to-tracker view, Sections 1-12)
> - Live code under `backend/`, `data/`, `tests/`, `scripts/`, `ui/`
>
> Phase 1 work (Steps 1-14 of the runtime Azure demo) is intentionally **out of scope for this file**. Phase 1 has its own progress log: `docs/phase1_azure_runtime_demo_progress.md`. This file is referenced from Section I of the status review and updated only when Phase 0 scope itself changes.

---

## Status legend

| Symbol           | Meaning                                                                                |
| ---------------- | -------------------------------------------------------------------------------------- |
| `ADDED`          | Delivered in Phase 0 but absent from the original scope.                               |
| `RENAMED`        | Original scope item shipped under a different identifier.                              |
| `RESHAPED`       | Original scope item shipped, but the artifact shape differs from the tracker's wording. |
| `PARTIAL`        | Original scope item shipped to a smaller surface than the scope called for.            |
| `DEFERRED`       | Original scope item not shipped in Phase 0 and explicitly handed to Phase 1.           |
| `MISSING`        | Original scope item not shipped and not yet rescheduled.                               |
| `MEASURE-DRIFT`  | KPI shipped but the metric definition changed from the original wording.               |

Every row carries an `Evidence` path that resolves inside this repo.

---

## A. Workflow scope changes

The original tracker named three workflow candidates. The repository ships two compiled canonical workflows with a different identifier set.

| # | Original scope item (tracker)                        | Status      | What actually shipped                                                                                                                            | Evidence |
|---|------------------------------------------------------|-------------|--------------------------------------------------------------------------------------------------------------------------------------------------|----------|
| A1 | `heartbeat_timeout_no_rms_alarm_v1`                  | RENAMED     | Legacy YAML kept under the original name; canonical compile uses `heartbeat_timeout_no_rms_fault_v1` (`workflow_ready: true`, `execution_ready: true`). | `data/workflows/heartbeat_timeout_no_rms_alarm_v1.yaml`, `data/workflows/canonical/heartbeat_timeout_no_rms_fault_v1.yaml` |
| A2 | `agvs_stopped_hospital_remove_hangs_v1`              | MISSING     | Not started under this ID. Nearest workflow candidate exists in ingestion output but has no plan, no canonical compile, and no SME review.       | `data/workflows/workflow_candidates.json` (`hospital_tote_removal_blocked_during_cat1_tipper_heartbeat_failure`) |
| A3 | `service_restart_recovery_flow_v1`                   | MISSING     | Not started under this ID. Nearest workflow candidate exists in ingestion output but has no plan, no canonical compile, and no SME review.       | `data/workflows/workflow_candidates.json` (`service_restart_recovered_but_rca_pending_with_monitoring_candidate`) |
| A4 | (no tracker row)                                     | ADDED       | `service_failure_with_customer_bridge_and_engineer_recovery_v1` compiled canonical, `execution_ready: true`, SME=No. Not in any tracker table.    | `data/workflows/canonical/service_failure_with_customer_bridge_and_engineer_recovery_v1.yaml`, `data/workflows/plans/service_failure_with_customer_bridge_and_engineer_recovery_v1_plan.yaml` |
| A5 | "SME-approved workflows = 3"                         | MISSING     | 0 SME-approved workflows. `data/review/sme_review_queue.json` is empty. This is the dominant remaining Phase 0 blocker, not an engineering gap. | `data/review/sme_review_queue.json` |

**Net effect on tracker rows:** rename A1, drop A2/A3 from the "in flight" column (or add a "not started" note), add A4 as a brand-new row.

---

## B. Incident normalization scope changes

| # | Original scope item                                  | Status      | What actually shipped                                                                                                                                                  | Evidence |
|---|------------------------------------------------------|-------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------|
| B1 | Incident packages normalized = 7                     | PARTIAL     | 6 of 7 incidents normalized: 229716, 229374, 229777, 229488, 228086, 223554. Incident **227895** has no canonical record, candidate, timeline, evidence, or agent dir. | `data/incidents/canonical_incidents.json`, `data/curated/candidate_incident_records.json` |
| B2 | SME approval per normalized incident                 | MISSING     | All 6 records carry `validation_status: candidate_extracted` and `requires_manual_review: true`. None SME-approved.                                                    | Same |
| B3 | (no tracker row)                                     | ADDED       | Per-incident KPI surfacing: 6/6 normalized incidents carry `incident_kpis` (MTTR computed for 5, time-to-recover computed for 6). Backfill CLI + audit committed.       | `backend/app/services/incident_kpi_calculator.py`, `scripts/backfill_incident_kpis.py`, `output/phase0/incident_kpi_backfill_audit.json` |

---

## C. Dataset scope changes

The scope called for "8 datasets / containers created". The repository ships 15 Cosmos repos defined in code, but four of the eight tracker datasets diverge.

| # | Original scope item                  | Status        | What actually shipped                                                                                                                                                                                                 | Evidence |
|---|--------------------------------------|---------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------|
| C1 | Dataset 0 - Context Reference        | MISSING       | `data/context/context_reference.json` is an empty array. The in-code seed `backend/app/seed/seed_context_reference.py` exists but is not the tracker artifact.                                                          | `data/context/context_reference.json` |
| C2 | Dataset 1 - Canonical Incidents      | PARTIAL       | 6 of 7 records (see B1).                                                                                                                                                                                                | `data/incidents/canonical_incidents.json` |
| C3 | Dataset 1.5 - Timeline Events        | ADDED         | Not a numbered dataset in the original tracker. 60 events committed; treated as part of Dataset 1 in the SOW.                                                                                                          | `data/timelines/timeline_events.json` |
| C4 | Dataset 2A - Incidence Workflow Definitions | RESHAPED  | No dedicated `data/workflows/dataset_2a*.json` artifact. Nearest equivalents are `data/workflows/workflow_candidates.json` + the markdown graphs under `data/workflows/graphs/`. Decision needed: subsume or author. | `data/workflows/workflow_candidates.json`, `data/workflows/graphs/` |
| C5 | Dataset 2B - Procedure Dictionary    | RESHAPED      | 8 canonical + 42 discovered procedures. Reusable procedure store empty. Original scope did not split canonical vs. discovered vs. reusable - this layering was added during Phase 4.5.                                  | `data/normalized/canonical_procedure_dictionary.json`, `data/normalized/discovered_canonical_procedures.json`, `data/procedures/reusable_procedures.json` |
| C6 | Dataset 2C - Workflow Definitions    | PARTIAL       | 1 legacy YAML + 2 canonical compiled `execution_ready` + 2 plan YAMLs. Original scope expected 3 workflows; ships 2 + 1 obsolete.                                                                                       | `data/workflows/`, `data/workflows/canonical/`, `data/workflows/plans/` |
| C7 | Dataset 3 - Raw Evidence Chunks      | OK            | 60 chunks across 6 incidents.                                                                                                                                                                                            | `data/evidence/raw_evidence_chunks.json` |
| C8 | Dataset 4 - Source Artifacts         | OK            | 119 artifacts.                                                                                                                                                                                                           | `data/evidence/source_artifacts.json` |
| C9 | Dataset 5 - Escalation Summaries     | OK (Phase 1)  | Standalone artifact now committed via Phase 1 Step 8: 2 workflow-scoped records (`heartbeat_timeout_no_rms_fault_v1`, `service_failure_with_customer_bridge_and_engineer_recovery_v1`) using the build-prompt 15-field schema, rendered at runtime by `escalation_node`.                                                                                                                                                              | `data/escalation/escalation_summaries.json`, `backend/app/services/escalation_templates.py`, `backend/app/graph/nodes/escalation.py` |
| C10 | (no tracker row)                    | ADDED         | 417-edge deterministic relationship graph (Phase 8 output). Not in the original tracker; added during Phase 8.                                                                                                          | `data/graph_edges/workflow_procedure_signal_edges.json`, `backend/app/tools/relationship_exporter.py` |

---

## D. Architecture / tooling scope changes

The original tracker did not anticipate the Phase 4.5/5/6/8/9/10/11 toolchain or the canonical-routing dual path. All of the following are ADDED relative to the tracker.

| # | Item                                                        | Status | Notes                                                                                                                                                                                                                              | Evidence |
|---|-------------------------------------------------------------|--------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------|
| D1 | Phase 4.5 procedure normalizer                              | ADDED  | Two-pass normalizer (seed canonical mapping = 21 merges, discovery = 47 merges, 0 audit conflicts). Not in the original Phase 0 Plan.                                                                                              | `backend/app/tools/procedure_normalizer.py`, `data/normalized/normalization_audit.json` |
| D2 | Phase 5a optional LLM planner + probe                       | ADDED  | Off by default. Probe script + report committed. Original scope assumed manual workflow authoring only.                                                                                                                            | `backend/app/tools/llm_workflow_planner.py`, `scripts/llm_planner_accuracy_probe.py`, `data/workflows/canonical/llm_planner_accuracy_20260522T124331Z.md` |
| D3 | Phase 5b deterministic workflow compiler                    | ADDED  | Plan YAML + procedures + composition mapping -> canonical workflow YAML. Both committed workflows compiled here (16 nodes / 25 edges and 20 nodes / 31 edges).                                                                     | `backend/app/tools/workflow_graph_builder.py`, `data/workflows/canonical/workflow_compilation_audit.json` |
| D4 | Phase 6 acceptance evaluator                                | ADDED  | 12 acceptance criteria; both compiled workflows PASS.                                                                                                                                                                              | `backend/app/validation/phase6_acceptance.py` |
| D5 | Phase 8 relationship exporter                               | ADDED  | 10/14 relation types live, 4 deferred. 417 edges total.                                                                                                                                                                            | `backend/app/tools/relationship_exporter.py`, `data/graph_edges/workflow_procedure_signal_edges.json` |
| D6 | Phase 9 procedure / workflow validator                      | ADDED  | 11 active gates, 9 deferred subprocedure/step gates. Both workflows `is_valid: true`.                                                                                                                                              | `backend/app/validation/workflow_procedure_validator.py`, `data/workflows/canonical/workflow_validation_report.md` |
| D7 | Phase 10 promotion CLI                                      | ADDED  | Composes Phase 9 + Phase 6 + provenance + safety gates; flips `execution_ready` on commit; both workflows promoted.                                                                                                                | `backend/app/promotion/promote_canonical_workflow.py`, `data/workflows/canonical/execution_ready_audit.json` |
| D8 | Phase 11 dual-path isolation tests                          | ADDED  | 11 tests pinning the legacy contract when `USE_CANONICAL_ROUTING=false`. Guards against flag-on regressions.                                                                                                                       | `tests/test_phase11_dual_path_isolation.py` |
| D9 | Hybrid signal-coverage router + signal translator + scorer  | ADDED  | `HybridWorkflowRouter`, `signal_translator`, `MissingSignalScorer`, `CanonicalWorkflowLoader`. Two routing systems live in parallel behind a feature flag.                                                                          | `backend/app/routing/` |
| D10 | `USE_CANONICAL_ROUTING` feature flag                       | ADDED  | Default `false`. When `true`, the canonical layer engages; otherwise the legacy graph runs byte-identically.                                                                                                                       | `backend/app/config/__init__.py`, `backend/app/graph/nodes/canonical_routing.py` |
| D11 | Seed / sync one-shot CLIs                                  | ADDED  | `seed_canonical_to_cosmos` (dry-run + apply: 50 procedure docs + 2 workflow docs + 417 relationship docs); `sync_canonical_to_search` (dry-run + apply: 2 workflow docs). Neither runs on the hot path.                              | `backend/app/scripts/seed_canonical_to_cosmos.py`, `backend/app/scripts/sync_canonical_to_search.py`, `output/cosmos_dry_run/`, `output/search_dry_run/` |
| D12 | FastAPI scaffold                                            | RESHAPED | Tracker shows `Pending 0%`. Shipped and tested.                                                                                                                                                                                    | `backend/app/main.py`, `backend/app/api/troubleshoot.py` |
| D13 | LangGraph scaffold                                          | RESHAPED | Tracker shows `Pending 0%`. Shipped: 7-node graph with conditional fan-out and the new `clarification` node behind `ENABLE_GUIDED_DIAGNOSTIC` (gated by Phase 1 Step 7).                                                            | `backend/app/graph/graph.py`, `backend/app/graph/nodes/` |
| D14 | Streamlit UI                                                | RESHAPED | Tracker shows `Pending 0%`. Shipped (chat, citation rendering, workflow state, escalation display, local-only).                                                                                                                    | `ui/streamlit_app.py` |
| D15 | Local BM25 retrieval agent (Azure AI Search substitute)     | ADDED    | LLM-orchestrated retrieval agent over an in-process BM25 index of the 303 Phase 1 search documents (`PhaseOneBM25Index` + `retrieval_tools.py` + `LocalBm25RetrievalAgent`). Opt-in via `RETRIEVAL_BACKEND=local_bm25_agent`; default backend stays `local`. Falls back to deterministic BM25 when `AZURE_OPENAI_*` is unset. Serves the active retrieval path until Azure AI Search free-tier quota is restored; the existing `AzureSearchRetrievalClient` and `RETRIEVAL_BACKEND=azure_search` path are intact for cutover. Added because Azure free-tier quota was exhausted and Phase 1 Step 5 live `--apply` could not proceed. | `backend/app/services/local_bm25_index.py`, `backend/app/services/retrieval_tools.py`, `backend/app/services/retrieval_agent.py`, `backend/app/services/azure_search_client.py`, `requirements-backend.txt` |

---

## E. KPI deltas (Phase 0 success metrics)

Numbers below are scope-target vs. verified-actual at the snapshot date. The original tracker's "tracker says" column is included so the gap is explicit.

| KPI                                              | Target | Tracker says | Verified actual                                                                                  | Status         | Evidence |
|--------------------------------------------------|--------|--------------|--------------------------------------------------------------------------------------------------|----------------|----------|
| Overall completion                               | 100%   | ~20%         | ~60-70%                                                                                          | MEASURE-DRIFT  | This file + `docs/phase0_status_review.md` |
| Incident packages normalized                     | 7      | 2            | 6 (227895 missing)                                                                                | PARTIAL        | `data/incidents/canonical_incidents.json` |
| Workflows authored                               | 3      | ~1           | 1 legacy + 2 canonical compiled `execution_ready`                                                  | PARTIAL        | `data/workflows/`, `data/workflows/canonical/` |
| SME-approved workflows                           | 3      | 0            | 0                                                                                                | MISSING        | `data/review/sme_review_queue.json` |
| Retrieval accuracy                               | >70%   | N/A          | Not measured (hot path is local JSON; no labeled-query test set)                                  | MISSING        | `backend/app/services/azure_search_client.py` |
| Citation coverage                                | 100%   | N/A          | Not measured                                                                                      | MISSING        | Same |
| End-to-end troubleshooting scenarios             | 3      | 0            | 0 SME-walked (1 programmatic graph test exercises the path)                                       | MISSING        | `tests/test_graph_routing.py` |
| Escalation templates validated                   | 3      | 0            | 2 of 3 seeded in `data/escalation/escalation_summaries.json` via Phase 1 Step 8; 3rd waits on SME walkthrough.  | PARTIAL        | C9 above |
| Dataset containers / databases created           | 8      | 0            | 15 Cosmos repos defined; 0 wired into runtime in Phase 0                                          | MEASURE-DRIFT  | `backend/app/repositories/` |

KPIs added by Phase 0 work but not in the tracker:

| KPI                                              | Verified actual                                                                                                                                                                | Evidence |
|--------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------|
| Tests passing                                    | ~432 cached cases across 32 files at the Phase 0 snapshot; the post-Phase-1-Step-14 suite (Step 9 session service + Step 10 dynamic runtime + Step 11 response contract + Step 12 UI helpers + Step 13 interaction logs + Step 14 5-scenario demo harness + integration tests) reports **668 passed, 1 skipped**                | `tests/` |
| Canonical procedures                             | 8 seed + 42 discovered                                                                                                                                                         | `data/normalized/` |
| Relationship edges                               | 417 across 10 relation types                                                                                                                                                   | `data/graph_edges/workflow_procedure_signal_edges.json` |
| Cosmos document dry-runs                         | 50 procedure docs / 2 workflow docs / 417 relationship docs                                                                                                                    | `output/cosmos_dry_run/` |
| Search document dry-runs (Phase 0 canonical)     | 2 workflow docs                                                                                                                                                                | `output/search_dry_run/canonical_search_documents.json` |
| Per-incident time KPIs surfaced                  | 6/6 normalized incidents carry `incident_kpis` (MTTR: 5 computed, 1 unavailable; time-to-recover: 6 computed). Incident 227895 still missing.                                  | `output/phase0/incident_kpi_backfill_audit.json` |

For a paste-back-into-the-`.docx` view (single-line edits in tracker-column order), see `docs/phase0_status_review_kpis.md` Section 12.

---

## F. Original scope items still open (Phase 0 gaps)

Sharp blockers carried over from `docs/phase0_status_review.md` Section F:

| # | Gap                                                             | Severity | Disposition                                                                                                                                                                                                                |
|---|-----------------------------------------------------------------|----------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| F1 | Incident **227895** not normalized                              | Medium   | Run through the existing case-agent pipeline. Closes B1 + the C2 sub-row.                                                                                                                                                  |
| F2 | Dataset 0 Context Reference empty                               | Medium   | Populate using `backend/app/seed/seed_context_reference.py` plus `docs/data_schema.md`. Closes C1.                                                                                                                         |
| F3 | Dataset 2A Incidence Workflow Definitions shape decision        | Medium   | Pick one of (a) "subsumed by workflow_candidates.json + graphs", (b) author the standalone artifact. Document the decision in this file. Closes C4.                                                                       |
| F4 | Dataset 5 Escalation Summaries missing                          | Medium   | **Closed by Phase 1 Step 8.** Two workflow-scoped records seeded in `data/escalation/escalation_summaries.json` and rendered by `escalation_node` via `backend/app/services/escalation_templates.py`. Closes C9.            |
| F5 | Hot-path Azure not wired                                        | High     | **Closed in code by Phase 1 Step 6.** Live Azure AI Search cutover **deferred** on Azure free-tier quota exhaustion; in the interim the local BM25 retrieval agent (D15) is the active runtime substitute, opt-in via `RETRIEVAL_BACKEND=local_bm25_agent`. Tracked in `docs/phase1_azure_runtime_demo_progress.md`.                              |
| F6 | `canonical_workflow` display-only + guided question not surfaced | High     | **Closed.** Guided-question half closed by Phase 1 Step 7; display-only half closed by Phase 1 Step 10 via `backend/app/services/canonical_workflow_runtime.py` gated by `ENABLE_CANONICAL_WORKFLOW_RUNTIME`.            |
| F7 | No session persistence on `/troubleshoot`                       | High     | **Closed by Phase 1 Step 9.** `backend/app/services/session_service.py` ships the build-prompt `WorkflowSession` schema with `InMemorySessionStore` + `CosmosSessionStore` backends keyed off `SESSION_BACKEND`.            |
| F8 | 0/3 SME walkthroughs and approvals                              | High     | **Dominant remaining Phase 0 risk.** Engineering ready; needs SME scheduling. Closes A5 + Stage 1 gate "Stakeholder alignment review" + every Stage 3 gate.                                                              |

---

## G. Items reshaped or deferred to Phase 1

These items appeared in or were implied by the Phase 0 SOW but the engineering path chose to defer them so Phase 0 could be closed:

| Item                                                | Disposition                       | Owner          | Reference |
|-----------------------------------------------------|-----------------------------------|----------------|-----------|
| Live Azure Cosmos provisioning + seed of all datasets | Phase 1 Steps 3-4 (live)         | Phase 1 build  | `docs/phase1_azure_runtime_demo_progress.md` Steps 3-4 |
| Azure AI Search runtime index + retrieval cutover     | Phase 1 Steps 5-6 (code complete; live `--apply` deferred on free-tier quota; local BM25 retrieval agent serves the active retrieval path in the interim) | Phase 1 build  | `docs/phase1_azure_runtime_demo_progress.md` Steps 5-6 + Step 6 follow-up |
| Local BM25 retrieval agent (Azure AI Search substitute) | Done (Step 6 follow-up)         | Phase 1 build  | `docs/phase1_azure_runtime_demo_progress.md` Step 6 follow-up |
| Guided clarification node                             | Phase 1 Step 7 (done)             | Phase 1 build  | `docs/phase1_azure_runtime_demo_progress.md` Step 7 |
| Dataset 5 escalation summaries (standalone artifact)  | Phase 1 Step 8 (done)             | Phase 1 build  | `docs/phase1_azure_runtime_demo_progress.md` Step 8 |
| Session persistence + multi-turn `/troubleshoot`      | Phase 1 Step 9 (done)             | Phase 1 build  | `docs/phase1_azure_runtime_demo_progress.md` Step 9 |
| Dynamic canonical workflow runtime (real step execution) | Phase 1 Step 10 (done)          | Phase 1 build  | `docs/phase1_azure_runtime_demo_progress.md` Step 10 |
| Updated `/troubleshoot` response contract             | Phase 1 Step 11 (done)            | Phase 1 build  | Same |
| Streamlit UI for multi-turn guided troubleshooting    | Phase 1 Step 12 (done; the Phase 1 Step 14 demo-scenarios harness pins the multi-turn flow end-to-end through `/troubleshoot`, closing the manual demo gate) | Phase 1 build  | Same |
| Interaction logging (`interaction_logs` container)    | Phase 1 Step 13 (done; `InteractionLogService` with memory / cosmos / disabled backends wired into `/troubleshoot`; logging failures cannot crash the runtime)         | Phase 1 build  | Same |
| End-to-end demo scenarios                             | Phase 1 Step 14 (done; 5-scenario acceptance harness in `tests/test_phase1_demo_scenarios.py` runs through the live graph; the 12 build-prompt test categories map to existing coverage with no duplication)         | Phase 1 build  | Same |

---

## H. How to update this file

When a Phase 0 deliverable changes scope, edit the rows here in this order:

1. **Update the relevant section** (A workflow, B incidents, C datasets, D architecture/tooling, E KPI).
2. **Update the status symbol** using the legend at the top.
3. **Update the Evidence path** to point to the new/edited artifact.
4. **Mirror the change into `docs/phase0_status_review_kpis.md` Section 12** if the change should be paste-back into `Phase 0 Execution Tracker.docx`.
5. **Bump the snapshot date** at the top of this file.

Do NOT use this file to track Phase 1 (or later) work - that lives in `docs/phase1_azure_runtime_demo_progress.md`. The two files cross-reference each other so a stakeholder can hop between Phase 0 scope deltas and Phase 1 forward progress without losing context.

When Phase 0 is formally closed (all gaps in Section F either resolved, deferred with a Phase ID, or accepted as out-of-scope), add a "Phase 0 closed - <date>" note at the top of this file and freeze it.
