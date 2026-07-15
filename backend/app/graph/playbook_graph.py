from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from backend.app.agents.runtime import (
    apply_branch_answer,
    apply_candidate_selection,
    embed_query,
    execute_playbook_node,
    extract_symptoms,
    hybrid_search,
    pin_playbook,
    request_more_symptoms,
    save_playbook_session,
    session_load,
    template_answer_from_hits,
)
from backend.app.graph.playbook_state import PlaybookSessionSlice


def _after_session(state: dict[str, Any]) -> str:
    branch_state = state.get("branch_state") or {}
    if branch_state.get("awaiting_candidate"):
        return "pick_candidate"
    if not state.get("active_playbook_id"):
        return "extract"
    if branch_state.get("awaiting_branch"):
        return "branch"
    return "execute"


def _after_extract(state: dict[str, Any]) -> str:
    if state.get("needs_symptom_clarification"):
        return "save"
    return "retrieve"


def _after_pin(state: dict[str, Any]) -> str:
    if state.get("active_playbook_id"):
        return "execute"
    return "ask_more"


def _after_branch(state: dict[str, Any]) -> str:
    route = str(state.get("_route_after_branch") or "execute").strip().lower()
    if route in {"extract", "save", "execute"}:
        return route
    return "execute"


def _after_candidate(state: dict[str, Any]) -> str:
    if str(state.get("_route_after_candidate") or "").strip().lower() == "extract":
        return "extract"
    if state.get("active_playbook_id"):
        return "execute"
    return "save"


def session_save_node(state: dict[str, Any]) -> dict[str, Any]:
    slice_: PlaybookSessionSlice = state["_playbook_slice"]
    slice_.active_playbook_id = state.get("active_playbook_id")
    slice_.active_case_id = state.get("active_case_id")
    slice_.current_node_id = state.get("current_node_id")
    slice_.branch_state = dict(state.get("branch_state") or {})
    slice_.completed_node_ids = list(state.get("completed_node_ids") or [])
    if state.get("retrieval_confidence") is not None:
        slice_.last_retrieval_confidence = float(state.get("retrieval_confidence") or 0.0)
    if state.get("extracted_observed_signals"):
        slice_.observed_signals = dict(state.get("extracted_observed_signals") or {})
    save_playbook_session(state["session_id"], slice_, state=state)
    return state


def playbook_retrieve_node(state: dict[str, Any]) -> dict[str, Any]:
    state = embed_query(state)
    variant = state.get("playbook_variant") or "prompt_a"
    record_type = "playbook_prompt_a" if variant == "prompt_a" else "playbook_prompt_b"
    state = hybrid_search(state, record_types={record_type}, top_k=5)
    return pin_playbook(state)


def build_playbook_graph():
    graph = StateGraph(dict)
    graph.add_node("session_load", session_load)
    graph.add_node("extract_symptoms", extract_symptoms)
    graph.add_node("playbook_retrieve", playbook_retrieve_node)
    graph.add_node("playbook_execute", execute_playbook_node)
    graph.add_node("branch_clarification", apply_branch_answer)
    graph.add_node("pick_candidate", apply_candidate_selection)
    graph.add_node("request_more_symptoms", request_more_symptoms)
    graph.add_node("session_save", session_save_node)
    graph.set_entry_point("session_load")
    graph.add_conditional_edges(
        "session_load",
        _after_session,
        {
            "execute": "playbook_execute",
            "extract": "extract_symptoms",
            "branch": "branch_clarification",
            "pick_candidate": "pick_candidate",
        },
    )
    graph.add_conditional_edges(
        "extract_symptoms",
        _after_extract,
        {"retrieve": "playbook_retrieve", "save": "session_save"},
    )
    graph.add_conditional_edges(
        "playbook_retrieve",
        _after_pin,
        {"execute": "playbook_execute", "ask_more": "request_more_symptoms"},
    )
    graph.add_conditional_edges(
        "pick_candidate",
        _after_candidate,
        {"execute": "playbook_execute", "save": "session_save", "extract": "extract_symptoms"},
    )
    graph.add_edge("playbook_execute", "session_save")
    graph.add_conditional_edges(
        "branch_clarification",
        _after_branch,
        {
            "execute": "playbook_execute",
            "extract": "extract_symptoms",
            "save": "session_save",
        },
    )
    graph.add_edge("request_more_symptoms", "session_save")
    graph.add_edge("session_save", END)
    return graph.compile()


def build_retrieve_graph():
    graph = StateGraph(dict)
    graph.add_node("embed", embed_query)
    graph.add_node("search", lambda state: hybrid_search(
        state,
        record_types=set(state.get("record_types") or []),
        top_k=int(state.get("top_k") or 5),
    ))
    graph.add_node("respond", template_answer_from_hits)
    graph.set_entry_point("embed")
    graph.add_edge("embed", "search")
    graph.add_edge("search", "respond")
    graph.add_edge("respond", END)
    return graph.compile()
