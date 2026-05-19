from __future__ import annotations

from pydantic import Field

from backend.app.models.base import KnowledgeDocument


class IngestionRun(KnowledgeDocument):
    dataset: str = "operational_ingestion_run"
    run_type: str = "manual_phase0"
    input_files: list[str] = Field(default_factory=list)
    records_created: dict[str, int] = Field(default_factory=dict)
    status: str = "completed"
    errors: list[str] = Field(default_factory=list)
    started_at: str | None = None
    completed_at: str | None = None
