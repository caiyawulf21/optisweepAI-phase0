# Phase 0 Tracker KPI Refresh

> Snapshot date: 2026-05-26. Pair with [`docs/phase0_status_review.md`](phase0_status_review.md) for narrative context.
> Purpose: paste-back-into-`Phase 0 Execution Tracker.docx`. Every row carries an evidence pointer.
> Conventions: `OK` = matches tracker, `UPDATE` = value changes, `NEW ROW` = add to tracker, `RENAME` = tracker item should be renamed/replaced.

---

## 1. Stage summary

| Stage | Tracker says | Status (verified) | % Complete (verified) | Note | Evidence |
|---|---|---|---|---|---|
| Stage 0 - Alignment & Scope Definition | Complete / 100% | OK Complete | 100% | Stakeholder walkthrough still pending. | `docs/phase0_scope.md`, `docs/architecture.md` |
| Stage 1 - Foundation & Knowledge Structuring | In Progress / 30% | UPDATE In Progress | **~80%** | 6/7 incidents normalized, 8 canonical procedures, 2 canonical workflows compiled. | `data/normalized/`, `data/workflows/canonical/` |
| Stage 2 - Workflow & Orchestration Validation | Not Started / 0% | UPDATE In Progress | **~75%** (engineering); 0% SME validation. Behind `USE_CANONICAL_ROUTING=false` flag. | `backend/app/main.py`, `backend/app/graph/graph.py`, `backend/app/routing/` |
| Stage 3 - Operational Validation & Stakeholder Demonstration | Not Started / 0% | UPDATE In Progress | **~10%** | Validation machinery shipped (Phase 6/9/10/11). 0 SME walkthroughs run. | `backend/app/validation/`, `tests/test_phase11_dual_path_isolation.py` |

---

## 2. Overall Phase 0 KPI dashboard

| KPI | Target | Tracker current | Verified current | Status | Evidence |
|---|---|---|---|---|---|
| Overall completion | 100% | ~20% | **~60-70%** | UPDATE | This snapshot |
| Incident packages normalized | 7 | 2 | **6** (227895 missing) | UPDATE | `data/incidents/canonical_incidents.json` (6 records) |
| Workflows authored | 3 | ~1 | **1 legacy + 2 canonical compiled, execution_ready** | UPDATE | `data/workflows/heartbeat_timeout_no_rms_alarm_v1.yaml` + `data/workflows/canonical/*.yaml` |
| SME-approved workflows | 3 | 0 | **0** | OK | `data/review/sme_review_queue.json` (`[]`) |
| Retrieval accuracy | >70% | N/A | Not measured (hot path is local JSON) | OK | `backend/app/services/azure_search_client.py` |
| Citation coverage | 100% | N/A | Not measured | OK | Same |
| End-to-end troubleshooting scenarios | 3 | 0 | **0 SME-walked** (1 graph integration test passes) | OK | `tests/test_graph_routing.py` |
| Escalation templates validated | 3 | 0 | **0** (no Dataset 5 artifact) | OK | Missing |

NEW ROWS proposed (the tracker does not currently capture these):

| KPI | Target | Verified current | Evidence |
|---|---|---|---|
| Tests passing | All | **~432 cached cases across 32 files**; 2 stale cache failures reference removed tests | `tests/`, `.pytest_cache/v/cache/lastfailed` |
| Canonical procedures | n/a | **8 seed + 42 discovered** | `data/normalized/canonical_procedure_dictionary.json`, `data/normalized/discovered_canonical_procedures.json` |
| Relationship edges | n/a | **417** across 10 relation types | `data/graph_edges/workflow_procedure_signal_edges.json` |
| Cosmos document dry-runs | n/a | 50 procedure docs / 2 workflow docs / 417 relationship docs | `output/cosmos_dry_run/` |
| Search document dry-runs | n/a | 2 workflow docs | `output/search_dry_run/canonical_search_documents.json` |
| Per-incident time KPIs surfaced | 7 | **6/6** normalized incidents carry `incident_kpis` (MTTR: 5 computed / 1 unavailable; Time-to-recover: 6 computed). Incident 227895 still missing. | `data/incidents/canonical_incidents.json`, `output/phase0/incident_kpi_backfill_audit.json`, `backend/app/services/incident_kpi_calculator.py` |

---

## 3. Stage 0 deliverable tracker

| Deliverable | Tracker status | Verified status | Evidence |
|---|---|---|---|
| Phase 0 SOW finalized | Complete 100% | OK | `docs/Optisweep-AI-Support-Assistant-Phase-0-SOW.txt` |
| CAT-1 scope finalized | Complete 100% | OK | `data/taxonomy/issue_taxonomy_v0.yaml` (CAT-1, 9 signals) |
| Dataset schemas finalized | In Progress 100% | OK | `backend/app/schemas/canonical/*` + `backend/app/models/*` |
| Workflow architecture finalized | Complete 100% | OK | `data/workflows/canonical/`, `backend/app/tools/workflow_graph_builder.py` |
| Escalation philosophy finalized | Complete 100% | OK | `backend/app/services/escalation_rules.py`, `backend/app/graph/nodes/escalation.py` |
| Stakeholder alignment review | Pending 100% | Pending | Needs scheduling - dominant remaining risk |

---

## 4. Stage 1 infrastructure tracker

| Task | Tracker status / % | Verified status / % | Evidence |
|---|---|---|---|
| Azure OpenAI setup | Pending 0% | **Pending 0%** (hot-path remains regex stub) | `backend/app/services/azure_openai_client.py` |
| Azure AI Search setup | Pending 0% | **Pending 0%** (sync CLI exists, runtime uses local JSON) | `backend/app/scripts/sync_canonical_to_search.py`, `backend/app/services/azure_search_client.py` |
| FastAPI scaffold | Pending 0% | **UPDATE - Complete 100%** | `backend/app/main.py` (15 lines), `backend/app/api/troubleshoot.py` |
| LangGraph scaffold | Pending 0% | **UPDATE - Complete 100%** (7 nodes, conditional fan-out) | `backend/app/graph/graph.py` lines 18-43 |
| GitHub repo structure | In Progress 20% | **UPDATE - Complete ~95%** (backend, data, tests, docs, ui, scripts, ingestion, output, config) | Repository tree |
| Dataset containers / databases created | Pending 0% | **UPDATE - Code 100%, Cosmos 0%** - 15 repos defined, none populated | `backend/app/repositories/` |
| Canonical incident database created | Pending 0% | **UPDATE - Local 100%, Cosmos 0%** | `data/incidents/canonical_incidents.json`, `backend/app/repositories/incident_repository.py` |
| Timeline events database created | Pending 0% | **UPDATE - Local 100%, Cosmos 0%** (60 events) | `data/timelines/timeline_events.json`, `backend/app/repositories/timeline_repository.py` |
| Workflow definitions database created | Pending 0% | **UPDATE - Local 100%, Cosmos 0%** (2 canonical execution_ready) | `data/workflows/canonical/`, `backend/app/repositories/canonical_workflow_repository.py` |
| Procedure dictionary database created | Pending 0% | **UPDATE - Local 100%, Cosmos 0%** (8 canonical + 42 discovered) | `data/normalized/`, `backend/app/repositories/canonical_procedure_repository.py` |
| Raw evidence database created | Pending 0% | **UPDATE - Local 100%, Cosmos 0%** (60 chunks, 119 artifacts) | `data/evidence/`, `backend/app/repositories/evidence_repository.py` |
| Escalation summary database created | Pending 0% | **Pending - no Dataset 5 artifact** (escalation fields embedded in CAT-1 records only) | Missing |
| Relationship model defined | Pending 0% | **UPDATE - Complete 100%** (417 edges exported, schema in canonical) | `backend/app/schemas/canonical/relationship.py`, `data/graph_edges/workflow_procedure_signal_edges.json` |

NEW ROWS to add to Stage 1 infrastructure tracker (currently absent from the .docx):

| Task | Verified status / % | Evidence |
|---|---|---|
| Phase 4.5 procedure normalizer | Complete 100% | `backend/app/tools/procedure_normalizer.py`, `data/normalized/normalization_audit.json` |
| Phase 5 workflow graph builder | Complete 100% | `backend/app/tools/workflow_graph_builder.py`, `data/workflows/canonical/workflow_compilation_audit.json` |
| Phase 5 LLM workflow planner | Complete 100% (optional, off by default) | `backend/app/tools/llm_workflow_planner.py`, `scripts/llm_planner_accuracy_probe.py` |
| Phase 6 acceptance evaluator | Complete 100% (2/2 workflows PASS) | `backend/app/validation/phase6_acceptance.py` |
| Phase 8 relationship exporter | Complete 100% (10/14 relation types) | `backend/app/tools/relationship_exporter.py` |
| Phase 9 workflow/procedure validator | Complete 100% active gates (9 deferred subprocedure/step gates) | `backend/app/validation/workflow_procedure_validator.py`, `data/workflows/canonical/workflow_validation_report.md` |
| Phase 10 promotion CLI | Complete 100% (both compiled workflows promoted) | `backend/app/promotion/promote_canonical_workflow.py`, `data/workflows/canonical/execution_ready_audit.json` |
| Phase 11 dual-path isolation tests | Complete 100% (11 tests) | `tests/test_phase11_dual_path_isolation.py` |
| Cosmos seed CLI | Complete 100% dry-run + apply | `backend/app/scripts/seed_canonical_to_cosmos.py` |
| Search sync CLI | Complete 100% dry-run + apply | `backend/app/scripts/sync_canonical_to_search.py` |

---

## 5. Dataset normalization tracker

| Incident | Category | Tracker status / % | Verified status / % | Notes / Evidence |
|---|---|---|---|---|
| 229716 | CAT-1 | Pending 80% | **UPDATE - Candidate normalized 100%** (still `validation_status=candidate_extracted, requires_manual_review=true`) | `data/incidents/canonical_incidents.json`, `output/phase0/case_229716*` |
| 229374 | CAT-1 | Pending 75% | **UPDATE - Candidate normalized 100%** | Same |
| 229777 | CAT-1 | Pending 0% | **UPDATE - Candidate normalized 100%** | Same |
| 229488 | CAT-1 | Pending 0% | **UPDATE - Candidate normalized 100%** | Same |
| 228086 | CAT-1 | Pending 0% | **UPDATE - Candidate normalized 100%** | Same |
| 223554 | CAT-1 | Pending 0% | **UPDATE - Candidate normalized 100%** | Same |
| 227895 | CAT-1 | Pending 0% | **0%** (no canonical record, candidate, timeline, evidence, or agent dir) | Missing |

Caveat: every normalized record is still `requires_manual_review=true`. They are normalized but not SME-approved.

---

## 6. Workflow candidate tracker

| Tracker name | Tracker status | Verified status | Notes / Evidence |
|---|---|---|---|
| `heartbeat_timeout_no_rms_alarm_v1` | Pending / SME=No | **RENAME** -> canonical compiled as `heartbeat_timeout_no_rms_fault_v1`. Legacy YAML also still present. `workflow_ready: true`, `execution_ready: true`. SME=No. | `data/workflows/heartbeat_timeout_no_rms_alarm_v1.yaml`, `data/workflows/canonical/heartbeat_timeout_no_rms_fault_v1.yaml` |
| `agvs_stopped_hospital_remove_hangs_v1` | Pending / SME=No | **NOT STARTED under this ID.** Nearest candidate: `hospital_tote_removal_blocked_during_cat1_tipper_heartbeat_failure`. | `data/workflows/workflow_candidates.json`, `data/workflows/graphs/hospital_tote_removal_blocked_during_cat1_tipper_heartbeat_failure.md` |
| `service_restart_recovery_flow_v1` | Pending / SME=No | **NOT STARTED under this ID.** Nearest candidate: `service_restart_recovered_but_rca_pending_with_monitoring_candidate`. | `data/workflows/workflow_candidates.json` |

NEW ROW to add (committed but absent from tracker):

| Workflow | Verified status | Evidence |
|---|---|---|
| `service_failure_with_customer_bridge_and_engineer_recovery_v1` | Compiled canonical, `execution_ready: true`, SME=No | `data/workflows/canonical/service_failure_with_customer_bridge_and_engineer_recovery_v1.yaml`, plan in `data/workflows/plans/` |

---

## 7. Stage 1 success metrics

| Metric | Target | Tracker current | Verified current | Status | Evidence |
|---|---|---|---|---|---|
| Incident packages normalized | 7 | 0 | **6** (227895 missing) | UPDATE | `data/incidents/canonical_incidents.json` |
| Workflow candidates authored | 3 | 0 | **18 ingestion + 9 agent-generated** candidates; **2 compiled to canonical execution_ready** | UPDATE | `data/workflows/workflow_candidates.json`, `data/workflows/generated_workflow_candidates.json`, `data/workflows/canonical/` |
| Dataset containers created | 8 | 0 | **15 code-defined, 0 populated in Cosmos** | UPDATE (clarify metric) | `backend/app/repositories/` |
| Retrieval accuracy | >70% | N/A | Not measured | OK | - |
| Citation coverage | 100% | N/A | Not measured | OK | - |
| Structured extraction success | >80% | N/A | Not formally measured (6/6 normalized records pass schema validation) | UPDATE (clarify metric) | `tests/test_canonical_schemas.py` (18 tests pass) |
| Workflow/procedure relationship model | Complete | 0% | **UPDATE - Complete (417 edges, schema defined)** | UPDATE | `backend/app/schemas/canonical/relationship.py`, `data/graph_edges/workflow_procedure_signal_edges.json` |

---

## 8. Stage 1 gate criteria

Each criterion: tracker requires Yes; verified status below.

| Gate criterion | Verified | Note |
|---|---|---|
| Azure environment operational | **No** | Hot path does not call Azure; SDK clients exist but env vars empty. |
| Dataset 0 exists | **No** | `data/context/context_reference.json` is `[]`. |
| Dataset containers/databases exist | **Partial** | 15 repos defined; local files populated; Cosmos empty. Decision needed on what this metric measures. |
| Initial incident records normalized | **Yes** | 6 records in `data/incidents/canonical_incidents.json`. |
| CAT-1 incidents normalized | **Partial** | 6/7. Incident 227895 missing. |
| Retrieval operational | **Yes** | `LocalCat1RetrievalClient` returns scored results + confidence. |
| Citations operational | **Yes** | Citations populated in `AssistantState.citations` for hot path. |
| Workflow candidates generated | **Yes** | 18 + 9 candidates exist. |
| LangGraph scaffold functional | **Yes** | `backend/app/graph/graph.py` compiles, tests pass. |
| Workflows stored separately from incidents | **Yes** | `data/workflows/` is distinct from `data/incidents/`. |
| Procedures stored separately from workflows | **Yes** | `data/procedures/` and `data/normalized/` distinct from `data/workflows/`. |
| Incidents linked to workflows/procedures | **Partial** | `data/review/workflow_procedure_links.json` has 10 links (review-only); no runtime resolver. |
| Retrieval works across incident records | **Yes** | `LocalCat1RetrievalClient` ranks across all CAT-1 records. |
| Workflow/procedure refinement model drafted | **Yes** | `docs/Phase0 Procedure Refinement Agent.md` + `backend/app/services/procedure_workflow_candidate_agent.py` + `backend/app/services/procedure_merge_service.py`. |
| Relationship model defined | **Yes** | Canonical schema + 417 exported edges. |

Net: 9 Yes, 4 Partial, 2 No. The 2 No items (Azure operational, Dataset 0 exists) are the smallest blockers; Azure-on-hot-path is the larger of the two.

---

## 9. Stage 2 orchestration / workflow / escalation / UI trackers

Tracker currently marks every Stage 2 task `Pending 0%`. Verified:

| Tracker task | Verified status | Evidence |
|---|---|---|
| Symptom extraction | **Implemented (stub: regex/phrase match, not LLM)** | `backend/app/services/azure_openai_client.py` |
| Retrieval routing | **Implemented** | `backend/app/graph/nodes/retrieval.py`, `backend/app/services/azure_search_client.py` (`LocalCat1RetrievalClient`) |
| Workflow confidence evaluation | **Implemented (legacy + canonical)** | `backend/app/services/workflow_loader.py`, `backend/app/routing/missing_signal_scorer.py` |
| Clarification prompting | **Partial** - `GuidedDiagnosticRoute.next_question_text` sets state, but `escalation_node` does not surface it to the user. | `backend/app/routing/hybrid_workflow_router.py`, `backend/app/graph/nodes/escalation.py` |
| Conversation state management | **Not implemented** - `/troubleshoot` is stateless single-shot. | `backend/app/api/troubleshoot.py` lines 12-15 |
| YAML workflow loader | **Implemented (legacy + canonical)** | `backend/app/services/workflow_loader.py`, `backend/app/routing/canonical_workflow_loader.py` |
| Step execution engine | **Implemented (legacy)**; **Partial (canonical: display-only)** | `backend/app/graph/nodes/workflow.py`, `backend/app/graph/nodes/canonical_workflow.py` |
| Branching logic | **Implemented** | Canonical workflow YAML branches + `canonical_route_branch` in `backend/app/graph/nodes/canonical_routing.py` |
| Stop conditions | **Implemented** | Workflow YAML schema |
| Validation checkpoints | **Implemented** | Phase 6 + Phase 9 validators |
| Deterministic escalation rules | **Implemented** | `backend/app/services/escalation_rules.py` |
| Escalation domain routing | **Implemented** | `backend/app/graph/nodes/escalation.py` |
| Escalation summary generation | **Implemented (per-request, runtime)**; **Templates: 0** (no Dataset 5) | Same |
| Engineer handoff formatting | **Implemented** | Same |
| Chat interface | **Implemented (local Streamlit)** | `ui/streamlit_app.py` |
| Citation rendering | **Implemented** | Same |
| Workflow progression UI | **Implemented (basic)** | Same |
| Escalation display | **Implemented** | Same |

---

## 10. Risks & blockers log (refresh)

| Risk / Blocker | Severity | Tracker status | Verified status / Note |
|---|---|---|---|
| Azure access delays | High | Open | OK - hot path still has no Azure calls. |
| SME review availability | Medium | Open | **UPGRADE TO HIGH** - this is now the dominant Phase 0 blocker. |
| Retrieval quality issues | High | Open | OK - cannot be measured until Azure Search is wired or until a labeled-query test set exists. |
| Workflow overcomplexity | Medium | Open | OK - canonical schema is rich; Phase 6/9 gates pass on both compiled workflows. |
| Scope creep | High | Open | OK - all committed work maps to documented Phases 4.5/5/6/8/9/10/11. |
| **NEW: Tracker drift** | Medium | - | The .docx tracker materially under-reports completion; stakeholder review based on it would misjudge state. |
| **NEW: Hot-path-vs-canonical dual code paths** | Medium | - | Two routing systems live in the repo. Default flag is `off`. Risk: drift between them, or flipping the flag without SME-validated canonical workflows. |
| **NEW: Workflow candidate rename** | Low | - | Two tracker workflow IDs do not exist; one execution-ready canonical workflow is not in the tracker. |

---

## 11. Stage 2 / Stage 3 success metrics (preview - not yet measurable)

These remain `Not Started` per the tracker because they require SME walkthroughs that have not happened. Engineering is ready to run them.

- Workflow routing accuracy (>75%): need labeled symptom -> expected-workflow set.
- Escalation trigger validation (SME validated): need SME session against the 2 execution-ready canonical workflows.
- End-to-end troubleshooting flow (Operational): can be demonstrated today via the Streamlit app + a manual symptom message; not formally measured.
- Workflow execution success (High-confidence): same.
- SME workflow approval / Retrieval usefulness / Escalation usefulness / Stakeholder confidence (all Stage 3): blocked on scheduling.

---

## 12. Single-line refresh notes for the .docx

If your goal is just to update cells in the existing .docx tables, here are the changes ordered by table position. Each is a (cell, new value) pair.

- Stage summary, Stage 1 row, % Complete: `30%` -> `~80%`. Notes: drop "Dependent on finalized CAT-1 source packages" (6/7 source packages now normalized).
- Stage summary, Stage 2 row, Status: `Not Started` -> `In Progress`. % Complete: `0%` -> `~75% engineering, 0% SME validation`. Notes: add "Behind USE_CANONICAL_ROUTING flag; default off".
- Stage summary, Stage 3 row, Status: `Not Started` -> `In Progress`. % Complete: `0%` -> `~10%`. Notes: add "Validation tooling shipped (Phase 6/9/10/11)".
- Overall KPI Dashboard, Overall completion / Current: `~20%` -> `~60-70%`.
- Overall KPI Dashboard, Incident packages normalized / Current: `2` -> `6`.
- Overall KPI Dashboard, Workflows authored / Current: `~1` -> `1 legacy + 2 canonical compiled (execution_ready)`.
- Stage 1 Infrastructure Tracker, FastAPI scaffold: `Pending 0%` -> `Complete 100%`.
- Stage 1 Infrastructure Tracker, LangGraph scaffold: `Pending 0%` -> `Complete 100%`.
- Stage 1 Infrastructure Tracker, GitHub repo structure: `In Progress 20%` -> `Complete ~95%`.
- Stage 1 Infrastructure Tracker, Relationship model defined: `Pending 0%` -> `Complete 100%`.
- Stage 1 Infrastructure Tracker, all "<dataset> database created" rows: `Pending 0%` -> `Local 100% / Cosmos 0%` (escalation summary stays Pending).
- Dataset Normalization Tracker, all 6 rows (229716, 229374, 229777, 229488, 228086, 223554): set Status `Candidate normalized` / % `100%`. Add note "requires_manual_review=true" to each. 227895 stays at 0%.
- Workflow Candidate Tracker, `heartbeat_timeout_no_rms_alarm_v1`: rename to `heartbeat_timeout_no_rms_fault_v1` (canonical) and note "legacy YAML also present"; mark Compiled canonical / SME=No.
- Workflow Candidate Tracker, `agvs_stopped_hospital_remove_hangs_v1` and `service_restart_recovery_flow_v1`: leave Pending but add note "ID not started; nearest candidate exists".
- Workflow Candidate Tracker: ADD `service_failure_with_customer_bridge_and_engineer_recovery_v1` as Compiled canonical / SME=No.
- Stage 1 Success Metrics, Incident packages normalized / Current: `0` -> `6`.
- Stage 1 Success Metrics, Workflow candidates authored / Current: `0` -> `18 + 9 candidates; 2 compiled canonical`.
- Stage 1 Success Metrics, Dataset containers created / Current: `0` -> `15 code-defined / 0 Cosmos-populated`.
- Stage 1 Success Metrics, Workflow/procedure relationship model / Current: `0%` -> `Complete (417 edges)`.
- Risks & Blockers Log, SME review availability: Severity `Medium` -> `High`. Mitigation: add date for SME walkthrough.
- Risks & Blockers Log: ADD `Tracker drift` (Severity Medium), `Canonical-vs-legacy dual path` (Severity Medium), `Workflow ID rename` (Severity Low).
