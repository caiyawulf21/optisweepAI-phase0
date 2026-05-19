from __future__ import annotations

from pydantic import BaseModel, Field

from backend.app.schemas.procedure import EvidenceReference, ValidationState


class WorkflowCandidate(BaseModel):
    workflow_id: str
    title: str
    issue_category: str = "CAT-1"
    operational_intent: str
    required_signals: list[str] = Field(default_factory=list)
    procedure_refs: list[str] = Field(default_factory=list)
    related_incidents: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)
    escalation_conditions: list[str] = Field(default_factory=list)
    status: ValidationState = "candidate_extracted"


class ReusableWorkflowDefinition(BaseModel):
    workflow_id: str
    title: str
    issue_category: str = "CAT-1"
    operational_intent: str
    required_signals: list[str] = Field(default_factory=list)
    procedure_refs: list[str] = Field(default_factory=list)
    related_incidents: list[str] = Field(default_factory=list)
    source_candidate_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)
    escalation_conditions: list[str] = Field(default_factory=list)
    status: ValidationState = "needs_sme_review"
