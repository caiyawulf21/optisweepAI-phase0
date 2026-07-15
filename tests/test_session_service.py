"""Tests for Phase 1 Step 9 — runtime session persistence."""
from __future__ import annotations

import os
from typing import Any

import pytest

from backend.app.config import (
    SESSION_BACKEND_COSMOS,
    SESSION_BACKEND_MEMORY,
    AppSettings,
)
from backend.app.services.session_service import (
    CosmosSessionStore,
    InMemorySessionStore,
    SessionService,
    SessionServiceError,
    VALID_SESSION_STATUSES,
    WorkflowSession,
    build_session_service,
)


def _settings_with_backend(backend: str) -> AppSettings:
    """Build an :class:`AppSettings` with the requested ``session_backend``.

    Avoids relying on process env so the tests do not leak state to other
    tests in the suite.
    """
    return AppSettings(session_backend=backend)


def test_workflow_session_defaults_match_build_prompt_schema():
    session = WorkflowSession(session_id="sess-123")
    document = session.to_dict()
    assert document["id"] == "sess-123"
    assert document["session_id"] == "sess-123"
    assert document["user_id"] == ""
    assert document["active_workflow_id"] is None
    assert document["current_node_id"] is None
    assert document["observed_signals"] == {}
    assert document["answered_questions"] == []
    assert document["retrieval_result_ids"] == []
    assert document["steps_attempted"] == []
    assert document["workflow_history"] == []
    assert document["escalation_state"] == {}
    assert document["status"] == "active"
    assert document["status"] in VALID_SESSION_STATUSES
    assert document["created_at"]
    assert document["updated_at"]


def test_workflow_session_round_trips_through_to_and_from_dict():
    session = WorkflowSession(
        session_id="sess-rt",
        user_id="user-1",
        active_workflow_id="wf-1",
        current_node_id="node-a",
        observed_signals={"agvs_stopped_before_tippers": True},
        retrieval_result_ids=["inc_229374"],
        steps_attempted=["entry_check"],
        status="active",
    )
    session.record_answer(
        node_id="entry_check",
        question="AGVs stopped?",
        answer="yes",
        resulting_signals={"agvs_stopped_before_tippers": True},
    )
    session.record_history(
        from_node_id="entry_check",
        to_node_id="check_rms",
        condition_signal="agvs_stopped_before_tippers",
        condition_value=True,
    )
    document = session.to_dict()
    reloaded = WorkflowSession.from_dict(document)
    assert reloaded.session_id == "sess-rt"
    assert reloaded.user_id == "user-1"
    assert reloaded.active_workflow_id == "wf-1"
    assert reloaded.current_node_id == "node-a"
    assert reloaded.observed_signals == {"agvs_stopped_before_tippers": True}
    assert reloaded.retrieval_result_ids == ["inc_229374"]
    assert reloaded.steps_attempted == ["entry_check"]
    assert reloaded.status == "active"
    assert len(reloaded.answered_questions) == 1
    assert reloaded.answered_questions[0]["answer"] == "yes"
    assert len(reloaded.workflow_history) == 1
    assert reloaded.workflow_history[0]["to_node_id"] == "check_rms"


def test_workflow_session_merge_signals_keeps_truthy_observations():
    session = WorkflowSession(session_id="sess-m")
    session.merge_signals({"agvs_stopped_before_tippers": True})
    session.merge_signals({"agvs_stopped_before_tippers": False, "rms_screen_no_faults_visible": True})
    assert session.observed_signals == {
        "agvs_stopped_before_tippers": True,
        "rms_screen_no_faults_visible": True,
    }


def test_workflow_session_merge_signals_records_observed_false_for_new_key():
    session = WorkflowSession(session_id="sess-false")
    session.merge_signals({"rms_screen_active_fault": False})
    assert session.observed_signals == {"rms_screen_active_fault": False}


def test_workflow_session_merge_canonical_signals_keeps_truthy_observations():
    """Truthy canonical observations are sticky across turns; later False
    observations cannot demote them. Ensures multi-turn dynamic mode
    accumulates positive evidence the way the build prompt requires.
    """
    session = WorkflowSession(session_id="sess-canon")
    session.merge_canonical_signals({"optisweep_service_restart_completed": True})
    session.merge_canonical_signals(
        {"optisweep_service_restart_completed": False, "tipper_heartbeat_normal": True}
    )
    assert session.observed_canonical_signals == {
        "optisweep_service_restart_completed": True,
        "tipper_heartbeat_normal": True,
    }


def test_workflow_session_merge_components_is_order_stable_and_deduped():
    session = WorkflowSession(session_id="sess-comp")
    session.merge_components(["agv", "tipper"])
    session.merge_components(["tipper", "hospital_tote", "agv"])
    assert session.observed_components == ["agv", "tipper", "hospital_tote"]


def test_workflow_session_observed_canonical_signals_round_trip():
    session = WorkflowSession(
        session_id="sess-rt",
        observed_canonical_signals={"optisweep_service_restart_completed": True},
        observed_components=["agv", "tipper"],
    )
    document = session.to_dict()
    assert document["observed_canonical_signals"] == {
        "optisweep_service_restart_completed": True
    }
    assert document["observed_components"] == ["agv", "tipper"]
    rehydrated = WorkflowSession.from_dict(document)
    assert (
        rehydrated.observed_canonical_signals.get("optisweep_service_restart_completed")
        is True
    )
    assert rehydrated.observed_components == ["agv", "tipper"]


def test_workflow_session_record_step_skips_consecutive_duplicates():
    session = WorkflowSession(session_id="sess-step")
    session.record_step("entry_check")
    session.record_step("entry_check")
    session.record_step("check_rms")
    session.record_step("check_rms")
    session.record_step("check_heartbeat")
    assert session.steps_attempted == ["entry_check", "check_rms", "check_heartbeat"]


def test_workflow_session_record_retrieval_ids_dedupes():
    session = WorkflowSession(session_id="sess-r")
    session.record_retrieval_ids(["inc_229374", "inc_229716"])
    session.record_retrieval_ids(["inc_229374", "inc_229777"])
    assert session.retrieval_result_ids == ["inc_229374", "inc_229716", "inc_229777"]


def test_workflow_session_from_dict_validates_session_id():
    with pytest.raises(SessionServiceError):
        WorkflowSession.from_dict({"observed_signals": {}})
    with pytest.raises(SessionServiceError):
        WorkflowSession.from_dict({"session_id": ""})


def test_workflow_session_from_dict_coerces_signals_to_bool():
    reloaded = WorkflowSession.from_dict(
        {
            "session_id": "sess-coerce",
            "observed_signals": {"a": 1, "b": 0, "c": "yes"},
        }
    )
    assert reloaded.observed_signals == {"a": True, "b": False, "c": True}


def test_workflow_session_from_dict_falls_back_to_active_for_unknown_status():
    reloaded = WorkflowSession.from_dict(
        {"session_id": "sess-status", "status": "bogus"}
    )
    assert reloaded.status == "active"


def test_inmemory_store_get_or_create_returns_existing_session_on_second_call():
    service = SessionService(store=InMemorySessionStore())
    first = service.get_or_create("sess-1", user_id="user-1")
    second = service.get_or_create("sess-1", user_id="someone-else-ignored")
    assert first.session_id == second.session_id == "sess-1"
    assert second.user_id == "user-1"
    third = service.get("sess-1")
    assert third is not None
    assert third.session_id == "sess-1"


def test_inmemory_store_save_persists_signal_mutations_across_turns():
    service = SessionService(store=InMemorySessionStore())
    session = service.get_or_create("sess-multi")
    session.merge_signals({"agvs_stopped_before_tippers": True})
    session.current_node_id = "check_rms"
    session.record_step("entry_check")
    service.save(session)

    reloaded = service.get("sess-multi")
    assert reloaded is not None
    assert reloaded.observed_signals == {"agvs_stopped_before_tippers": True}
    assert reloaded.current_node_id == "check_rms"
    assert reloaded.steps_attempted == ["entry_check"]

    reloaded.merge_signals({"rms_screen_no_faults_visible": True})
    reloaded.record_step("check_rms")
    service.save(reloaded)

    final = service.get("sess-multi")
    assert final is not None
    assert final.observed_signals == {
        "agvs_stopped_before_tippers": True,
        "rms_screen_no_faults_visible": True,
    }
    assert final.steps_attempted == ["entry_check", "check_rms"]


def test_inmemory_store_save_bumps_updated_at():
    store = InMemorySessionStore()
    service = SessionService(store=store)
    session = service.get_or_create("sess-touch")
    original_updated = session.updated_at
    session.merge_signals({"x": True})
    saved = service.save(session)
    assert saved.updated_at >= original_updated


def test_inmemory_store_delete_removes_session():
    service = SessionService(store=InMemorySessionStore())
    service.get_or_create("sess-del")
    assert service.get("sess-del") is not None
    service.delete("sess-del")
    assert service.get("sess-del") is None
    service.delete("sess-del")


def test_session_service_status_transitions():
    service = SessionService(store=InMemorySessionStore())
    session = service.get_or_create("sess-status")
    service.mark_escalated(
        session, escalation_state={"reason": "operator opt-out", "domain": "controls"}
    )
    assert service.get("sess-status").status == "escalated"
    assert service.get("sess-status").escalation_state["domain"] == "controls"

    service.mark_resolved(session)
    assert service.get("sess-status").status == "resolved"

    service.mark_abandoned(session)
    assert service.get("sess-status").status == "abandoned"


def test_build_session_service_defaults_to_memory_store():
    service = build_session_service(_settings_with_backend(SESSION_BACKEND_MEMORY))
    assert isinstance(service.store, InMemorySessionStore)


def test_save_playbook_session_syncs_top_level_memory_fields():
    from backend.app.agents.runtime import save_playbook_session
    from backend.app.graph.playbook_state import PlaybookSessionSlice
    from backend.app.services.session_service import reset_for_tests

    reset_for_tests()
    slice_ = PlaybookSessionSlice(
        publish_version_id="v1",
        playbook_variant="prompt_a",
        active_playbook_id="playbook_incident_228086",
        active_case_id="228086",
        current_node_id="node_1",
        observed_signals={"agvs_stopped": True},
        last_retrieval_confidence=0.71,
        pin_source="retrieval",
    )
    save_playbook_session(
        "sess-memory-sync",
        slice_,
        state={
            "operator_role": "L1_support",
            "current_node_id": "node_1",
            "retrieval_hits": [
                {"record_id": "emb_1", "source_record_id": "playbook_incident_228086"}
            ],
        },
    )
    service = build_session_service(_settings_with_backend(SESSION_BACKEND_MEMORY))
    session = service.get("sess-memory-sync")
    assert session is not None
    assert session.active_workflow_id == "playbook_incident_228086"
    assert session.observed_signals.get("agvs_stopped") is True
    assert session.mode == "playbook"
    assert session.operator_role == "L1_support"
    assert "emb_1" in session.retrieval_result_ids
    assert session.dynamic_path["playbook"]["active_playbook_id"] == "playbook_incident_228086"
    assert session.dynamic_path["playbook"]["last_retrieval_confidence"] == 0.71


def test_build_session_service_returns_cosmos_store_when_selected(monkeypatch):
    sentinel_repo = object()

    def _fake_init(self, repository=None):
        self._repository = repository or sentinel_repo
        self._lazy_loaded = True

    monkeypatch.setattr(CosmosSessionStore, "__init__", _fake_init)
    service = build_session_service(_settings_with_backend(SESSION_BACKEND_COSMOS))
    assert isinstance(service.store, CosmosSessionStore)


def test_build_session_service_raises_for_unknown_backend():
    with pytest.raises(SessionServiceError):
        build_session_service(_settings_with_backend("invented_backend"))


class _StubCosmosRepository:
    """In-memory stand-in for :class:`WorkflowSessionRepository`.

    Exercises the contract the real Cosmos repository exposes: ``upsert(doc)``,
    ``get(item_id, partition_key)``, ``delete(item_id, partition_key)``. The
    stub records every call so tests can assert dispatch behaviour.
    """

    def __init__(self) -> None:
        self.store: dict[str, dict[str, Any]] = {}
        self.upsert_calls: list[dict[str, Any]] = []
        self.get_calls: list[tuple[str, str]] = []
        self.delete_calls: list[tuple[str, str]] = []

    def upsert(self, document: dict[str, Any]) -> dict[str, Any]:
        self.upsert_calls.append(dict(document))
        self.store[document["id"]] = dict(document)
        return dict(document)

    def get(self, item_id: str, partition_key: str) -> dict[str, Any]:
        self.get_calls.append((item_id, partition_key))
        if item_id not in self.store:
            try:
                from azure.cosmos.exceptions import (  # type: ignore
                    CosmosResourceNotFoundError,
                )
            except ImportError:  # pragma: no cover - exercised only when azure SDK absent
                class _FakeNotFound(Exception):
                    pass

                raise _FakeNotFound("not found")
            raise CosmosResourceNotFoundError(status_code=404, message="not found")
        return dict(self.store[item_id])

    def delete(self, item_id: str, partition_key: str) -> None:
        self.delete_calls.append((item_id, partition_key))
        self.store.pop(item_id, None)


def test_cosmos_store_persists_through_stub_repository_round_trip():
    repo = _StubCosmosRepository()
    store = CosmosSessionStore(repository=repo)
    service = SessionService(store=store)

    session = service.get_or_create("sess-cosmos", user_id="op-1")
    assert len(repo.upsert_calls) == 1
    upserted = repo.upsert_calls[0]
    assert upserted["id"] == "sess-cosmos"
    assert upserted["session_id"] == "sess-cosmos"
    assert upserted["user_id"] == "op-1"
    assert upserted["status"] == "active"

    session.merge_signals({"agvs_stopped_before_tippers": True})
    session.current_node_id = "check_rms"
    service.save(session)

    reloaded = service.get("sess-cosmos")
    assert reloaded is not None
    assert reloaded.observed_signals == {"agvs_stopped_before_tippers": True}
    assert reloaded.current_node_id == "check_rms"

    service.delete("sess-cosmos")
    assert repo.delete_calls == [("sess-cosmos", "sess-cosmos")]


def test_cosmos_store_get_returns_none_when_repository_raises_not_found():
    pytest.importorskip("azure.cosmos")
    repo = _StubCosmosRepository()
    store = CosmosSessionStore(repository=repo)
    assert store.get("missing-session") is None
    assert repo.get_calls == [("missing-session", "missing-session")]


def test_cosmos_store_wraps_unexpected_exceptions_in_session_service_error():
    class _BoomRepo:
        def upsert(self, doc):
            raise RuntimeError("transport down")

    store = CosmosSessionStore(repository=_BoomRepo())
    with pytest.raises(SessionServiceError) as exc_info:
        store.save(WorkflowSession(session_id="sess-boom"))
    assert "sess-boom" in str(exc_info.value)
    assert "transport down" in str(exc_info.value)
