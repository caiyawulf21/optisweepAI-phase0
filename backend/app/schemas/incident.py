from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


KpiBasis = Literal["computed", "extracted", "inferred", "unavailable"]


class IncidentKpi(BaseModel):
    value_minutes: float | None = None
    kpi_basis: KpiBasis = "unavailable"
    source_event_ids: list[str] = Field(default_factory=list)
    narrative_excerpt: str | None = None
    confidence: float | None = None
    requires_manual_review: bool = True


class IncidentKpis(BaseModel):
    time_to_resolve_minutes: IncidentKpi = Field(default_factory=IncidentKpi)
    time_to_recover_minutes: IncidentKpi = Field(default_factory=IncidentKpi)


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
    incident_kpis: IncidentKpis | None = None
