from backend.app.services.workflow_loader import WorkflowLoader


def test_load_starter_workflow():
    workflow = WorkflowLoader().load_workflow("heartbeat_timeout_no_rms_alarm_v1")

    assert workflow.workflow_id == "heartbeat_timeout_no_rms_alarm_v1"
    assert "tipper_heartbeat_timeout" in workflow.required_signals
    assert workflow.steps[0].step_id == "confirm_no_rms_alarms"


def test_select_workflow_when_confidence_and_signals_match():
    workflow = WorkflowLoader().select_workflow(
        {
            "agvs_stopped": True,
            "no_rms_alarm": True,
            "tipper_heartbeat_timeout": True,
        },
        0.9,
    )

    assert workflow is not None
    assert workflow.workflow_id == "heartbeat_timeout_no_rms_alarm_v1"
