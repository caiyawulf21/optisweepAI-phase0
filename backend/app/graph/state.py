from __future__ import annotations

from typing import Any, Literal, TypedDict

from backend.app.schemas.assistant import Citation, RetrievalResult


CanonicalRouteMode = Literal[
    "disabled",
    "no_execution_ready_workflows",
    "approved",
    "guided_diagnostic",
    "escalation",
    "fallback_legacy",
    "dynamic_procedure_guidance",
    "retrieval_only",
]


RuntimeMode = Literal[
    "canonical_workflow",
    "dynamic_procedure_guidance",
    "retrieval_only",
    "escalation",
]


class AssistantState(TypedDict, total=False):
    session_id: str
    user_message: str
    operator_role: str | None
    case_triage_mode: str | None
    case_triage_confirmed: bool | None
    case_triage_top_matches: list[dict[str, Any]]
    case_triage_confirmation_question: str | None
    case_triage_answer: str | None
    case_triage_seed_message: str | None
    case_triage_seed_signals: dict[str, bool]
    case_triage_seed_canonical_signals: dict[str, bool]
    case_triage_seed_components: list[str]
    case_triage_selected_case_id: str | None
    suggested_workflow_ids: list[str]
    suggested_workflow_id: str | None
    case_triage_debug: dict[str, Any] | None
    extracted_signals: dict[str, bool]
    extracted_observed_signals: dict[str, bool]
    extracted_canonical_signals: dict[str, bool]
    extracted_components: list[str]
    extracted_signal_metadata: dict[str, Any] | None
    issue_category: str | None
    retrieval_results: list[RetrievalResult]
    retrieval_confidence: float
    canonical_images: list[dict[str, Any]]
    selected_workflow_id: str | None
    workflow_state: dict[str, Any]
    escalation_required: bool
    escalation_reason: str | None
    final_response: str
    citations: list[Citation]
    canonical_route_mode: CanonicalRouteMode | None
    canonical_workflow_id: str | None
    canonical_next_node_id: str | None
    canonical_next_question_text: str | None
    canonical_coverage_ratio: float | None
    canonical_signal_translation: dict[str, bool] | None
    guided_question: dict[str, Any] | None
    escalation_summary: dict[str, Any] | None
    mode: RuntimeMode | None
    dynamic_procedure_state: dict[str, Any] | None
    dynamic_path_progress: dict[str, Any] | None
    dynamic_procedure_routing_diagnostics: dict[str, Any] | None
    workflow_reasoning_decision: dict[str, Any] | None
    workflow_reasoning_baseline: dict[str, Any] | None
    workflow_reasoning_applied: bool
    workflow_reasoning_fallback_reason: str | None


def create_initial_state(session_id: str, user_message: str) -> AssistantState:
    return {
        "session_id": session_id,
        "user_message": user_message,
        "operator_role": None,
        "case_triage_mode": None,
        "case_triage_confirmed": None,
        "case_triage_top_matches": [],
        "case_triage_confirmation_question": None,
        "case_triage_answer": None,
        "case_triage_seed_message": None,
        "case_triage_seed_signals": {},
        "case_triage_seed_canonical_signals": {},
        "case_triage_seed_components": [],
        "case_triage_selected_case_id": None,
        "suggested_workflow_ids": [],
        "suggested_workflow_id": None,
        "case_triage_debug": None,
        "extracted_signals": {},
        "extracted_observed_signals": {},
        "extracted_canonical_signals": {},
        "extracted_components": [],
        "extracted_signal_metadata": None,
        "issue_category": None,
        "retrieval_results": [],
        "retrieval_confidence": 0.0,
        "canonical_images": [],
        "selected_workflow_id": None,
        "workflow_state": {},
        "escalation_required": False,
        "escalation_reason": None,
        "final_response": "",
        "citations": [],
        "canonical_route_mode": None,
        "canonical_workflow_id": None,
        "canonical_next_node_id": None,
        "canonical_next_question_text": None,
        "canonical_coverage_ratio": None,
        "canonical_signal_translation": None,
        "guided_question": None,
        "escalation_summary": None,
        "mode": None,
        "dynamic_procedure_state": None,
        "dynamic_path_progress": None,
        "dynamic_procedure_routing_diagnostics": None,
        "workflow_reasoning_decision": None,
        "workflow_reasoning_baseline": None,
        "workflow_reasoning_applied": False,
        "workflow_reasoning_fallback_reason": None,
    }
