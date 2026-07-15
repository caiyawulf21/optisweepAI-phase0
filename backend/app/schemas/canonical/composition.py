from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.canonical.provenance import AgentProvenance


class ProposedComposition(BaseModel):
    """A single composition entry proposed by the LLM composition synthesizer.

    Mirrors the structural shape of an entry in
    ``backend/app/tools/workflow_composition_mapping.yaml`` so that approved
    proposals can be appended verbatim into the live mapping. Adds
    ``related_incidents``, ``rationale`` and ``confidence`` metadata that are
    consumed by the post-validator and the demo audit trail.
    """

    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    canonical_title: str
    issue_category: str
    source_workflow_candidate_ids: list[str] = Field(min_length=1)
    assigned_canonical_procedure_refs: list[str] = Field(min_length=1)
    allowed_escalation_domains: list[str] = Field(min_length=1)
    plan_file: str
    related_incidents: list[str] = Field(min_length=1)
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: AgentProvenance


class CompositionSynthesisResult(BaseModel):
    """Top-level synthesizer output written to
    ``data/workflows/proposed_compositions.yaml`` (and consumed by ``--apply``).
    """

    model_config = ConfigDict(extra="forbid")

    proposed_compositions: list[ProposedComposition] = Field(default_factory=list)
    unmapped_candidate_ids_remaining: list[str] = Field(default_factory=list)
    unmapped_candidate_reasons: dict[str, str] = Field(default_factory=dict)
    overall_provenance: AgentProvenance
