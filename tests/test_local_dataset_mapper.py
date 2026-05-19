import json

from backend.app.seed.local_dataset_mapper import export_bundle_to_local
from backend.app.seed.local_graph_exporter import export_graphs


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
        },
    }


def test_export_bundle_to_local_is_idempotent_and_aggregates_workflows(tmp_path):
    bundle_path = tmp_path / "seed_records.json"
    bundle_path.write_text(json.dumps(minimal_bundle()), encoding="utf-8")

    first = export_bundle_to_local(bundle_path, tmp_path)
    second = export_bundle_to_local(bundle_path, tmp_path)

    workflows = json.loads((tmp_path / "workflows" / "workflow_candidates.json").read_text(encoding="utf-8"))
    curated = json.loads((tmp_path / "curated" / "cat1_records.json").read_text(encoding="utf-8"))

    assert first == second
    assert len(workflows) == 1
    assert workflows[0]["workflow_id"] == "heartbeat_timeout_no_rms_alarm_v1"
    assert "confirm_heartbeat_candidate" in workflows[0]["procedure_refs"]
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
