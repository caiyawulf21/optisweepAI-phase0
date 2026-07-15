from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.schemas.canonical.evidence import CanonicalEvidenceReference
from backend.app.schemas.canonical.procedure import GraphReadiness
from backend.app.schemas.canonical.provenance import AgentProvenance
from backend.app.schemas.canonical.relationship import (
    RelationshipEdgesSummary,
    RoleRequirement,
    WorkflowNodeRelationshipTracking,
)
from backend.app.schemas.canonical.visual_evidence import VisualEvidence


NodeType = Literal[
    "question",
    "decision",
    "diagnostic_check",
    "action",
    "validation",
    "escalation",
    "terminal",
]


BranchOperator = Literal[
    "equals",
    "not_equals",
    "present",
    "absent",
    "gte",
    "lte",
]


class WorkflowBranch(BaseModel):
    condition_signal: str | None = None
    operator: BranchOperator = "equals"
    value: Any = True
    label: str | None = None
    aliases: list[str] = Field(default_factory=list)
    next_node: str


class WorkflowNode(BaseModel):
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
    role_required: RoleRequirement | None = None
    support_safe: bool | None = None
    relationship_tracking: WorkflowNodeRelationshipTracking
    relationship_edges: RelationshipEdgesSummary | None = None
    visual_evidence: VisualEvidence
    branches: list[WorkflowBranch] = Field(default_factory=list)
    escalation_domain: str | None = None
    evidence_refs: list[CanonicalEvidenceReference] = Field(default_factory=list)
    source_artifacts: list[str] = Field(default_factory=list)
    preceding_node_ids: list[str] = Field(default_factory=list)


class WorkflowEdge(BaseModel):
    edge_id: str
    source_node_id: str
    target_node_id: str
    condition_signal: str | None = None
    operator: BranchOperator | None = None
    value: Any = None


class CanonicalWorkflow(BaseModel):
    workflow_id: str
    workflow_version: str = "0.1"
    canonical_title: str
    title: str | None = None
    purpose: str | None = None
    issue_category: str | None = None
    entry_conditions: list[str] = Field(default_factory=list)
    required_signals: list[str] = Field(default_factory=list)
    entry_signals: list[str] = Field(default_factory=list)
    minimum_confidence: float = 0.65
    related_incidents: list[str] = Field(default_factory=list)
    nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(default_factory=list)
    escalation_conditions: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    evidence_refs: list[CanonicalEvidenceReference] = Field(default_factory=list)
    source_artifacts: list[str] = Field(default_factory=list)
    provenance: AgentProvenance
    relationship_edges: RelationshipEdgesSummary | None = None
    graph_readiness: GraphReadiness = Field(default_factory=GraphReadiness)
