from __future__ import annotations

from pydantic import Field

from backend.app.models.base import KnowledgeDocument


class ProcedureRefinementCandidate(KnowledgeDocument):
    dataset: str = "dataset_2c_procedure_refinement_candidate"
    candidate_family: str
    procedure_type: str
    title: str
    source_procedure_candidate_ids: list[str] = Field(default_factory=list)
    source_incident_ids: list[str] = Field(default_factory=list)
    source_evidence_refs: list[str] = Field(default_factory=list)
    merged_step_sequence: list[dict] = Field(default_factory=list)
    screenshot_requirements: list[dict] = Field(default_factory=list)
    known_variations: list[str] = Field(default_factory=list)
    missing_steps: list[str] = Field(default_factory=list)
    sme_questions: list[str] = Field(default_factory=list)
    status: str = "needs_sme_review"
    promotion_target: str = "procedure_dictionary"
