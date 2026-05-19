from backend.app.services.escalation_rules import EscalationRules


def test_escalates_for_remote_access_unavailable():
    required, reason, domains = EscalationRules().evaluate(
        {"remote_access_unavailable": True},
        retrieval_confidence=0.9,
        selected_workflow_id="heartbeat_timeout_no_rms_alarm_v1",
    )

    assert required is True
    assert "Remote access unavailable" in reason
    assert "infrastructure" in domains


def test_escalates_for_low_confidence_no_workflow():
    required, reason, domains = EscalationRules().evaluate(
        {},
        retrieval_confidence=0.2,
        selected_workflow_id=None,
    )

    assert required is True
    assert "Low confidence or no matching workflow" in reason
    assert "application" in domains
