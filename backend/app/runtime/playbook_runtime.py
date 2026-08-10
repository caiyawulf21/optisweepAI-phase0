from __future__ import annotations

from typing import Any

from backend.app.corpus.bootstrap import get_corpus_index
from backend.app.corpus.settings import get_corpus_settings
from backend.app.graph.playbook_graph import build_playbook_graph, build_retrieve_graph
from backend.app.services.retrieve_memory import (
    RetrieveMemoryPacket,
    append_retrieve_ai_message,
    append_retrieve_user_message,
    build_retrieve_memory_packet,
)


_DEFAULT_RETRIEVE_TYPES = (
    "canonical_runbook",
    "operational_context",
    "incident_source_runbook",
    "playbook_prompt_a",
    "playbook_prompt_b",
)
_REQUIRED_RETRIEVE_TYPES = ("operational_context",)


def resolve_retrieve_record_types(record_types: list[str] | None) -> list[str]:
    """Resolve `/retrieve` types and always keep operational_context searchable."""
    requested = [str(item).strip() for item in (record_types or []) if str(item).strip()]
    resolved: list[str] = []
    if requested:
        resolved = list(dict.fromkeys(requested))
    else:
        try:
            types = sorted(
                {
                    str(item.record_type).strip()
                    for item in get_corpus_index().embeddings
                    if str(item.record_type or "").strip()
                }
            )
            if types:
                resolved = types
        except Exception:
            resolved = []
        if not resolved:
            resolved = list(_DEFAULT_RETRIEVE_TYPES)
    for required in _REQUIRED_RETRIEVE_TYPES:
        if required not in resolved:
            resolved.append(required)
    return resolved


_playbook_graph_compiled = None
_retrieve_graph_compiled = None


def reset_playbook_graphs() -> None:
    global _playbook_graph_compiled, _retrieve_graph_compiled
    _playbook_graph_compiled = None
    _retrieve_graph_compiled = None


def get_playbook_graph():
    global _playbook_graph_compiled
    if _playbook_graph_compiled is None:
        _playbook_graph_compiled = build_playbook_graph()
    return _playbook_graph_compiled


def get_retrieve_graph():
    global _retrieve_graph_compiled
    if _retrieve_graph_compiled is None:
        _retrieve_graph_compiled = build_retrieve_graph()
    return _retrieve_graph_compiled


def run_playbook_troubleshoot(
    session_id: str,
    user_message: str,
    *,
    operator_role: str | None = None,
    playbook_variant: str | None = None,
) -> dict[str, Any]:
    settings = get_corpus_settings()
    state = {
        "session_id": session_id,
        "user_message": user_message,
        "operator_role": operator_role,
        "playbook_variant": playbook_variant or settings.default_playbook_variant,
        "runtime_trace": {"surface": "troubleshoot", "agents": []},
        "surface": "troubleshoot",
    }
    result = get_playbook_graph().invoke(state)
    result.setdefault("runtime_trace", {})
    result["runtime_trace"]["surface"] = "troubleshoot"
    return result


def run_retrieve_chat(
    query: str,
    *,
    session_id: str | None = None,
    playbook_variant: str | None = None,
    record_types: list[str] | None = None,
    top_k: int = 8,
    prior_turns: list[dict[str, Any]] | None = None,
    commit_user_turn: bool = True,
    search_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from backend.app.services.search_context import (
        build_contextual_retrieval_query,
        compact_search_context,
        search_context_trace_fields,
    )

    settings = get_corpus_settings()
    resolved_types = resolve_retrieve_record_types(record_types)
    sid = str(session_id or "").strip()
    compact_context = compact_search_context(search_context)

    memory: RetrieveMemoryPacket
    if prior_turns is not None and not sid:
        # Explicit prior turns (tests) without a session store.
        from backend.app.services.retrieve_memory import resolve_retrieve_intent

        user_texts = [
            str(item.get("content") or "")
            for item in prior_turns
            if isinstance(item, dict) and item.get("role") == "user"
        ]
        intent = resolve_retrieve_intent(query, prior_user_texts=user_texts)
        memory = RetrieveMemoryPacket(
            session_id="",
            resolved_intent=intent,
            retrieval_hints=[text for text in user_texts[-3:] if text and text.lower() != query.lower()],
            synth_turns=[
                {
                    "role": str(item.get("role") or ""),
                    "content": str(item.get("content") or "")[:240],
                }
                for item in prior_turns[-4:]
                if isinstance(item, dict)
            ],
            message_count=len(prior_turns),
            trimmed_message_count=min(len(prior_turns), 4),
        )
    else:
        if sid and commit_user_turn:
            append_retrieve_user_message(sid, query)
        memory = build_retrieve_memory_packet(sid, query, hydrate=True)

    intent = memory.resolved_intent
    rewritten = build_contextual_retrieval_query(query, compact_context)
    state = {
        "session_id": sid,
        "user_message": query,
        "retrieval_query_override": rewritten if rewritten != query else None,
        "search_context": compact_context,
        "conversation_history": memory.synth_turns,
        "retrieve_memory_hints": memory.retrieval_hints,
        "retrieve_intent": intent,
        "playbook_variant": playbook_variant or settings.default_playbook_variant,
        "record_types": resolved_types,
        "top_k": top_k,
        "runtime_trace": {
            "surface": "retrieve",
            "agents": [],
            "corpus_source": settings.corpus_source,
            "retrieve_intent": intent,
            "memory_messages": memory.message_count,
            "memory_trimmed": memory.trimmed_message_count,
            "memory_hints": list(memory.retrieval_hints),
            **search_context_trace_fields(compact_context),
            "retrieval_query_rewritten": rewritten if rewritten != query else None,
        },
        "surface": "retrieve",
    }
    result = get_retrieve_graph().invoke(state)
    result.setdefault("runtime_trace", {})
    result["runtime_trace"]["surface"] = "retrieve"
    result["runtime_trace"]["corpus_source"] = settings.corpus_source
    result["runtime_trace"]["record_types"] = resolved_types
    result["runtime_trace"]["retrieve_intent"] = intent
    result["runtime_trace"]["memory_messages"] = memory.message_count
    result["runtime_trace"]["memory_trimmed"] = memory.trimmed_message_count
    result["runtime_trace"].update(search_context_trace_fields(compact_context))
    if rewritten != query:
        result["runtime_trace"]["retrieval_query_rewritten"] = rewritten
    result["retrieve_intent"] = intent
    result["search_context"] = compact_context
    return result


def commit_retrieve_turn_memory(
    session_id: str,
    *,
    answer: str,
    intent: str | None = None,
    source_ids: list[str] | None = None,
) -> None:
    if not session_id:
        return
    append_retrieve_ai_message(
        session_id,
        answer,
        intent=intent,
        source_ids=source_ids,
    )
