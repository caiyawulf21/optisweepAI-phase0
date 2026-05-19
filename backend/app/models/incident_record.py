from __future__ import annotations

from pydantic import Field

from backend.app.models.base import KnowledgeDocument


class IncidentRecord(KnowledgeDocument):
    dataset: str = "dataset_1_canonical_incident"
    incident_id: str
    source_case_id: str | None = None
    issue_category: str
    site: str | None = None
    customer: str | None = None
    priority: str | None = None
    failure_signature: list[str] = Field(default_factory=list)
    symptom_summary: str | None = None
    component: list[str] = Field(default_factory=list)
    observed_failure_signals: list[str] = Field(default_factory=list)
    diagnostic_signals: list[str] = Field(default_factory=list)
    action_signals: list[str] = Field(default_factory=list)
    recovery_validation_signals: list[str] = Field(default_factory=list)
    escalation_signals: list[str] = Field(default_factory=list)
    candidate_inferred_causes: list[dict] = Field(default_factory=list)
    validated_root_cause: bool = False
    resolution_summary: str | None = None
    escalated: bool | None = None
    escalation_domains: list[str] = Field(default_factory=list)
    workflow_candidate: bool | None = None
    resolution_status: str | None = None
