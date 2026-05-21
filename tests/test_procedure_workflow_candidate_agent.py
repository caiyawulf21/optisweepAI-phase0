import json

import pytest

from backend.app.graph.nodes.workflow_procedure import procedure_workflow_candidate_node
from backend.app.services.procedure_workflow_candidate_agent import ProcedureWorkflowCandidateAgent


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def non_cat1_package(data_root):
    write_json(
        data_root / "incidents" / "canonical_incidents.json",
        [
            {
                "incident_id": "880001",
                "issue_category": "CAT-7: Tote Data Integrity",
                "title": "Tote record mismatch blocked hospital removal",
                "observed_failure_signals": ["tote_record_mismatch", "hospital_remove_hangs"],
                "diagnostic_signals": ["rms_alarm_state_unknown"],
                "candidate_inferred_causes": [{"cause_summary": "Possible stale tote task", "validation_status": "candidate"}],
            },
            {
                "incident_id": "880002",
                "issue_category": "CAT-7: Tote Data Integrity",
                "title": "Hospital remove hung with tote task mismatch",
                "observed_failure_signals": ["tote_record_mismatch", "hospital_remove_hangs"],
                "diagnostic_signals": ["rms_alarm_state_unknown"],
                "candidate_inferred_causes": [{"cause_summary": "Possible stale tote task", "validation_status": "candidate"}],
            },
        ],
    )
    write_json(
        data_root / "procedures" / "procedure_candidates.json",
        [
            {
                "procedure_id": "proc_880001_confirm_no_active_rms_alarms",
                "title": "Confirm no active RMS alarms",
                "issue_category": "CAT-7: Tote Data Integrity",
                "operational_intent": "Verify RMS does not show active alarms before proceeding with tote recovery.",
                "role_required": "support",
                "support_safe": True,
                "steps": [
                    {
                        "step_id": "confirm_rms",
                        "instruction": "Open RMS alarm view and confirm no active alarms are present.",
                        "validation_check": "RMS alarm view shows no active alarm.",
                    }
                ],
                "related_incidents": ["880001"],
                "evidence_refs": [{"incident_id": "880001", "evidence_id": "chunk_880001_01"}],
                "source_artifacts": ["artifact_880001_rms"],
                "comparable_signal_groups": ["rms_alarm_state_unknown", "hospital_remove_hangs"],
                "pattern_candidate_notes": "Reusable diagnostic check before tote task recovery.",
            },
            {
                "procedure_id": "proc_880002_confirm_no_active_rms_alarms",
                "title": "Check RMS alarm state",
                "issue_category": "CAT-7: Tote Data Integrity",
                "operational_intent": "Confirm RMS has no active alarms before continuing troubleshooting.",
                "role_required": "support",
                "support_safe": True,
                "steps": [
                    {
                        "step_id": "check_rms",
                        "instruction": "Review RMS alarm screen for active alarms.",
                        "validation_check": "No active alarm is visible.",
                    }
                ],
                "related_incidents": ["880002"],
                "evidence_refs": [{"incident_id": "880002", "evidence_id": "chunk_880002_01"}],
                "source_artifacts": ["artifact_880002_rms"],
                "comparable_signal_groups": ["rms_alarm_state_unknown", "hospital_remove_hangs"],
                "pattern_candidate_notes": "Reusable diagnostic check before tote task recovery.",
            },
            {
                "procedure_id": "proc_restart_lane",
                "title": "Restart lane",
                "issue_category": "CAT-7: Tote Data Integrity",
                "operational_intent": "Restart the affected lane.",
                "role_required": "engineer",
                "support_safe": False,
                "steps": [{"step_id": "restart_lane", "instruction": "Restart the lane.", "validation_check": "Lane returns to available state."}],
                "related_incidents": ["880001"],
                "evidence_refs": [{"incident_id": "880001", "evidence_id": "chunk_880001_02"}],
            },
            {
                "procedure_id": "proc_restart_wcs_web_application",
                "title": "Restart WCS web application",
                "issue_category": "CAT-7: Tote Data Integrity",
                "operational_intent": "Restart the WCS web application.",
                "role_required": "infrastructure",
                "support_safe": False,
                "steps": [{"step_id": "restart_wcs_web", "instruction": "Restart WCS web application.", "validation_check": "WCS web application responds."}],
                "related_incidents": ["880002"],
                "evidence_refs": [{"incident_id": "880002", "evidence_id": "chunk_880002_02"}],
            },
        ],
    )
    write_json(
        data_root / "workflows" / "workflow_candidates.json",
        [
            {
                "workflow_id": "tote_record_mismatch_hospital_remove_hangs_a",
                "title": "tote_record_mismatch_hospital_remove_hangs_a",
                "issue_category": "CAT-7: Tote Data Integrity",
                "required_signals": ["tote_record_mismatch", "hospital_remove_hangs", "rms_alarm_state_unknown"],
                "procedure_refs": ["proc_880001_confirm_no_active_rms_alarms"],
                "related_incidents": ["880001"],
                "evidence_refs": [{"incident_id": "880001", "evidence_id": "chunk_880001_01"}],
                "comparable_signal_groups": ["tote_record_mismatch", "hospital_remove_hangs"],
                "pattern_candidate_notes": "Hospital remove hangs with tote task mismatch and unknown RMS state.",
            },
            {
                "workflow_id": "tote_task_mismatch_hospital_remove_hangs_b",
                "title": "tote_task_mismatch_hospital_remove_hangs_b",
                "issue_category": "CAT-7: Tote Data Integrity",
                "required_signals": ["tote_record_mismatch", "hospital_remove_hangs", "rms_alarm_state_unknown"],
                "procedure_refs": ["proc_880002_confirm_no_active_rms_alarms"],
                "related_incidents": ["880002"],
                "evidence_refs": [{"incident_id": "880002", "evidence_id": "chunk_880002_01"}],
                "comparable_signal_groups": ["tote_record_mismatch", "hospital_remove_hangs"],
                "pattern_candidate_notes": "Hospital remove hangs with tote task mismatch and unknown RMS state.",
            },
        ],
    )
    write_json(
        data_root / "timelines" / "timeline_events.json",
        [
            {
                "incident_id": "880001",
                "event_id": "evt_880001_01",
                "event_order": 1,
                "actor_role": "support",
                "event_summary": "Support confirmed no active RMS alarms on the RMS alarm screen.",
                "action_taken": "Confirm no active RMS alarms on the RMS alarm screen.",
                "evidence_refs": ["chunk_880001_01"],
                "source_artifact_ids": ["artifact_880001_rms"],
            },
            {
                "incident_id": "880001",
                "event_id": "evt_880001_02",
                "event_order": 2,
                "actor_role": "engineer",
                "event_summary": "Engineer cancelled stuck tote tasks after confirming tote record mismatch.",
                "action_taken": "Cancel stuck tote tasks after confirming tote record mismatch.",
                "evidence_refs": ["chunk_880001_02"],
            },
            {
                "incident_id": "880002",
                "event_id": "evt_880002_01",
                "event_order": 1,
                "actor_role": "support",
                "event_summary": "Support confirmed no active RMS alarms on the RMS alarm screen.",
                "action_taken": "Confirm no active RMS alarms on the RMS alarm screen.",
                "evidence_refs": ["chunk_880002_01"],
                "source_artifact_ids": ["artifact_880002_rms"],
            },
            {
                "incident_id": "880002",
                "event_id": "evt_880002_02",
                "event_order": 2,
                "actor_role": "engineer",
                "event_summary": "Engineer cancelled stuck tote tasks after confirming tote record mismatch.",
                "action_taken": "Cancel stuck tote tasks after confirming tote record mismatch.",
                "evidence_refs": ["chunk_880002_02"],
            },
        ],
    )
    write_json(
        data_root / "evidence" / "raw_evidence_chunks.json",
        [
            {"incident_id": "880001", "chunk_id": "chunk_880001_01", "chunk_text": "RMS screen shows no active alarm."},
            {"incident_id": "880001", "chunk_id": "chunk_880001_02", "chunk_text": "Tote tasks were stuck and cancelled by engineer."},
            {"incident_id": "880002", "chunk_id": "chunk_880002_01", "chunk_text": "RMS screen shows no active alarm."},
            {"incident_id": "880002", "chunk_id": "chunk_880002_02", "chunk_text": "Tote tasks were stuck and cancelled by engineer."},
        ],
    )
    write_json(
        data_root / "evidence" / "source_artifacts.json",
        [
            {
                "incident_id": "880001",
                "artifact_id": "artifact_880001_rms",
                "artifact_type": "screenshot",
                "file_name": "rms_alarm_state.png",
            },
            {
                "incident_id": "880002",
                "artifact_id": "artifact_880002_rms",
                "artifact_type": "screenshot",
                "file_name": "rms_alarm_state.png",
            },
        ],
    )
    (data_root / "taxonomy").mkdir(parents=True, exist_ok=True)
    (data_root / "taxonomy" / "issue_taxonomy_v0.yaml").write_text(
        "\n".join(
            [
                'version: "0.1"',
                "categories:",
                "  - category_id: CAT-7",
                "    name: Tote Data Integrity",
                "    supported: true",
                "    signals:",
                "      - tote_record_mismatch",
                "      - hospital_remove_hangs",
                "      - rms_alarm_state_unknown",
            ]
        ),
        encoding="utf-8",
    )


class FakeSynthesisClient:
    def __init__(self, response):
        self.response = response
        self.packets = []

    def synthesize(self, packet):
        self.packets.append(packet)
        return self.response


def llm_response():
    return {
        "procedure_groups": [
            {
                "canonical_procedure_id": "confirm_no_active_rms_alarms_v1",
                "canonical_title": "Confirm No Active RMS Alarms",
                "purpose": "Verify RMS does not show active alarms before proceeding with tote recovery.",
                "issue_category": "CAT-7: Tote Data Integrity",
                "action_tuple": {
                    "action_type": "confirm",
                    "target_system": "RMS",
                    "target_component": "alarm screen",
                    "operational_scope": "diagnostic_check",
                    "role_required": "support",
                    "support_safe": True,
                    "validation_goal": "No active RMS alarms are visible.",
                },
                "source_procedure_ids": ["proc_880001_confirm_no_active_rms_alarms", "proc_880002_confirm_no_active_rms_alarms"],
                "related_incidents": ["880001", "880002"],
                "preconditions": ["hospital_remove_hangs", "rms_alarm_state_unknown"],
                "steps": [
                    {
                        "step_number": 1,
                        "instruction": "Open the RMS alarm view and confirm there are no active alarms.",
                        "validation_check": "No active RMS alarms are visible.",
                        "expected_result": "RMS is not presenting an active alarm that explains the hospital removal issue.",
                        "evidence_refs": [
                            {"incident_id": "880001", "evidence_id": "chunk_880001_01"},
                            {"incident_id": "880002", "evidence_id": "chunk_880002_01"},
                        ],
                        "image_refs": ["artifact_880001_rms", "artifact_880002_rms"],
                        "screenshot_required": True,
                    }
                ],
                "escalation_conditions": ["Escalate if RMS alarms are active or cannot be verified."],
                "evidence_refs": [
                    {"incident_id": "880001", "evidence_id": "chunk_880001_01"},
                    {"incident_id": "880002", "evidence_id": "chunk_880002_01"},
                ],
                "image_refs": ["artifact_880001_rms", "artifact_880002_rms"],
                "confidence": 0.84,
            }
        ],
        "workflow_groups": [
            {
                "canonical_workflow_id": "tote_record_mismatch_hospital_remove_hangs_v1",
                "title": "Tote Record Mismatch With Hospital Remove Hangs",
                "issue_category": "CAT-7: Tote Data Integrity",
                "source_workflow_ids": ["tote_record_mismatch_hospital_remove_hangs_a", "tote_task_mismatch_hospital_remove_hangs_b"],
                "related_cases": ["880001", "880002"],
                "required_signals": ["tote_record_mismatch", "hospital_remove_hangs", "rms_alarm_state_unknown"],
                "shared_signals": ["tote_record_mismatch", "hospital_remove_hangs"],
                "differing_signals": [],
                "common_root_cause_hypotheses": ["Possible stale tote task"],
                "procedure_refs": ["confirm_no_active_rms_alarms_v1"],
                "steps": [
                    {
                        "step_id": "confirm_rms_alarm_state",
                        "step_type": "diagnostic_check",
                        "instruction": "Confirm RMS alarm state before selecting recovery actions.",
                        "procedure_refs": ["confirm_no_active_rms_alarms_v1"],
                        "evidence_refs": [
                            {"incident_id": "880001", "evidence_id": "chunk_880001_01"},
                            {"incident_id": "880002", "evidence_id": "chunk_880002_01"},
                        ],
                    }
                ],
                "evidence_refs": [
                    {"incident_id": "880001", "evidence_id": "chunk_880001_01"},
                    {"incident_id": "880002", "evidence_id": "chunk_880002_01"},
                ],
                "image_refs": ["artifact_880001_rms", "artifact_880002_rms"],
                "confidence": 0.82,
            }
        ],
        "workflow_procedure_links": [
            {
                "workflow_id": "tote_record_mismatch_hospital_remove_hangs_v1",
                "procedure_id": "confirm_no_active_rms_alarms_v1",
                "step_ids": ["confirm_rms_alarm_state"],
                "source_workflow_candidate_ids": ["tote_record_mismatch_hospital_remove_hangs_a", "tote_task_mismatch_hospital_remove_hangs_b"],
                "source_procedure_candidate_ids": ["proc_880001_confirm_no_active_rms_alarms", "proc_880002_confirm_no_active_rms_alarms"],
                "related_incidents": ["880001", "880002"],
                "shared_signals": ["tote_record_mismatch", "hospital_remove_hangs"],
                "shared_resolution_patterns": ["RMS alarm state checked before tote recovery"],
                "similar_root_cause_hypotheses": ["Possible stale tote task"],
                "evidence_refs": [
                    {"incident_id": "880001", "evidence_id": "chunk_880001_01"},
                    {"incident_id": "880002", "evidence_id": "chunk_880002_01"},
                ],
                "image_refs": ["artifact_880001_rms", "artifact_880002_rms"],
                "rationale": "Both workflow candidates use the RMS alarm check before recovery selection.",
                "merge_confidence": 0.82,
                "merge_risk_notes": [],
            }
        ],
        "review_notes": [],
        "rejected_merge_groups": [
            {
                "group_id": "restart_lane_vs_wcs_web",
                "artifact_type": "procedure",
                "reason": "Restart lane and Restart WCS web application have incompatible targets and scopes.",
            }
        ],
    }


def test_candidate_agent_generates_review_only_category_agnostic_outputs(tmp_path):
    non_cat1_package(tmp_path)
    original_procedures = json.loads((tmp_path / "procedures" / "procedure_candidates.json").read_text(encoding="utf-8"))
    original_workflows = json.loads((tmp_path / "workflows" / "workflow_candidates.json").read_text(encoding="utf-8"))
    fake_client = FakeSynthesisClient(llm_response())

    result = ProcedureWorkflowCandidateAgent(tmp_path, synthesis_client=fake_client).run()

    procedures = json.loads((tmp_path / "procedures" / "generated_procedure_candidates.json").read_text(encoding="utf-8"))
    workflows = json.loads((tmp_path / "workflows" / "generated_workflow_candidates.json").read_text(encoding="utf-8"))
    links = json.loads((tmp_path / "review" / "workflow_procedure_links.json").read_text(encoding="utf-8"))
    notes = json.loads((tmp_path / "review" / "review_notes.json").read_text(encoding="utf-8"))

    assert json.loads((tmp_path / "procedures" / "procedure_candidates.json").read_text(encoding="utf-8")) == original_procedures
    assert json.loads((tmp_path / "workflows" / "workflow_candidates.json").read_text(encoding="utf-8")) == original_workflows
    assert result["procedure_candidates"] == 1
    assert result["workflow_candidates"] == 1
    assert workflows[0]["issue_category"] == "CAT-7: Tote Data Integrity"
    assert workflows[0]["source_workflow_candidate_ids"] == ["tote_record_mismatch_hospital_remove_hangs_a", "tote_task_mismatch_hospital_remove_hangs_b"]
    assert workflows[0]["related_cases"] == ["880001", "880002"]
    assert workflows[0]["validation_status"] == "needs_review"
    assert workflows[0]["status"] == "draft"
    assert "880001" not in workflows[0]["workflow_id"]
    assert workflows[0]["procedure_refs"]
    assert links
    assert {link["procedure_id"] for link in links}.issubset(set(workflows[0]["procedure_refs"]))
    assert links[0]["source_workflow_candidate_ids"]
    assert links[0]["source_procedure_candidate_ids"]
    assert links[0]["shared_resolution_patterns"]
    assert links[0]["similar_root_cause_hypotheses"]
    assert all(procedure["validation_status"] == "needs_review" for procedure in procedures)
    assert all(step["evidence_refs"] for procedure in procedures for step in procedure["steps"])
    assert any(step["image_refs"] for procedure in procedures for step in procedure["steps"])
    assert not any("Support documented" in step["instruction"] for procedure in procedures for step in procedure["steps"])
    assert any("incompatible targets" in note["note"] for note in notes)
    assert not (tmp_path / "workflows" / "workflow_definitions.json").exists()
    assert not (tmp_path / "procedures" / "reusable_procedures.json").exists()
    assert not (tmp_path / "context" / "context_reference.json").exists()
    packet = fake_client.packets[0]
    assert packet["source_procedures"][0]["candidate_inferred_causes"]
    assert packet["source_procedures"][0]["resolution_behavior"] == []
    assert packet["source_workflows"][0]["source_workflow_id"] == "tote_record_mismatch_hospital_remove_hangs_a"
    assert packet["source_workflows"][0]["evidence_refs"][0]["evidence_id"] == "chunk_880001_01"


def test_candidate_node_returns_output_counts(tmp_path):
    non_cat1_package(tmp_path)

    result = procedure_workflow_candidate_node({"data_root": str(tmp_path), "synthesis_client": FakeSynthesisClient(llm_response())})

    assert result["procedure_candidates"] == 1
    assert result["workflow_candidates"] == 1
    assert result["workflow_procedure_links"] >= 1
    assert result["review_notes"] >= 1


def test_candidate_agent_rejects_incompatible_restart_merge(tmp_path):
    non_cat1_package(tmp_path)
    response = llm_response()
    response["procedure_groups"] = [
        {
            "canonical_procedure_id": "restart_operational_component_v1",
            "canonical_title": "Restart Operational Component",
            "purpose": "Restart an operational component.",
            "action_tuple": {
                "action_type": "restart",
                "target_system": "generic service",
                "target_component": "service",
                "operational_scope": "application_service",
                "role_required": "engineer",
                "support_safe": False,
                "validation_goal": "Component returns online.",
            },
            "source_procedure_ids": ["proc_restart_lane", "proc_restart_wcs_web_application"],
            "related_incidents": ["880001", "880002"],
            "steps": [
                {
                    "step_number": 1,
                    "instruction": "Restart the operational component.",
                    "validation_check": "Component returns online.",
                    "evidence_refs": [
                        {"incident_id": "880001", "evidence_id": "chunk_880001_02"},
                        {"incident_id": "880002", "evidence_id": "chunk_880002_02"},
                    ],
                }
            ],
            "evidence_refs": [
                {"incident_id": "880001", "evidence_id": "chunk_880001_02"},
                {"incident_id": "880002", "evidence_id": "chunk_880002_02"},
            ],
            "confidence": 0.4,
        }
    ]
    response["workflow_groups"] = []
    response["workflow_procedure_links"] = []
    agent = ProcedureWorkflowCandidateAgent(tmp_path, synthesis_client=FakeSynthesisClient(response))

    with pytest.raises(ValueError, match="incompatible restart targets"):
        agent.run()


def test_candidate_agent_validation_rejects_unknown_evidence(tmp_path):
    non_cat1_package(tmp_path)
    response = llm_response()
    response["procedure_groups"][0]["evidence_refs"] = [{"incident_id": "880001", "evidence_id": "missing_chunk"}]
    response["procedure_groups"][0]["steps"][0]["evidence_refs"] = [{"incident_id": "880001", "evidence_id": "missing_chunk"}]
    agent = ProcedureWorkflowCandidateAgent(tmp_path, synthesis_client=FakeSynthesisClient(response))

    with pytest.raises(ValueError, match="unknown evidence"):
        agent.run()


def test_candidate_agent_requires_llm_config_without_injected_client(tmp_path):
    agent = ProcedureWorkflowCandidateAgent(tmp_path, llm_config_path=tmp_path / "missing_config.json")

    with pytest.raises(RuntimeError, match="Azure OpenAI config"):
        agent.generate(
            {
                "canonical_incidents": [],
                "timeline_events": [],
                "raw_evidence_chunks": [],
                "source_artifacts": [],
                "taxonomy": {},
                "prior_procedure_candidates": [],
                "prior_workflow_candidates": [],
            }
        )
