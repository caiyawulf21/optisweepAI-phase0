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
from backend.app.services.search_context import (
    compact_search_context,
    infer_workflow_relevance,
    search_context_trace_fields,
)


router = APIRouter()
interaction_log_service = build_interaction_log_service()


class SearchContext(BaseModel):
    session_id: str | None = None
    active_playbook_id: str | None = None
    active_playbook_version: str | None = None
    playbook_title: str | None = None
    current_node_id: str | None = None
    current_node_title: str | None = None
    current_node_type: str | None = None
    current_runbook_id: str | None = None
    current_procedure_title: str | None = None
    symptoms: list[str] = Field(default_factory=list)
    observed_signals: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    systems: list[str] = Field(default_factory=list)
    completed_nodes: list[str] = Field(default_factory=list)
    allowed_answers: list[str] = Field(default_factory=list)


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
    top_k: int = 8
    search_context: SearchContext | None = Field(
        default=None,
        description=(
            "Compact active-troubleshooting context for retrieval precision. "
            "Never mutates playbook/workflow state."
        ),
    )


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


class PossibleStateUpdate(BaseModel):
    field: str
    value: str
    node_id: str | None = None
    requires_user_confirmation: bool = True


class WorkflowRelevance(BaseModel):
    related_to_current_node: bool = False
    possible_state_update: PossibleStateUpdate | None = None


class RetrieveResponse(BaseModel):
    query: str
    hits: list[RetrieveHit] = Field(default_factory=list)
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    canonical_images: list[dict[str, Any]] = Field(default_factory=list)
    playbook_variant: str | None = None
    record_types: list[str] = Field(default_factory=list)
    corpus_source: str | None = None
    retrieved_record_ids: list[str] = Field(default_factory=list)
    related_runbook_ids: list[str] = Field(default_factory=list)
    related_artifact_ids: list[str] = Field(default_factory=list)
    workflow_relevance: WorkflowRelevance = Field(default_factory=WorkflowRelevance)
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
    search_context = compact_search_context(
        request.search_context.model_dump() if request.search_context else None
    )
    state = run_retrieve_chat(
        request.query,
        session_id=request.session_id,
        playbook_variant=request.playbook_variant,
        record_types=resolved_types,
        top_k=request.top_k,
        search_context=search_context or None,
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
    hit_dicts = [hit.model_dump() for hit in hits]
    answer = str(state.get("final_response") or "")
    relevance_raw = infer_workflow_relevance(
        answer=answer,
        hits=hit_dicts,
        search_context=search_context,
    )
    update_raw = relevance_raw.get("possible_state_update")
    relevance = WorkflowRelevance(
        related_to_current_node=bool(relevance_raw.get("related_to_current_node")),
        possible_state_update=(
            PossibleStateUpdate(**update_raw) if isinstance(update_raw, dict) else None
        ),
    )
    related_runbook_ids = [
        hit.source_record_id
        for hit in hits
        if hit.source_record_id
        and hit.record_type in {"canonical_runbook", "incident_source_runbook"}
    ]
    related_artifact_ids: list[str] = []
    for image in list(state.get("canonical_images") or []):
        if not isinstance(image, dict):
            continue
        artifact_id = str(
            image.get("artifact_id") or image.get("image_id") or image.get("id") or ""
        ).strip()
        if artifact_id and artifact_id not in related_artifact_ids:
            related_artifact_ids.append(artifact_id)
    trace = dict(state.get("runtime_trace") or {})
    trace.update(search_context_trace_fields(search_context))
    trace["workflow_relevance"] = relevance.model_dump()
    response = RetrieveResponse(
        query=request.query,
        hits=hits,
        answer=answer,
        citations=_hits_to_citations(hits),
        canonical_images=[
            item
            for item in list(state.get("canonical_images") or [])
            if isinstance(item, dict)
        ],
        playbook_variant=state.get("playbook_variant"),
        record_types=list(trace.get("record_types") or resolved_types),
        corpus_source=str(trace.get("corpus_source") or "") or None,
        retrieved_record_ids=[hit.source_record_id for hit in hits if hit.source_record_id],
        related_runbook_ids=related_runbook_ids,
        related_artifact_ids=related_artifact_ids,
        workflow_relevance=relevance,
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
