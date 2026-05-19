from __future__ import annotations

from backend.app.graph.state import AssistantState
from backend.app.services.escalation_rules import EscalationRules


def escalation_node(state: AssistantState) -> AssistantState:
    required, reason, domains = EscalationRules().evaluate(
        state.get("extracted_signals", {}),
        state.get("retrieval_confidence", 0.0),
        state.get("selected_workflow_id"),
    )
    state["escalation_required"] = required
    state["escalation_reason"] = reason
    if required:
        state["workflow_state"] = {
            **state.get("workflow_state", {}),
            "escalation_domains": domains,
        }
        state["final_response"] = f"{state.get('final_response', '')} Escalation required: {reason}."
    return state
