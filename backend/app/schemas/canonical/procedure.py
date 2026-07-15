from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.schemas.canonical.evidence import CanonicalEvidenceReference
from backend.app.schemas.canonical.provenance import AgentProvenance
from backend.app.schemas.canonical.relationship import (
    RelationshipEdgesSummary,
    RelationshipTracking,
    RoleRequirement,
    StepRelationshipTracking,
    SubprocedureRelationshipTracking,
)
from backend.app.schemas.canonical.visual_evidence import (
    CanonicalImage,
    SourceArtifact,
    StepVisualEvidence,
    VisualEvidence,
)


ProcedureType = Literal[
    "diagnostic_check",
    "recovery_action",
    "validation",
    "evidence_collection",
    "coordination",
    "observation",
    "action",
    "state_review",
    "operator_action",
    "support_action",
]


class GraphReadiness(BaseModel):
    relationship_complete: bool = False
    signal_complete: bool = False
    visual_evidence_complete: bool = False
    workflow_ready: bool = False
    execution_ready: bool = False


class OperatorGuidance(BaseModel):
    how_to_access: str | None = None
    what_to_look_for: str | None = None
    normal_example: str | None = None
    abnormal_example: str | None = None


class ProcedureRoleModel(BaseModel):
    primary_role: str | None = None
    supporting_roles: list[str] = Field(default_factory=list)
    escalation_owner: str | None = None


class ExpectedVisualState(BaseModel):
    state: str
    description: str


class StepVisualValidation(BaseModel):
    validation_type: str | None = None
    expected_visual_states: list[ExpectedVisualState] = Field(default_factory=list)


class CanonicalStep(BaseModel):
    step_id: str
    title: str | None = None
    instruction: str
    relationship_tracking: StepRelationshipTracking
    visual_evidence: StepVisualEvidence
    evidence_refs: list[CanonicalEvidenceReference] = Field(default_factory=list)
    produces_signals: list[str] = Field(default_factory=list)
    rules_out_signals: list[str] = Field(default_factory=list)
    expected_outcome: str | None = None
    validation_check: str | None = None
    visual_validation: StepVisualValidation | None = None
    escalation_condition: str | None = None
    role_required: str | None = None
    role_requirement: RoleRequirement | None = None
    support_safe: bool | None = None
    operator_guidance: OperatorGuidance | None = None


class CanonicalSubprocedure(BaseModel):
    subprocedure_id: str
    canonical_title: str | None = None
    parent_procedure_id: str | None = None
    relationship_tracking: SubprocedureRelationshipTracking
    visual_evidence: VisualEvidence
    steps: list[CanonicalStep] = Field(default_factory=list)
    evidence_refs: list[CanonicalEvidenceReference] = Field(default_factory=list)
    source_artifacts: list[str] = Field(default_factory=list)
    role_required: str | None = None
    role_requirement: RoleRequirement | None = None
    relationship_edges: RelationshipEdgesSummary | None = None
    operator_guidance: OperatorGuidance | None = None


class ProcedureSourceVariant(BaseModel):
    source_procedure_id: str
    title: str | None = None
    operational_intent: str | None = None
    role_required: str | None = None
    support_safe: bool | None = None
    related_incidents: list[str] = Field(default_factory=list)
    evidence_refs: list[CanonicalEvidenceReference] = Field(default_factory=list)
    source_artifacts: list[str] = Field(default_factory=list)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    quality_tier: str | None = None
    source_file: str | None = None
    variant_id: str | None = None
    source_incident_id: str | None = None
    source_systems: list[str] = Field(default_factory=list)
    variant_signals: list[str] = Field(default_factory=list)
    variant_screenshots: list[str] = Field(default_factory=list)
    canonical_images: list[CanonicalImage] = Field(default_factory=list)
    role_seed_enrichment: dict[str, Any] = Field(default_factory=dict)
    runtime_enrichment_provenance: AgentProvenance | None = None
    include_in_demo: bool = True
    demo_status: str = "approved_for_demo"
    variant_notes: list[str] = Field(default_factory=list)
    variant_differences: list[str] = Field(default_factory=list)


class CanonicalProcedure(BaseModel):
    procedure_id: str
    canonical_title: str
    title: str | None = None
    purpose: str | None = None
    entry_symptoms: list[str] = Field(default_factory=list)
    entry_signals: list[str] = Field(default_factory=list)
    exclusion_signals: list[str] = Field(default_factory=list)
    procedure_goal: str | None = None
    procedure_outcome: str | None = None
    issue_categories: list[str] = Field(default_factory=list)
    roles_allowed: list[str] = Field(default_factory=list)
    estimated_duration_minutes: int | None = None
    prerequisites: list[str] = Field(default_factory=list)
    procedure_type: ProcedureType
    support_safe: bool | None = None
    role_model: ProcedureRoleModel | None = None
    relationship_tracking: RelationshipTracking
    relationship_edges: RelationshipEdgesSummary | None = None
    visual_evidence: VisualEvidence
    evidence_refs: list[CanonicalEvidenceReference] = Field(default_factory=list)
    source_artifacts: list[str] = Field(default_factory=list)
    source_artifact_records: list[SourceArtifact] = Field(default_factory=list)
    source_procedure_candidate_ids: list[str] = Field(default_factory=list)
    source_variants: list[ProcedureSourceVariant] = Field(default_factory=list)
    subprocedures: list[CanonicalSubprocedure] = Field(default_factory=list)
    operator_guidance: OperatorGuidance | None = None
    navigation_path: list[str] = Field(default_factory=list)
    navigation_instructions: str | None = None
    next_procedure_candidates: list[dict[str, str]] = Field(default_factory=list)
    role_required: str | None = None
    role_requirement: RoleRequirement | None = None
    provenance: AgentProvenance
    status: str = "seed_canonical"
    graph_readiness: GraphReadiness = Field(default_factory=GraphReadiness)
    discovery_cluster_size: int = 1
    source_systems: list[str] = Field(default_factory=list)
    canonical_images: list[CanonicalImage] = Field(default_factory=list)
    role_seed_enrichment: dict[str, Any] = Field(default_factory=dict)
    include_in_demo: bool = True
    demo_status: str = "approved_for_demo"
