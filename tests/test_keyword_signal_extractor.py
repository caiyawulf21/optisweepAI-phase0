"""Tests for the deterministic keyword signal extractor."""
from __future__ import annotations

import pytest

from backend.app.schemas.assistant import INITIAL_CAT1_SIGNALS
from backend.app.services.keyword_signal_extractor import KeywordSignalExtractor


@pytest.fixture
def default_extractor() -> KeywordSignalExtractor:
    return KeywordSignalExtractor.from_files()


def test_empty_message_returns_all_false(default_extractor):
    result = default_extractor.extract("")
    assert result.signals == {key: False for key in INITIAL_CAT1_SIGNALS}
    assert result.observed_signals == {}
    assert result.negated_signals == set()
    assert result.components == set()


def test_flagship_cat1_signature_matches_all_expected_signals(default_extractor):
    result = default_extractor.extract(
        "AGVs stopped, no RMS alarms, all tippers heartbeat timeout, "
        "hospital tote removal hangs, system active but frozen"
    )
    assert result.signals["agvs_stopped"] is True
    assert result.signals["no_rms_alarm"] is True
    assert result.observed_signals["no_rms_alarm"] is True
    assert result.signals["tipper_heartbeat_timeout"] is True
    assert result.signals["hospital_tote_removal_hangs"] is True
    assert result.signals["system_active_but_frozen"] is True
    assert result.observed_signals["hospital_tote_removal_hangs"] is True
    assert result.canonical_signals["hospital_tote_removal_failed"] is True


@pytest.mark.parametrize(
    "message,expected",
    [
        ("AGVs stop, no rms alarms", {"agvs_stopped", "no_rms_alarm"}),
        ("without rms alarms", {"no_rms_alarm"}),
        ("AGVs stopped, without any rms alarms", {"agvs_stopped", "no_rms_alarm"}),
    ],
)
def test_absence_and_stop_phrase_variants(default_extractor, message, expected):
    result = default_extractor.extract(message)
    for key in expected:
        assert result.observed_signals.get(key) is True, key


def test_negation_window_demotes_phrase_to_false():
    """A negation cue immediately before a matched phrase flips the signal."""
    extractor = KeywordSignalExtractor.from_phrases(
        signal_phrases={
            "heartbeat_recovered_after_restart": ["heartbeat recovered"],
        },
    )
    affirm = extractor.extract("heartbeat recovered after restart")
    assert affirm.signals["heartbeat_recovered_after_restart"] is True
    assert "heartbeat_recovered_after_restart" not in affirm.negated_signals

    negated = extractor.extract("no heartbeat recovered after restart")
    assert negated.signals["heartbeat_recovered_after_restart"] is False
    assert negated.observed_signals["heartbeat_recovered_after_restart"] is False
    assert "heartbeat_recovered_after_restart" in negated.negated_signals


def test_negation_window_does_not_leak_across_sentence_boundary():
    extractor = KeywordSignalExtractor.from_phrases(
        signal_phrases={
            "service_restart_required": ["service restart required"],
        },
    )
    result = extractor.extract(
        "AGVs are stopped. service restart required."
    )
    assert result.signals["service_restart_required"] is True


def test_negation_demotes_signal_outside_phrase_match():
    extractor = KeywordSignalExtractor.from_phrases(
        signal_phrases={"service_restart_required": ["restart required"]},
    )
    result = extractor.extract("no restart required, system is healthy")
    assert result.signals["service_restart_required"] is False
    assert "service_restart_required" in result.negated_signals


def test_components_extracted_from_message(default_extractor):
    result = default_extractor.extract(
        "AGV stuck, tipper heartbeat is bad, hospital tote line is hung"
    )
    assert "agv" in result.components
    assert "tipper" in result.components
    assert "hospital_tote" in result.components


def test_user_requests_escalation_via_regex(default_extractor):
    result = default_extractor.extract("please escalate to engineer now")
    assert result.signals["user_requests_escalation"] is True


def test_custom_phrase_table_isolates_test_behavior():
    extractor = KeywordSignalExtractor.from_phrases(
        signal_phrases={"agvs_stopped": ["robots halted"]},
        component_phrases={"agv": ["robot"]},
    )
    affirm = extractor.extract("the robots halted on the floor")
    assert affirm.signals["agvs_stopped"] is True
    assert "agv" in affirm.components

    negated = extractor.extract("never robots halted, all moving")
    assert negated.signals["agvs_stopped"] is False
    assert "agvs_stopped" in negated.negated_signals


def test_phrase_with_active_but_frozen_is_not_truncated_by_conjunction(
    default_extractor,
):
    result = default_extractor.extract(
        "system active but frozen, no movement"
    )
    assert result.signals["system_active_but_frozen"] is True


def test_signals_dict_always_contains_all_legacy_keys(default_extractor):
    result = default_extractor.extract("nothing relevant here")
    for key in INITIAL_CAT1_SIGNALS:
        assert key in result.signals
        assert isinstance(result.signals[key], bool)
    assert result.observed_signals == {}


@pytest.mark.parametrize(
    "message",
    [
        "agvs aren't moving",
        "AGVs aren't moving",
        "agvs are not moving",
        "agvs not moving",
        "nothing is moving",
        "nothing moving",
    ],
)
def test_agvs_not_moving_variants_emit_agvs_stopped(default_extractor, message):
    result = default_extractor.extract(message)
    assert result.signals["agvs_stopped"] is True
    assert result.observed_signals.get("agvs_stopped") is True
    assert "agvs_stopped" not in result.negated_signals


def test_agvs_are_not_stopped_does_not_false_positive(default_extractor):
    result = default_extractor.extract("agvs are not stopped")
    assert result.signals["agvs_stopped"] is False
    assert "agvs_stopped" not in result.observed_signals or result.observed_signals.get(
        "agvs_stopped"
    ) is not True


@pytest.mark.parametrize(
    "message",
    [
        "hospital tote removal hangs",
        "tote removal stuck",
        "tote removal command did not execute",
        "hospital removal failed",
        "can't remove tote",
        "cannot remove tote",
    ],
)
def test_hospital_tote_removal_phrases_emit_observed_and_canonical_signals(
    default_extractor,
    message,
):
    result = default_extractor.extract(message)
    assert result.signals["hospital_tote_removal_hangs"] is True
    assert result.observed_signals == {"hospital_tote_removal_hangs": True}
    assert result.canonical_signals["hospital_tote_removal_failed"] is True


def test_canonical_phrases_emit_canonical_signals_directly():
    """The canonical phrase table populates ``canonical_signals`` only for
    phrases that fired -- there is no False-padding -- so routing layers
    can treat the absence of a key as "we don't know" rather than
    "operator said no"."""
    extractor = KeywordSignalExtractor.from_phrases(
        signal_phrases={},
        canonical_signal_phrases={
            "optisweep_service_restart_completed": [
                "service restart completed",
                "we restarted the service",
            ],
            "tipper_heartbeat_normal": ["tipper heartbeat normal"],
        },
    )
    result = extractor.extract("yes service restart completed and tipper heartbeat normal")
    assert result.canonical_signals.get("optisweep_service_restart_completed") is True
    assert result.canonical_signals.get("tipper_heartbeat_normal") is True
    assert "agvs_resumed_movement" not in result.canonical_signals


def test_canonical_phrase_negation_flips_to_false():
    extractor = KeywordSignalExtractor.from_phrases(
        signal_phrases={},
        canonical_signal_phrases={
            "optisweep_service_restart_completed": ["service restart completed"],
        },
    )
    affirm = extractor.extract("service restart completed")
    assert affirm.canonical_signals.get("optisweep_service_restart_completed") is True

    negated = extractor.extract("no service restart completed")
    assert (
        negated.canonical_signals.get("optisweep_service_restart_completed") is False
    )
    assert "optisweep_service_restart_completed" in negated.negated_signals


def test_default_extractor_loads_canonical_phrases_from_yaml(default_extractor):
    """The committed canonical_signal_phrases.yaml must be loaded by the
    default extractor, otherwise the follow-up answer path silently
    falls back to an empty canonical signal dict."""
    result = default_extractor.extract("the service restart completed")
    assert (
        result.canonical_signals.get("optisweep_service_restart_completed") is True
    )


@pytest.mark.parametrize(
    "message",
    [
        "system is stopped after bagout.",
        "system isn't bagging out after sorting",
        "System stopped at bag-out after sorting",
        "bag-out entered request",
    ],
)
def test_bagout_operator_phrasing_emits_bagout_failure(default_extractor, message):
    result = default_extractor.extract(message)
    assert result.signals["bagout_failure"] is True
    assert result.observed_signals.get("bagout_failure") is True
    assert "bagout" in result.components
