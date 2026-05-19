from __future__ import annotations

from pydantic import BaseModel, Field


class WorkflowStep(BaseModel):
    step_id: str
    role_required: str
    instruction: str
    expected_outcome: str
    validation_check: str
    escalation_condition: str | None = None
    support_safe: bool = True
    stop_condition: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class WorkflowDefinition(BaseModel):
    workflow_id: str
    name: str
    version: str = "1.0"
    issue_category: str = "CAT-1"
    status: str = "draft"
    entry_conditions: list[str] = Field(default_factory=list)
    required_signals: list[str] = Field(default_factory=list)
    minimum_confidence: float = 0.65
    related_incidents: list[str] = Field(default_factory=list)
    procedure_refs: list[str] = Field(default_factory=list)
    escalation_conditions: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    steps: list[WorkflowStep] = Field(default_factory=list)


class WorkflowState(BaseModel):
    workflow_id: str | None = None
    current_step_id: str | None = None
    completed_step_ids: list[str] = Field(default_factory=list)
    available_steps: list[WorkflowStep] = Field(default_factory=list)
    status: str = "not_started"
