# Workflow Authoring

Workflows are symptom-driven YAML runbooks. Names must describe observable operational signatures, not case IDs, customers, or assumed root causes.

Each step must include:

- `step_id`
- `role_required`
- `instruction`
- `expected_outcome`
- `validation_check`
- `escalation_condition`
- `support_safe`
- `stop_condition`

Workflow instructions must come from curated evidence or SME-authored YAML. The assistant must not invent operational steps at runtime.

Reusable procedure and workflow drafts must preserve source evidence references. The Workflow Procedure Agent may merge candidates only when overlap is backed by incident timelines, source artifacts, raw evidence, or procedure candidates, not by similar wording alone.

The starter workflow is `data/workflows/heartbeat_timeout_no_rms_alarm_v1.yaml`.

## `entry_signals` vs `required_signals`

Each compiled canonical workflow under `data/workflows/canonical/` carries two signal lists with different semantics:

- `entry_signals` — the operator-knowable subset the router uses as the **coverage denominator**. These are the signals an operator could plausibly report from a free-text message on turn 1 (e.g. `agvs_not_moving`, `tipper_heartbeat_timeout_or_zero`, `hospital_tote_add_failed`). Authored on the corresponding plan file as `required_signals`; carried straight through by `workflow_graph_builder` without modification.
- `required_signals` — the **full union** of every signal the workflow ever touches: `entry_signals` plus every `branch.condition_signal` on every node (e.g. `optisweep_service_restart_completed`, `master_estop_confirmed_off`, `customer_bridge_established`, `evidence_inconclusive`). Used by validation criteria like *every edge condition_signal must be in `required_signals`* and by visualization / audit tooling.

`MissingSignalScorer.score` divides `coverage_ratio` by `entry_signals` (or `required_signals` when a workflow declares no `entry_signals`, for back-compat with hand-authored fixtures). This is the fix for the routing-math bug where mid-flow branch signals were hoisted into the routing denominator and made it mathematically impossible for synthesized workflows to clear `minimum_confidence` on turn 1 — operators cannot emit signals that are produced by mid-workflow node execution.

When authoring or editing a plan:

1. Put **only** signals an operator could report on the opening message into `plan.required_signals`. The compiled YAML's `entry_signals` is set to this verbatim.
2. Branch condition signals belong on the corresponding `WorkflowBranch.condition_signal`. The compiler hoists those into the YAML's `required_signals` automatically; do not list them in `plan.required_signals`.
3. The router counts only **truthy** observations toward coverage. A signal observed-as-False (operator answered "no" or the legacy translator padded the canonical dict with False) is observed-but-not-covering. Per-node branch resolution still treats False as observed because there an operator actually answered.

## Runtime-generated procedure paths are NOT workflows

When `ENABLE_DYNAMIC_PROCEDURE_GUIDANCE=true` and canonical workflow coverage falls below `CANONICAL_WORKFLOW_HIGH_CONFIDENCE_THRESHOLD` (default `0.75`), the runtime may engage `dynamic_procedure_guidance` mode (status: experimental). In that mode the `DynamicProcedureSelector` ranks linked canonical procedures by signal/component/retrieval/incident overlap, source authority, and relationship strength, and the dynamic path assembler stitches the top procedures into a session-only `DynamicProcedurePath` (max 3 procedures / 8 active steps).

These dynamic paths are **NOT a substitute for an approved workflow** and authoring rules:

- The runtime never writes a `DynamicProcedurePath` to `data/workflows/canonical/` (or anywhere else on disk). The path lives only on the active `WorkflowSession.dynamic_path` and disappears with the session.
- Every dynamic path carries a hard-coded `validation_status="runtime_generated_unapproved"`. Authors must not copy this value into a YAML workflow; only `approved_for_runtime` (or the equivalent canonical statuses) is valid for files under `data/workflows/canonical/`.
- The Streamlit UI banners every dynamic-procedure response with *"Procedure-guided troubleshooting — based on linked canonical procedures and evidence, NOT an approved workflow."* Do not screenshot a dynamic path and promote it to YAML without reviewing each step against canonical procedure records.
- Engineer-only steps are stripped from dynamic paths. If the next required step is engineer-only or no support-safe step remains, the runtime escalates instead of emitting an unsafe instruction. That is the only safe way for an engineer-only action to surface in this mode.
- To promote a recurring dynamic path into a real workflow, follow the standard authoring path: SME drafts a YAML workflow under `data/workflows/canonical/`, links the canonical procedures explicitly, sets a real `minimum_confidence`, and goes through the normal review/promotion flow. The dynamic runtime is for filling gaps, not for generating runbooks.