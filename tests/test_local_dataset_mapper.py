import json
import zipfile

import pytest

from backend.app.seed.bundle_mapper import map_phase0_bundle
from backend.app.seed.issue_category_context import category_for_case, issue_category_context
from backend.app.seed.local_dataset_mapper import export_bundle_to_local
from backend.app.seed.local_graph_exporter import export_graphs
from backend.app.seed.seed_reusable_assets import seed_documents


def minimal_bundle() -> dict:
    return {
        "bundle_metadata": {
            "incident_id": "229999",
            "category": "CAT-1: WCS / Service Failure",
            "validation_status": "candidate_extracted",
            "requires_manual_review": True,
        },
        "records": {
            "canonical_incident": {
                "incident_id": "229999",
                "source_case_id": "00229999",
                "title": "AGVs stopped with heartbeat timeout",
                "symptom_summary": "AGVs stopped and tipper heartbeat timeout was observed.",
                "observed_failure_signals": ["AGVs stopped", "tipper heartbeat timeout"],
                "diagnostic_signals": ["no RMS alarm"],
                "validation_status": "candidate_extracted",
            },
            "timeline_events": [
                {"event_id": "evt_229999_01", "event_summary": "Support confirmed no RMS alarm."}
            ],
            "raw_evidence_chunks": [
                {"chunk_id": "chunk_229999_01", "chunk_text": "No RMS alarm and heartbeat timeout."}
            ],
            "source_artifact_references": [
                {"artifact_id": "artifact_229999_01", "file_name": "case.docx"}
            ],
            "procedure_candidates": [
                {
                    "procedure_id": "confirm_heartbeat_candidate",
                    "title": "Confirm heartbeat timeout",
                    "procedure_goal": "Confirm heartbeat timeout before escalation.",
                    "role_required": "support",
                    "support_safe": True,
                    "procedure_steps": [{"step_id": "confirm_heartbeat", "instruction": "Confirm heartbeat timeout."}],
                    "supporting_evidence_chunks": ["chunk_229999_01"],
                    "validation_status": "candidate_extracted",
                }
            ],
            "workflow_candidate_steps": [
                {
                    "candidate_workflow_name": "heartbeat_timeout_no_rms_alarm_v1",
                    "candidate_step": "Confirm no RMS alarm.",
                    "required_signals": ["AGVs stopped", "tipper heartbeat timeout", "no RMS alarm"],
                    "procedure_refs": ["confirm_heartbeat_candidate"],
                    "evidence_refs": ["chunk_229999_01"],
                },
                {
                    "candidate_workflow_name": "heartbeat_timeout_no_rms_alarm_v1",
                    "candidate_step": "Validate heartbeat recovery.",
                    "required_signals": ["tipper heartbeat timeout"],
                    "procedure_refs": ["confirm_heartbeat_candidate"],
                    "evidence_refs": ["chunk_229999_01"],
                },
            ],
            "escalation_summary_template": {
                "trigger_reason": "Candidate escalation context.",
                "symptoms": ["AGVs stopped"],
                "handoff_summary": "Candidate handoff summary.",
            },
        },
    }


def test_export_bundle_to_local_is_idempotent_and_aggregates_workflows(tmp_path):
    bundle_path = tmp_path / "seed_records.json"
    bundle_path.write_text(json.dumps(minimal_bundle()), encoding="utf-8")

    first = export_bundle_to_local(bundle_path, tmp_path)
    second = export_bundle_to_local(bundle_path, tmp_path)

    workflows = json.loads((tmp_path / "workflows" / "workflow_candidates.json").read_text(encoding="utf-8"))
    curated = json.loads((tmp_path / "curated" / "candidate_incident_records.json").read_text(encoding="utf-8"))

    assert first == second
    assert len(workflows) == 1
    assert workflows[0]["workflow_id"] == "heartbeat_timeout_no_rms_alarm_v1"
    assert "confirm_heartbeat_candidate" in workflows[0]["procedure_refs"]
    assert workflows[0]["required_signals"] == ["AGVs stopped", "tipper heartbeat timeout", "no RMS alarm"]
    assert workflows[0]["issue_category"] == "CAT-1: WCS / Service Failure"
    assert curated[0]["observed_signals"] == ["AGVs stopped", "tipper heartbeat timeout", "no RMS alarm"]
    assert curated[0]["issue_category"] == "CAT-1: WCS / Service Failure"
    assert curated[0]["validation_status"] == "candidate_extracted"


def test_export_bundle_versions_changed_records_with_same_stable_key(tmp_path):
    bundle_path = tmp_path / "seed_records.json"
    original = minimal_bundle()
    bundle_path.write_text(json.dumps(original), encoding="utf-8")
    export_bundle_to_local(bundle_path, tmp_path)

    changed = minimal_bundle()
    changed["records"]["canonical_incident"]["title"] = "AGVs stopped with heartbeat timeout updated extraction"
    changed["records"]["timeline_events"][0]["event_summary"] = "Support confirmed no RMS alarm after updated extraction."
    bundle_path.write_text(json.dumps(changed), encoding="utf-8")

    export_bundle_to_local(bundle_path, tmp_path)
    export_bundle_to_local(bundle_path, tmp_path)

    incidents = json.loads((tmp_path / "incidents" / "canonical_incidents.json").read_text(encoding="utf-8"))
    timelines = json.loads((tmp_path / "timelines" / "timeline_events.json").read_text(encoding="utf-8"))

    assert [record["local_dataset_id"] for record in incidents] == ["229999", "229999_v2"]
    assert [record["ingestion_version"] for record in incidents] == [1, 2]
    assert incidents[1]["supersedes_local_dataset_id"] == "229999"
    assert len(timelines) == 2


def test_export_graphs_writes_dataset_and_asset_graphs(tmp_path):
    bundle_path = tmp_path / "seed_records.json"
    bundle_path.write_text(json.dumps(minimal_bundle()), encoding="utf-8")
    export_bundle_to_local(bundle_path, tmp_path)

    result = export_graphs(tmp_path)

    assert result["curated\\graph.md"] == 1
    assert (tmp_path / "curated" / "graph.md").exists()
    assert (tmp_path / "procedures" / "graphs" / "confirm_heartbeat_candidate.md").exists()
    assert (tmp_path / "workflows" / "graphs" / "heartbeat_timeout_no_rms_alarm_v1.md").exists()


def test_source_silent_category_stays_uncategorized_for_cat2_like_symptoms(tmp_path):
    bundle = minimal_bundle()
    bundle["bundle_metadata"].pop("category")
    canonical = bundle["records"]["canonical_incident"]
    canonical.pop("issue_category", None)
    canonical["title"] = "Dimension check failed after induction"
    canonical["symptom_summary"] = "Package dimensions were rejected and needed operator correction."
    canonical["observed_failure_signals"] = ["dimension check failed", "operator correction required"]
    bundle["records"]["workflow_candidate_steps"][0]["required_signals"] = ["dimension check failed"]
    bundle["records"]["workflow_candidate_steps"][1]["required_signals"] = ["operator correction required"]
    bundle_path = tmp_path / "seed_records.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    export_bundle_to_local(bundle_path, tmp_path)

    curated = json.loads((tmp_path / "curated" / "candidate_incident_records.json").read_text(encoding="utf-8"))
    workflows = json.loads((tmp_path / "workflows" / "workflow_candidates.json").read_text(encoding="utf-8"))

    assert "issue_category" not in curated[0]
    assert "issue_category" not in workflows[0]
    assert curated[0]["observed_signals"] == ["dimension check failed", "operator correction required", "no RMS alarm"]
    assert workflows[0]["required_signals"] == ["dimension check failed", "operator correction required"]


def test_bundle_mapper_keeps_procedure_candidates_out_of_runtime_dictionary():
    documents = map_phase0_bundle(minimal_bundle())

    assert "procedure_dictionary" not in documents
    relationship_types = {record["relationship_type"] for record in documents["knowledge_relationships"]}
    assert "INCIDENT_RESOLVED_BY_PROCEDURE" not in relationship_types
    assert "WORKFLOW_CANDIDATE_USES_PROCEDURE" not in relationship_types
    assert "INCIDENT_HAS_PROCEDURE_CANDIDATE" in relationship_types
    assert "INCIDENT_HAS_WORKFLOW_CANDIDATE" in relationship_types
    assert "WORKFLOW_CANDIDATE_REFERENCES_PROCEDURE_CANDIDATE" in relationship_types


def test_issue_category_doc_context_supports_explicit_case_lookup(tmp_path):
    docx_path = tmp_path / "issue_categories.docx"
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>Optisweep issue category source facts.</w:t></w:r></w:p>
    <w:tbl>
      <w:tr><w:tc><w:p><w:r><w:t>case_id</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>issue_category</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>description</w:t></w:r></w:p></w:tc></w:tr>
      <w:tr><w:tc><w:p><w:r><w:t>229999</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>CAT-1: WCS / Service Failure</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Known Phase 0 source row.</w:t></w:r></w:p></w:tc></w:tr>
    </w:tbl>
  </w:body>
</w:document>"""
    with zipfile.ZipFile(docx_path, "w") as archive:
        archive.writestr("word/document.xml", document_xml)

    context = issue_category_context(docx_path)

    assert category_for_case("229999", context) == "CAT-1: WCS / Service Failure"
    assert category_for_case("230000", context) is None
    assert "keyword_or_symptom_based_category_inference" in context["non_usage"]


def test_runtime_asset_seeding_fails_closed_by_default():
    with pytest.raises(RuntimeError, match="Runtime asset seeding is disabled"):
        seed_documents([], [])


def test_fallback_review_only_procedures_and_workflows_are_not_exported(tmp_path):
    bundle = minimal_bundle()
    bundle["records"]["procedure_candidates"][0].update(
        {
            "quality_tier": "fallback_review_only",
            "eligible_for_cross_incident_synthesis": False,
            "eligible_for_workflow_grouping": False,
        }
    )
    for workflow in bundle["records"]["workflow_candidate_steps"]:
        workflow.update(
            {
                "quality_tier": "fallback_review_only",
                "fallback_only": True,
                "eligible_for_cross_incident_synthesis": False,
                "eligible_for_workflow_grouping": False,
            }
        )
    bundle_path = tmp_path / "seed_records.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    result = export_bundle_to_local(bundle_path, tmp_path)

    assert result["procedure_candidates"] == 0
    assert result["workflow_candidates"] == 0
    assert json.loads((tmp_path / "procedures" / "procedure_candidates.json").read_text(encoding="utf-8")) == []
    assert json.loads((tmp_path / "workflows" / "workflow_candidates.json").read_text(encoding="utf-8")) == []


def test_high_quality_candidates_remain_exportable_with_quality_metadata(tmp_path):
    bundle = minimal_bundle()
    bundle["records"]["procedure_candidates"][0].update(
        {
            "quality_tier": "llm_operational_synthesis",
            "eligible_for_cross_incident_synthesis": True,
            "synthesis_level": "HIGH_WHEN_EVIDENCE_SUPPORTS",
        }
    )
    bundle["records"]["workflow_candidate_steps"][0].update(
        {
            "quality_tier": "llm_operational_synthesis",
            "eligible_for_cross_incident_synthesis": True,
            "eligible_for_workflow_grouping": True,
            "synthesis_level": "HIGH",
        }
    )
    bundle_path = tmp_path / "seed_records.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    export_bundle_to_local(bundle_path, tmp_path)

    procedures = json.loads((tmp_path / "procedures" / "procedure_candidates.json").read_text(encoding="utf-8"))
    workflows = json.loads((tmp_path / "workflows" / "workflow_candidates.json").read_text(encoding="utf-8"))

    assert procedures[0]["quality_tier"] == "llm_operational_synthesis"
    assert procedures[0]["eligible_for_cross_incident_synthesis"] is True
    assert workflows[0]["quality_tier"] == "llm_operational_synthesis"


def test_operator_action_projects_to_procedure_instruction(tmp_path):
    bundle = minimal_bundle()
    bundle["records"]["procedure_candidates"][0]["title"] = None
    bundle["records"]["procedure_candidates"][0]["procedure_name"] = "Review operational state"
    bundle["records"]["procedure_candidates"][0]["procedure_steps"] = [
        {
            "step_id": "capture_state",
            "operator_action": "Open the support UI and capture the visible operational state.",
            "validation_check": "The captured evidence shows current operational state.",
            "expected_result": "Operational state is documented.",
            "escalation_boundary": "Escalate if state cannot be confirmed.",
        }
    ]
    bundle_path = tmp_path / "seed_records.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    export_bundle_to_local(bundle_path, tmp_path)

    procedures = json.loads((tmp_path / "procedures" / "procedure_candidates.json").read_text(encoding="utf-8"))

    assert procedures[0]["title"] == "Review operational state"
    assert procedures[0]["steps"][0]["instruction"] == "Open the support UI and capture the visible operational state."
    assert procedures[0]["steps"][0]["expected_outcome"] == "Operational state is documented."
    assert procedures[0]["steps"][0]["escalation_condition"] == "Escalate if state cannot be confirmed."
