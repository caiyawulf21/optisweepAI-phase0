"""Tests for Phase 1 Cosmos container provisioning (Step 3).

Verifies that every container called out in
the Phase 1 master brief declared in ``container_config.CONTAINERS`` with a sensible partition
key, that the two new runtime containers
(``workflow_sessions`` / ``interaction_logs``) have repositories, and
that the provisioning CLI offers them on dry-run.
"""
from __future__ import annotations

import json

from backend.app.repositories import (
    InteractionLogRepository,
    WorkflowSessionRepository,
)
from backend.app.repositories.container_config import (
    CONTAINERS,
    PHASE1_RUNTIME_CONTAINER_NAMES,
)
from backend.app.scripts import create_cosmos_containers
from backend.app.services.interaction_log_service import CosmosInteractionLogStore


EXPECTED_PARTITION_KEYS: dict[str, str] = {
    "context_reference": "/context_type",
    "incident_records": "/issue_category",
    "timeline_events": "/incident_id",
    "workflow_definitions": "/issue_category",
    "procedure_dictionary": "/procedure_type",
    "raw_evidence_chunks": "/incident_id",
    "source_artifacts": "/incident_id",
    "canonical_images": "/category",
    "escalation_summaries": "/incident_id",
    "workflow_sessions": "/session_id",
    "interaction_logs": "/session_id",
}


def test_phase1_runtime_container_list_matches_build_prompt() -> None:
    assert set(PHASE1_RUNTIME_CONTAINER_NAMES) == set(EXPECTED_PARTITION_KEYS)


def test_all_phase1_containers_are_registered_with_expected_partition_keys() -> None:
    for name, partition_key in EXPECTED_PARTITION_KEYS.items():
        assert name in CONTAINERS, (
            f"Required Phase 1 container {name!r} missing from CONTAINERS"
        )
        assert CONTAINERS[name].partition_key == partition_key, (
            f"Container {name!r} has partition_key "
            f"{CONTAINERS[name].partition_key!r}, expected {partition_key!r}"
        )


def test_workflow_session_repository_targets_workflow_sessions_container() -> None:
    assert WorkflowSessionRepository.container_name == "workflow_sessions"


def test_interaction_log_repository_targets_interaction_logs_container() -> None:
    assert InteractionLogRepository.container_name == "interaction_logs"


def test_cosmos_interaction_log_store_lazy_loads_interaction_log_repository(
    monkeypatch,
) -> None:
    """Pin the wiring from the Step 13 store to the Step 3 Cosmos repository.

    The store must defer construction until first use AND target the
    ``interaction_logs`` container so it lands on the same partition key
    (``/session_id``) the provisioning CLI declared.
    """
    captured: dict[str, object] = {}

    def _stub_init(self, container=None) -> None:
        captured["called"] = True
        self.container = container or object()

    monkeypatch.setattr(
        "backend.app.repositories.base_repository.CosmosRepository.__init__",
        _stub_init,
    )

    store = CosmosInteractionLogStore()
    assert "called" not in captured, (
        "CosmosInteractionLogStore must not build the repository at __init__ time"
    )
    repo = store._repo()
    assert captured.get("called") is True
    assert repo.container_name == "interaction_logs"
    assert isinstance(repo, InteractionLogRepository)


def test_create_cosmos_containers_dry_run_lists_phase1_containers(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr("sys.argv", ["create_cosmos_containers", "--dry-run"])
    create_cosmos_containers.main()
    payload = json.loads(capsys.readouterr().out)
    listed = {entry["container"] for entry in payload["containers"]}
    for name in PHASE1_RUNTIME_CONTAINER_NAMES:
        assert name in listed, f"Provisioning CLI missed {name!r} on --dry-run"
