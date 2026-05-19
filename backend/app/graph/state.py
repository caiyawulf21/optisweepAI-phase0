from __future__ import annotations

from typing import Any, TypedDict

from backend.app.schemas.assistant import Citation, RetrievalResult


class AssistantState(TypedDict, total=False):
    session_id: str
    user_message: str
    extracted_signals: dict[str, bool]
    issue_category: str | None
    retrieval_results: list[RetrievalResult]
    retrieval_confidence: float
    selected_workflow_id: str | None
    workflow_state: dict[str, Any]
    escalation_required: bool
    escalation_reason: str | None
    final_response: str
    citations: list[Citation]


def create_initial_state(session_id: str, user_message: str) -> AssistantState:
    return {
        "session_id": session_id,
        "user_message": user_message,
        "extracted_signals": {},
        "issue_category": None,
        "retrieval_results": [],
        "retrieval_confidence": 0.0,
        "selected_workflow_id": None,
        "workflow_state": {},
        "escalation_required": False,
        "escalation_reason": None,
        "final_response": "",
        "citations": [],
    }
