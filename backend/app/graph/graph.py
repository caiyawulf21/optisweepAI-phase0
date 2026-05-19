from __future__ import annotations

from langgraph.graph import END, StateGraph

from backend.app.graph.nodes.escalation import escalation_node
from backend.app.graph.nodes.orchestration import orchestration_node
from backend.app.graph.nodes.retrieval import retrieval_node
from backend.app.graph.nodes.symptom_extraction import symptom_extraction_node
from backend.app.graph.nodes.workflow import workflow_node
from backend.app.graph.state import AssistantState, create_initial_state


def build_troubleshooting_graph():
    graph = StateGraph(AssistantState)
    graph.add_node("symptom_extraction", symptom_extraction_node)
    graph.add_node("retrieval", retrieval_node)
    graph.add_node("orchestration", orchestration_node)
    graph.add_node("workflow", workflow_node)
    graph.add_node("escalation", escalation_node)
    graph.set_entry_point("symptom_extraction")
    graph.add_edge("symptom_extraction", "retrieval")
    graph.add_edge("retrieval", "orchestration")
    graph.add_edge("orchestration", "workflow")
    graph.add_edge("workflow", "escalation")
    graph.add_edge("escalation", END)
    return graph.compile()


def run_troubleshooting(session_id: str, user_message: str) -> AssistantState:
    app = build_troubleshooting_graph()
    return app.invoke(create_initial_state(session_id, user_message))
