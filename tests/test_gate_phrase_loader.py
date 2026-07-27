from __future__ import annotations

from backend.app.services.gate_phrase_loader import (
    gate_phrase_table_usable,
    install_extractor_from_gate_phrase_table,
    normalize_gate_phrase_doc,
)
from backend.app.services.keyword_signal_extractor import (
    get_default_extractor,
    reset_for_tests,
)


def test_normalize_accepts_top_level_and_payload_nested() -> None:
    top = normalize_gate_phrase_doc(
        {
            "legacy_signal_phrases": {"agvs_stopped": ["AGVs stopped", "agvs stopped"]},
            "canonical_signal_phrases": {"rms_screen_no_faults_visible": ["no rms alarms"]},
            "component_phrases": {"agv": ["agv"]},
        }
    )
    assert top["symptom_phrases"]["agvs_stopped"] == ["agvs stopped"]
    nested = normalize_gate_phrase_doc(
        {
            "payload": {
                "symptom_phrases": {"no_rms_alarm": ["rms showing no alarms"]},
            }
        }
    )
    assert nested["symptom_phrases"]["no_rms_alarm"] == ["rms showing no alarms"]


def test_install_from_cosmos_table_drives_first_turn_gate() -> None:
    reset_for_tests()
    source = install_extractor_from_gate_phrase_table(
        {
            "legacy_signal_phrases": {
                "agvs_stopped": ["agvs are not moving", "agvs stopped"],
                "no_rms_alarm": ["rms showing no alarms", "no rms alarms"],
            },
            "canonical_signal_phrases": {
                "rms_screen_no_faults_visible": ["rms showing no alarms"],
            },
            "component_phrases": {},
        }
    )
    assert source == "cosmos"
    result = get_default_extractor().extract(
        "agvs aren't moving, rms showing no alarms"
    )
    assert result.observed_signals.get("agvs_stopped") is True
    assert result.observed_signals.get("no_rms_alarm") is True
    reset_for_tests()


def test_missing_table_falls_back_to_yaml() -> None:
    reset_for_tests()
    assert gate_phrase_table_usable(None) is False
    source = install_extractor_from_gate_phrase_table(None)
    assert source == "yaml_fallback"
    result = get_default_extractor().extract("AGVs stopped")
    assert result.observed_signals.get("agvs_stopped") is True
    reset_for_tests()
