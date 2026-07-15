from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.schemas.assistant import Citation, RetrievalResult


CaseTriageMode = Literal["troubleshoot", "qa"]


class CaseTriageRequest(BaseModel):
    session_id: str
    user_message: str
    operator_role: str | None = None
    mode: CaseTriageMode
    confirm_match: bool | None = None
    selected_case_id: str | None = None


class CaseMatchSummary(BaseModel):
    record_id: str
    case_id: str | None = None
    title: str
    issue_category: str | None = None
    matched_signals: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    symptoms: list[str] = Field(default_factory=list)
    summary: str
    excerpt: str | None = None


class CaseTriageResponse(BaseModel):
    session_id: str
    mode: CaseTriageMode
    extracted_signals: dict[str, bool] = Field(default_factory=dict)
    extracted_observed_signals: dict[str, bool] = Field(default_factory=dict)
    retrieval_results: list[RetrievalResult] = Field(default_factory=list)
    retrieval_confidence: float = 0.0
    canonical_images: list[dict[str, Any]] = Field(default_factory=list)
    top_matches: list[CaseMatchSummary] = Field(default_factory=list)
    confirmation_question: str | None = None
    answer: str | None = None
    suggested_workflow_id: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    runtime_trace: dict[str, Any] = Field(default_factory=dict)
    response_type: Literal["case_match"] = "case_match"
