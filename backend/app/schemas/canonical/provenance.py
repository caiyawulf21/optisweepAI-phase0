from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


ValidationStatus = Literal[
    "needs_review",
    "sme_reviewed",
    "approved",
    "approved_for_workflow",
    "promoted_for_demo",
    "rejected",
    "deprecated",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentProvenance(BaseModel):
    created_by_agent: str = "workflow_procedure_architecture_agent"
    prompt_id: str
    prompt_version: str = "0.1"
    source_input_files: list[str] = Field(default_factory=list)
    llm_model: str | None = None
    created_at: str = Field(default_factory=_utc_now)
    validation_status: ValidationStatus = "needs_review"
    reviewed_by_human_checklist: bool = False
