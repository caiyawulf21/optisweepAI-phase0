from __future__ import annotations

from typing import Any

from pydantic import Field

from backend.app.models.base import KnowledgeDocument


class EscalationSummary(KnowledgeDocument):
    dataset: str = "dataset_5_escalation_summary"
    incident_id: str | None = None
    template: bool = False
    issue_category: str | None = None
    escalation_domain: str | None = None
    priority: str | None = None
    trigger_reason: str | None = None
    symptoms: list[Any] = Field(default_factory=list)
    steps_attempted: list[Any] = Field(default_factory=list)
    known_facts: list[Any] = Field(default_factory=list)
    actions_taken: list[Any] = Field(default_factory=list)
    evidence_available: list[Any] = Field(default_factory=list)
    open_questions: list[Any] = Field(default_factory=list)
    follow_up_owners: list[Any] = Field(default_factory=list)
    evidence_refs: list[Any] = Field(default_factory=list)
    recommended_owner: str | None = None
    handoff_summary: str | None = None
