"""Runtime Pydantic models for the dynamic procedure-guidance runtime.

The shapes here are the source-of-truth for the fallback path; they do
NOT replace any existing canonical schema or response model. The
canonical workflow runtime keeps using its own structured payloads
unchanged. These models are introduced so the new selector + path
assembler + LangGraph node can pass deterministic, typed values around
without leaking through dict-of-Any.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.schemas.assistant import Citation
from backend.app.schemas.canonical import CanonicalEvidenceReference


RuntimeMode = Literal[
    "canonical_workflow",
    "dynamic_procedure_guidance",
    "retrieval_only",
    "escalation",
]


StepResponseType = Literal[
    "workflow",
    "workflow_step",
    "guided_question",
    "dynamic_procedure_step",
    "escalation",
    "terminal_state",
]


SignalSource = Literal["user", "extracted", "produced", "derived"]


class RuntimeSignal(BaseModel):
    """A single observed signal annotated with provenance.

    The dynamic procedure-guidance runtime needs to remember WHERE each
    signal came from (operator answer vs. retrieval-derived vs. produced
    by a procedure step) so it can rank candidates and audit decisions
    without re-running symptom extraction.
    """

    key: str
    value: bool
    source: SignalSource = "extracted"
    produced_by_procedure_id: str | None = None
    turn_index: int = 0


class RuntimeProcedureMatch(BaseModel):
    """A scored candidate procedure for the dynamic-guidance path.

    The selector ranks ``CanonicalProcedure`` records into a list of
    these and the path assembler walks the top N. Every component score
    is normalised to ``[0, 1]``; the composite ``score`` is the sum of
    weighted features (see :mod:`dynamic_procedure_selector`).
    """

    procedure_id: str
    score: float = 0.0
    signal_overlap: float = 0.0
    component_overlap: float = 0.0
    entry_symptom_overlap: float = 0.0
    retrieval_overlap: float = 0.0
    incident_overlap: float = 0.0
    source_authority: float = 0.0
    relationship_strength: float = 0.0
    support_safe: bool = True
    requires_role: str | None = None
    engineer_only: bool = False
    selection_rationale: str = ""
    citations: list[Citation] = Field(default_factory=list)
    evidence_refs: list[CanonicalEvidenceReference] = Field(default_factory=list)
    source_artifacts: list[str] = Field(default_factory=list)
    entry_symptoms: list[str] = Field(default_factory=list)
    entry_signals: list[str] = Field(default_factory=list)
    exclusion_signals: list[str] = Field(default_factory=list)
    procedure_goal: str | None = None
    procedure_outcome: str | None = None
    operator_guidance: dict[str, Any] | None = None
    navigation_path: list[str] = Field(default_factory=list)
    navigation_instructions: str | None = None
    next_procedure_candidates: list[dict[str, str]] = Field(default_factory=list)


class RuntimeProcedureStep(BaseModel):
    """A single executable step inside a :class:`DynamicProcedurePath`.

    Steps are EITHER a question (``question`` set, ``allowed_answers``
    populated) OR an instruction (``instruction`` set). They always
    carry citations and source refs so guardrails can assert that no
    ungrounded action ever surfaces to the operator.
    """

    step_id: str
    procedure_id: str
    subprocedure_id: str | None = None
    instruction: str | None = None
    question: str | None = None
    allowed_answers: list[str] = Field(default_factory=list)
    evidence_refs: list[CanonicalEvidenceReference] = Field(default_factory=list)
    source_artifacts: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    support_safe: bool = True
    role_required: str | None = None
    produces_signals: list[str] = Field(default_factory=list)
    confirms_signals: list[str] = Field(default_factory=list)
    rules_out_signals: list[str] = Field(default_factory=list)
    selection_rationale: str = ""
    visual_validation: dict[str, Any] | None = None
    operator_guidance: dict[str, Any] | None = None

    def has_grounding(self) -> bool:
        """Return True iff the step has at least one evidence/citation/source ref.

        Used by the path assembler + tests as the "every emitted step has
        citations or source refs" guardrail. We accept any of the three
        forms because not every canonical procedure has the full triple.
        """
        return bool(self.evidence_refs or self.source_artifacts or self.citations)


class DynamicProcedurePath(BaseModel):
    """A session-only assembled troubleshooting path.

    NEVER written to disk. NEVER promoted to ``data/workflows/canonical/``.
    The hard-coded ``validation_status`` is the runtime guardrail: any
    consumer that reads this object knows the path is unapproved and
    must be presented to the user as procedure-guided troubleshooting,
    not as an approved workflow.
    """

    path_id: str
    created_at: str
    validation_status: Literal["runtime_generated_unapproved"] = (
        "runtime_generated_unapproved"
    )
    procedures: list[RuntimeProcedureMatch] = Field(default_factory=list)
    steps: list[RuntimeProcedureStep] = Field(default_factory=list)
    escalation_triggers: list[str] = Field(default_factory=list)
    produced_signals: dict[str, bool] = Field(default_factory=dict)
    excluded_procedure_ids: list[str] = Field(default_factory=list)


class RuntimeWorkflowState(BaseModel):
    """Wraps the dynamic-runtime view of a :class:`WorkflowSession`.

    Used by the dynamic procedure-guidance node to package the live state
    into a single typed structure. The session itself stays the source
    of truth for persistence; this is a read-mostly projection.
    """

    session_id: str
    mode: RuntimeMode | None = None
    canonical_workflow_id: str | None = None
    current_node_id: str | None = None
    dynamic_path: DynamicProcedurePath | None = None
    current_procedure_id: str | None = None
    current_step_index: int = 0
    observed_signals: dict[str, bool] = Field(default_factory=dict)
    answered_questions: list[dict[str, Any]] = Field(default_factory=list)
    completed_procedures: list[str] = Field(default_factory=list)
    failed_procedures: list[str] = Field(default_factory=list)
    produced_signals: dict[str, bool] = Field(default_factory=dict)
    escalation_triggers: list[str] = Field(default_factory=list)
    shown_citation_ids: list[str] = Field(default_factory=list)


class RuntimeRoutingPreview(BaseModel):
    """Snapshot of the dynamic-routing decision before the dpg node runs.

    The canonical routing node populates this shape on
    ``state["dynamic_procedure_state"]`` whenever it picks
    ``dynamic_procedure_guidance`` mode. The dpg node then OVERWRITES
    ``state["dynamic_procedure_state"]`` with a :class:`RuntimePathState`
    once the path has been materialised, so the shape transitions:

    ``None`` -> ``RuntimeRoutingPreview`` -> ``RuntimePathState``

    Both shapes share the ``stage`` discriminator so consumers (API,
    tests, debugger) can tell what they are looking at without sniffing
    keys.
    """

    stage: Literal["routing_preview"] = "routing_preview"
    top_match_score: float = 0.0
    candidate_count: int = 0
    top_candidates: list[dict[str, Any]] = Field(default_factory=list)


class RuntimePathState(BaseModel):
    """Snapshot of the materialised dynamic procedure path on the session.

    Written by the dpg node after it builds (or loads) the path. The
    shape is what the API surfaces on ``TroubleshootResponse`` via
    ``dynamic_procedure_state`` and is the same shape the Streamlit UI
    consumes.
    """

    stage: Literal["path_active", "escalated"] = "path_active"
    path_id: str
    validation_status: Literal["runtime_generated_unapproved"] = (
        "runtime_generated_unapproved"
    )
    procedures: list[dict[str, Any]] = Field(default_factory=list)
    completed_procedures: list[str] = Field(default_factory=list)
    failed_procedures: list[str] = Field(default_factory=list)
    escalation_triggers: list[str] = Field(default_factory=list)
    trigger: str | None = None


class RuntimeRoutingDiagnostics(BaseModel):
    """Breadcrumb explaining why a routing decision landed where it did.

    Populated on every dynamic-routing fallback (gap #12 in the audit).
    Never required for routing; purely observability so the next agent
    or developer can see "checked 0 candidates" vs "checked 12, top
    score 0.41" at a glance.
    """

    decision: str
    reason: str
    candidates_evaluated: int = 0
    top_score: float = 0.0
    threshold: float = 0.0
    components_seen: list[str] = Field(default_factory=list)
    canonical_signals_seen: list[str] = Field(default_factory=list)
    excluded_procedure_ids: list[str] = Field(default_factory=list)


class RuntimeStepResponse(BaseModel):
    """Internal Pydantic model used by the dynamic procedure-guidance node.

    The dynamic node builds one of these per turn and serialises selected
    fields onto :class:`backend.app.schemas.assistant.TroubleshootResponse`.
    The wire-format response stays
    :class:`backend.app.schemas.assistant.TroubleshootResponse`; this
    model exists so the node and its tests can pass typed values around
    without leaking dict-of-Any into the rest of the runtime.
    """

    response_type: StepResponseType
    mode: RuntimeMode
    workflow_id: str | None = None
    current_node_id: str | None = None
    current_procedure_id: str | None = None
    question: str | None = None
    instruction: str | None = None
    allowed_answers: list[str] = Field(default_factory=list)
    signals: list[RuntimeSignal] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    role_required: str | None = None
    support_safe: bool = True
    confidence: float = 0.0
    escalation_reason: str | None = None
    terminal_state: dict[str, Any] | None = None


__all__ = [
    "DynamicProcedurePath",
    "RuntimeMode",
    "RuntimePathState",
    "RuntimeProcedureMatch",
    "RuntimeProcedureStep",
    "RuntimeRoutingDiagnostics",
    "RuntimeRoutingPreview",
    "RuntimeSignal",
    "RuntimeStepResponse",
    "RuntimeWorkflowState",
    "SignalSource",
    "StepResponseType",
]
