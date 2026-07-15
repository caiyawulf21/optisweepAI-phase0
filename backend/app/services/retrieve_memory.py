from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any

from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, trim_messages


# Keep a tiny working window so synthesize / retrieval enrichment stay cheap.
_MAX_MESSAGES = 6
_MAX_CHARS_USER = 320
_MAX_CHARS_AI = 240
_MAX_SYNTH_TURNS = 4

_lock = threading.Lock()
_histories: dict[str, InMemoryChatMessageHistory] = {}
_session_slots: dict[str, dict[str, Any]] = {}


@dataclass
class RetrieveMemoryPacket:
    """Bounded conversational context for `/retrieve` (RAG chatbot)."""

    session_id: str
    resolved_intent: str | None = None
    retrieval_hints: list[str] = field(default_factory=list)
    synth_turns: list[dict[str, str]] = field(default_factory=list)
    message_count: int = 0
    trimmed_message_count: int = 0


def reset_retrieve_memory() -> None:
    with _lock:
        _histories.clear()
        _session_slots.clear()


def get_retrieve_history(session_id: str) -> InMemoryChatMessageHistory:
    key = str(session_id or "").strip() or "_anon"
    with _lock:
        history = _histories.get(key)
        if history is None:
            history = InMemoryChatMessageHistory()
            _histories[key] = history
        return history


def get_session_slots(session_id: str) -> dict[str, Any]:
    key = str(session_id or "").strip() or "_anon"
    with _lock:
        slots = _session_slots.get(key)
        if slots is None:
            slots = {"resolved_intent": None, "last_source_ids": []}
            _session_slots[key] = slots
        return slots


def _truncate(text: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", str(text or "").strip())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def _compact_assistant_text(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    # Drop citation appendix before normalizing whitespace (keeps memory slim).
    match = re.search(r"(?i)(?:^|\n)\s*sources\s*:", value)
    if match is None:
        match = re.search(r"(?i)\bsources\s*:", value)
    if match is not None and match.start() >= 12:
        value = value[: match.start()].strip()
    return _truncate(value, _MAX_CHARS_AI)


def resolve_retrieve_intent(
    query: str,
    *,
    prior_user_texts: list[str] | None = None,
    existing_intent: str | None = None,
) -> str | None:
    if existing_intent in {"software_stack", "maintenance", "incident"}:
        # Sticky intent unless the new turn clearly switches topics.
        text = str(query or "").lower()
        if existing_intent == "software_stack" and any(
            phrase in text for phrase in ("maintenance", "hardware", "fault", "alarm", "tipper")
        ) and "software" not in text:
            pass
        else:
            if existing_intent == "software_stack":
                return "software_stack"
            if existing_intent == "maintenance" and not (
                {"software", "wcs", "rms", "ignition"} & set(re.findall(r"[a-z0-9]+", text))
            ):
                return "maintenance"
            if existing_intent == "incident" and "software stack" not in text:
                return "incident"

    blobs = [str(query or "")]
    blobs.extend(str(item or "") for item in (prior_user_texts or []))
    text = " ".join(blobs).lower()
    if any(
        phrase in text
        for phrase in (
            "software stack",
            "service stack",
            "software service",
            "software roles",
            "wcs",
            "rms",
            "ignition",
            "communication path",
            "optisweep software",
            "meant the software",
            "meant software",
            "i meant the optisweep service software",
        )
    ):
        return "software_stack"
    if any(
        phrase in text
        for phrase in (
            "maintenance",
            "hardware",
            "weights",
            "tipper",
            "motor",
            "belt",
            "replace",
            "install",
        )
    ) and not any(token in text for token in ("software", "service stack", "wcs")):
        return "maintenance"
    if any(
        phrase in text
        for phrase in ("incident", "fault", "alarm", "stopped", "troubleshoot", "agv")
    ):
        return "incident"
    return existing_intent if existing_intent in {"software_stack", "maintenance", "incident"} else None


def hydrate_retrieve_memory_from_logs(session_id: str) -> InMemoryChatMessageHistory:
    """Seed LC history from interaction logs once (compacted)."""
    history = get_retrieve_history(session_id)
    if history.messages:
        return history
    try:
        from backend.app.services.interaction_log_service import build_interaction_log_service

        logs = build_interaction_log_service().list_for_session(session_id)
    except Exception:
        return history
    for log in logs[-(_MAX_MESSAGES // 2) :]:
        user_message = str(getattr(log, "user_message", "") or "").strip()
        if user_message:
            history.add_message(HumanMessage(content=_truncate(user_message, _MAX_CHARS_USER)))
        assistant = _compact_assistant_text(str(getattr(log, "final_response", "") or ""))
        if assistant:
            history.add_message(AIMessage(content=assistant))
    return history


def append_retrieve_user_message(session_id: str, text: str) -> None:
    if not session_id:
        return
    history = get_retrieve_history(session_id)
    history.add_message(HumanMessage(content=_truncate(text, _MAX_CHARS_USER)))


def append_retrieve_ai_message(
    session_id: str,
    text: str,
    *,
    intent: str | None = None,
    source_ids: list[str] | None = None,
) -> None:
    if not session_id:
        return
    history = get_retrieve_history(session_id)
    compact = _compact_assistant_text(text)
    if compact:
        history.add_message(AIMessage(content=compact))
    slots = get_session_slots(session_id)
    if intent:
        slots["resolved_intent"] = intent
    if source_ids:
        slots["last_source_ids"] = [str(item) for item in source_ids[:5] if str(item).strip()]


def _trim_history(messages: list[BaseMessage]) -> list[BaseMessage]:
    if not messages:
        return []
    return trim_messages(
        messages,
        max_tokens=_MAX_MESSAGES,
        token_counter=len,
        strategy="last",
        start_on="human",
        include_system=False,
    )


def _message_to_turn(message: BaseMessage) -> dict[str, str] | None:
    content = _truncate(str(getattr(message, "content", "") or ""), _MAX_CHARS_USER)
    if not content:
        return None
    if isinstance(message, HumanMessage):
        return {"role": "user", "content": content}
    if isinstance(message, AIMessage):
        return {"role": "assistant", "content": _truncate(content, _MAX_CHARS_AI)}
    return None


def build_retrieve_memory_packet(
    session_id: str,
    query: str,
    *,
    hydrate: bool = True,
) -> RetrieveMemoryPacket:
    if hydrate and session_id:
        hydrate_retrieve_memory_from_logs(session_id)
    history = get_retrieve_history(session_id) if session_id else InMemoryChatMessageHistory()
    slots = get_session_slots(session_id) if session_id else {"resolved_intent": None}
    raw = list(history.messages)
    trimmed = _trim_history(raw)
    user_texts = [
        str(msg.content)
        for msg in trimmed
        if isinstance(msg, HumanMessage) and str(msg.content or "").strip()
    ]
    intent = resolve_retrieve_intent(
        query,
        prior_user_texts=user_texts,
        existing_intent=slots.get("resolved_intent"),
    )
    if intent:
        slots["resolved_intent"] = intent
    # Retrieval enrichment: recent user clarifications only (not AI essays).
    hints = [text for text in user_texts[-3:] if text.strip() and text.strip().lower() != query.strip().lower()]
    synth_turns: list[dict[str, str]] = []
    for message in trimmed[-_MAX_SYNTH_TURNS:]:
        turn = _message_to_turn(message)
        if turn:
            synth_turns.append(turn)
    return RetrieveMemoryPacket(
        session_id=str(session_id or ""),
        resolved_intent=intent,
        retrieval_hints=hints,
        synth_turns=synth_turns,
        message_count=len(raw),
        trimmed_message_count=len(trimmed),
    )


__all__ = [
    "RetrieveMemoryPacket",
    "append_retrieve_ai_message",
    "append_retrieve_user_message",
    "build_retrieve_memory_packet",
    "get_retrieve_history",
    "hydrate_retrieve_memory_from_logs",
    "reset_retrieve_memory",
    "resolve_retrieve_intent",
]
