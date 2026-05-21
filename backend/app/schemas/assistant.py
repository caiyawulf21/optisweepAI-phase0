from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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


class TroubleshootRequest(BaseModel):
    session_id: str
    user_message: str


class TroubleshootResponse(BaseModel):
    session_id: str
    issue_category: str | None = None
    extracted_signals: dict[str, bool] = Field(default_factory=dict)
    retrieval_results: list[RetrievalResult] = Field(default_factory=list)
    retrieval_confidence: float = 0.0
    selected_workflow_id: str | None = None
    workflow_state: dict[str, Any] = Field(default_factory=dict)
    escalation_required: bool = False
    escalation_reason: str | None = None
    final_response: str
    citations: list[Citation] = Field(default_factory=list)
