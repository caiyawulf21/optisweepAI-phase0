import json

from backend.app.search.index_documents import search_document
from backend.app.seed.seed_local_datasets import local_documents
from backend.app.services.azure_search_client import LocalCat1RetrievalClient
from backend.app.services.record_status import is_runtime_retrieval_record


def cat_record(record_id: str, validation_status: str) -> dict:
    return {
        "record_id": record_id,
        "source_case_id": "229999",
        "data_source": "test",
        "source_type": "incident_summary",
        "source_authority": 1.0,
        "issue_category": "CAT-1",
        "failure_signature": "AGVs stopped with heartbeat timeout",
        "symptom_summary": "AGVs stopped, no RMS alarm, and tipper heartbeat timeout.",
        "component": ["WCS"],
        "observed_signals": ["agvs_stopped", "no_rms_alarm", "tipper_heartbeat_timeout"],
        "resolution_status": "resolved",
        "validation_status": validation_status,
    }


def test_local_runtime_retrieval_ignores_candidate_curated_records(tmp_path):
    path = tmp_path / "cat1_records.json"
    path.write_text(
        json.dumps(
            [
                cat_record("candidate_record", "candidate_extracted"),
                cat_record("approved_record", "approved_for_retrieval"),
            ]
        ),
        encoding="utf-8",
    )

    results = LocalCat1RetrievalClient(path).search(
        "AGVs stopped with no RMS alarm and heartbeat timeout",
        {"agvs_stopped": True, "no_rms_alarm": True, "tipper_heartbeat_timeout": True},
    )

    assert [result.record_id for result in results] == ["approved_record"]
    assert not is_runtime_retrieval_record({"validation_status": "candidate_extracted"})


def test_search_document_filters_unapproved_candidates_and_blocked_records():
    approved = {
        "id": "inc_approved",
        "validation_status": "approved_for_retrieval",
        "retrieval_text": "Approved searchable record",
    }
    candidate_workflow = {
        "id": "wfc_candidate",
        "validation_status": "candidate_extracted",
        "retrieval_text": "Candidate workflow",
    }
    rejected = {
        "id": "inc_rejected",
        "validation_status": "rejected",
        "retrieval_text": "Rejected record",
    }

    assert search_document("incident_records", approved) is not None
    assert search_document("workflow_candidates", candidate_workflow) is None
    assert search_document("incident_records", rejected) is None


def test_local_dataset_dry_run_mapping_does_not_require_azure_credentials(tmp_path):
    (tmp_path / "incidents").mkdir()
    (tmp_path / "timelines").mkdir()
    (tmp_path / "evidence").mkdir()
    (tmp_path / "incidents" / "canonical_incidents.json").write_text("[]", encoding="utf-8")
    (tmp_path / "timelines" / "timeline_events.json").write_text("[]", encoding="utf-8")
    (tmp_path / "evidence" / "raw_evidence_chunks.json").write_text("[]", encoding="utf-8")
    (tmp_path / "evidence" / "source_artifacts.json").write_text("[]", encoding="utf-8")

    documents = local_documents(tmp_path)

    assert documents == {
        "canonical_incidents": [],
        "timeline_events": [],
        "raw_evidence_chunks": [],
        "source_artifacts": [],
    }
