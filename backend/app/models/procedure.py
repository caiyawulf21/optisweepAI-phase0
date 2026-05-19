from __future__ import annotations

from pydantic import Field

from backend.app.models.base import KnowledgeDocument


class Procedure(KnowledgeDocument):
    dataset: str = "dataset_2b_procedure_dictionary"
    procedure_id: str
    procedure_version: str = "1.0"
    procedure_type: str
    title: str
    role_required: str | None = None
    support_safe: bool | None = None
    steps: list[dict] = Field(default_factory=list)
    expected_outcome: str | None = None
    escalation_conditions: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    supporting_timeline_events: list[str] = Field(default_factory=list)
    supporting_evidence_chunks: list[str] = Field(default_factory=list)
    status: str = "draft"
    procedure_category_status: str | None = None
    candidate_maturity: str | None = None
    promotion_blockers: list[str] = Field(default_factory=list)
    refinement_opportunities: list[str] = Field(default_factory=list)
    procedure_detail_level: str | None = None
    procedure_refinement_status: str | None = None
    missing_operational_details: list[str] = Field(default_factory=list)
    required_screenshot_examples: list[str] = Field(default_factory=list)
    candidate_refinement_questions: list[str] = Field(default_factory=list)
    supporting_artifacts: list[str] = Field(default_factory=list)
