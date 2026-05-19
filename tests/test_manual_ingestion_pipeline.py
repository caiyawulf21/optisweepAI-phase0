import hashlib
import json
from pathlib import Path

from ingestion.manual_ingestion import run_manual_ingestion
from tests.test_local_dataset_mapper import minimal_bundle


def digest_tree(path: Path) -> dict[str, str]:
    return {
        str(file.relative_to(path)): hashlib.sha256(file.read_bytes()).hexdigest()
        for file in sorted(path.rglob("*"))
        if file.is_file()
    }


def write_bundle(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(minimal_bundle()), encoding="utf-8")


def test_manual_ingestion_without_auto_export_only_writes_seed_records(tmp_path):
    source = tmp_path / "source_seed_records.json"
    destination = tmp_path / "output" / "seed_records.json"
    data_root = tmp_path / "data"
    write_bundle(source)

    result = run_manual_ingestion(source, destination, data_root=data_root)

    assert destination.exists()
    assert not data_root.exists()
    assert result["auto_export"] is False
    assert result["local_dataset_files_updated"] == []
    assert result["records_exported_by_dataset"] == {}


def test_manual_ingestion_with_auto_export_updates_local_datasets(tmp_path):
    source = tmp_path / "seed_records.json"
    data_root = tmp_path / "data"
    write_bundle(source)

    result = run_manual_ingestion(source, source, auto_export=True, data_root=data_root)

    assert (data_root / "incidents" / "canonical_incidents.json").exists()
    assert (data_root / "workflows" / "workflow_candidates.json").exists()
    assert result["records_exported_by_dataset"]["canonical_incidents"] == 1
    assert result["records_exported_by_dataset"]["workflow_candidates"] == 1


def test_manual_ingestion_auto_export_with_graphs_creates_markdown_graphs(tmp_path):
    source = tmp_path / "seed_records.json"
    data_root = tmp_path / "data"
    write_bundle(source)

    result = run_manual_ingestion(source, source, auto_export=True, generate_graphs=True, data_root=data_root)

    assert (data_root / "curated" / "graph.md").exists()
    assert (data_root / "procedures" / "graphs" / "confirm_heartbeat_candidate.md").exists()
    assert (data_root / "workflows" / "graphs" / "heartbeat_timeout_no_rms_alarm_v1.md").exists()
    assert result["graph_files_generated"]["curated\\graph.md"] == 1


def test_manual_ingestion_auto_export_does_not_run_agent_or_azure_sync(tmp_path):
    source = tmp_path / "seed_records.json"
    data_root = tmp_path / "data"
    write_bundle(source)

    result = run_manual_ingestion(source, source, auto_export=True, data_root=data_root)

    assert result["guardrails"] == {
        "workflow_procedure_agent_ran": False,
        "azure_cosmos_sync_ran": False,
        "azure_search_sync_ran": False,
        "blob_upload_ran": False,
    }
    assert json.loads((data_root / "procedures" / "reusable_procedures.json").read_text(encoding="utf-8")) == []
    assert json.loads((data_root / "workflows" / "workflow_definitions.json").read_text(encoding="utf-8")) == []


def test_manual_ingestion_auto_export_does_not_create_approved_runtime_records(tmp_path):
    source = tmp_path / "seed_records.json"
    data_root = tmp_path / "data"
    write_bundle(source)

    run_manual_ingestion(source, source, auto_export=True, data_root=data_root)

    curated = json.loads((data_root / "curated" / "cat1_records.json").read_text(encoding="utf-8"))
    workflows = json.loads((data_root / "workflows" / "workflow_candidates.json").read_text(encoding="utf-8"))

    assert {record["validation_status"] for record in curated} == {"candidate_extracted"}
    assert {record["status"] for record in workflows} == {"candidate_extracted"}


def test_manual_ingestion_auto_export_is_idempotent(tmp_path):
    source = tmp_path / "seed_records.json"
    data_root = tmp_path / "data"
    write_bundle(source)

    first = run_manual_ingestion(source, source, auto_export=True, generate_graphs=True, data_root=data_root)
    first_digest = digest_tree(data_root)
    second = run_manual_ingestion(source, source, auto_export=True, generate_graphs=True, data_root=data_root)
    second_digest = digest_tree(data_root)

    assert first["records_exported_by_dataset"] == second["records_exported_by_dataset"]
    assert first_digest == second_digest
