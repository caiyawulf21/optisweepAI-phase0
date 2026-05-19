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
