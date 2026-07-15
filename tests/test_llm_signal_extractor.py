"""Unit tests for LLMSignalExtractor post-validation."""
from __future__ import annotations

from backend.app.services.keyword_signal_extractor import ExtractionResult
from backend.app.tools.llm_signal_extractor import LLMSignalExtractor


def test_validate_drops_unknown_keys_and_low_confidence(monkeypatch):
    extractor = LLMSignalExtractor(
        legacy_vocabulary={"agvs_stopped": "AGVs stopped"},
        canonical_vocabulary={"agvs_remain_stopped": "AGVs remain stopped"},
        component_vocabulary=["agv"],
    )

    def _fake_complete(packet):
        return """
        {
          "signals": {"agvs_stopped": true, "made_up_signal": true},
          "canonical_signals": {"agvs_remain_stopped": true},
          "confidences": {"agvs_stopped": 0.8, "made_up_signal": 0.9, "agvs_remain_stopped": 0.2},
          "components": ["agv", "spaceship"],
          "fresh_issue": false,
          "rationale": "Paraphrased site report implies fleet stoppage."
        }
        """

    monkeypatch.setattr(extractor, "_complete_json", _fake_complete)
    out = extractor.extract(
        user_message="robots just sitting there",
        keyword_result=ExtractionResult(),
    )
    assert out["signals"] == {"agvs_stopped": True}
    assert "agvs_remain_stopped" not in out["canonical_signals"]
    assert out["components"] == ["agv"]
    assert "made_up_signal" in out["dropped_unknown_keys"]
    assert "spaceship" in out["dropped_unknown_keys"]


def test_runtime_extract_merges_llm_when_keyword_empty(monkeypatch):
    from backend.app.agents.runtime import extract_symptoms
    from backend.app.graph.playbook_state import PlaybookSessionSlice
    from backend.app.services.keyword_signal_extractor import ExtractionResult

    class _Cfg:
        enable_llm_symptom_extraction = True

    monkeypatch.setattr(
        "backend.app.config.get_app_settings",
        lambda: _Cfg(),
    )

    class _Keyword:
        def extract(self, _message):
            return ExtractionResult()

    monkeypatch.setattr(
        "backend.app.services.keyword_signal_extractor.get_default_extractor",
        lambda: _Keyword(),
    )
    monkeypatch.setattr(
        "backend.app.agents.runtime._maybe_llm_symptom_overlay",
        lambda **_kwargs: {
            "signals": {"agvs_stopped": True},
            "canonical_signals": {},
            "confidences": {"agvs_stopped": 0.75},
            "components": ["agv"],
            "fresh_issue": False,
            "rationale": "AGVs are not moving.",
            "model": "stub",
            "dropped_unknown_keys": [],
        },
    )

    state = {
        "session_id": "llm-symptom-test",
        "user_message": "fleet is just sitting there motionless",
        "_playbook_slice": PlaybookSessionSlice(publish_version_id="handoff-demo-v1"),
        "runtime_trace": {"agents": []},
    }
    out = extract_symptoms(state)
    assert out["extracted_observed_signals"].get("agvs_stopped") is True
    assert out.get("needs_symptom_clarification") is False
    assert (out.get("extracted_signal_metadata") or {}).get("extractor") == "keyword+llm"
