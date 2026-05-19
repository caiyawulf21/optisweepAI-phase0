from __future__ import annotations

from backend.app.graph.state import AssistantState
from backend.app.services.workflow_loader import WorkflowLoader


def workflow_node(state: AssistantState) -> AssistantState:
    workflow_id = state.get("selected_workflow_id")
    if not workflow_id:
        state["workflow_state"] = {"status": "not_started", "reason": "No confidence-gated workflow matched"}
        state["final_response"] = "No validated workflow matched with sufficient confidence. Review the cited CAT-1 records and escalate if symptoms persist."
        return state

    workflow = WorkflowLoader().load_workflow(workflow_id)
    steps = [step.model_dump() for step in workflow.steps]
    state["workflow_state"] = {
        "workflow_id": workflow.workflow_id,
        "status": "ready",
        "current_step_id": workflow.steps[0].step_id if workflow.steps else None,
        "available_steps": steps,
        "related_incidents": workflow.related_incidents,
    }
    state["final_response"] = (
        f"Matched workflow {workflow.workflow_id} with confidence "
        f"{state.get('retrieval_confidence', 0.0):.2f}. Follow the YAML workflow steps in order and honor role requirements."
    )
    return state
