from __future__ import annotations

from pydantic import Field

from backend.app.models.base import KnowledgeDocument


class CanonicalImage(KnowledgeDocument):
    dataset: str = "dataset_4b_canonical_image"
    image_id: str | None = None
    image_type: str = "screenshot"
    category: str
    use_case: str = "workflow_step_visual"
    title: str
    description: str | None = None
    annotation_summary: str | None = None
    screen_name: str | None = None
    system_name: str | None = None
    normal_state_description: str | None = None
    abnormal_state_description: str | None = None
    observable_signals: list[str] = Field(default_factory=list)
    visual_elements: list[str] = Field(default_factory=list)
    navigation_context: str | None = None
    component: str | None = None
    issue_categories: list[str] = Field(default_factory=list)
    related_signals: list[str] = Field(default_factory=list)
    storage_uri: str | None = None
    source_artifact_ids: list[str] = Field(default_factory=list)
    linked_incident_ids: list[str] = Field(default_factory=list)
    linked_workflow_ids: list[str] = Field(default_factory=list)
    linked_procedure_ids: list[str] = Field(default_factory=list)
    linked_step_ids: list[str] = Field(default_factory=list)
    observed_signals: list[str] = Field(default_factory=list)
    source_artifact_records: list[dict[str, object]] = Field(default_factory=list)
