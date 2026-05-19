from __future__ import annotations

from pydantic import BaseModel, Field


class Cat1KnowledgeRecord(BaseModel):
    record_id: str
    source_case_id: str | None = None
    data_source: str
    source_type: str
    source_authority: float = 1.0
    site: str | None = None
    issue_category: str = "CAT-1"
    failure_signature: str
    symptom_summary: str
    component: list[str] = Field(default_factory=list)
    observed_signals: list[str] = Field(default_factory=list)
    root_cause_summary: str | None = None
    resolution_summary: str | None = None
    resolution_steps: list[str] = Field(default_factory=list)
    escalation_domains: list[str] = Field(default_factory=list)
    escalation_notes: str | None = None
    resolution_status: str = "unknown"
    validation_status: str = "candidate_extracted"
    source_notes: str | None = None
    notes: str | None = None
