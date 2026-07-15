"""Tests for Phase 1 Step 13 — interaction logging service.

Covers the build-prompt acceptance criteria verbatim:

* every troubleshooting interaction logged — exercised here at the
  service/store level; the endpoint-level coverage lives in
  ``tests/test_troubleshoot_response_contract.py``;
* logging failures do not crash runtime — the
  ``test_*_swallows_*`` cases prove that any exception (store-level
  Cosmos failures, repository-level boom) is converted to ``False`` and
  never escapes.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.config import (
    INTERACTION_LOG_BACKEND_COSMOS,
    INTERACTION_LOG_BACKEND_DISABLED,
    INTERACTION_LOG_BACKEND_MEMORY,
    AppSettings,
)
from backend.app.services import interaction_log_service as svc_module
from backend.app.services.interaction_log_service import (
    CosmosInteractionLogStore,
    DisabledInteractionLogStore,
    InMemoryInteractionLogStore,
    InteractionLog,
    InteractionLogService,
    InteractionLogServiceError,
    build_interaction_log_service,
    reset_for_tests,
)


def _settings_with_log_backend(backend: str) -> AppSettings:
    return AppSettings(interaction_log_backend=backend)


@pytest.fixture(autouse=True)
def _clear_singletons():
    """Every test starts with a clean process-wide singleton."""
    reset_for_tests()
    yield
    reset_for_tests()


# ---------------------------------------------------------------------------
# InteractionLog dataclass / schema
# ---------------------------------------------------------------------------


def test_interaction_log_defaults_match_build_prompt_schema():
    log = InteractionLog(session_id="sess-1", user_message="msg")
    document = log.to_dict()
    assert document["id"] == log.interaction_id
    assert document["interaction_id"] == log.interaction_id
    assert document["session_id"] == "sess-1"
    assert document["user_message"] == "msg"
    assert document["response_type"] == "answer"
    assert document["selected_workflow_id"] is None
    assert document["current_node_id"] is None
    assert document["observed_signals"] == {}
    assert document["retrieval_result_ids"] == []
    assert document["escalation_triggered"] is False
    assert document["assistant_response"] == {}
    assert document["runtime_trace"] == {}
    assert document["timestamp"]


def test_interaction_log_id_mirrors_interaction_id_for_cosmos():
    log = InteractionLog(
        interaction_id="fixed-id",
        session_id="sess-id",
        user_message="hi",
    )
    document = log.to_dict()
    assert document["id"] == "fixed-id"
    assert document["interaction_id"] == "fixed-id"


# ---------------------------------------------------------------------------
# InteractionLog.from_state per response_type
# ---------------------------------------------------------------------------


def _retrieval_obj(record_id: str) -> Any:
    return SimpleNamespace(record_id=record_id)


def _response(
    *,
    response_type: str = "answer",
    workflow_step: Any = None,
    escalation: Any = None,
) -> Any:
    return SimpleNamespace(
        response_type=response_type,
        workflow_step=workflow_step,
        escalation=escalation,
    )


def _state(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "session_id": "sess-from-state",
        "user_message": "msg",
        "selected_workflow_id": None,
        "canonical_workflow_id": None,
        "canonical_next_node_id": None,
        "extracted_signals": {},
        "retrieval_results": [],
        "escalation_required": False,
        "workflow_state": {},
    }
    base.update(overrides)
    return base


def test_from_state_answer_picks_extracted_signals_and_retrieval_ids():
    state = _state(
        extracted_signals={"agvs_stopped": True},
        retrieval_results=[_retrieval_obj("rec-1"), _retrieval_obj("rec-2")],
    )
    log = InteractionLog.from_state(
        session_id="sess-A",
        user_message="AGVs stopped",
        state=state,
        response=_response(response_type="answer"),
    )
    assert log.session_id == "sess-A"
    assert log.user_message == "AGVs stopped"
    assert log.response_type == "answer"
    assert log.selected_workflow_id is None
    assert log.current_node_id is None
    assert log.observed_signals == {"agvs_stopped": True}
    assert log.retrieval_result_ids == ["rec-1", "rec-2"]
    assert log.escalation_triggered is False


def test_from_state_persists_assistant_response_and_runtime_trace():
    response = SimpleNamespace(
        response_type="workflow_step",
        final_response="Restart guidance.",
        citations=[{"source_id": "src-1", "title": "Source"}],
        runtime_trace={"routing": {"canonical_route_mode": "approved"}},
    )
    log = InteractionLog.from_state(
        session_id="sess-trace",
        user_message="AGVs stopped",
        state=_state(canonical_workflow_id="wf-1"),
        response=response,
    )
    document = log.to_dict()
    assert document["final_response"] == "Restart guidance."
    assert document["citations"] == [{"source_id": "src-1", "title": "Source"}]
    assert document["assistant_response"]["response_type"] == "workflow_step"
    assert document["runtime_trace"]["routing"]["canonical_route_mode"] == "approved"


def test_interaction_log_from_dict_round_trips_enriched_fields():
    original = InteractionLog(
        interaction_id="fixed",
        session_id="sess",
        user_message="msg",
        response_type="answer",
        final_response="reply",
        citations=[{"source_id": "src"}],
        assistant_response={"response_type": "answer"},
        runtime_trace={"retrieval": {"top_confidence": 0.8}},
    )
    restored = InteractionLog.from_dict(original.to_dict())
    assert restored.interaction_id == "fixed"
    assert restored.final_response == "reply"
    assert restored.citations == [{"source_id": "src"}]
    assert restored.assistant_response == {"response_type": "answer"}
    assert restored.runtime_trace == {"retrieval": {"top_confidence": 0.8}}


def test_from_state_guided_question_uses_workflow_state_fields():
    state = _state(
        selected_workflow_id="wf-guided",
        canonical_next_node_id="entry_check",
        workflow_state={
            "current_node_id": "entry_check",
            "observed_signals": {"agvs_stopped": True},
        },
    )
    log = InteractionLog.from_state(
        session_id="sess-G",
        user_message="?",
        state=state,
        response=_response(response_type="guided_question"),
    )
    assert log.response_type == "guided_question"
    assert log.selected_workflow_id == "wf-guided"
    assert log.current_node_id == "entry_check"
    assert log.observed_signals == {"agvs_stopped": True}
    assert log.escalation_triggered is False


def test_from_state_workflow_step_prefers_runtime_payload_observed_signals():
    runtime_payload = {
        "workflow_id": "wf-runtime",
        "current_node_id": "check_rms",
        "observed_signals": {"agvs_stopped_before_tippers": True},
    }
    state = _state(
        selected_workflow_id="wf-runtime",
        workflow_state={
            "current_node_id": "OUTER",
            "observed_signals": {"OUTER": True},
            "workflow_step": runtime_payload,
        },
        extracted_signals={"LEGACY": True},
    )
    log = InteractionLog.from_state(
        session_id="sess-W",
        user_message="?",
        state=state,
        response=_response(response_type="workflow_step"),
    )
    assert log.response_type == "workflow_step"
    assert log.selected_workflow_id == "wf-runtime"
    assert log.current_node_id == "check_rms"
    assert log.observed_signals == {"agvs_stopped_before_tippers": True}


def test_from_state_escalation_marks_escalation_triggered_true():
    state = _state(
        selected_workflow_id="wf-esc",
        escalation_required=True,
        workflow_state={
            "current_node_id": "escalate_controls",
            "workflow_step": {
                "workflow_id": "wf-esc",
                "current_node_id": "escalate_controls",
                "observed_signals": {"rms_active_fault": True},
            },
        },
    )
    log = InteractionLog.from_state(
        session_id="sess-E",
        user_message="?",
        state=state,
        response=_response(response_type="escalation"),
    )
    assert log.response_type == "escalation"
    assert log.escalation_triggered is True
    assert log.current_node_id == "escalate_controls"


def test_from_state_escalation_triggered_true_even_when_response_type_is_answer():
    """escalation_required dominates regardless of the response_type label."""
    state = _state(escalation_required=True)
    log = InteractionLog.from_state(
        session_id="sess-Eflag",
        user_message="?",
        state=state,
        response=_response(response_type="answer"),
    )
    assert log.response_type == "answer"
    assert log.escalation_triggered is True


def test_from_state_terminal_pulls_through_runtime_payload():
    state = _state(
        selected_workflow_id="wf-term",
        workflow_state={
            "workflow_step": {
                "workflow_id": "wf-term",
                "current_node_id": "terminal_recovered",
                "observed_signals": {"agvs_resumed_movement": True},
            },
        },
    )
    log = InteractionLog.from_state(
        session_id="sess-T",
        user_message="?",
        state=state,
        response=_response(response_type="terminal"),
    )
    assert log.response_type == "terminal"
    assert log.selected_workflow_id == "wf-term"
    assert log.current_node_id == "terminal_recovered"
    assert log.observed_signals == {"agvs_resumed_movement": True}
    assert log.escalation_triggered is False


def test_from_state_handles_dict_retrieval_results():
    """Retrieval results may arrive as dicts (legacy serialisation paths)."""
    state = _state(retrieval_results=[{"record_id": "rec-dict"}])
    log = InteractionLog.from_state(
        session_id="sess",
        user_message="?",
        state=state,
        response=_response(response_type="answer"),
    )
    assert log.retrieval_result_ids == ["rec-dict"]


def test_from_state_defaults_response_type_to_answer_when_missing():
    state = _state()
    log = InteractionLog.from_state(
        session_id="sess",
        user_message="?",
        state=state,
        response=SimpleNamespace(response_type=None),
    )
    assert log.response_type == "answer"


def test_from_state_tolerates_empty_state():
    log = InteractionLog.from_state(
        session_id="sess-empty",
        user_message="?",
        state=None,
        response=_response(response_type="answer"),
    )
    assert log.session_id == "sess-empty"
    assert log.observed_signals == {}
    assert log.retrieval_result_ids == []


# ---------------------------------------------------------------------------
# InMemoryInteractionLogStore
# ---------------------------------------------------------------------------


def test_in_memory_store_record_and_list_for_session_round_trip():
    store = InMemoryInteractionLogStore()
    store.record(InteractionLog(session_id="sess-A", user_message="m1"))
    store.record(InteractionLog(session_id="sess-A", user_message="m2"))
    store.record(InteractionLog(session_id="sess-B", user_message="m3"))

    assert [log.user_message for log in store.list_for_session("sess-A")] == [
        "m1",
        "m2",
    ]
    assert [log.user_message for log in store.list_for_session("sess-B")] == ["m3"]
    assert len(store.all()) == 3


def test_in_memory_store_clear_drops_every_log():
    store = InMemoryInteractionLogStore()
    store.record(InteractionLog(session_id="sess", user_message="m"))
    store.clear()
    assert store.all() == []


# ---------------------------------------------------------------------------
# CosmosInteractionLogStore — happy path + error wrapping
# ---------------------------------------------------------------------------


class _StubCosmosRepository:
    """In-memory stand-in for :class:`InteractionLogRepository`."""

    def __init__(self) -> None:
        self.upsert_calls: list[dict[str, Any]] = []

    def upsert(self, document: dict[str, Any]) -> dict[str, Any]:
        self.upsert_calls.append(dict(document))
        return dict(document)

    def list_for_session(self, session_id: str) -> list[dict[str, Any]]:
        return [
            row for row in self.upsert_calls if row.get("session_id") == session_id
        ]


def test_cosmos_store_record_round_trips_through_stub_repository():
    repo = _StubCosmosRepository()
    store = CosmosInteractionLogStore(repository=repo)
    log = InteractionLog(
        interaction_id="fixed-id",
        session_id="sess-cosmos",
        user_message="msg",
        response_type="guided_question",
    )
    store.record(log)
    assert len(repo.upsert_calls) == 1
    document = repo.upsert_calls[0]
    assert document["id"] == "fixed-id"
    assert document["session_id"] == "sess-cosmos"
    assert document["response_type"] == "guided_question"


def test_cosmos_store_lists_session_logs_from_repository():
    repo = _StubCosmosRepository()
    store = CosmosInteractionLogStore(repository=repo)
    store.record(InteractionLog(session_id="sess-cosmos", user_message="m1"))
    store.record(InteractionLog(session_id="other", user_message="m2"))
    assert [log.user_message for log in store.list_for_session("sess-cosmos")] == [
        "m1"
    ]


def test_cosmos_store_wraps_repository_failures_in_service_error():
    class _BoomRepo:
        def upsert(self, document):
            raise RuntimeError("transport down")

    store = CosmosInteractionLogStore(repository=_BoomRepo())
    with pytest.raises(InteractionLogServiceError) as exc_info:
        store.record(InteractionLog(session_id="sess-boom", user_message="?"))
    assert "transport down" in str(exc_info.value)
    assert "sess-boom" in str(exc_info.value)


# ---------------------------------------------------------------------------
# DisabledInteractionLogStore
# ---------------------------------------------------------------------------


def test_disabled_store_record_is_no_op():
    store = DisabledInteractionLogStore()
    store.record(InteractionLog(session_id="sess", user_message="?"))
    assert store.list_for_session("sess") == []


# ---------------------------------------------------------------------------
# InteractionLogService.record — the "must not crash runtime" guarantee
# ---------------------------------------------------------------------------


def test_service_record_returns_true_on_success():
    store = InMemoryInteractionLogStore()
    service = InteractionLogService(store=store)
    log = InteractionLog(session_id="sess", user_message="ok")
    assert service.record(log) is True
    assert store.list_for_session("sess") == [log]


def test_service_list_for_session_swallows_store_errors():
    class _BoomStore:
        def list_for_session(self, session_id):
            raise RuntimeError("boom")

    service = InteractionLogService(store=_BoomStore())
    assert service.list_for_session("sess") == []


def test_service_record_swallows_store_service_errors_returns_false():
    class _BoomStore:
        def record(self, log):
            raise InteractionLogServiceError("cosmos exploded")

    service = InteractionLogService(store=_BoomStore())
    assert service.record(InteractionLog(session_id="sess", user_message="?")) is False


def test_service_record_swallows_arbitrary_exceptions_returns_false():
    class _NuclearStore:
        def record(self, log):
            raise ValueError("anything can throw")

    service = InteractionLogService(store=_NuclearStore())
    assert service.record(InteractionLog(session_id="sess", user_message="?")) is False


# ---------------------------------------------------------------------------
# build_interaction_log_service factory + singleton semantics
# ---------------------------------------------------------------------------


def test_build_factory_defaults_to_memory_store():
    service = build_interaction_log_service(
        _settings_with_log_backend(INTERACTION_LOG_BACKEND_MEMORY)
    )
    assert isinstance(service.store, InMemoryInteractionLogStore)


def test_build_factory_returns_disabled_store_when_selected():
    service = build_interaction_log_service(
        _settings_with_log_backend(INTERACTION_LOG_BACKEND_DISABLED)
    )
    assert isinstance(service.store, DisabledInteractionLogStore)


def test_build_factory_returns_cosmos_store_when_selected(monkeypatch):
    def _fake_init(self, repository=None):
        self._repository = repository or object()

    monkeypatch.setattr(CosmosInteractionLogStore, "__init__", _fake_init)
    service = build_interaction_log_service(
        _settings_with_log_backend(INTERACTION_LOG_BACKEND_COSMOS)
    )
    assert isinstance(service.store, CosmosInteractionLogStore)


def test_build_factory_raises_for_unknown_backend():
    with pytest.raises(InteractionLogServiceError):
        build_interaction_log_service(
            _settings_with_log_backend("invented_backend")
        )


def test_build_factory_returns_same_memory_singleton_across_calls():
    """Co-requisite for Step 14 — multi-turn demos share a single store."""
    settings = _settings_with_log_backend(INTERACTION_LOG_BACKEND_MEMORY)
    first = build_interaction_log_service(settings)
    second = build_interaction_log_service(settings)
    assert first is second
    assert first.store is second.store


def test_reset_for_tests_clears_singleton():
    settings = _settings_with_log_backend(INTERACTION_LOG_BACKEND_MEMORY)
    first = build_interaction_log_service(settings)
    first.record(InteractionLog(session_id="sess", user_message="?"))
    assert isinstance(first.store, InMemoryInteractionLogStore)
    assert first.store.list_for_session("sess")

    reset_for_tests()

    second = build_interaction_log_service(settings)
    assert second is not first
    assert isinstance(second.store, InMemoryInteractionLogStore)
    assert second.store.list_for_session("sess") == []


def test_reset_for_tests_swaps_backends():
    """After reset, the next build sees the new backend env."""
    first = build_interaction_log_service(
        _settings_with_log_backend(INTERACTION_LOG_BACKEND_MEMORY)
    )
    assert isinstance(first.store, InMemoryInteractionLogStore)

    reset_for_tests()

    second = build_interaction_log_service(
        _settings_with_log_backend(INTERACTION_LOG_BACKEND_DISABLED)
    )
    assert isinstance(second.store, DisabledInteractionLogStore)


def test_module_exposes_singleton_state_for_test_hooks():
    """Sanity check that the private singleton is reachable for monkeypatch."""
    assert hasattr(svc_module, "_memory_store_singleton")
    assert hasattr(svc_module, "_service_singleton")
