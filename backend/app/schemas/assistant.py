from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


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


ResponseType = Literal[
    "answer",
    "guided_question",
    "playbook_candidates",
    "workflow_step",
    "dynamic_procedure_step",
    "escalation",
    "terminal",
]


INITIAL_CAT1_SIGNALS = (
    "agvs_stopped",
    "no_rms_alarm",
    "tipper_heartbeat_timeout",
    "hospital_tote_removal_hangs",
    "system_active_but_frozen",
    "ignition_or_wcs_down",
    "service_restart_required",
    "remote_access_unavailable",
    "ot_hardware_alarm_present",
    "safety_risk_present",
    "engineer_only_action_required",
    "heartbeat_recovered_after_restart",
    "user_requests_escalation",
)


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
    """Phase 1 Step 11 — sidebar/header summary of the active canonical workflow.

    Emitted by :func:`backend.app.api.troubleshoot._build_troubleshoot_response`
    whenever the request resolved to a canonical workflow (legacy or the
    dynamic runtime added in Step 10). ``progress_label`` is intentionally a
    free-form string ("Step 3 of 13" when the canonical loader can resolve a
    total node count, "Step 3" otherwise) so the UI does not have to imply a
    real percentage progress bar.
    """

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
    canonical_route_mode: CanonicalRouteMode | None = None
    canonical_workflow_id: str | None = None
    canonical_next_node_id: str | None = None
    canonical_next_question_text: str | None = None
    canonical_coverage_ratio: float | None = None
    canonical_signal_translation: dict[str, bool] | None = None
    guided_question: dict[str, Any] | None = None
    escalation_summary: dict[str, Any] | None = None
    response_type: ResponseType | None = None
    workflow: WorkflowSummary | None = None
    workflow_step: dict[str, Any] | None = None
    escalation: dict[str, Any] | None = None
    terminal_state: dict[str, Any] | None = None
    mode: RuntimeMode | None = None
    dynamic_procedure_step: dict[str, Any] | None = None
    dynamic_path_progress: dict[str, Any] | None = None
    role_warning: str | None = None
    runtime_trace: dict[str, Any] = Field(default_factory=dict)
