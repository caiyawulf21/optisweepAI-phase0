from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.app.schemas.canonical.procedure import GraphReadiness
from backend.app.schemas.canonical.provenance import AgentProvenance
from backend.app.schemas.canonical.workflow import BranchOperator, NodeType


class WorkflowPlanBranch(BaseModel):
    condition_signal: str | None = None
    operator: BranchOperator = "equals"
    value: Any = True
    label: str | None = None
    aliases: list[str] = Field(default_factory=list)
    next_node: str


class WorkflowPlanNode(BaseModel):
    node_id: str
    node_type: NodeType
    title: str | None = None
    question: str | None = None
    instruction: str | None = None
    why_this_matters: str | None = None
    how_to_check: list[str] = Field(default_factory=list)
    expected_healthy_state: str | None = None
    expected_failure_state: str | None = None
    answer_options: list[str] = Field(default_factory=list)
    procedure_ref: str | None = None
    procedure_refs: list[str] = Field(default_factory=list)
    requires_role: str | None = None
    support_safe: bool | None = None
    branches: list[WorkflowPlanBranch] = Field(default_factory=list)
    escalation_domain: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    source_artifacts: list[str] = Field(default_factory=list)
    screenshot_category_hints: list[str] = Field(default_factory=list)
    extra_requires_signals: list[str] = Field(default_factory=list)
    extra_produces_signals: list[str] = Field(default_factory=list)
    extra_affects_components: list[str] = Field(default_factory=list)
    extra_escalates_to: list[str] = Field(default_factory=list)
    extra_primary_screenshot_refs: list[str] = Field(default_factory=list)
    extra_supporting_screenshot_refs: list[str] = Field(default_factory=list)
    extra_visual_region_hints: list[str] = Field(default_factory=list)
    screenshot_required: bool | None = None


class WorkflowPlan(BaseModel):
    workflow_id: str
    canonical_title: str
    workflow_version: str = "0.1"
    issue_category: str | None = None
    source_workflow_candidate_ids: list[str] = Field(default_factory=list)
    entry_node_id: str
    nodes: list[WorkflowPlanNode]
    entry_conditions: list[str] = Field(default_factory=list)
    required_signals: list[str] = Field(default_factory=list)
    minimum_confidence: float = 0.65
    related_incidents: list[str] = Field(default_factory=list)
    escalation_conditions: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    provenance: AgentProvenance
    graph_readiness: GraphReadiness = Field(default_factory=GraphReadiness)
