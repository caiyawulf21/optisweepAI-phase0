from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ValidationState = Literal[
    "raw",
    "proposed",
    "draft",
    "candidate",
    "candidate_extracted",
    "merged_candidate",
    "needs_sme_review",
    "sme_reviewed",
    "approved",
    "approved_for_workflow",
    "deprecated",
    "validated",
    "rejected",
    "promoted",
]


class EvidenceReference(BaseModel):
    incident_id: str
    evidence_id: str
    source_artifact_id: str | None = None
    excerpt: str | None = None


class ProcedureStep(BaseModel):
    step_id: str
    instruction: str
    validation_check: str | None = None
    expected_outcome: str | None = None
    escalation_condition: str | None = None


class ProcedureCandidate(BaseModel):
    procedure_id: str
    title: str
    operational_intent: str
    role_required: str
    support_safe: bool
    steps: list[ProcedureStep] = Field(default_factory=list)
    validation_checks: list[str] = Field(default_factory=list)
    escalation_conditions: list[str] = Field(default_factory=list)
    related_incidents: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)
    status: ValidationState = "candidate_extracted"


class ReusableProcedure(BaseModel):
    procedure_id: str
    title: str
    operational_intent: str
    role_required: str
    support_safe: bool
    steps: list[ProcedureStep] = Field(default_factory=list)
    validation_checks: list[str] = Field(default_factory=list)
    escalation_conditions: list[str] = Field(default_factory=list)
    related_incidents: list[str] = Field(default_factory=list)
    source_candidate_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)
    status: ValidationState = "needs_sme_review"


class MergeReport(BaseModel):
    merge_id: str
    reusable_id: str
    source_candidate_ids: list[str]
    related_incidents: list[str]
    status: ValidationState = "merged_candidate"
    reasons: list[str] = Field(default_factory=list)


class SmeReviewQueueItem(BaseModel):
    review_item_id: str
    item_type: Literal["procedure", "workflow"]
    item_id: str
    related_incidents: list[str] = Field(default_factory=list)
    status: ValidationState = "needs_sme_review"
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)
