from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

PLACEHOLDER_FALLBACK = "(not captured)"

_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


class EscalationTemplateError(ValueError):
    """Raised when an escalation template payload is malformed."""


def _coerce_placeholder_value(value: Any) -> str:
    if value is None:
        return PLACEHOLDER_FALLBACK
    if isinstance(value, str):
        return value if value else PLACEHOLDER_FALLBACK
    if isinstance(value, (list, tuple, set)):
        items = [str(item) for item in value if item is not None and str(item) != ""]
        return ", ".join(items) if items else PLACEHOLDER_FALLBACK
    if isinstance(value, dict):
        items = [
            f"{key}={_coerce_placeholder_value(val)}"
            for key, val in value.items()
            if val is not None
        ]
        return "; ".join(items) if items else PLACEHOLDER_FALLBACK
    return str(value)


def render_handoff_summary(template: dict[str, Any], runtime: dict[str, Any]) -> str:
    summary_template = template.get("handoff_summary_template", "")

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in runtime:
            return _coerce_placeholder_value(runtime[key])
        if key in template:
            return _coerce_placeholder_value(template[key])
        return PLACEHOLDER_FALLBACK

    return _PLACEHOLDER_PATTERN.sub(_replace, summary_template)


def _collect_playbook_escalation_guidance(
    playbook_id: str | None,
    *,
    playbook_variant: str = "prompt_a",
    current_node_id: str | None = None,
) -> list[str]:
    if not playbook_id:
        return []
    try:
        from backend.app.corpus.cosmos_client import CosmosCorpusClient

        payload = CosmosCorpusClient().get_playbook(playbook_id, playbook_variant)
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    guidance: list[str] = []
    nodes = payload.get("nodes") or []
    if not isinstance(nodes, list):
        return guidance
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("node_id") or "")
        if current_node_id and node_id and node_id != current_node_id:
            continue
        raw = node.get("escalation_guidance")
        if isinstance(raw, list):
            guidance.extend(str(item) for item in raw if item)
        elif raw:
            guidance.append(str(raw))
    return guidance


def build_manual_escalation_summary(
    *,
    session_id: str,
    workflow_id: str | None = None,
    playbook_id: str | None = None,
    playbook_variant: str = "prompt_a",
    current_node_id: str | None = None,
    escalation_reason: str | None = None,
    observed_signals: dict[str, bool] | list[str] | None = None,
    observed_canonical_signals: dict[str, bool] | list[str] | None = None,
    observed_components: list[str] | None = None,
    steps_attempted: list[str] | None = None,
    retrieval_result_ids: list[str] | None = None,
    escalation_domains: list[str] | None = None,
) -> dict[str, Any]:
    selected_playbook_id = playbook_id or workflow_id or "manual_escalation"
    template = _manual_escalation_template(selected_playbook_id)
    guidance = _collect_playbook_escalation_guidance(
        selected_playbook_id if selected_playbook_id != "manual_escalation" else playbook_id or workflow_id,
        playbook_variant=playbook_variant,
        current_node_id=current_node_id,
    )
    if guidance:
        template["escalation_guidance"] = guidance

    observed = _normalize_observed(observed_signals)
    canonical = _normalize_observed(observed_canonical_signals)
    if canonical:
        observed = sorted({*observed, *canonical})
    components = [str(item) for item in observed_components or [] if item]
    if components:
        observed = sorted({*observed, *(f"component:{item}" for item in components)})

    runtime = {
        "session_id": session_id,
        "workflow_id": selected_playbook_id,
        "current_node_id": current_node_id,
        "observed_signals": observed,
        "steps_attempted": [str(item) for item in steps_attempted or [] if item],
        "retrieval_result_ids": [
            str(item) for item in retrieval_result_ids or [] if item
        ],
        "retrieval_confidence": None,
        "escalation_reason": escalation_reason
        or "Manual escalation summary requested by support.",
        "escalation_domains": escalation_domains
        or [template.get("escalation_domain") or "application_engineering"],
        "triggered_at": datetime.now(timezone.utc).isoformat(),
    }
    return {
        **template,
        "workflow_id": selected_playbook_id,
        "handoff_summary": render_handoff_summary(template, runtime),
        "runtime": runtime,
    }


def _normalize_observed(signals: dict[str, bool] | list[str] | None) -> list[str]:
    if isinstance(signals, dict):
        return sorted(str(key) for key, value in signals.items() if bool(value))
    if isinstance(signals, list):
        return sorted(str(item) for item in signals if item)
    return []


def _manual_escalation_template(workflow_id: str) -> dict[str, Any]:
    return {
        "escalation_summary_id": f"{workflow_id}_manual",
        "workflow_id": workflow_id,
        "issue_category": "manual_escalation",
        "escalation_domain": "application_engineering",
        "priority": "P2",
        "trigger_reason": "Manual escalation summary requested by support.",
        "symptoms": [],
        "observed_signals": [],
        "steps_attempted": [],
        "steps_not_attempted": [],
        "evidence_refs": [],
        "logs_collected": [],
        "source_artifacts": [],
        "recommended_owner": "Optisweep Application Engineering",
        "handoff_summary_template": (
            "Manual escalation summary for session {{session_id}} / workflow "
            "{{workflow_id}} at node {{current_node_id}}. Reason: "
            "{{escalation_reason}}. Observed signals and components: "
            "{{observed_signals}}. Steps attempted: {{steps_attempted}}. "
            "Retrieval result IDs reviewed: {{retrieval_result_ids}}. "
            "Recommended owner: {{recommended_owner}}."
        ),
    }
