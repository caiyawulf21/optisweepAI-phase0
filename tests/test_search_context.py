from __future__ import annotations

from backend.app.services.search_context import (
    build_contextual_retrieval_query,
    compact_search_context,
    infer_workflow_relevance,
)


def test_compact_search_context_drops_empty_and_caps_lists() -> None:
    compact = compact_search_context(
        {
            "session_id": "ts-1",
            "active_playbook_id": "pb_agv",
            "current_node_id": "inspect_agv",
            "current_node_title": "Inspect affected AGV state",
            "current_runbook_id": "rb_rms",
            "symptoms": ["AGVs stopped", "bag-out issue"] + [f"extra-{i}" for i in range(20)],
            "observed_signals": {"agvs_stopped": True, "no_rms_alarm": False},
            "components": ["AGV"],
            "systems": ["RMS"],
            "noise": {"huge": "dump"},
            "allowed_answers": ["healthy", "unhealthy", "unknown"],
        }
    )
    assert compact["session_id"] == "ts-1"
    assert compact["current_node_title"] == "Inspect affected AGV state"
    assert "noise" not in compact
    assert len(compact["symptoms"]) <= 8
    assert compact["observed_signals"] == ["agvs stopped"]
    assert compact["allowed_answers"] == ["healthy", "unhealthy", "unknown"]


def test_build_contextual_retrieval_query_embeds_node_and_symptoms() -> None:
    rewritten = build_contextual_retrieval_query(
        "How do I check this in RMS?",
        {
            "current_node_title": "Inspect affected AGV state",
            "active_playbook_id": "pb_agv_state",
            "symptoms": ["AGVs stopped", "state mismatch"],
            "systems": ["RMS"],
        },
    )
    assert "How do I check this in RMS?" in rewritten
    assert "Inspect affected AGV state" in rewritten
    assert "AGVs stopped" in rewritten
    assert "RMS" in rewritten


def test_infer_workflow_relevance_requires_allowed_answer_match() -> None:
    relevance = infer_workflow_relevance(
        answer="The AGV database state looks unhealthy based on RMS.",
        hits=[{"title": "Check AGV state", "snippet": "unhealthy when mismatch"}],
        search_context={
            "current_node_id": "n1",
            "current_node_title": "Inspect AGV state",
            "allowed_answers": ["healthy", "unhealthy", "unknown"],
        },
    )
    assert relevance["related_to_current_node"] is True
    update = relevance["possible_state_update"]
    assert update is not None
    assert update["value"] == "unhealthy"
    assert update["requires_user_confirmation"] is True


def test_infer_workflow_relevance_no_auto_update_without_match() -> None:
    relevance = infer_workflow_relevance(
        answer="Open RMS and inspect the AGV detail screen.",
        hits=[{"title": "RMS AGV screen", "snippet": "navigate to AGV detail"}],
        search_context={
            "current_node_id": "n1",
            "allowed_answers": ["healthy", "unhealthy", "unknown"],
        },
    )
    assert relevance["possible_state_update"] is None


def test_build_search_context_from_troubleshoot_ui_helper() -> None:
    from ui.playbook_ui import build_search_context_from_troubleshoot

    context = build_search_context_from_troubleshoot(
        {
            "selected_workflow_id": "pb_1",
            "extracted_observed_signals": {"agvs_stopped": True},
            "guided_question": {
                "node_id": "n1",
                "allowed_answers": ["healthy", "unhealthy"],
            },
            "workflow_state": {
                "playbook_id": "pb_1",
                "playbook_title": "AGV state mismatch",
                "playbook_variant": "prompt_a",
                "current_node_id": "n1",
                "current_node": {"node_id": "n1", "title": "Inspect AGV", "node_type": "diagnostic"},
                "runbook": {"procedure_id": "rb_1", "title": "RMS AGV check"},
                "observed_entry_symptoms": ["AGVs stopped"],
                "path_evidence": [{"node_id": "n0", "title": "Confirm stoppage", "outcome": "yes"}],
            },
        },
        session_id="ts-abc",
    )
    assert context["session_id"] == "ts-abc"
    assert context["active_playbook_id"] == "pb_1"
    assert context["current_node_title"] == "Inspect AGV"
    assert context["current_runbook_id"] == "rb_1"
    assert "AGVs stopped" in context["symptoms"]
    assert "agvs stopped" in context["observed_signals"]
    assert context["allowed_answers"] == ["healthy", "unhealthy"]
