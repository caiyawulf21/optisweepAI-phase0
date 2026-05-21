import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import phase0_ingestion_agent as agent


def minimal_state(tmp_path):
    state = agent.Phase0AgentState(
        case_id="229999",
        active_source_file="data/Case 229999 Data.docx",
        output_dir=tmp_path,
        extracted_dir=tmp_path / "extracted",
    )
    state.extracted_dir.mkdir(parents=True, exist_ok=True)
    state.prompt_text = "test prompt"
    state.reference = {"paragraphs": []}
    state.ocr_data = {"pages": [{"page": 1, "text": "AGVs stopped and support reviewed heartbeat."}]}
    state.layout_blocks = {"pages": [{"page": 1, "blocks": []}]}
    state.semantic_regions = {
        "regions": [
            {
                "region_id": "region_229999_001",
                "region_type": "teams_message_thread",
                "source_page": 1,
                "source_section": "Teams Chat Data",
                "source_ref": "case.docx#page=1",
                "artifact_id": "artifact_229999_01",
                "artifact_path": "output/artifact.png",
                "text": "AGVs stopped and support reviewed heartbeat.",
            }
        ]
    }
    return state


def test_llm_input_packet_includes_examples_and_synthesis_policy(tmp_path):
    state = minimal_state(tmp_path)

    packet = agent.build_llm_input_packet(state)

    assert packet["ingestion_examples"]["examples_used"] is True
    assert packet["ingestion_examples"]["examples_version"] == "phase0_ingestion_examples_v1"
    assert packet["dataset_synthesis_policy"]["canonical_incident"] == "HIGH"
    assert packet["required_output_contract"]["synthesis_policy"]["raw_evidence_chunk"] == "LOW_MEDIUM"


def test_fallback_markers_make_records_review_only():
    interpretations = {
        "canonical_incident": {},
        "semantic_chunks": [{}],
        "timeline_events": [{}],
        "procedure_candidates": [{}],
        "workflow_candidate_steps": [{}],
        "escalation_summary_template": {},
    }

    agent.apply_fallback_markers_to_interpretations(interpretations, "test failure")

    for record in [
        interpretations["canonical_incident"],
        interpretations["semantic_chunks"][0],
        interpretations["timeline_events"][0],
        interpretations["procedure_candidates"][0],
        interpretations["workflow_candidate_steps"][0],
        interpretations["escalation_summary_template"],
    ]:
        assert record["quality_tier"] == "fallback_review_only"
        assert record["eligible_for_cross_incident_synthesis"] is False
        assert record["eligible_for_workflow_grouping"] is False
        assert record["requires_manual_reingestion"] is True


def test_procedure_step_none_instruction_fails_validation():
    errors = agent.validate_procedure_candidate_shape(
        {
            "procedure_detail_level": "medium",
            "procedure_steps": [
                {
                    "instruction": "None",
                    "operator_action": "None",
                    "refinement_gap_notes": [],
                }
            ],
        },
        1,
    )

    assert any("instruction must not be None" in error for error in errors)


def test_case_named_workflow_fails_unless_fallback_only():
    errors = agent.validate_workflow_candidate_shape(
        {
            "candidate_workflow_name": "case_229999_candidate_triage_flow_v1",
            "entry_conditions": ["AGVs stopped"],
            "required_signals": ["AGVs stopped"],
            "evidence_refs": ["chunk_1"],
            "procedure_refs": ["procedure_1"],
        },
        1,
        "229999",
    )
    fallback_errors = agent.validate_workflow_candidate_shape(
        {
            "candidate_workflow_name": "case_229999_candidate_triage_flow_v1",
            "fallback_only": True,
        },
        1,
        "229999",
    )

    assert any("case-number driven" in error for error in errors)
    assert fallback_errors == []


def test_stage_validation_catches_missing_timeline_region_ids(tmp_path):
    state = minimal_state(tmp_path)

    errors = agent.validate_stage_output(
        {
            "canonical_incident": {
                field_name: [] if field_name.endswith("_signals") or field_name in {"raw_terms", "normalized_terms", "candidate_inferred_causes"} else "value"
                for field_name in agent.llm_output_contract(state)["canonical_incident_required"]
            },
            "timeline_events": [
                {
                    field_name: [] if field_name.endswith("_signals") else "value"
                    for field_name in agent.llm_output_contract(state)["timeline_event_required"]
                    if field_name != "region_ids"
                }
            ],
            "escalation_summary_template": {
                field_name: [] if field_name.endswith("_signals") else "value"
                for field_name in agent.llm_output_contract(state)["escalation_summary_required"]
            },
        },
        {"stage": "incident_timeline", "output_keys": ["canonical_incident", "timeline_events", "escalation_summary_template"]},
        state,
    )

    assert "timeline_events[1] missing region_ids" in errors


def test_stage_validation_catches_invalid_step_evidence_quality(tmp_path):
    state = minimal_state(tmp_path)
    procedure = {
        field_name: [] if field_name.endswith("s") or field_name in {"missing_operational_details", "candidate_refinement_questions"} else "value"
        for field_name in agent.llm_output_contract(state)["procedure_candidate_required"]
    }
    procedure["procedure_detail_level"] = "medium"
    procedure["procedure_steps"] = [
        {
            field_name: [] if field_name.endswith("ids") or field_name.endswith("refs") or field_name == "refinement_gap_notes" else "value"
            for field_name in agent.llm_output_contract(state)["procedure_step_required"]
        }
    ]
    procedure["procedure_steps"][0]["operator_action"] = "Capture evidence."
    procedure["procedure_steps"][0]["evidence_quality"] = "source_backed"

    errors = agent.validate_stage_output(
        {"procedure_candidates": [procedure]},
        {"stage": "procedure_candidates", "output_keys": ["procedure_candidates"]},
        state,
    )

    assert "procedure_candidates[1].procedure_steps[1] invalid evidence_quality" in errors
