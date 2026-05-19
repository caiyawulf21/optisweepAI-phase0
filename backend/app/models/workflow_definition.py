from __future__ import annotations

from typing import Literal

from pydantic import Field

from backend.app.models.base import KnowledgeDocument


WorkflowDefinitionStatus = Literal["proposed", "draft", "approved_for_workflow", "sme_reviewed", "approved", "deprecated"]


class WorkflowDefinition(KnowledgeDocument):
    dataset: str = "dataset_2a_workflow_definition"
    workflow_id: str
    workflow_version: str = "1.0"
    status: WorkflowDefinitionStatus = "draft"
    issue_category: str
    title: str | None = None
    operational_intent: str | None = None
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
    related_incidents: list[str] = Field(default_factory=list)
    source_candidate_ids: list[str] = Field(default_factory=list)
    runtime_workflow_refs: list[str] = Field(default_factory=list)
