from __future__ import annotations


class EscalationRules:
    def evaluate(
        self,
        signals: dict[str, bool],
        retrieval_confidence: float,
        selected_workflow_id: str | None,
    ) -> tuple[bool, str | None, list[str]]:
        reasons: list[str] = []
        domains: list[str] = []

        if signals.get("safety_risk_present"):
            reasons.append("Safety risk present")
            domains.append("controls")
        if signals.get("engineer_only_action_required") or signals.get("service_restart_required"):
            reasons.append("Engineer-only action required")
            domains.append("application")
        if signals.get("remote_access_unavailable"):
            reasons.append("Remote access unavailable")
            domains.append("infrastructure")
        if signals.get("service_restart_required") and not signals.get("heartbeat_recovered_after_restart"):
            reasons.append("Heartbeat does not recover after restart")
            domains.append("application")
        if signals.get("ot_hardware_alarm_present"):
            reasons.append("OT hardware alarms present")
            domains.append("OT networking")
        if retrieval_confidence < 0.65 or not selected_workflow_id:
            reasons.append("Low confidence or no matching workflow")
            domains.append("application")
        if signals.get("user_requests_escalation"):
            reasons.append("User explicitly requests escalation")
            domains.append("application")

        unique_domains = sorted(set(domains))
        return bool(reasons), "; ".join(dict.fromkeys(reasons)) if reasons else None, unique_domains
