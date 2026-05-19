from __future__ import annotations

from pydantic import Field

from backend.app.models.base import KnowledgeDocument


class TimelineEvent(KnowledgeDocument):
    dataset: str = "dataset_1_5_timeline_event"
    incident_id: str
    event_id: str | None = None
    event_order: int
    event_type: str
    actor_role: str | None = None
    event_summary: str
    event_occurred_at: str | None = None
    event_documented_at: str | None = None
    observed_failure_signals: list[str] = Field(default_factory=list)
    diagnostic_signals: list[str] = Field(default_factory=list)
    action_signals: list[str] = Field(default_factory=list)
    recovery_validation_signals: list[str] = Field(default_factory=list)
    escalation_signals: list[str] = Field(default_factory=list)
    action_taken: str | None = None
    outcome: str | None = None
    next_action: str | None = None
    source_ref: str | None = None
    source_region_refs: list[str] = Field(default_factory=list)
    source_artifact_ids: list[str] = Field(default_factory=list)
