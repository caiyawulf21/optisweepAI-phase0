"""Tests for the symptom_extraction_node integration with both extractors."""
from __future__ import annotations

import pytest

from backend.app.graph.nodes.symptom_extraction import symptom_extraction_node
from backend.app.graph.state import create_initial_state


def test_node_runs_keyword_extractor_by_default(monkeypatch):
    monkeypatch.setenv("ENABLE_LLM_SYMPTOM_EXTRACTION", "false")
    from backend.app.config import get_app_settings

    if hasattr(get_app_settings, "cache_clear"):
        get_app_settings.cache_clear()
    state = create_initial_state(
        "test-session",
        "AGVs stopped, no RMS alarms, all tippers heartbeat timeout",
    )
    result = symptom_extraction_node(state)
    assert result["extracted_signals"]["agvs_stopped"] is True
    assert result["extracted_signals"]["tipper_heartbeat_timeout"] is True
    assert result["extracted_observed_signals"] == {
        "agvs_stopped": True,
        "no_rms_alarm": True,
        "tipper_heartbeat_timeout": True,
    }
    assert "agv" in (result.get("extracted_components") or [])
    assert "tipper" in (result.get("extracted_components") or [])
    assert result["issue_category"] == "CAT-1"
    metadata = result.get("extracted_signal_metadata") or {}
    assert metadata.get("extractor") == "keyword"


def test_node_swallows_llm_extractor_failures(monkeypatch):
    """A failing LLM must never block the runtime; keyword baseline wins."""
    monkeypatch.setenv("ENABLE_LLM_SYMPTOM_EXTRACTION", "true")

    class _ExplodingExtractor:
        def extract(self, **_kwargs):
            raise RuntimeError("LLM unavailable")

    state = create_initial_state(
        "test-session",
        "AGVs stopped, all tippers heartbeat timeout",
    )
    result = symptom_extraction_node(
        state, llm_extractor=_ExplodingExtractor()
    )
    assert result["extracted_signals"]["agvs_stopped"] is True
    metadata = result.get("extracted_signal_metadata") or {}
    assert metadata.get("extractor") == "keyword"


def test_node_merges_llm_extractor_signals_when_enabled(monkeypatch):
    monkeypatch.setenv("ENABLE_LLM_SYMPTOM_EXTRACTION", "true")

    class _StubExtractor:
        def extract(self, **_kwargs):
            return {
                "signals": {"engineer_only_action_required": True},
                "canonical_signals": {"agvs_stopped_before_tippers": True},
                "confidences": {"agvs_stopped": 0.9},
                "components": ["agv", "tipper"],
                "fresh_issue": False,
                "rationale": "Operator describes typical heartbeat-timeout signature.",
                "model": "stub-deployment",
                "dropped_unknown_keys": [],
            }

    state = create_initial_state(
        "test-session",
        "AGVs stopped, all tippers heartbeat timeout",
    )
    result = symptom_extraction_node(state, llm_extractor=_StubExtractor())
    assert result["extracted_signals"]["agvs_stopped"] is True
    assert result["extracted_signals"]["engineer_only_action_required"] is True
    assert result["extracted_observed_signals"]["engineer_only_action_required"] is True
    metadata = result.get("extracted_signal_metadata") or {}
    assert metadata.get("extractor") == "keyword+llm"
    llm_meta = metadata.get("llm")
    assert llm_meta is not None
    assert llm_meta["model"] == "stub-deployment"
    assert "agvs_stopped_before_tippers" in llm_meta["extracted_canonical_signals"]


def test_node_marks_fresh_issue_in_metadata(monkeypatch):
    monkeypatch.setenv("ENABLE_LLM_SYMPTOM_EXTRACTION", "true")

    class _StubExtractor:
        def extract(self, **_kwargs):
            return {
                "signals": {},
                "canonical_signals": {},
                "confidences": {},
                "components": [],
                "fresh_issue": True,
                "rationale": "Operator opens a different issue.",
                "model": "stub",
                "dropped_unknown_keys": [],
            }

    state = create_initial_state(
        "test-session",
        "different problem now, never mind the AGVs",
    )
    result = symptom_extraction_node(state, llm_extractor=_StubExtractor())
    metadata = result.get("extracted_signal_metadata") or {}
    assert metadata.get("fresh_issue") is True
