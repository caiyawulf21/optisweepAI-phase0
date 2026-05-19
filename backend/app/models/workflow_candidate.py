from __future__ import annotations

from typing import Literal

from pydantic import Field

from backend.app.models.base import KnowledgeDocument


WorkflowCandidateReviewStatus = Literal["needs_review", "in_review", "accepted", "rejected", "promoted"]
WorkflowCandidateStatus = Literal["candidate", "validated", "rejected"]


class WorkflowCandidate(KnowledgeDocument):
    dataset: str = "dataset_2a_workflow_candidate"
    candidate_type: str = "proposed"
    source_incident_ids: list[str] = Field(default_factory=list)
    target_workflow_id: str | None = None
    candidate_workflow_name: str | None = None
    proposed_change: str | None = None
    reason: str | None = None
    issue_category: str | None = None
    workflow_step_id: str | None = None
    step_type: str | None = None
    node_type: str | None = None
    decision_question: str | None = None
    question: str | None = None
    why_asked: str | None = None
    candidate_step: str | None = None
    entry_points: list[str] = Field(default_factory=list)
    initial_symptoms: list[str] = Field(default_factory=list)
    diagnoses: list[str] = Field(default_factory=list)
    entry_conditions: list[str] = Field(default_factory=list)
    required_signals: list[str] = Field(default_factory=list)
    negative_signals: list[str] = Field(default_factory=list)
    exclusion_conditions: list[str] = Field(default_factory=list)
    role_constraints: list[str] = Field(default_factory=list)
    next_procedure_refs: list[str] = Field(default_factory=list)
    procedure_refs: list[str] = Field(default_factory=list)
    success_routes: list[str] = Field(default_factory=list)
    failure_routes: list[str] = Field(default_factory=list)
    escalation_conditions: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    image_refs: list[str] = Field(default_factory=list)
    region_ids: list[str] = Field(default_factory=list)
    status: WorkflowCandidateStatus = "candidate"
    review_status: WorkflowCandidateReviewStatus = "needs_review"
    reviewer: str | None = None
    review_notes: str | None = None
    reviewed_at: str | None = None
