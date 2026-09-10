"""Feedback capture API — persists locally, optionally forwards to Brain HTTP.

Local store: feedback_events (+ interaction_logs linkage). Brain writes only
via POST /brain/v1/feedback when BRAIN_HTTP_FEEDBACK is enabled.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.app.services.attachment_service import build_attachment_service
from backend.app.services.brain_http_client import (
    BrainFeedbackRequest,
    build_brain_http_client,
    safe_submit_feedback,
)
from backend.app.services.feedback_service import FeedbackEvent, build_feedback_service
from backend.app.services.interaction_log_service import build_interaction_log_service


router = APIRouter()


class FeedbackTargets(BaseModel):
    playbook_id: str | None = None
    runbook_id: str | None = None
    node_id: str | None = None
    record_ids: list[str] = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    session_id: str
    interaction_id: str
    surface: Literal["troubleshoot", "retrieve"] = "troubleshoot"
    sentiment: Literal["helpful", "not_helpful", "suggestion"] = "suggestion"
    about: str | None = None
    targets: FeedbackTargets = Field(default_factory=FeedbackTargets)
    user_text: str = ""
    proposed_change: str = ""
    attachment_ids: list[str] = Field(default_factory=list)


class FeedbackResponse(BaseModel):
    accepted: bool
    feedback_id: str | None = None
    message: str
    brain_handoff_status: str = "deferred"
    brain_review_id: str | None = None
    brain_apply_status: str | None = None


def _feedback_user_message(*, brain_handoff_status: str, brain_apply_status: str | None) -> str:
    if brain_handoff_status == "forwarded":
        status = (brain_apply_status or "").strip().lower()
        if status in {"applied_unreviewed", "conflicting"}:
            return (
                "Recorded in app audit and forwarded to Brain. "
                "Knowledge may be stored as unreviewed/conflicting — not approved guidance."
            )
        if status == "gap":
            return (
                "Recorded in app audit and forwarded to Brain as a gap for human review. "
                "Trusted Brain guidance was not changed."
            )
        return (
            "Recorded in app audit and forwarded to Brain. "
            "Not treated as approved OptiSweep guidance."
        )
    if brain_handoff_status == "forward_failed":
        return (
            "Saved in app audit, but Brain handoff failed. "
            "Trusted Brain knowledge was not updated."
        )
    return (
        "Saved in app audit for review. "
        "Trusted Brain knowledge was not updated (Brain HTTP handoff off or deferred)."
    )


@router.post("/feedback", response_model=FeedbackResponse)
def submit_feedback(request: FeedbackRequest) -> FeedbackResponse:
    interaction_logs = build_interaction_log_service()
    parent = interaction_logs.get(request.session_id, request.interaction_id)
    attachment_ids = [str(item) for item in list(request.attachment_ids or []) if str(item)]
    image_summaries = build_attachment_service().resolve_summaries(attachment_ids)
    snapshot: dict[str, Any] = {
        "user_message": "",
        "assistant_excerpt": "",
        "response_type": "",
        "observed_signals": {},
        "attachment_ids": [],
        "image_summaries": [],
    }
    targets = request.targets.model_dump()
    if parent is not None:
        snapshot = {
            "user_message": parent.user_message,
            "assistant_excerpt": (parent.final_response or "")[:500],
            "response_type": parent.response_type,
            "observed_signals": dict(parent.observed_signals),
            "attachment_ids": list(parent.attachment_ids),
            "image_summaries": list(parent.image_summaries),
        }
        if not targets.get("playbook_id"):
            targets["playbook_id"] = parent.playbook_id
        if not targets.get("runbook_id"):
            targets["runbook_id"] = parent.runbook_id
        if not targets.get("node_id"):
            targets["node_id"] = parent.node_id or parent.current_node_id
        if not targets.get("record_ids"):
            targets["record_ids"] = list(parent.record_ids or parent.retrieval_result_ids)

    event = FeedbackEvent(
        session_id=request.session_id,
        interaction_id=request.interaction_id,
        surface=request.surface,
        sentiment=request.sentiment,
        about=request.about,
        targets=targets,
        user_text=request.user_text,
        proposed_change=request.proposed_change,
        attachment_ids=attachment_ids,
        image_summaries=image_summaries,
        context_snapshot=snapshot,
    )
    accepted = build_feedback_service().record(event)
    if not accepted:
        raise HTTPException(
            status_code=502,
            detail="Failed to persist feedback event",
        )

    interaction_logs.append_feedback_id(
        request.session_id, request.interaction_id, event.feedback_id
    )

    brain = safe_submit_feedback(
        build_brain_http_client(),
        BrainFeedbackRequest(
            session_id=event.session_id,
            interaction_id=event.interaction_id,
            surface=event.surface if event.surface in {"troubleshoot", "retrieve"} else "troubleshoot",
            sentiment=(
                event.sentiment
                if event.sentiment in {"helpful", "not_helpful", "suggestion"}
                else "suggestion"
            ),
            about=event.about,
            user_text=event.user_text,
            proposed_change=event.proposed_change,
            targets=event.targets,
            attachment_ids=event.attachment_ids,
            image_summaries=event.image_summaries,
            context_snapshot=event.context_snapshot,
            app_feedback_id=event.feedback_id,
        ),
    )
    if brain is None:
        handoff = "deferred"
    elif brain.accepted:
        handoff = "forwarded"
        event.brain_handoff_status = handoff
        event.brain_review_id = brain.brain_review_id
        event.brain_apply_status = brain.status or None
        event.brain_mutated_record_ids = list(brain.mutated_record_ids or [])
        build_feedback_service().record(event)
    else:
        handoff = "forward_failed"
        event.brain_handoff_status = handoff
        event.brain_apply_status = brain.status or "rejected"
        build_feedback_service().record(event)

    return FeedbackResponse(
        accepted=True,
        feedback_id=event.feedback_id,
        message=_feedback_user_message(
            brain_handoff_status=handoff,
            brain_apply_status=event.brain_apply_status,
        ),
        brain_handoff_status=handoff,
        brain_review_id=event.brain_review_id,
        brain_apply_status=event.brain_apply_status,
    )


@router.get("/feedback/sessions/{session_id}")
def list_feedback(session_id: str) -> dict[str, Any]:
    events = build_feedback_service().list_for_session(session_id)
    return {
        "session_id": session_id,
        "feedback": [event.to_dict() for event in events],
    }
