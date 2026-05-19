from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class KnowledgeDocument(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    dataset: str
    created_at: str = Field(default_factory=utc_now)
    updated_at: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    source_authority: str | None = None
    retrieval_text: str | None = None
    validation_status: str | None = None
    requires_manual_review: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

def model_to_dict(model: BaseModel | dict[str, Any]) -> dict[str, Any]:
    if isinstance(model, dict):
        return model
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_none=True)
    return model.dict(exclude_none=True)
