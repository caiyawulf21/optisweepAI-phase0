from __future__ import annotations

from pydantic import Field

from backend.app.models.base import KnowledgeDocument


class IncidenceWorkflowDefinition(KnowledgeDocument):
    dataset: str = "dataset_2a_incidence_workflow_definition"
    incidence_workflow_id: str
    workflow_version: str = "1.0"
    status: str = "needs_sme_review"
    issue_category: str
    source_incident_ids: list[str] = Field(default_factory=list)
    entry_points: list[str] = Field(default_factory=list)
    initial_symptoms: list[str] = Field(default_factory=list)
    diagnoses: list[str] = Field(default_factory=list)
    entry_conditions: list[str] = Field(default_factory=list)
    required_signals: list[str] = Field(default_factory=list)
    exclusion_conditions: list[str] = Field(default_factory=list)
    minimum_confidence: float | None = None
    roles_allowed: list[str] = Field(default_factory=list)
    steps: list[dict] = Field(default_factory=list)
    escalation_conditions: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    procedure_refs: list[str] = Field(default_factory=list)
    related_cases: list[str] = Field(default_factory=list)
    runtime_workflow_refs: list[str] = Field(default_factory=list)
