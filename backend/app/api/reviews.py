"""SME review queue — thin proxy to Brain HTTP reviews endpoints.

Requires BRAIN_HTTP_ENABLED + BRAIN_HTTP_REVIEWS. App does not mutate brain_*
directly; MERGE/apply happens inside Brain. See docs/brain/HTTP_BOUNDARY.md.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.app.config import get_app_settings
from backend.app.services.brain_http_client import (
    BrainHttpError,
    BrainResolveRequest,
    build_brain_http_client,
)
from backend.app.services.review_ui import format_resolve_outcome


router = APIRouter(prefix="/reviews", tags=["reviews"])


class ResolveBody(BaseModel):
    resolution: Literal["approve", "reject", "edit"] = "approve"
    resolved_by: Literal["human", "agent"] = "human"
    reviewer_id: str | None = None
    notes: str | None = None
    edited_proposed_change: Any = None


class ResolveApiResponse(BaseModel):
    review_id: str = ""
    status: str = ""
    resolution: str = ""
    mutated_record_ids: list[str] = Field(default_factory=list)
    message: str = ""
    applied: bool | None = None
    apply_status: str | None = None
    execution_status: str | None = None
    errors: list[str] = Field(default_factory=list)
    outcome_level: str = "info"
    outcome_message: str = ""


def _require_reviews_client():
    settings = get_app_settings()
    if not settings.brain_http_enabled or not settings.brain_http_reviews:
        raise HTTPException(
            status_code=503,
            detail=(
                "Brain reviews are disabled. Set BRAIN_HTTP_ENABLED=true, "
                "BRAIN_HTTP_REVIEWS=true, and BRAIN_HTTP_BASE_URL."
            ),
        )
    if not (settings.brain_http_base_url or "").strip():
        raise HTTPException(
            status_code=503,
            detail="BRAIN_HTTP_BASE_URL is not set.",
        )
    return build_brain_http_client(settings)


@router.get("")
def list_reviews(
    status: str = Query(default="open"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    client = _require_reviews_client()
    try:
        result = client.list_reviews(status=status, limit=limit)
    except BrainHttpError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=503, detail="Brain reviews client returned no data.")
    return {
        "reviews": [item.model_dump(mode="json") for item in result.reviews],
        "total": result.total if result.total is not None else len(result.reviews),
        "status_filter": result.status_filter or status,
        "open_count": len(result.reviews) if status == "open" else None,
    }


@router.get("/{review_id}")
def get_review(review_id: str) -> dict[str, Any]:
    client = _require_reviews_client()
    try:
        detail = client.get_review(review_id)
    except BrainHttpError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if detail is None:
        raise HTTPException(status_code=503, detail="Brain reviews client returned no data.")
    payload = detail.model_dump(mode="json")
    payload["review_id"] = detail.effective_id()
    return payload


@router.post("/{review_id}/resolve", response_model=ResolveApiResponse)
def resolve_review(review_id: str, body: ResolveBody) -> ResolveApiResponse:
    client = _require_reviews_client()
    request = BrainResolveRequest(
        resolution=body.resolution,
        resolved_by=body.resolved_by,
        reviewer_id=body.reviewer_id,
        notes=body.notes,
        edited_proposed_change=body.edited_proposed_change,
    )
    try:
        result = client.resolve_review(review_id, request)
    except BrainHttpError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=503, detail="Brain reviews client returned no data.")
    dumped = result.model_dump(mode="json")
    level, outcome_message = format_resolve_outcome(dumped)
    return ResolveApiResponse(
        review_id=result.review_id or review_id,
        status=result.status,
        resolution=result.resolution,
        mutated_record_ids=list(result.mutated_record_ids or []),
        message=result.message,
        applied=result.applied,
        apply_status=result.apply_status,
        execution_status=result.execution_status,
        errors=list(result.errors or []),
        outcome_level=level,
        outcome_message=outcome_message,
    )
