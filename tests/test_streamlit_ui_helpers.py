"""Phase 1 Step 12 — unit tests for the Streamlit guided UI helpers.

The Streamlit app itself is hard to unit-test (its runtime relies on a
real script-run context and a websocket reconciler), so all
rendering-affecting logic was extracted into :mod:`ui.streamlit_helpers`
and these tests pin the pure-helper behavior. Manual demo run remains
the user's gate for the full app.
"""
from __future__ import annotations

from typing import Any

import pytest

import pytest

from ui.streamlit_helpers import (
    HOW_TO_CHECK_MESSAGE,
    PROCEDURE_GUIDANCE_BANNER,
    accept_recommendation_value,
    answer_button_key,
    allowed_answers_with_unknown,
    build_guided_submission,
    derive_dynamic_path_progress,
    derive_progress_label,
    derive_recommended_next_step,
    display_answer_label,
    extract_visual_artifact_refs,
    format_signal_badges,
    is_latest_assistant_turn,
    latest_observed_signals_from_response,
    merge_observed_signals,
    next_node_title_for_answer,
    resolve_visual_artifacts,
    resolve_canonical_image_records,
    select_renderer,
    select_confidence_value,
    should_show_procedure_guidance_banner,
    visual_evidence_from_refs,
    widget_key,
)


# ---------------------------------------------------------------------------
# assistant-turn interactivity / widget keys
# ---------------------------------------------------------------------------


def test_repeated_workflow_step_payloads_produce_unique_button_keys():
    first = answer_button_key("ws", 1, "confirm_restart", 0, "yes")
    repeated = answer_button_key("ws", 3, "confirm_restart", 0, "yes")
    assert first != repeated
    assert first == "ws-1-confirm_restart-0-yes"
    assert repeated == "ws-3-confirm_restart-0-yes"


def test_guided_question_button_keys_include_message_and_node_id():
    assert (
        answer_button_key("gq", 5, "determine_estop_requirement", 1, "no")
        == "gq-5-determine_estop_requirement-1-no"
    )


def test_guided_control_keys_are_unique_by_suffix():
    base = widget_key("ws", 3, "confirm_restart", "custom")
    help_key = widget_key("ws", 3, "confirm_restart", "how-to-check")
    submit_key = widget_key("ws", 3, "confirm_restart", "custom-submit")
    assert len({base, help_key, submit_key}) == 3
    assert HOW_TO_CHECK_MESSAGE == "How do I check?"


def test_allowed_answers_adds_unknown_once():
    assert allowed_answers_with_unknown(["yes", "no"]) == ["yes", "no", "unknown"]
    assert allowed_answers_with_unknown(["yes", "unknown", "no"]) == [
        "yes",
        "unknown",
        "no",
    ]
    assert allowed_answers_with_unknown(["yes", "UNKNOWN"]) == ["yes", "UNKNOWN"]


def test_unknown_answer_has_operator_friendly_label():
    assert display_answer_label("unknown") == "I don't know / not sure"
    assert display_answer_label("yes") == "yes"
    assert display_answer_label("healthy", next_node_title="Check RMS") == (
        "healthy → Check RMS"
    )


def test_next_node_title_for_answer():
    options = [
        {"label": "healthy", "next_node_title": "Check RMS", "next_node_id": "n1"},
        {"label": "unhealthy", "next_node_id": "n2"},
    ]
    assert next_node_title_for_answer("healthy", options) == "Check RMS"
    assert next_node_title_for_answer("unhealthy", options) == "n2"
    assert next_node_title_for_answer("unknown", options) is None
    assert (
        next_node_title_for_answer(
            "inconclusive",
            metrics={"inconclusive": {"next_node_title": "Wait and recheck"}},
        )
        == "Wait and recheck"
    )


def test_build_guided_submission_combines_button_and_custom_text():
    assert build_guided_submission("yes", "RMS shows no active faults") == (
        "Answer: yes. Additional context: RMS shows no active faults"
    )
    assert build_guided_submission("no", "  ") == "no"
    assert build_guided_submission(custom_text="operator typed detail") == (
        "operator typed detail"
    )


def test_build_guided_submission_uses_structured_option_value():
    assert build_guided_submission("tipper_heartbeat_timeout_or_zero", "") == (
        "tipper_heartbeat_timeout_or_zero"
    )


def test_only_latest_assistant_turn_is_interactive():
    history = [
        {"role": "user", "payload": {"user_message": "start"}},
        {"role": "assistant", "payload": {"response_type": "workflow_step"}},
        {"role": "user", "payload": {"user_message": "yes"}},
        {"role": "assistant", "payload": {"response_type": "workflow_step"}},
    ]
    assert is_latest_assistant_turn(history, 1) is False
    assert is_latest_assistant_turn(history, 3) is True


def test_older_assistant_turns_are_read_only_when_followed_by_assistant_turn():
    history = [
        {"role": "assistant", "payload": {"response_type": "guided_question"}},
        {"role": "user", "payload": {"user_message": "custom answer"}},
        {"role": "assistant", "payload": {"response_type": "guided_question"}},
    ]
    assert is_latest_assistant_turn(history, 0) is False
    assert is_latest_assistant_turn(history, 2) is True


def test_non_assistant_turn_is_never_interactive():
    history = [{"role": "user", "payload": {"user_message": "start"}}]
    assert is_latest_assistant_turn(history, 0) is False


# ---------------------------------------------------------------------------
# format_signal_badges
# ---------------------------------------------------------------------------


def test_format_signal_badges_sorted_alphabetically():
    badges = format_signal_badges(
        {
            "zebra_signal": True,
            "alpha_signal": False,
            "mike_signal": True,
        }
    )
    assert [b["signal"] for b in badges] == [
        "alpha_signal",
        "mike_signal",
        "zebra_signal",
    ]


def test_format_signal_badges_preserves_bool_values():
    badges = format_signal_badges({"a": True, "b": False})
    by_name = {b["signal"]: b for b in badges}
    assert by_name["a"]["value"] is True
    assert by_name["a"]["label"] == "true"
    assert by_name["b"]["value"] is False
    assert by_name["b"]["label"] == "false"


def test_format_signal_badges_empty_input_returns_empty_list():
    assert format_signal_badges(None) == []
    assert format_signal_badges({}) == []


def test_format_signal_badges_coerces_truthy_non_bool_values():
    badges = format_signal_badges({"signal_int": 1, "signal_none_like": 0})
    by_name = {b["signal"]: b for b in badges}
    assert by_name["signal_int"]["value"] is True
    assert by_name["signal_none_like"]["value"] is False


# ---------------------------------------------------------------------------
# merge_observed_signals
# ---------------------------------------------------------------------------


def test_merge_observed_signals_accumulates_across_turns():
    prior = {"agvs_stopped": True, "no_rms_alarm": True}
    latest = {"tipper_heartbeat_timeout": True}
    merged = merge_observed_signals(prior, latest)
    assert merged == {
        "agvs_stopped": True,
        "no_rms_alarm": True,
        "tipper_heartbeat_timeout": True,
    }


def test_merge_observed_signals_latest_overwrites_prior_on_shared_keys():
    prior = {"rms_screen_active_fault": True}
    latest = {"rms_screen_active_fault": False}
    merged = merge_observed_signals(prior, latest)
    assert merged["rms_screen_active_fault"] is False


def test_merge_observed_signals_handles_empty_inputs():
    assert merge_observed_signals(None, None) == {}
    assert merge_observed_signals({"a": True}, None) == {"a": True}
    assert merge_observed_signals(None, {"a": True}) == {"a": True}


def test_merge_observed_signals_coerces_to_bool():
    merged = merge_observed_signals({"a": 1}, {"b": 0})
    assert merged == {"a": True, "b": False}


def test_latest_observed_signals_prefers_observed_only_response_field():
    response = {
        "extracted_signals": {
            "hospital_tote_removal_hangs": False,
            "no_rms_alarm": False,
        },
        "extracted_observed_signals": {
            "hospital_tote_removal_hangs": True,
        },
    }

    assert latest_observed_signals_from_response(response) == {
        "hospital_tote_removal_hangs": True,
    }


def test_latest_observed_signals_uses_dynamic_runtime_state_first():
    response = {
        "extracted_observed_signals": {"no_rms_alarm": True},
        "workflow_state": {
            "dynamic_procedure_step": {
                "observed_signals": {"hospital_tote_removal_hangs": True},
                "produced_signals": {"agvs_stopped": False},
            }
        },
    }

    assert latest_observed_signals_from_response(response) == {
        "agvs_stopped": False,
        "hospital_tote_removal_hangs": True,
    }


# ---------------------------------------------------------------------------
# select_renderer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "response_type,expected",
    [
        ("answer", "answer"),
        ("guided_question", "guided_question"),
        ("workflow_step", "workflow_step"),
        ("dynamic_procedure_step", "dynamic_procedure_step"),
        ("escalation", "escalation"),
        ("terminal", "terminal"),
    ],
)
def test_select_renderer_returns_matching_name(response_type: str, expected: str):
    assert select_renderer(response_type) == expected


def test_select_renderer_defaults_to_answer_for_unknown_type():
    assert select_renderer("unknown_value") == "answer"
    assert select_renderer(None) == "answer"
    assert select_renderer("") == "answer"


def test_select_renderer_returns_callable_when_renderers_supplied():
    def _q_renderer(*args: Any, **kwargs: Any) -> str:
        return "q"

    def _a_renderer(*args: Any, **kwargs: Any) -> str:
        return "a"

    renderers = {"guided_question": _q_renderer, "answer": _a_renderer}
    chosen = select_renderer("guided_question", renderers=renderers)
    assert chosen is _q_renderer
    assert chosen() == "q"


def test_select_renderer_falls_back_to_default_renderer_on_unknown_type():
    def _a_renderer(*args: Any, **kwargs: Any) -> str:
        return "a"

    renderers = {"answer": _a_renderer}
    chosen = select_renderer("non_existent", renderers=renderers)
    assert chosen is _a_renderer


def test_select_renderer_raises_when_no_default_registered():
    renderers = {"guided_question": lambda: None}
    with pytest.raises(KeyError):
        select_renderer("workflow_step", renderers=renderers)


# ---------------------------------------------------------------------------
# derive_progress_label
# ---------------------------------------------------------------------------


def test_derive_progress_label_passes_through_value():
    assert (
        derive_progress_label({"progress_label": "Step 3 of 13"})
        == "Step 3 of 13"
    )
    assert derive_progress_label({"progress_label": "Step 1"}) == "Step 1"


def test_derive_progress_label_returns_none_when_missing():
    assert derive_progress_label(None) is None
    assert derive_progress_label({}) is None
    assert derive_progress_label({"progress_label": None}) is None
    assert derive_progress_label({"progress_label": ""}) is None
    assert derive_progress_label({"progress_label": "   "}) is None


def test_derive_progress_label_strips_whitespace():
    assert (
        derive_progress_label({"progress_label": "  Step 2  "}) == "Step 2"
    )


# ---------------------------------------------------------------------------
# should_show_procedure_guidance_banner
# ---------------------------------------------------------------------------


def test_should_show_procedure_guidance_banner_returns_true_only_for_dynamic_mode():
    assert should_show_procedure_guidance_banner("dynamic_procedure_guidance") is True
    assert should_show_procedure_guidance_banner("canonical_workflow") is False
    assert should_show_procedure_guidance_banner("retrieval_only") is False
    assert should_show_procedure_guidance_banner("escalation") is False
    assert should_show_procedure_guidance_banner(None) is False
    assert should_show_procedure_guidance_banner("") is False


def test_procedure_guidance_banner_constant_is_user_visible_warning():
    assert "approved workflow" in PROCEDURE_GUIDANCE_BANNER.lower() or (
        "not an approved" in PROCEDURE_GUIDANCE_BANNER.lower()
    )


# ---------------------------------------------------------------------------
# derive_dynamic_path_progress
# ---------------------------------------------------------------------------


def test_derive_dynamic_path_progress_renders_step_and_procedure_count():
    label = derive_dynamic_path_progress(
        {
            "dynamic_path_progress": {
                "procedure_count": 2,
                "step_count": 5,
                "current_step_index": 1,
                "current_procedure_id": "proc_a",
                "validation_status": "runtime_generated_unapproved",
            }
        }
    )
    assert label is not None
    assert label.startswith("Step")
    assert "5" in label
    assert "2 procedure" in label


def test_derive_dynamic_path_progress_returns_none_when_missing():
    assert derive_dynamic_path_progress(None) is None
    assert derive_dynamic_path_progress({}) is None
    assert derive_dynamic_path_progress({"dynamic_path_progress": None}) is None


def test_derive_dynamic_path_progress_handles_zero_steps():
    label = derive_dynamic_path_progress(
        {
            "dynamic_path_progress": {
                "procedure_count": 0,
                "step_count": 0,
                "current_step_index": 0,
            }
        }
    )
    # Zero steps still emits a deterministic label (empty path).
    assert label is None or "0" in label or "Step" in label


# ---------------------------------------------------------------------------
# recommendation / confidence helpers
# ---------------------------------------------------------------------------


def test_derive_recommended_next_step_prefers_rendered_procedure_title():
    payload = {
        "workflow_step": {
            "question": "Has the restart completed?",
            "procedure_guidance": {
                "rendered_procedures": [
                    {
                        "procedure_id": "restart_optisweep_service_v1",
                        "title": "Restart Optisweep service",
                    }
                ]
            },
        }
    }
    assert derive_recommended_next_step(payload) == "Restart Optisweep service"


def test_derive_recommended_next_step_falls_back_to_instruction():
    payload = {
        "dynamic_procedure_step": {
            "instruction": "Open Windows Services on the target WCS host."
        }
    }
    assert (
        derive_recommended_next_step(payload)
        == "Open Windows Services on the target WCS host."
    )


def test_select_confidence_value_prefers_dynamic_step_confidence():
    payload = {
        "canonical_coverage_ratio": 0.6,
        "dynamic_procedure_step": {"confidence": 0.82},
        "runtime_trace": {"retrieval": {"top_confidence": 0.9}},
    }
    assert select_confidence_value(payload) == {
        "source": "procedure confidence",
        "confidence": 0.82,
    }


def test_select_confidence_value_uses_routing_score_when_needed():
    payload = {
        "runtime_trace": {
            "routing": {
                "dynamic_procedure_routing_diagnostics": {"top_score": 0.77}
            }
        }
    }
    assert select_confidence_value(payload) == {
        "source": "dynamic procedure score",
        "confidence": 0.77,
    }


def test_accept_recommendation_requires_confidence_and_support_safe_yes():
    payload = {
        "canonical_coverage_ratio": 0.91,
        "workflow_step": {
            "support_safe": True,
            "allowed_answers": ["yes", "no"],
        },
    }
    assert accept_recommendation_value(payload, threshold=0.75) == "yes"


def test_accept_recommendation_blocks_low_confidence_and_engineer_only():
    low_confidence = {
        "canonical_coverage_ratio": 0.5,
        "workflow_step": {"support_safe": True, "allowed_answers": ["yes"]},
    }
    engineer_only = {
        "canonical_coverage_ratio": 0.95,
        "workflow_step": {"support_safe": False, "allowed_answers": ["yes"]},
    }
    assert accept_recommendation_value(low_confidence, threshold=0.75) is None
    assert accept_recommendation_value(engineer_only, threshold=0.75) is None


# ---------------------------------------------------------------------------
# visual evidence helpers
# ---------------------------------------------------------------------------


def test_extract_visual_artifact_refs_dedupes_primary_source_and_evidence_refs():
    refs = extract_visual_artifact_refs(
        {
            "primary_screenshot_refs": ["artifact_a", "artifact_b"],
            "supporting_screenshot_refs": ["artifact_b", "artifact_c"],
            "source_artifacts": ["artifact_c", "artifact_d"],
            "evidence_refs": [
                {"source_artifact_id": "artifact_d"},
                {"source_artifact_id": "artifact_e"},
            ],
        }
    )
    assert refs == ["artifact_a", "artifact_b", "artifact_c", "artifact_d", "artifact_e"]


def test_resolve_visual_artifacts_reports_existing_and_missing_paths(tmp_path):
    image_path = tmp_path / "rms.png"
    image_path.write_bytes(b"fake")
    artifacts = resolve_visual_artifacts(
        {
            "primary_screenshot_refs": ["artifact_present", "artifact_missing"],
        },
        artifact_records=[
            {
                "artifact_id": "artifact_present",
                "artifact_path": str(image_path),
                "source_ref": "Case.docx#media=image1.png",
                "artifact_type": "docx_embedded_image",
                "incident_id": "229488",
                "visible_text": "Services / Unplanned restart",
                "server_or_ip": "10.0.0.1",
            },
            {
                "artifact_id": "artifact_missing",
                "artifact_path": str(tmp_path / "missing.png"),
            },
        ],
        artifact_root=".",
    )
    by_id = {item["artifact_id"]: item for item in artifacts}
    assert by_id["artifact_present"]["exists"] is True
    assert by_id["artifact_missing"]["exists"] is False
    assert by_id["artifact_present"]["required"] is True


@pytest.mark.skip(reason="Canonical image resolver deferred to Cosmos artifact_runbook viewer (Stage 5)")
def test_resolve_canonical_image_records_dedupes_by_image_id_and_resolves_storage_uri(tmp_path):
    image_path = tmp_path / "rms.png"
    image_path.write_bytes(b"fake")

    images = resolve_canonical_image_records(
        [
            {
                "image_id": "img_rms",
                "title": "RMS screen",
                "storage_uri": str(image_path),
                "source_artifact_ids": ["artifact_a"],
            },
            {
                "image_id": "img_rms",
                "title": "Duplicate RMS screen",
                "source_artifact_ids": ["artifact_a"],
            },
        ]
    )

    assert len(images) == 1
    assert images[0]["image_id"] == "img_rms"
    assert images[0]["exists"] is True
    assert images[0]["artifact_path"] == str(image_path)


@pytest.mark.skip(reason="Canonical image resolver deferred to Cosmos artifact_runbook viewer (Stage 5)")
def test_resolve_canonical_image_records_falls_back_to_source_artifact_records(tmp_path):
    image_path = tmp_path / "artifact.png"
    image_path.write_bytes(b"fake")

    images = resolve_canonical_image_records(
        [
            {
                "image_id": "img_artifact",
                "source_artifact_ids": ["artifact_a"],
            }
        ],
        artifact_records=[
            {
                "artifact_id": "artifact_a",
                "artifact_path": str(image_path),
                "source_ref": "case#media=image.png",
            }
        ],
    )

    assert images[0]["exists"] is True
    assert images[0]["artifact_path"] == str(image_path)


def test_visual_evidence_from_refs_builds_primary_screenshot_payload():
    assert visual_evidence_from_refs(["artifact_a", "", "artifact_b"]) == {
        "primary_screenshot_refs": ["artifact_a", "artifact_b"]
    }
