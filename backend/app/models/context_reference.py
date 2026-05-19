from __future__ import annotations

from pydantic import Field

from backend.app.models.base import KnowledgeDocument


class ContextReference(KnowledgeDocument):
    dataset: str = "dataset_0_context_reference"
    context_type: str
    title: str
    applies_to: list[str] = Field(default_factory=list)
