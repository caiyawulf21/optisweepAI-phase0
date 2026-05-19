import json

from backend.app.seed.video_context_mapper import export_video_context_bundle_to_local, map_video_context_bundle
import pytest

from ingestion.video_training_ingestion import VideoTrainingIngestionError, run_video_training_ingestion


def minimal_video_bundle() -> dict:
    return {
        "video_metadata": {
            "video_id": "training_rms_overview_001",
            "title": "RMS Overview Training",
        },
        "records": {
            "context_domain_records": [
                {
                    "context_id": "rms_map_ui",
                    "context_type": "ui_reference",
                    "title": "RMS Map UI",
                    "description": "RMS map screen is shown with AGV positions and task status.",
                    "components": ["RMS", "AGV"],
                    "source_video": "training_rms_overview_001",
                    "timestamps": ["00:00:10-00:00:25"],
                    "artifact_refs": ["frame_000010"],
                    "scene_id": "scene_001",
                    "sequence_id": "seq_rms_map",
                    "frame_range": {
                        "start": "frame_000010",
                        "end": "frame_000025",
                    },
                    "observation_type": "visual",
                    "workflow_candidate_hint": True,
                    "procedure_candidate_hint": False,
                    "operational_signal_tags": ["agv_position", "task_status"],
                    "retrieval_text": "RMS map UI shows AGV positions and task status.",
                }
            ]
        },
    }


def write_bundle(path, bundle=None) -> None:
    path.write_text(json.dumps(bundle or minimal_video_bundle()), encoding="utf-8")


def test_map_video_context_bundle_preserves_temporal_and_provenance_metadata():
    records = map_video_context_bundle(minimal_video_bundle())

    assert len(records) == 1
    record = records[0]
    assert record["id"] == "ctx_rms_map_ui"
    assert record["dataset"] == "dataset_0_context_reference"
    assert record["context_type"] == "ui_reference"
    assert record["applies_to"] == ["RMS", "AGV"]
    assert record["source_authority"] == "training_video"
    assert record["validation_status"] == "needs_review"
    assert record["requires_manual_review"] is True
    assert record["observation_type"] == "visual"
    assert record["scene_id"] == "scene_001"
    assert record["sequence_id"] == "seq_rms_map"
    assert record["frame_range"] == {"start": "frame_000010", "end": "frame_000025"}
    assert record["workflow_candidate_hint"] is True
    assert record["procedure_candidate_hint"] is False
    assert record["operational_signal_tags"] == ["agv_position", "task_status"]
    assert "video:training_rms_overview_001" in record["source_refs"]
    assert "timestamp:00:00:10-00:00:25" in record["source_refs"]
    assert "artifact:frame_000010" in record["source_refs"]
    assert record["metadata"]["observation_type"] == "visual"
    assert record["metadata"]["frame_range"] == {"start": "frame_000010", "end": "frame_000025"}


def test_export_video_context_bundle_to_local_is_idempotent(tmp_path):
    bundle_path = tmp_path / "video_bundle.json"
    write_bundle(bundle_path)

    first = export_video_context_bundle_to_local(bundle_path, tmp_path)
    second = export_video_context_bundle_to_local(bundle_path, tmp_path)
    records = json.loads((tmp_path / "context" / "context_reference.json").read_text(encoding="utf-8"))

    assert first == second
    assert first["context_reference"] == 1
    assert len(records) == 1
    assert records[0]["id"] == "ctx_rms_map_ui"


def test_export_video_context_bundle_versions_changed_records_with_same_key(tmp_path):
    bundle_path = tmp_path / "video_bundle.json"
    original = minimal_video_bundle()
    write_bundle(bundle_path, original)
    export_video_context_bundle_to_local(bundle_path, tmp_path)

    changed = minimal_video_bundle()
    changed["records"]["context_domain_records"][0]["title"] = "RMS Map UI Updated"
    changed["records"]["context_domain_records"][0]["retrieval_text"] = "Updated RMS map context."
    write_bundle(bundle_path, changed)
    export_video_context_bundle_to_local(bundle_path, tmp_path)
    export_video_context_bundle_to_local(bundle_path, tmp_path)
    records = json.loads((tmp_path / "context" / "context_reference.json").read_text(encoding="utf-8"))

    assert [record.get("local_dataset_id") or record["id"] for record in records] == ["ctx_rms_map_ui", "ctx_rms_map_ui_v2"]
    assert records[1]["ingestion_version"] == 2
    assert records[1]["supersedes_local_dataset_id"] == "ctx_rms_map_ui"


def test_video_training_ingestion_dry_run_keeps_runtime_guardrails(tmp_path):
    bundle_path = tmp_path / "video_bundle.json"
    dry_run_path = tmp_path / "cosmos_dry_run.json"
    data_root = tmp_path / "data"
    write_bundle(bundle_path)

    result = run_video_training_ingestion(
        bundle_path,
        data_root=data_root,
        dry_run_cosmos=True,
        dry_run_output=dry_run_path,
    )

    assert (data_root / "context" / "context_reference.json").exists()
    assert json.loads((data_root / "incidents" / "canonical_incidents.json").read_text(encoding="utf-8")) == []
    assert result["records_exported_by_dataset"] == {"context_reference": 1}
    assert result["cosmos_dry_run"] is True
    assert result["cosmos_dry_run_documents"]["context_reference"][0]["id"] == "ctx_rms_map_ui"
    assert json.loads(dry_run_path.read_text(encoding="utf-8")) == result["cosmos_dry_run_documents"]
    assert result["guardrails"] == {
        "video_ocr_ran": False,
        "video_frame_extraction_ran": False,
        "workflow_procedure_mining_ran": False,
        "azure_cosmos_sync_ran": False,
        "azure_search_sync_ran": False,
        "blob_upload_ran": False,
        "runtime_retrieval_promotion_ran": False,
        "incident_evidence_records_created": False,
    }


def test_video_training_ingestion_rejects_raw_video_input(tmp_path):
    video_path = tmp_path / "training.mp4"
    video_path.write_bytes(b"\x00\x00\x00 ftypmp42")

    with pytest.raises(VideoTrainingIngestionError, match="pre-extracted video context JSON bundle"):
        run_video_training_ingestion(video_path, data_root=tmp_path / "data", dry_run_cosmos=True)
