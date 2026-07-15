"""Tests for runtime escalation summary builder."""

from __future__ import annotations

from backend.app.services.escalation_templates import (
    PLACEHOLDER_FALLBACK,
    build_manual_escalation_summary,
    render_handoff_summary,
)


def test_build_manual_escalation_summary_includes_runtime_context() -> None:
    summary = build_manual_escalation_summary(
        session_id="sess-1",
        workflow_id="playbook_incident_228086",
        current_node_id="node_check_rms",
        escalation_reason="Heartbeat does not recover after restart",
        observed_signals=["agvs_stopped_before_tippers"],
        steps_attempted=["Confirmed no RMS fault"],
        retrieval_result_ids=["emb_123"],
    )
    assert summary["workflow_id"] == "playbook_incident_228086"
    assert "sess-1" in summary["handoff_summary"]
    assert "node_check_rms" in summary["handoff_summary"]
    assert "agvs_stopped_before_tippers" in summary["handoff_summary"]
    assert "Confirmed no RMS fault" in summary["handoff_summary"]
    assert "emb_123" in summary["handoff_summary"]
    assert "{{" not in summary["handoff_summary"]


def test_build_manual_escalation_summary_without_workflow_id() -> None:
    summary = build_manual_escalation_summary(session_id="sess-2")
    assert summary["workflow_id"] == "manual_escalation"
    assert summary["handoff_summary"]


def test_render_handoff_summary_falls_through_for_unknown_placeholders() -> None:
    template = {"handoff_summary_template": "ID={{escalation_summary_id}} runtime={{not_set}}"}
    rendered = render_handoff_summary(template, {})
    assert "ID=(not captured)" in rendered
    assert PLACEHOLDER_FALLBACK in rendered


def test_render_handoff_summary_falls_back_to_template_field_when_runtime_missing() -> None:
    template = {
        "escalation_summary_id": "template_id",
        "handoff_summary_template": "id={{escalation_summary_id}}",
    }
    rendered = render_handoff_summary(template, {})
    assert "id=template_id" in rendered


def test_render_handles_empty_list_and_dict_values() -> None:
    template = {
        "handoff_summary_template": "signals={{observed_signals}} meta={{meta}}",
    }
    rendered = render_handoff_summary(template, {"observed_signals": [], "meta": {}})
    assert f"signals={PLACEHOLDER_FALLBACK}" in rendered
    assert f"meta={PLACEHOLDER_FALLBACK}" in rendered
