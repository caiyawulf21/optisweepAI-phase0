from __future__ import annotations

from pydantic import BaseModel, Field

from backend.app.schemas.procedure import EvidenceReference, ValidationState


class WorkflowCandidateStep(BaseModel):
    step_id: str
    step_type: str
    question: str | None = None
    why_asked: str | None = None
    instruction: str
    role_required: str | None = None
    support_safe: bool = True
    procedure_refs: list[str] = Field(default_factory=list)
    image_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)
    expected_outcome: str | None = None
    branches: list[dict] = Field(default_factory=list)
    escalation_conditions: list[str] = Field(default_factory=list)


class WorkflowCandidate(BaseModel):
    workflow_id: str
    workflow_version: str = "0.1"
    title: str | None = None
    issue_category: str | None = None
    operational_intent: str | None = None
    source_workflow_candidate_ids: list[str] = Field(default_factory=list)
    entry_conditions: list[str] = Field(default_factory=list)
    required_signals: list[str] = Field(default_factory=list)
    shared_signals: list[str] = Field(default_factory=list)
    differing_signals: list[str] = Field(default_factory=list)
    common_root_cause_hypotheses: list[str] = Field(default_factory=list)
    exclusion_conditions: list[str] = Field(default_factory=list)
    minimum_confidence: float = 0.75
    roles_allowed: list[str] = Field(default_factory=list)
    steps: list[WorkflowCandidateStep] = Field(default_factory=list)
    validation_checks: list[str] = Field(default_factory=list)
    procedure_refs: list[str] = Field(default_factory=list)
    related_incidents: list[str] = Field(default_factory=list)
    related_cases: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)
    image_refs: list[str] = Field(default_factory=list)
    escalation_conditions: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    status: ValidationState = "draft"
    validation_status: str = "needs_review"


class WorkflowProcedureLink(BaseModel):
    link_id: str
    workflow_id: str
    procedure_id: str
    link_type: str = "workflow_uses_procedure"
    step_ids: list[str] = Field(default_factory=list)
    source_workflow_candidate_ids: list[str] = Field(default_factory=list)
    source_procedure_candidate_ids: list[str] = Field(default_factory=list)
    related_incidents: list[str] = Field(default_factory=list)
    shared_signals: list[str] = Field(default_factory=list)
    shared_resolution_patterns: list[str] = Field(default_factory=list)
    similar_root_cause_hypotheses: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)
    image_refs: list[str] = Field(default_factory=list)
    rationale: str | None = None
    merge_confidence: float = 0.0
    merge_risk_notes: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    validation_status: str = "needs_review"


class ReviewNote(BaseModel):
    note_id: str
    artifact_type: str
    artifact_id: str
    severity: str
    note: str
    recommended_review_owner: str
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)


class ReusableWorkflowDefinition(BaseModel):
    workflow_id: str
    title: str | None = None
    issue_category: str | None = None
    operational_intent: str | None = None
    required_signals: list[str] = Field(default_factory=list)
    procedure_refs: list[str] = Field(default_factory=list)
    related_incidents: list[str] = Field(default_factory=list)
    source_candidate_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)
    escalation_conditions: list[str] = Field(default_factory=list)
    status: ValidationState = "needs_sme_review"
