from __future__ import annotations

from pydantic import Field

from backend.app.models.base import KnowledgeDocument


class SourceArtifact(KnowledgeDocument):
    dataset: str = "dataset_4_source_artifact"
    incident_id: str
    artifact_id: str | None = None
    artifact_type: str
    artifact_role: str | None = None
    artifact_role_status: str | None = None
    source_system: str | None = None
    file_name: str
    file_path: str | None = None
    blob_container: str | None = None
    blob_path: str | None = None
    description: str | None = None
    linked_record_ids: list[str] = Field(default_factory=list)
