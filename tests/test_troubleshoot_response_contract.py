from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.api.troubleshoot import _build_troubleshoot_response
from backend.app.main import app


def test_build_troubleshoot_response_stub() -> None:
    state = {
        "session_id": "sess-1",
        "final_response": "Playbook orchestration is not wired yet.",
        "response_type": "answer",
        "runtime_trace": {"stage": "0_cleanup"},
        "extracted_observed_signals": {"agvs_stopped": True},
        "retrieval_hits": [
            {
                "record_id": "emb_1",
                "source_record_id": "playbook_1",
                "title": "Stoppage playbook",
                "combined_score": 0.82,
                "snippet": "AGVs stopped",
                "record_type": "playbook_prompt_a",
                "filter_metadata": {"case_id": "228086"},
            }
        ],
        "retrieval_confidence": 0.82,
        "playbook_payload": {
            "title": "Site stoppage",
            "observed_entry_symptoms": ["AGVs stopped"],
            "validation_status": "needs_sme_review",
        },
        "active_playbook_id": "playbook_1",
        "active_case_id": "228086",
        "current_node_id": "node_1",
        "runbook_payload": {
            "procedure_id": "proc_1",
            "title": "Review alarms",
            "summary": "Check HMI alarms",
            "steps": [{"step_number": 1, "instruction": "Open alarms"}],
        },
        "runbook_step": {
            "step_number": 1,
            "title": "Open alarms",
            "instruction": "Open the Alarms screen",
        },
    }
    response = _build_troubleshoot_response(state)
    assert response.session_id == "sess-1"
    assert response.response_type == "answer"
    assert "not wired yet" in response.final_response
    assert response.runtime_trace.get("stage") == "0_cleanup"
    assert response.retrieval_confidence == 0.82
    assert response.extracted_observed_signals.get("agvs_stopped") is True
    assert response.retrieval_results[0].confidence == 0.82
    assert response.workflow_state.get("playbook_title") == "Site stoppage"
    assert response.workflow_state.get("runbook", {}).get("title") == "Review alarms"
    assert response.workflow_state.get("runbooks", [{}])[0].get("title") == "Review alarms"


def test_build_troubleshoot_response_includes_all_node_runbooks() -> None:
    state = {
        "session_id": "sess-multi-runbook",
        "final_response": "Choose an outcome.",
        "response_type": "guided_question",
        "extracted_observed_signals": {"agvs_stopped": True},
        "retrieval_hits": [],
        "retrieval_confidence": 0.7,
        "playbook_payload": {"title": "Site stoppage"},
        "active_playbook_id": "playbook_1",
        "current_node_id": "node_1",
        "runbook_payload": {
            "procedure_id": "proc_1",
            "title": "Primary checks",
            "steps": [{"step_number": 1, "instruction": "Open alarms"}],
        },
        "runbook_payloads": [
            {
                "procedure_id": "proc_1",
                "title": "Primary checks",
                "steps": [{"step_number": 1, "instruction": "Open alarms"}],
            },
            {
                "procedure_id": "proc_2",
                "title": "Secondary corroboration",
                "summary": "Confirm RMS map state",
                "steps": [{"step_number": 1, "instruction": "Open map monitor"}],
            },
        ],
        "runbook_step": {"step_number": 1, "instruction": "Open alarms"},
    }
    response = _build_troubleshoot_response(state)
    runbooks = response.workflow_state.get("runbooks") or []
    assert len(runbooks) == 2
    assert runbooks[0]["procedure_id"] == "proc_1"
    assert runbooks[1]["title"] == "Secondary corroboration"
    assert response.workflow_state.get("runbook", {}).get("procedure_id") == "proc_1"


def test_troubleshoot_endpoint_smoke() -> None:
    client = TestClient(app)
    response = client.post(
        "/troubleshoot",
        json={"session_id": "test-session", "user_message": "AGVs stopped"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == "test-session"
    assert payload["response_type"] in {
        "answer",
        "guided_question",
        "playbook_candidates",
        "workflow_step",
    }
    assert payload["final_response"]
