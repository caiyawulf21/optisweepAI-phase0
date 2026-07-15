from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from backend.app.schemas.canonical.evidence import CanonicalEvidenceReference
from backend.app.schemas.canonical.provenance import AgentProvenance


class RelationshipTracking(BaseModel):
    parent_workflow_nodes: list[str] = Field(default_factory=list)
    parent_procedure_ids: list[str] = Field(default_factory=list)
    uses_subprocedures: list[str] = Field(default_factory=list)
    depends_on_procedures: list[str] = Field(default_factory=list)
    requires_signals: list[str] = Field(default_factory=list)
    produces_signals: list[str] = Field(default_factory=list)
    confirms_signals: list[str] = Field(default_factory=list)
    rules_out_signals: list[str] = Field(default_factory=list)
    produces_artifacts: list[str] = Field(default_factory=list)
    produces_context: list[str] = Field(default_factory=list)
    produces_state_changes: list[str] = Field(default_factory=list)
    affects_components: list[str] = Field(default_factory=list)
    requires_components: list[str] = Field(default_factory=list)
    requires_role: str | None = None
    escalates_to: list[str] = Field(default_factory=list)
    validated_by_incidents: list[str] = Field(default_factory=list)


class RoleRequirement(BaseModel):
    primary: str | None = None
    supporting: list[str] = Field(default_factory=list)
    escalation_owner: str | None = None
    access_required: list[str] = Field(default_factory=list)
    role_constraints: list[str] = Field(default_factory=list)


class SubprocedureRelationshipTracking(BaseModel):
    parent_procedure_id: str | None = None
    depends_on_subprocedures: list[str] = Field(default_factory=list)
    next_subprocedures: list[str] = Field(default_factory=list)
    requires_signals: list[str] = Field(default_factory=list)
    produces_signals: list[str] = Field(default_factory=list)
    affects_components: list[str] = Field(default_factory=list)
    requires_role: str | None = None


class StepRelationshipTracking(BaseModel):
    parent_subprocedure_id: str | None = None
    requires_signals: list[str] = Field(default_factory=list)
    produces_signals: list[str] = Field(default_factory=list)
    affects_components: list[str] = Field(default_factory=list)


class WorkflowNodeRelationshipTracking(BaseModel):
    parent_workflow_id: str | None = None
    procedure_ref: str | None = None
    requires_signals: list[str] = Field(default_factory=list)
    produces_signals: list[str] = Field(default_factory=list)
    affects_components: list[str] = Field(default_factory=list)
    escalates_to: list[str] = Field(default_factory=list)


class RelationshipEdgesSummary(BaseModel):
    requires_signals: list[str] = Field(default_factory=list)
    produces_signals: list[str] = Field(default_factory=list)
    affects_components: list[str] = Field(default_factory=list)
    uses_procedures: list[str] = Field(default_factory=list)
    validated_by_incidents: list[str] = Field(default_factory=list)
    supported_by_evidence: list[str] = Field(default_factory=list)
    uses_screenshots: list[str] = Field(default_factory=list)
    escalates_to: list[str] = Field(default_factory=list)
    checks_components: list[str] = Field(default_factory=list)
    branches_to_nodes: list[str] = Field(default_factory=list)
    applies_to_components: list[str] = Field(default_factory=list)
    requires_roles: list[str] = Field(default_factory=list)
    requires_tools: list[str] = Field(default_factory=list)
    validates_signals: list[str] = Field(default_factory=list)
    used_by_workflows: list[str] = Field(default_factory=list)


RelationEdgeType = Literal[
    "HAS_NODE",
    "USES_PROCEDURE",
    "USES_SUBPROCEDURE",
    "CONTAINS_STEP",
    "PRODUCES_SIGNAL",
    "AFFECTS",
    "REQUIRES_ROLE",
    "VALIDATED_BY",
    "ROUTES_TO",
    "ESCALATES_TO",
    "REFERENCES_SCREENSHOT",
    "DEPENDS_ON",
    "REQUIRES_SIGNAL",
    "CONFIRMS_SIGNAL",
    "RULES_OUT_SIGNAL",
]


class RelationshipEdge(BaseModel):
    edge_id: str
    source_type: str
    source_id: str
    relation: RelationEdgeType
    target_type: str
    target_id: str
    evidence_refs: list[CanonicalEvidenceReference] = Field(default_factory=list)
    source_artifacts: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    provenance: AgentProvenance
