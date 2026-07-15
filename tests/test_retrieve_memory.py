from __future__ import annotations

from backend.app.services.retrieve_memory import (
    append_retrieve_ai_message,
    append_retrieve_user_message,
    build_retrieve_memory_packet,
    reset_retrieve_memory,
    resolve_retrieve_intent,
)


def setup_function() -> None:
    reset_retrieve_memory()


def test_resolve_intent_sticky_software_stack() -> None:
    assert (
        resolve_retrieve_intent(
            "I meant the software stack",
            prior_user_texts=["tell me about optisweep service"],
        )
        == "software_stack"
    )
    assert (
        resolve_retrieve_intent(
            "ok continue",
            existing_intent="software_stack",
        )
        == "software_stack"
    )


def test_memory_packet_trims_and_compacts() -> None:
    session_id = "mem-trim-1"
    append_retrieve_user_message(session_id, "tell me about optisweep service")
    append_retrieve_ai_message(
        session_id,
        "Clarifying question...\n\nSources:\n- a\n- b\n" + ("x" * 800),
        intent="software_stack",
        source_ids=["ctx_1"],
    )
    append_retrieve_user_message(session_id, "I meant the software stack")
    packet = build_retrieve_memory_packet(session_id, "I meant the software stack", hydrate=False)
    assert packet.resolved_intent == "software_stack"
    assert packet.trimmed_message_count <= 6
    assert packet.retrieval_hints
    assert all(len(turn["content"]) <= 320 for turn in packet.synth_turns)
    # AI content should be truncated and Sources stripped for context budget.
    ai_turns = [turn for turn in packet.synth_turns if turn["role"] == "assistant"]
    assert ai_turns
    assert "sources:" not in ai_turns[-1]["content"].lower()
    assert len(ai_turns[-1]["content"]) <= 240


def test_memory_window_keeps_recent_user_hints() -> None:
    session_id = "mem-window-1"
    for index in range(8):
        append_retrieve_user_message(session_id, f"user turn {index} about optisweep")
        append_retrieve_ai_message(session_id, f"assistant reply {index}")
    packet = build_retrieve_memory_packet(session_id, "latest question", hydrate=False)
    assert packet.message_count >= 6
    assert packet.trimmed_message_count <= 6
    assert any("user turn 7" in hint or "user turn 6" in hint for hint in packet.retrieval_hints) or any(
        "user turn 7" in turn["content"] for turn in packet.synth_turns if turn["role"] == "user"
    )
