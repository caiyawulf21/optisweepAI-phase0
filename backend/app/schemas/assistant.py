from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ResponseType = Literal[
    "answer",
    "guided_question",
    "playbook_candidates",
    "workflow_step",
    "escalation",
    "terminal",
]


INITIAL_CAT1_SIGNALS = (
    "agvs_stopped",
    "no_rms_alarm",
    "tipper_heartbeat_timeout",
    "hospital_tote_removal_hangs",
    "system_active_but_frozen",
    "bagout_failure",
    "ignition_or_wcs_down",
    "service_restart_required",
    "remote_access_unavailable",
    "ot_hardware_alarm_present",
    "safety_risk_present",
    "engineer_only_action_required",
    "heartbeat_recovered_after_restart",
    "user_requests_escalation",
)
# Deprecated name kept for older escalation helpers. Playbook first-turn gate
# vocabulary comes from Cosmos gate_phrase_table (or YAML fallback keys).


class Citation(BaseModel):
    source_id: str
    title: str
    reference: str | None = None
    excerpt: str | None = None


class RetrievalResult(BaseModel):
    record_id: str
    source_case_id: str | None = None
    title: str
    issue_category: str | None = None
    failure_signature: str | None = None
    matched_signals: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    citation: Citation
    source_notes: str | None = None
    cosine_score: float = 0.0
    jaccard_score: float = 0.0
    symptom_score: float = 0.0
    coverage: float = 0.0
    combined_score: float | None = None


class TroubleshootRequest(BaseModel):
    session_id: str
    user_message: str
    operator_role: str | None = None
    playbook_variant: str | None = None


class EscalationSummaryRequest(BaseModel):
    session_id: str
    workflow_id: str | None = None
    current_node_id: str | None = None
    escalation_reason: str | None = None


class EscalationSummaryResponse(BaseModel):
    session_id: str
    escalation_summary: dict[str, Any]


class ConversationInteraction(BaseModel):
    interaction_id: str
    session_id: str
    timestamp: str
    user_message: str
    response_type: str = "answer"
    selected_workflow_id: str | None = None
    current_node_id: str | None = None
    observed_signals: dict[str, bool] = Field(default_factory=dict)
    retrieval_result_ids: list[str] = Field(default_factory=list)
    escalation_triggered: bool = False
    final_response: str | None = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    assistant_response: dict[str, Any] = Field(default_factory=dict)
    runtime_trace: dict[str, Any] = Field(default_factory=dict)


class ConversationReplayResponse(BaseModel):
    session_id: str
    interactions: list[ConversationInteraction] = Field(default_factory=list)


class WorkflowSummary(BaseModel):
    """Sidebar/header summary of the active playbook."""

    workflow_id: str
    title: str
    current_node_id: str | None = None
    progress_label: str | None = None
    role_required: str | None = None


class TroubleshootResponse(BaseModel):
    session_id: str
    issue_category: str | None = None
    extracted_signals: dict[str, bool] = Field(default_factory=dict)
    extracted_observed_signals: dict[str, bool] = Field(default_factory=dict)
    retrieval_results: list[RetrievalResult] = Field(default_factory=list)
    retrieval_confidence: float = 0.0
    retrieval_confidence_reason: str | None = None
    canonical_images: list[dict[str, Any]] = Field(default_factory=list)
    selected_workflow_id: str | None = None
    workflow_state: dict[str, Any] = Field(default_factory=dict)
    escalation_required: bool = False
    escalation_reason: str | None = None
    final_response: str
    citations: list[Citation] = Field(default_factory=list)
    guided_question: dict[str, Any] | None = None
    escalation_summary: dict[str, Any] | None = None
    response_type: ResponseType | None = None
    workflow: WorkflowSummary | None = None
    workflow_step: dict[str, Any] | None = None
    escalation: dict[str, Any] | None = None
    terminal_state: dict[str, Any] | None = None
    role_warning: str | None = None
    runtime_trace: dict[str, Any] = Field(default_factory=dict)
