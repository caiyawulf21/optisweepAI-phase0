from __future__ import annotations

import pytest

from backend.app.corpus.cosmos_client import CosmosCorpusClient
from backend.app.corpus.settings import CorpusSettings
from backend.app.runtime.playbook_runtime import (
    reset_playbook_graphs,
    run_playbook_troubleshoot,
    run_retrieve_chat,
)
from backend.app.agents.runtime import _unique_branch_answers
from backend.app.api.troubleshoot import _build_troubleshoot_response


@pytest.fixture(autouse=True)
def _reset_graphs() -> None:
    reset_playbook_graphs()
    yield
    reset_playbook_graphs()


@pytest.fixture
def sample_client() -> CosmosCorpusClient:
    settings = CorpusSettings(
        cosmos_endpoint="",
        cosmos_key="",
        cosmos_database="test",
        container_runbooks="runbooks",
        container_playbooks_a="playbooks_prompt_a",
        container_playbooks_b="playbooks_prompt_b",
        container_relationship_links="relationship_links",
        container_source_artifacts="source_artifacts",
        container_operational_context="operational_context",
        container_canonical_images="publish_canonical_images",
        publish_version_id="handoff-demo-v1",
        auto_publish_version=False,
        playbook_match_threshold=0.80,
        playbook_high_confidence_threshold=0.90,
        playbook_pin_coverage_threshold=0.40,
        default_playbook_variant="prompt_a",
        skip_playbook_confirmation=True,
        enable_llm_branch_match=False,
        enable_llm_retrieve_synthesis=False,
        enable_llm_orchestrator=False,
    )
    return CosmosCorpusClient(settings)


def test_load_sample_playbook_228086(sample_client: CosmosCorpusClient) -> None:
    index = sample_client.load_index()
    assert len(index.embeddings) > 0
    playbook_hits = [item for item in index.embeddings if "228086" in item.source_record_id]
    assert playbook_hits
    playbook_id = playbook_hits[0].source_record_id
    payload = sample_client.get_playbook(playbook_id, variant="prompt_a")
    assert payload is not None
    assert payload.get("case_id") == "228086"


def test_agvs_stopped_surfaces_candidates_for_user_select(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKIP_PLAYBOOK_CONFIRMATION", "false")
    state = run_playbook_troubleshoot(
        "test-agvs",
        "AGVs stopped and nothing is moving on site",
        playbook_variant="prompt_a",
    )
    assert state.get("extracted_observed_signals", {}).get("agvs_stopped") is True
    assert state.get("retrieval_confidence", 0) > 0
    assert not state.get("active_playbook_id")
    assert state.get("response_type") == "playbook_candidates"
    candidates = list(state.get("playbook_candidates") or [])
    assert candidates
    top = candidates[0]
    assert top.get("incidence_id") or top.get("case_id")
    assert top.get("incidence_summary")
    assert top.get("when_to_choose") or top.get("observed_entry_symptoms")
    hit = (state.get("retrieval_hits") or [{}])[0]
    assert float(hit.get("combined_score") or 0.0) >= 0.55
    assert "coverage" in hit and "symptom_score" in hit
    response = _build_troubleshoot_response(state)
    assert response.retrieval_confidence > 0
    assert response.extracted_observed_signals.get("agvs_stopped") is True
    assert response.response_type == "playbook_candidates"


def test_agvs_stopped_auto_pins_when_confirmation_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKIP_PLAYBOOK_CONFIRMATION", "true")
    state = run_playbook_troubleshoot(
        "test-agvs-autopin",
        "AGVs stopped and nothing is moving on site",
        playbook_variant="prompt_a",
    )
    assert state.get("active_playbook_id")
    assert "228086" in str(state.get("active_playbook_id") or state.get("active_case_id") or "")


def test_sparse_agvs_stopped_defers_to_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKIP_PLAYBOOK_CONFIRMATION", "false")
    state = run_playbook_troubleshoot(
        "test-agvs-sparse",
        "AGVs stopped",
        playbook_variant="prompt_a",
    )
    assert not state.get("active_playbook_id")
    assert state.get("response_type") == "playbook_candidates"
    top = (state.get("retrieval_hits") or [{}])[0]
    assert float(top.get("coverage") or 0.0) >= 0.25
    agents = (state.get("runtime_trace") or {}).get("agents") or []
    assert any(
        step.get("agent") == "playbook_pin_agent"
        and step.get("action") == "defer_to_candidates"
        for step in agents
    )


def test_sparse_agvs_stopped_pins_with_coverage_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKIP_PLAYBOOK_CONFIRMATION", "true")
    state = run_playbook_troubleshoot(
        "test-agvs-sparse-pin",
        "AGVs stopped",
        playbook_variant="prompt_a",
    )
    assert state.get("active_playbook_id")
    assert "228086" in str(state.get("active_playbook_id") or state.get("active_case_id") or "")
    top = (state.get("retrieval_hits") or [{}])[0]
    assert float(top.get("coverage") or 0.0) >= 0.25
    combined = float(top.get("combined_score") or 0.0)
    assert combined >= 0.55
    agents = (state.get("runtime_trace") or {}).get("agents") or []
    pin_steps = [
        step
        for step in agents
        if step.get("agent") == "playbook_pin_agent" and step.get("action") == "pin"
    ]
    assert pin_steps
    assert "cosine" in pin_steps[0] and "coverage" in pin_steps[0]


def test_prompt_phrase_no_rms_alarms_observed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKIP_PLAYBOOK_CONFIRMATION", "false")
    monkeypatch.setenv("ENABLE_LLM_SYMPTOM_EXTRACTION", "false")
    from backend.app.services.keyword_signal_extractor import reset_for_tests

    reset_for_tests()
    state = run_playbook_troubleshoot(
        "test-no-rms",
        "AGVs stop, no RMS alarms",
        playbook_variant="prompt_a",
    )
    observed = state.get("extracted_observed_signals") or {}
    assert observed.get("no_rms_alarm") is True
    assert observed.get("agvs_stopped") is True


def test_llm_false_cannot_drop_keyword_no_rms_alarm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKIP_PLAYBOOK_CONFIRMATION", "false")
    monkeypatch.setenv("ENABLE_LLM_SYMPTOM_EXTRACTION", "true")
    from backend.app.config import get_app_settings
    from backend.app.services.keyword_signal_extractor import reset_for_tests

    if hasattr(get_app_settings, "cache_clear"):
        get_app_settings.cache_clear()
    reset_for_tests()

    def _fake_overlay(**_kwargs):
        return {
            "signals": {"agvs_stopped": True, "no_rms_alarm": False},
            "canonical_signals": {"rms_screen_no_faults_visible": False},
            "components": ["agv", "rms"],
            "confidences": {"agvs_stopped": 0.9, "no_rms_alarm": 0.9},
            "fresh_issue": False,
            "rationale": "test stub incorrectly treats absence as false",
            "model": "test-stub",
            "dropped_unknown_keys": [],
        }

    monkeypatch.setattr(
        "backend.app.agents.runtime._maybe_llm_symptom_overlay",
        _fake_overlay,
    )
    state = run_playbook_troubleshoot(
        "test-no-rms-llm-false",
        "AGVs stop, no RMS alarms",
        playbook_variant="prompt_a",
    )
    observed = state.get("extracted_observed_signals") or {}
    assert observed.get("no_rms_alarm") is True
    assert observed.get("agvs_stopped") is True


def test_extraction_memory_persists_across_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKIP_PLAYBOOK_CONFIRMATION", "false")
    monkeypatch.setenv("ENABLE_LLM_SYMPTOM_EXTRACTION", "false")
    from backend.app.agents.runtime import load_playbook_session
    from backend.app.services.keyword_signal_extractor import reset_for_tests
    from backend.app.services.session_service import build_session_service

    reset_for_tests()
    turn1 = run_playbook_troubleshoot(
        "test-memory",
        "AGVs stopped",
        playbook_variant="prompt_a",
    )
    assert turn1.get("extracted_observed_signals", {}).get("agvs_stopped") is True
    turn2 = run_playbook_troubleshoot(
        "test-memory",
        "also no RMS alarms",
        playbook_variant="prompt_a",
    )
    observed = turn2.get("extracted_observed_signals") or {}
    assert observed.get("agvs_stopped") is True
    assert observed.get("no_rms_alarm") is True
    session = build_session_service().get_or_create("test-memory")
    slice_ = load_playbook_session(session)
    turns = list((slice_.extraction_memory or {}).get("operator_symptom_turns") or [])
    assert len(turns) >= 2


def test_no_symptoms_skips_retrieval() -> None:
    state = run_playbook_troubleshoot(
        "test-no-symptoms",
        "hello can you help",
        playbook_variant="prompt_a",
    )
    assert state.get("needs_symptom_clarification") is True
    assert not state.get("active_playbook_id")
    assert (state.get("retrieval_hits") or []) == []
    assert "observable symptoms" in str(state.get("final_response") or "").lower()


def test_thin_coverage_asks_for_candidates() -> None:
    state = run_playbook_troubleshoot(
        "test-thin-coverage",
        "robots",
        playbook_variant="prompt_b",
    )
    assert state.get("issue_category") is None
    if not state.get("active_playbook_id"):
        assert state.get("response_type") in {"playbook_candidates", "answer"}
        agents = (state.get("runtime_trace") or {}).get("agents") or []
        assert any(
            step.get("agent") in {"orchestrator_agent", "playbook_pin_agent"}
            for step in agents
        )


def test_unique_branch_answers_skips_runbook_step_noise() -> None:
    node = {
        "decision_outcomes": [
            {"outcome_label": "healthy", "source": "playbook_expected_result"},
            {"outcome_label": "unhealthy", "source": "playbook_expected_result"},
            {"outcome_label": "inconclusive", "source": "playbook_expected_result"},
            {"outcome_label": "healthy", "source": "runbook_step"},
            {"outcome_label": "healthy", "source": "runbook_step"},
            {"outcome_label": "unhealthy", "source": "runbook_step"},
        ],
        "branches": [{"outcome": "healthy"}],
    }
    assert _unique_branch_answers(node) == ["healthy", "unhealthy", "inconclusive"]


def test_branch_options_include_next_node_titles() -> None:
    from backend.app.agents.runtime import _branch_options

    playbook = {
        "nodes": [
            {"node_id": "node_1", "title": "Check RMS"},
            {"node_id": "node_2", "title": "Inspect OptiSweep service"},
            {"node_id": "node_3", "title": "Escalate to L2"},
        ]
    }
    node = {
        "decision_outcomes": [
            {
                "outcome_label": "healthy",
                "next_node_id": "node_2",
                "source": "playbook_expected_result",
            },
            {
                "outcome_label": "unhealthy",
                "next_node_id": "node_3",
                "source": "playbook_expected_result",
            },
            {
                "outcome_label": "inconclusive",
                "source": "playbook_expected_result",
            },
        ]
    }
    options = _branch_options(node, playbook)
    by_label = {item["label"]: item for item in options}
    assert by_label["healthy"]["next_node_title"] == "Inspect OptiSweep service"
    assert by_label["unhealthy"]["next_node_title"] == "Escalate to L2"
    assert by_label["inconclusive"]["next_node_id"] is None


def test_branch_options_fill_next_node_from_branches() -> None:
    from backend.app.agents.runtime import _branch_options

    playbook = {
        "nodes": [
            {"node_id": "node_1", "title": "Confirm stoppage"},
            {
                "node_id": "node_6",
                "title": "Check for residual AGV desynchronization after service recovery",
            },
        ]
    }
    node = {
        "decision_outcomes": [
            {
                "outcome_label": "healthy",
                "next_node_id": "",
                "source": "playbook_expected_result",
            },
            {
                "outcome_label": "unhealthy",
                "next_node_id": "",
                "source": "playbook_expected_result",
            },
            {
                "outcome_label": "inconclusive",
                "next_node_id": "",
                "source": "playbook_expected_result",
            },
        ],
        "branches": [
            {
                "outcome": "healthy",
                "next_node_id": "node_6",
            }
        ],
    }
    options = _branch_options(node, playbook)
    by_label = {item["label"]: item for item in options}
    assert by_label["healthy"]["next_node_id"] == "node_6"
    assert by_label["healthy"]["next_node_title"] == (
        "Check for residual AGV desynchronization after service recovery"
    )
    assert by_label["unhealthy"]["next_node_id"] is None


def test_branch_answer_advances_to_next_node() -> None:
    from backend.app.agents.runtime import apply_branch_answer
    from backend.app.graph.playbook_state import PlaybookSessionSlice

    playbook = {
        "nodes": [
            {
                "node_id": "node_1",
                "title": "Confirm site-wide stoppage and abnormal control-system presentation",
                "decision_outcomes": [
                    {
                        "outcome_label": "healthy",
                        "next_node_id": "",
                        "source": "playbook_expected_result",
                    },
                    {
                        "outcome_label": "unhealthy",
                        "next_node_id": "",
                        "source": "playbook_expected_result",
                    },
                    {
                        "outcome_label": "inconclusive",
                        "next_node_id": "",
                        "source": "playbook_expected_result",
                    },
                ],
                "branches": [{"outcome": "healthy", "next_node_id": "node_6"}],
            },
            {
                "node_id": "node_6",
                "title": "Check for residual AGV desynchronization after service recovery",
                "intent": "Determine whether AGVs remain out of sync.",
                "decision_outcomes": [
                    {
                        "outcome_label": "healthy",
                        "source": "playbook_expected_result",
                    },
                    {
                        "outcome_label": "unhealthy",
                        "source": "playbook_expected_result",
                    },
                    {
                        "outcome_label": "inconclusive",
                        "source": "playbook_expected_result",
                    },
                ],
            },
        ]
    }
    slice_ = PlaybookSessionSlice(
        publish_version_id="handoff-demo-v1",
        active_playbook_id="playbook_incident_228086_site_wide_motion_stoppage_service_recovery",
        current_node_id="node_1",
        branch_state={
            "awaiting_branch": True,
            "resolved": False,
            "allowed_answers": ["healthy", "unhealthy", "inconclusive"],
            "node_id": "node_1",
        },
    )
    state = {
        "session_id": "test-branch-advance",
        "user_message": "healthy",
        "playbook_payload": playbook,
        "branch_state": dict(slice_.branch_state),
        "guided_question": {
            "allowed_answers": ["healthy", "unhealthy", "inconclusive"],
            "node_id": "node_1",
        },
        "completed_node_ids": [],
        "current_node_id": "node_1",
        "_playbook_slice": slice_,
        "runtime_trace": {"agents": []},
    }
    out = apply_branch_answer(state)
    assert out["current_node_id"] == "node_6"
    assert slice_.current_node_id == "node_6"
    assert slice_.completed_node_ids == ["node_1"]
    assert out.get("branch_state") == {}
    assert not out.get("branch_state", {}).get("resolved")
    assert out.get("_guided_button_answer") is True
    assert slice_.path_evidence
    assert slice_.path_evidence[-1]["node_id"] == "node_1"
    assert slice_.path_evidence[-1]["outcome"] == "healthy"
    agents = (out.get("runtime_trace") or {}).get("agents") or []
    assert any(
        step.get("action") == "keyword_classify" and step.get("guided_button")
        for step in agents
    )
    assert not any(step.get("action") == "llm_classify" for step in agents)

    from backend.app.agents.runtime import execute_playbook_node

    executed = execute_playbook_node(out)
    assert executed["current_node_id"] == "node_6"
    assert executed.get("response_type") == "guided_question"
    answers = (executed.get("guided_question") or {}).get("allowed_answers") or []
    assert {"healthy", "unhealthy", "inconclusive"} <= {str(item).lower() for item in answers}
    assert "desynchronization" in str(executed.get("final_response") or "").lower()


def test_branch_classify_retriage_clears_playbook() -> None:
    from backend.app.agents.runtime import apply_branch_answer
    from backend.app.graph.playbook_state import PlaybookSessionSlice

    slice_ = PlaybookSessionSlice(
        publish_version_id="handoff-demo-v1",
        active_playbook_id="playbook_incident_228086_site_wide_motion_stoppage_service_recovery",
        active_case_id="228086",
        current_node_id="node_6",
        branch_state={
            "awaiting_branch": True,
            "resolved": False,
            "allowed_answers": ["healthy", "unhealthy", "inconclusive"],
            "node_id": "node_6",
        },
        observed_signals={"agvs_stopped": True},
        path_evidence=[
            {
                "node_id": "node_1",
                "title": "Confirm stoppage",
                "outcome": "unhealthy",
                "evidence": "Site-wide stoppage",
            }
        ],
    )
    state = {
        "session_id": "test-branch-retriage",
        "user_message": "actually the zone cannot get a pair and AMRs are going to hospital",
        "playbook_payload": {
            "nodes": [
                {
                    "node_id": "node_6",
                    "title": "Check for residual AGV desynchronization after service recovery",
                    "decision_outcomes": [
                        {"outcome_label": "healthy", "source": "playbook_expected_result"},
                        {"outcome_label": "unhealthy", "source": "playbook_expected_result"},
                        {"outcome_label": "inconclusive", "source": "playbook_expected_result"},
                    ],
                }
            ]
        },
        "branch_state": dict(slice_.branch_state),
        "guided_question": {
            "allowed_answers": ["healthy", "unhealthy", "inconclusive"],
            "node_id": "node_6",
        },
        "completed_node_ids": ["node_1"],
        "current_node_id": "node_6",
        "active_playbook_id": slice_.active_playbook_id,
        "_playbook_slice": slice_,
        "runtime_trace": {"agents": []},
    }
    out = apply_branch_answer(state)
    assert out.get("_route_after_branch") == "extract"
    assert out.get("active_playbook_id") is None
    assert slice_.active_playbook_id is None
    assert out.get("_retriage_turn") is True
    assert slice_.observed_signals.get("agvs_stopped") is True
    assert slice_.path_evidence[0]["node_id"] == "node_1"
    assert out.get("_retriage_prior", {}).get("node_id") == "node_6"
    agents = (out.get("runtime_trace") or {}).get("agents") or []
    assert any(step.get("action") == "retriage" for step in agents)


def test_branch_classify_probe_keeps_awaiting() -> None:
    from backend.app.agents.runtime import apply_branch_answer
    from backend.app.graph.playbook_state import PlaybookSessionSlice

    slice_ = PlaybookSessionSlice(
        publish_version_id="handoff-demo-v1",
        active_playbook_id="playbook_x",
        current_node_id="node_1",
        branch_state={
            "awaiting_branch": True,
            "resolved": False,
            "allowed_answers": ["healthy", "unhealthy", "inconclusive"],
            "node_id": "node_1",
        },
    )
    state = {
        "session_id": "test-branch-probe",
        "user_message": "hmm",
        "playbook_payload": {
            "nodes": [
                {
                    "node_id": "node_1",
                    "title": "Confirm stoppage",
                    "decision_outcomes": [
                        {"outcome_label": "healthy", "source": "playbook_expected_result"},
                        {"outcome_label": "unhealthy", "source": "playbook_expected_result"},
                        {"outcome_label": "inconclusive", "source": "playbook_expected_result"},
                    ],
                }
            ]
        },
        "branch_state": dict(slice_.branch_state),
        "guided_question": {
            "allowed_answers": ["healthy", "unhealthy", "inconclusive"],
            "node_id": "node_1",
        },
        "completed_node_ids": [],
        "current_node_id": "node_1",
        "_playbook_slice": slice_,
        "runtime_trace": {"agents": []},
    }
    out = apply_branch_answer(state)
    assert out.get("_route_after_branch") == "save"
    assert out.get("response_type") == "guided_question"
    assert out.get("branch_state", {}).get("awaiting_branch") is True
    assert "branch" in str(out.get("final_response") or "").lower() or "symptom" in str(
        out.get("final_response") or ""
    ).lower()


def test_present_candidates_message_is_concise() -> None:
    from backend.app.agents.runtime import request_more_symptoms
    from backend.app.graph.playbook_state import PlaybookSessionSlice

    slice_ = PlaybookSessionSlice(publish_version_id="handoff-demo-v1")
    state = {
        "session_id": "test-concise-candidates",
        "user_message": "robots",
        "playbook_variant": "prompt_a",
        "retrieval_hits": [
            {
                "source_record_id": "playbook_incident_228086_site_wide_motion_stoppage_service_recovery",
                "title": "Site-wide robotic motion stoppage",
                "combined_score": 0.33,
                "cosine_score": 0.0,
                "jaccard_score": 0.06,
                "symptom_score": 0.33,
                "coverage": 0.67,
                "snippet": "long summary " * 40,
                "filter_metadata": {"case_id": "228086"},
            }
        ],
        "retrieval_confidence": 0.33,
        "extracted_observed_signals": {"agvs_stopped": True},
        "_playbook_slice": slice_,
        "runtime_trace": {"agents": []},
    }
    out = request_more_symptoms(state)
    assert out.get("response_type") == "playbook_candidates"
    message = str(out.get("final_response") or "")
    assert len(message) < 420
    assert "Candidate playbooks:" not in message
    assert "Entry symptoms:" not in message
    assert out.get("playbook_candidates")


def test_healthy_advances_case_228086_playbook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKIP_PLAYBOOK_CONFIRMATION", "true")
    turn1 = run_playbook_troubleshoot(
        "test-branch-228086",
        "AGVs stopped and nothing is moving on site",
        playbook_variant="prompt_a",
    )
    assert turn1.get("active_playbook_id")
    assert "228086" in str(turn1.get("active_playbook_id") or turn1.get("active_case_id") or "")
    assert turn1.get("current_node_id") == "node_1"
    assert turn1.get("response_type") == "guided_question"

    turn2 = run_playbook_troubleshoot(
        "test-branch-228086",
        "healthy",
        playbook_variant="prompt_a",
    )
    assert turn2.get("current_node_id") == "node_6"
    assert turn2.get("response_type") == "guided_question"
    answers = (turn2.get("guided_question") or {}).get("allowed_answers") or []
    assert len(answers) >= 2
    assert "healthy" in {str(item).lower() for item in answers}
    node = turn2.get("current_node_payload") or {}
    assert "desynchronization" in str(node.get("title") or "").lower()
    assert turn2.get("branch_state", {}).get("awaiting_branch") is True
    assert turn2.get("branch_state", {}).get("resolved") is not True


def test_branch_qualification_metrics_maps_outcomes_and_runbook_checks() -> None:
    from backend.app.agents.runtime import _branch_qualification_metrics

    node = {
        "expected_or_observed_result": "Site-wide stoppage vs localized.",
        "decision_outcomes": [
            {
                "outcome_label": "healthy",
                "descriptor": "No site-wide stoppage pattern.",
                "source": "playbook_expected_result",
            },
            {
                "outcome_label": "unhealthy",
                "descriptor": "Site-wide stoppage pattern present.",
                "source": "playbook_expected_result",
            },
            {
                "outcome_label": "inconclusive",
                "descriptor": "Cannot tell breadth of stoppage.",
                "source": "playbook_expected_result",
            },
            {
                "outcome_label": "healthy",
                "descriptor": "Alarms screen visible.",
                "source": "runbook_step",
            },
            {
                "outcome_label": "unhealthy",
                "descriptor": "Whole runbook dump should be ignored.",
                "source": "runbook_step",
            },
        ],
    }
    runbook = {
        "steps": [
            {
                "step_number": 1,
                "healthy_condition": "Alarms list visible.",
                "failure_condition": "Alarms screen unavailable.",
            }
        ]
    }
    metrics = _branch_qualification_metrics(node, runbook)
    assert set(metrics) == {"healthy", "unhealthy", "inconclusive"}
    assert metrics["healthy"]["summary"] == "No site-wide stoppage pattern."
    assert metrics["unhealthy"]["summary"] == "Site-wide stoppage pattern present."
    assert metrics["inconclusive"]["summary"] == "Cannot tell breadth of stoppage."
    assert metrics["healthy"]["checks"] == []
    assert metrics["unhealthy"]["checks"] == []


def test_branch_qualification_metrics_include_next_destination() -> None:
    from backend.app.agents.runtime import _branch_qualification_metrics

    playbook = {
        "nodes": [
            {"node_id": "node_a", "title": "Confirm alarms"},
            {"node_id": "node_b", "title": "Isolate AGV"},
        ]
    }
    node = {
        "decision_outcomes": [
            {
                "outcome_label": "healthy",
                "descriptor": "Clear.",
                "next_node_id": "node_a",
                "source": "playbook_expected_result",
            },
            {
                "outcome_label": "unhealthy",
                "descriptor": "Fault present.",
                "next_node_id": "node_b",
                "source": "playbook_expected_result",
            },
        ]
    }
    metrics = _branch_qualification_metrics(node, {}, playbook)
    assert metrics["healthy"]["next_node_title"] == "Confirm alarms"
    assert metrics["unhealthy"]["next_node_title"] == "Isolate AGV"


def test_branch_qualification_metrics_fills_from_node_branches() -> None:
    from backend.app.agents.runtime import _branch_qualification_metrics

    playbook = {
        "nodes": [
            {"node_id": "node_1", "title": "Confirm stoppage"},
            {
                "node_id": "node_6",
                "title": "Check for residual AGV desynchronization after service recovery",
            },
        ]
    }
    node = {
        "node_id": "node_1",
        "decision_outcomes": [
            {
                "outcome_label": "healthy",
                "next_node_id": "",
                "source": "playbook_expected_result",
                "descriptor": "Healthy path.",
            },
            {
                "outcome_label": "unhealthy",
                "next_node_id": "",
                "source": "playbook_expected_result",
            },
            {
                "outcome_label": "inconclusive",
                "next_node_id": "",
                "source": "playbook_expected_result",
            },
        ],
        "branches": [{"outcome": "healthy", "next_node_id": "node_6"}],
    }
    metrics = _branch_qualification_metrics(node, {}, playbook)
    assert metrics["healthy"]["next_node_id"] == "node_6"
    assert "residual AGV" in str(metrics["healthy"]["next_node_title"])
    assert metrics["unhealthy"]["next_node_id"] is None


def test_branch_qualification_metrics_always_defines_three_branches() -> None:
    from backend.app.agents.runtime import _branch_qualification_metrics

    metrics = _branch_qualification_metrics({"title": "Check RMS"}, {})
    assert set(metrics) == {"healthy", "unhealthy", "inconclusive"}
    for label in ("healthy", "unhealthy", "inconclusive"):
        assert metrics[label]["summary"]


def test_orchestrator_llm_skipped_for_guided_button_and_templates(monkeypatch) -> None:
    from backend.app.agents import runtime as runtime_mod
    from backend.app.graph.playbook_state import PlaybookSessionSlice

    calls: list[str] = []

    def fake_compose(briefing):
        calls.append(str(briefing.get("mode")))
        return {"user_message": "llm text", "confidence_reason": "llm reason"}

    monkeypatch.setattr(
        "backend.app.services.llm_playbook_client.llm_compose_orchestrator_message",
        fake_compose,
    )
    monkeypatch.setattr(
        runtime_mod,
        "get_corpus_settings",
        lambda: type(
            "S",
            (),
            {
                "enable_llm_orchestrator": True,
                "playbook_match_threshold": 0.80,
                "playbook_pin_coverage_threshold": 0.40,
            },
        )(),
    )
    slice_ = PlaybookSessionSlice(publish_version_id="handoff-demo-v1")
    state = {
        "_playbook_slice": slice_,
        "_guided_button_answer": True,
        "user_message": "healthy",
        "runtime_trace": {"agents": []},
        "retrieval_hits": [],
    }
    message, reason = runtime_mod._maybe_llm_orchestrate(
        state,
        mode="branch_prompt",
        fallback_user_message="template message",
        confidence_reason_seed="seed reason",
    )
    assert message == "template message"
    assert reason == "seed reason"
    assert calls == []

    state2 = {
        "_playbook_slice": slice_,
        "_retriage_turn": True,
        "user_message": "new symptoms",
        "runtime_trace": {"agents": []},
        "retrieval_hits": [{"cosine_score": 0.5, "jaccard_score": 0.2, "symptom_score": 0.4, "coverage": 0.3}],
        "retrieval_confidence": 0.5,
        "playbook_candidates": [],
        "correlated_symptoms": [],
        "active_playbook_id": None,
        "playbook_payload": {},
        "current_node_id": None,
        "extracted_observed_signals": {"agvs_stopped": True},
        "path_evidence": [{"node_id": "node_1", "title": "Stoppage", "outcome": "unhealthy"}],
        "_retriage_prior": {"playbook_id": "pb1", "node_id": "node_1"},
    }
    message2, _ = runtime_mod._maybe_llm_orchestrate(
        state2,
        mode="present_candidates",
        fallback_user_message="template candidates",
        confidence_reason_seed="seed",
    )
    assert message2 == "llm text"
    assert calls == ["present_candidates"]


def test_lean_working_memory_caps_path_and_signals() -> None:
    from backend.app.agents.runtime import _lean_working_memory
    from backend.app.graph.playbook_state import PlaybookSessionSlice

    slice_ = PlaybookSessionSlice(
        publish_version_id="v1",
        observed_signals={f"sig_{index}": True for index in range(20)},
        path_evidence=[
            {"node_id": f"n{index}", "title": f"Node {index}", "outcome": "unhealthy"}
            for index in range(10)
        ],
    )
    memory = _lean_working_memory(
        {"_retriage_prior": {"playbook_id": "pb", "node_id": "n9"}},
        slice_,
    )
    assert len(memory["signals"]) <= 12
    assert len(memory["path"]) <= 6
    assert memory["prior_playbook"] == "pb"


def test_branch_qualification_metrics_parse_expected_evidence_for_generic_outcomes() -> None:
    from backend.app.agents.runtime import _branch_qualification_metrics

    node = {
        "title": "Confirm site-wide robotic stoppage pattern",
        "expected_or_observed_result": (
            "Unhealthy evidence includes site reports that nothing is moving, "
            "small sort is stopped, hospital tote removal is blocked, or RMS/HMI "
            "is visibly abnormal. Healthy or narrower evidence would indicate "
            "movement is limited to one robot or one localized area only."
        ),
        "decision_outcomes": [
            {
                "outcome_label": "healthy",
                "descriptor": (
                    "Checks for 'Confirm site-wide robotic stoppage pattern' "
                    "do not indicate the fault condition being evaluated."
                ),
                "source": "playbook_expected_result",
            },
            {
                "outcome_label": "unhealthy",
                "descriptor": (
                    "Checks for 'Confirm site-wide robotic stoppage pattern' "
                    "indicate the fault condition being evaluated."
                ),
                "source": "playbook_expected_result",
            },
            {
                "outcome_label": "inconclusive",
                "descriptor": (
                    "Unhealthy evidence includes site reports that nothing is "
                    "moving. Healthy or narrower evidence would indicate "
                    "movement is limited to one robot only."
                ),
                "source": "playbook_expected_result",
            },
        ],
    }
    metrics = _branch_qualification_metrics(node, {})
    assert "nothing is moving" in metrics["unhealthy"]["summary"]
    assert "one robot" in metrics["healthy"]["summary"]
    assert "Unhealthy evidence includes" not in metrics["inconclusive"]["summary"]


def test_retrieve_rms_query() -> None:
    state = run_retrieve_chat(
        "How do I check RMS for active AGV faults",
        record_types=["canonical_runbook"],
        top_k=3,
    )
    hits = state.get("retrieval_hits") or []
    assert hits
    answer = str(state.get("final_response") or "")
    assert answer
    assert "Top match:" not in answer
    assert "Sources:" in answer
    assert float(hits[0].get("combined_score") or 0.0) > 0.05
    assert isinstance(state.get("canonical_images"), list)


def test_retrieve_template_answer_always_cites_source_ids() -> None:
    from backend.app.agents.runtime import (
        _compose_template_retrieve_answer,
        _ensure_retrieve_answer_cites_sources,
    )

    hits = [
        {
            "title": "Check RMS Faults",
            "source_record_id": "proc_rms_1",
            "record_type": "canonical_runbook",
            "snippet": "Ask whether there are system faults.",
            "combined_score": 0.61,
        },
        {
            "title": "Blank RMS page context",
            "source_record_id": "ctx_blank_rms",
            "record_type": "operational_context",
            "snippet": "Blank RMS may mean firewall access is blocked.",
            "combined_score": 0.44,
        },
    ]
    answer = _compose_template_retrieve_answer("rms blank", hits)
    assert "Sources:" in answer
    assert "proc_rms_1" in answer
    assert "Check RMS Faults" in answer
    patched = _ensure_retrieve_answer_cites_sources("No attribution here.", hits)
    assert "Sources:" in patched
    assert "ctx_blank_rms" in patched

