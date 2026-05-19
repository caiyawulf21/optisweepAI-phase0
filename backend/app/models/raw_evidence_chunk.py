from __future__ import annotations

from pydantic import Field

from backend.app.models.base import KnowledgeDocument


class RawEvidenceChunk(KnowledgeDocument):
    dataset: str = "dataset_3_raw_evidence_chunk"
    incident_id: str
    source_case_id: str | None = None
    chunk_id: str | None = None
    source_type: str | None = None
    raw_source_type: str | None = None
    evidence_type: str | None = None
    source_ref: str | None = None
    chunk_order: int | None = None
    chunk_text: str
    observed_failure_signals: list[str] = Field(default_factory=list)
    diagnostic_signals: list[str] = Field(default_factory=list)
    action_signals: list[str] = Field(default_factory=list)
    recovery_validation_signals: list[str] = Field(default_factory=list)
    escalation_signals: list[str] = Field(default_factory=list)
    linked_records: list[str] = Field(default_factory=list)
    source_region_refs: list[str] = Field(default_factory=list)
    source_artifact_ids: list[str] = Field(default_factory=list)
