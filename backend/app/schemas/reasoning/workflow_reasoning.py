from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.schemas.canonical.provenance import AgentProvenance


ReasoningAction = Literal[
    "commit_branch",
    "clarify",
    "dynamic_procedure",
    "escalate",
    "defer",
]

ReasoningMode = Literal["routing", "runtime"]


class DeterministicBaseline(BaseModel):
    action: str = "defer"
    workflow_id: str | None = None
    next_node_id: str | None = None
    question_node_id: str | None = None
    coverage_ratio: float = 0.0
    reason: str = ""


class WorkflowReasoningContext(BaseModel):
    mode: ReasoningMode = "routing"
    operator_message: str = ""
    observed_signals: dict[str, bool] = Field(default_factory=dict)
    legacy_signals: dict[str, bool] = Field(default_factory=dict)
    extracted_components: list[str] = Field(default_factory=list)
    extracted_canonical_signals: dict[str, bool] = Field(default_factory=dict)
    retrieval_evidence: list[dict[str, Any]] = Field(default_factory=list)
    session_summary: dict[str, Any] = Field(default_factory=dict)
    deterministic_baseline: DeterministicBaseline = Field(
        default_factory=DeterministicBaseline
    )
    allowed_workflow_ids: list[str] = Field(default_factory=list)
    allowed_procedure_ids: list[str] = Field(default_factory=list)
    allowed_signal_keys: list[str] = Field(default_factory=list)
    allowed_citation_ids: list[str] = Field(default_factory=list)
    current_node: dict[str, Any] | None = None
    candidate_workflows: list[dict[str, Any]] = Field(default_factory=list)
    procedure_candidates: list[dict[str, Any]] = Field(default_factory=list)
    procedure_details: list[dict[str, Any]] = Field(default_factory=list)
    allowed_escalation_domains: list[str] = Field(default_factory=list)
    retrieval_inputs: list[Any] = Field(default_factory=list)


class WorkflowReasoningDecisionPayload(BaseModel):
    action: ReasoningAction
    confidence: float = 0.0
    rationale: str = ""
    citation_ids: list[str] = Field(default_factory=list)
    workflow_id: str | None = None
    current_node_id: str | None = None
    next_node_id: str | None = None
    branch_index: int | None = None
    implied_signals: dict[str, bool] = Field(default_factory=dict)
    question_node_id: str | None = None
    procedure_ids: list[str] = Field(default_factory=list)
    escalation_domain: str | None = None
    escalation_reason: str | None = None


class WorkflowReasoningDecision(BaseModel):
    action: ReasoningAction
    confidence: float
    rationale: str
    citation_ids: list[str] = Field(default_factory=list)
    workflow_id: str | None = None
    current_node_id: str | None = None
    next_node_id: str | None = None
    branch_index: int | None = None
    implied_signals: dict[str, bool] = Field(default_factory=dict)
    question_node_id: str | None = None
    procedure_ids: list[str] = Field(default_factory=list)
    escalation_domain: str | None = None
    escalation_reason: str | None = None
    model: str | None = None
    dropped_fields: list[str] = Field(default_factory=list)


class WorkflowReasoningResult(BaseModel):
    decision: WorkflowReasoningDecision | None = None
    baseline: DeterministicBaseline = Field(default_factory=DeterministicBaseline)
    applied: bool = False
    fallback_reason: str | None = None
    provenance: AgentProvenance | None = None
