"""HTTP routes for corpus search chat (`POST /retrieve`).

Primary path: in-memory hybrid search over Cosmos publish embeddings.
Optional Brain retrieve context (when BRAIN_HTTP_RETRIEVE is enabled) feeds
hydrated excerpts into answer synthesis (basic Brain retrieval, not a graph).
"""

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
from backend.app.services.attachment_service import (
    build_attachment_service,
    enrich_user_message,
)
from backend.app.services.brain_cite import (
    excerpts_for_synthesis,
    excerpts_to_citations,
)
from backend.app.services.brain_http_client import (
    RetrieveContextRequest,
    build_brain_http_client,
    safe_retrieve_context,
)
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
    attachment_ids: list[str] = Field(default_factory=list)
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
    related_playbook_ids: list[str] = Field(default_factory=list)
    retrieve_intent: str | None = None
    workflow_relevance: WorkflowRelevance = Field(default_factory=WorkflowRelevance)
    runtime_trace: dict[str, Any] = Field(default_factory=dict)
    interaction_id: str | None = None
    image_summaries: list[str] = Field(default_factory=list)
    enriched_user_message: str | None = None
    attachment_ids: list[str] = Field(default_factory=list)


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


def _compact_brain_query(query: str) -> str:
    """Drop filler words so Brain lexical/semantic match is less brittle."""
    stop = {
        "tell",
        "me",
        "about",
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "for",
        "with",
        "please",
        "what",
        "is",
        "are",
        "how",
        "do",
        "does",
        "can",
        "you",
    }
    tokens = [
        token
        for token in "".join(
            ch if ch.isalnum() or ch.isspace() else " " for ch in str(query or "")
        ).split()
        if token and token.lower() not in stop
    ]
    compacted = " ".join(tokens).strip()
    return compacted or str(query or "").strip()


def _fetch_brain_retrieve_context(query: str, session_id: str | None):
    """Basic Brain retrieve for hydrated excerpts (optional compact-query retry)."""
    client = build_brain_http_client()
    primary = safe_retrieve_context(
        client,
        RetrieveContextRequest(
            query=query,
            session_id=session_id,
            limit=12,
        ),
    )
    if primary is None:
        return None
    if primary.approved_excerpts or primary.working_material:
        return primary
    compacted = _compact_brain_query(query)
    if not compacted or compacted.lower() == str(query or "").strip().lower():
        return primary
    secondary = safe_retrieve_context(
        client,
        RetrieveContextRequest(
            query=compacted,
            session_id=session_id,
            limit=12,
        ),
    )
    if secondary is not None and (
        secondary.approved_excerpts or secondary.working_material
    ):
        return secondary
    return primary


@router.post("/retrieve", response_model=RetrieveResponse)
def retrieve(request: RetrieveRequest) -> RetrieveResponse:
    attachment_ids = [str(item) for item in list(request.attachment_ids or []) if str(item)]
    image_summaries = build_attachment_service().resolve_summaries(attachment_ids)
    enriched_query = enrich_user_message(request.query, image_summaries)
    resolved_types = resolve_retrieve_record_types(request.record_types)
    search_context = compact_search_context(
        request.search_context.model_dump() if request.search_context else None
    )
    brain_context = _fetch_brain_retrieve_context(
        enriched_query or request.query,
        request.session_id,
    )
    approved_dicts = (
        brain_context.approved_excerpt_dicts() if brain_context is not None else []
    )
    working_dicts = (
        brain_context.working_excerpt_dicts() if brain_context is not None else []
    )
    brain_for_synth = excerpts_for_synthesis(
        approved_dicts,
        working_excerpts=working_dicts,
        include_working=True,
    )
    state = run_retrieve_chat(
        enriched_query,
        session_id=request.session_id,
        playbook_variant=request.playbook_variant,
        record_types=resolved_types,
        top_k=request.top_k,
        search_context=search_context or None,
        brain_excerpts=brain_for_synth,
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
    related_playbook_ids = [
        hit.source_record_id
        for hit in hits
        if hit.source_record_id
        and hit.record_type in {"playbook_prompt_a", "playbook_prompt_b"}
    ]
    retrieve_intent = str(state.get("retrieve_intent") or "").strip() or None
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
    if not retrieve_intent:
        retrieve_intent = str(trace.get("retrieve_intent") or "").strip() or None
    trace.update(search_context_trace_fields(search_context))
    trace["workflow_relevance"] = relevance.model_dump()
    trace["attachment_ids"] = attachment_ids
    trace["image_summaries"] = image_summaries
    trace["retrieve_intent"] = retrieve_intent
    citations = _hits_to_citations(hits)

    if brain_context is not None:
        brain_citations = excerpts_to_citations(
            list(approved_dicts) + list(working_dicts),
            include_working=True,
        )
        existing_ids = {item.source_id for item in citations}
        for item in brain_citations:
            source_id = str(item.get("source_id") or "")
            if source_id and source_id in existing_ids:
                continue
            citations.append(
                Citation(
                    source_id=str(item.get("source_id") or item.get("title") or "brain"),
                    title=str(item.get("title") or item.get("source_id") or "Brain"),
                    reference=item.get("reference"),
                    excerpt=item.get("excerpt"),
                )
            )
            if source_id:
                existing_ids.add(source_id)
        trace["brain_context"] = {
            "query_echo": brain_context.query_echo,
            "brain_backend": brain_context.brain_backend,
            "packet": brain_context.packet.model_dump(),
            "approved_excerpts": approved_dicts,
            "working_material": working_dicts,
            "conflicts": [item.model_dump() for item in brain_context.conflicts],
            "used_in_synthesis": True,
            "include_working_in_synthesis": True,
            "synthesis_excerpt_count": len(brain_for_synth),
            "synthesis_working_count": sum(
                1
                for item in brain_for_synth
                if str(item.get("review_state") or "") == "operational_unreviewed"
            ),
        }
    else:
        trace["brain_context"] = {
            "used_in_synthesis": False,
            "include_working_in_synthesis": False,
            "synthesis_excerpt_count": 0,
        }

    response = RetrieveResponse(
        query=request.query,
        hits=hits,
        answer=answer,
        citations=citations,
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
        related_playbook_ids=related_playbook_ids,
        related_artifact_ids=related_artifact_ids,
        retrieve_intent=retrieve_intent,
        workflow_relevance=relevance,
        runtime_trace=trace,
        image_summaries=list(image_summaries),
        enriched_user_message=enriched_query,
        attachment_ids=list(attachment_ids),
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
            log = InteractionLog(
                session_id=request.session_id,
                user_message=request.query,
                response_type="answer",
                final_response=response.answer,
                assistant_response=response.model_dump(),
                runtime_trace=response.runtime_trace,
                surface="retrieve",
                playbook_id=(
                    search_context.get("active_playbook_id") if search_context else None
                ),
                runbook_id=(
                    search_context.get("current_runbook_id") if search_context else None
                ),
                node_id=(
                    search_context.get("current_node_id") if search_context else None
                ),
                record_ids=list(response.retrieved_record_ids),
                attachment_ids=list(attachment_ids),
                image_summaries=list(image_summaries),
                enriched_user_message=enriched_query,
            )
            interaction_log_service.record(log)
            response.interaction_id = log.interaction_id
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
