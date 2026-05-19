from backend.app.graph.graph import run_troubleshooting


def test_graph_routes_flagship_cat1_signature_to_workflow():
    state = run_troubleshooting(
        "test-session",
        "AGVs stopped, no RMS alarms, all tippers heartbeat timeout, hospital tote removal hangs, system active but frozen",
    )

    assert state["issue_category"] == "CAT-1"
    assert state["extracted_signals"]["agvs_stopped"] is True
    assert state["retrieval_confidence"] >= 0.65
    assert state["selected_workflow_id"] == "heartbeat_timeout_no_rms_alarm_v1"
    assert state["workflow_state"]["available_steps"][0]["step_id"] == "confirm_no_rms_alarms"
    assert state["citations"]
