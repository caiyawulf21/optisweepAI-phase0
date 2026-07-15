from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.app.runtime.playbook_runtime import (
    commit_retrieve_turn_memory,
    resolve_retrieve_record_types,
    run_retrieve_chat,
)
from backend.app.schemas.assistant import Citation
from backend.app.services.interaction_log_service import InteractionLog, build_interaction_log_service


router = APIRouter()
interaction_log_service = build_interaction_log_service()


class RetrieveRequest(BaseModel):
    query: str
    session_id: str | None = None
    playbook_variant: str | None = None
    record_types: list[str] | None = Field(
        default=None,
        description=(
            "Optional filter of embedding record types. "
            "Omit or pass [] to search all published embeddings in Cosmos."
        ),
    )
    top_k: int = 5


class RetrieveHit(BaseModel):
    record_type: str
    source_record_id: str
    title: str
    combined_score: float
    snippet: str
    filter_metadata: dict[str, Any] = Field(default_factory=dict)
    cosine_score: float = 0.0
    jaccard_score: float = 0.0
    symptom_score: float = 0.0
    coverage: float = 0.0


class RetrieveResponse(BaseModel):
    query: str
    hits: list[RetrieveHit] = Field(default_factory=list)
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    canonical_images: list[dict[str, Any]] = Field(default_factory=list)
    playbook_variant: str | None = None
    record_types: list[str] = Field(default_factory=list)
    corpus_source: str | None = None
    runtime_trace: dict[str, Any] = Field(default_factory=dict)


def _hit_title(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "").strip()
    if title:
        return title
    metadata = item.get("filter_metadata") if isinstance(item.get("filter_metadata"), dict) else {}
    meta_title = str(metadata.get("title") or "").strip()
    if meta_title:
        return meta_title
    return str(item.get("source_record_id") or item.get("record_id") or "")


def _hits_to_citations(hits: list[RetrieveHit]) -> list[Citation]:
    return [
        Citation(
            source_id=hit.source_record_id or hit.title,
            title=hit.title or hit.source_record_id,
            reference=hit.record_type or None,
            excerpt=hit.snippet or None,
        )
        for hit in hits
    ]


@router.post("/retrieve", response_model=RetrieveResponse)
def retrieve(request: RetrieveRequest) -> RetrieveResponse:
    resolved_types = resolve_retrieve_record_types(request.record_types)
    state = run_retrieve_chat(
        request.query,
        session_id=request.session_id,
        playbook_variant=request.playbook_variant,
        record_types=resolved_types,
        top_k=request.top_k,
    )
    hits = [
        RetrieveHit(
            record_type=str(item.get("record_type") or ""),
            source_record_id=str(item.get("source_record_id") or ""),
            title=_hit_title(item),
            combined_score=float(item.get("combined_score") or 0.0),
            snippet=str(item.get("snippet") or ""),
            filter_metadata=dict(item.get("filter_metadata") or {}),
            cosine_score=float(item.get("cosine_score") or 0.0),
            jaccard_score=float(item.get("jaccard_score") or 0.0),
            symptom_score=float(item.get("symptom_score") or 0.0),
            coverage=float(item.get("coverage") or 0.0),
        )
        for item in state.get("retrieval_hits") or []
        if isinstance(item, dict)
    ]
    trace = dict(state.get("runtime_trace") or {})
    response = RetrieveResponse(
        query=request.query,
        hits=hits,
        answer=str(state.get("final_response") or ""),
        citations=_hits_to_citations(hits),
        canonical_images=[
            item
            for item in list(state.get("canonical_images") or [])
            if isinstance(item, dict)
        ],
        playbook_variant=state.get("playbook_variant"),
        record_types=list(trace.get("record_types") or resolved_types),
        corpus_source=str(trace.get("corpus_source") or "") or None,
        runtime_trace=trace,
    )
    if request.session_id:
        try:
            commit_retrieve_turn_memory(
                request.session_id,
                answer=response.answer,
                intent=str(state.get("retrieve_intent") or trace.get("retrieve_intent") or "")
                or None,
                source_ids=[hit.source_record_id for hit in hits if hit.source_record_id],
            )
        except Exception:
            pass
        try:
            interaction_log_service.record(
                InteractionLog(
                    session_id=request.session_id,
                    user_message=request.query,
                    response_type="answer",
                    final_response=response.answer,
                    assistant_response=response.model_dump(),
                    runtime_trace=response.runtime_trace,
                )
            )
        except Exception:
            pass
    return response


@router.get("/retrieve/sessions/{session_id}/interactions")
def get_retrieve_interactions(session_id: str) -> dict[str, Any]:
    logs = interaction_log_service.list_for_session(session_id)
    return {
        "session_id": session_id,
        "interactions": [log.to_dict() if hasattr(log, "to_dict") else vars(log) for log in logs],
    }
