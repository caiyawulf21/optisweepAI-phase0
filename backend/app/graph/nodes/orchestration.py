from __future__ import annotations

from backend.app.graph.state import AssistantState
from backend.app.services.workflow_loader import WorkflowLoader


def orchestration_node(state: AssistantState) -> AssistantState:
    loader = WorkflowLoader()
    workflow = loader.select_workflow(
        state.get("extracted_signals", {}),
        state.get("retrieval_confidence", 0.0),
    )
    state["selected_workflow_id"] = workflow.workflow_id if workflow else None
    return state
