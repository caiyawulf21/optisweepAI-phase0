from __future__ import annotations

from pydantic import Field

from backend.app.models.base import KnowledgeDocument


class KnowledgeRelationship(KnowledgeDocument):
    dataset: str = "cross_dataset_knowledge_relationship"
    relationship_type: str
    from_id: str
    from_type: str
    to_id: str
    to_type: str
    confidence: float | None = None
    status: str = "candidate"
    evidence_refs: list[str] = Field(default_factory=list)
    notes: str | None = None
