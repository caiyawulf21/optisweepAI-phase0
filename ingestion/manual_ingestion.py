from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.app.seed.local_dataset_mapper import DATASET_PATHS, export_bundle_to_local, load_json
from backend.app.seed.local_graph_exporter import export_graphs


DEFAULT_CANDIDATE_DESTINATION = Path("data/curated/candidate_incident_records.json")


def copy_local_record(source: Path, destination: Path) -> None:
    raw = json.loads(source.read_text(encoding="utf-8"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(raw, indent=2), encoding="utf-8")


def status_value(record: dict[str, Any]) -> str:
    return str(record.get("validation_status") or record.get("status") or record.get("review_status") or "").strip().lower()


def candidate_summary(data_root: Path) -> dict[str, int]:
    candidate_statuses = {"raw", "candidate", "candidate_extracted", "merged_candidate", "needs_sme_review", "proposed", "draft"}
    summary: dict[str, int] = {}
    for dataset_name, relative_path in DATASET_PATHS.items():
        records = load_json(data_root / relative_path)
        if not isinstance(records, list):
            continue
        count = sum(1 for record in records if isinstance(record, dict) and status_value(record) in candidate_statuses)
        if count:
            summary[dataset_name] = count
    return summary


def run_manual_ingestion(source: Path, destination: Path, auto_export: bool = False, generate_graphs: bool = False, data_root: Path = Path("data")) -> dict[str, Any]:
    copy_local_record(source, destination)
    result: dict[str, Any] = {
        "seed_records_path": str(destination),
        "auto_export": auto_export,
        "generate_graphs": generate_graphs,
        "local_dataset_files_updated": [],
        "graph_files_generated": {},
        "records_exported_by_dataset": {},
        "candidate_non_runtime_records": {},
        "guardrails": {
            "workflow_procedure_agent_ran": False,
            "azure_cosmos_sync_ran": False,
            "azure_search_sync_ran": False,
            "blob_upload_ran": False,
        },
    }
    if not auto_export:
        return result

    exported = export_bundle_to_local(destination, data_root)
    result["records_exported_by_dataset"] = exported
    result["local_dataset_files_updated"] = [
        str(data_root / DATASET_PATHS[name])
        for name in exported
        if name in DATASET_PATHS
    ]
    if generate_graphs:
        result["graph_files_generated"] = export_graphs(data_root)
    result["candidate_non_runtime_records"] = candidate_summary(data_root)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Copy manually curated candidate records into the local Phase 0 data store.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--auto-export", action="store_true")
    parser.add_argument("--generate-graphs", action="store_true")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    args = parser.parse_args()
    destination = args.destination or (args.source if args.auto_export else DEFAULT_CANDIDATE_DESTINATION)
    result = run_manual_ingestion(
        args.source,
        destination,
        auto_export=args.auto_export,
        generate_graphs=args.generate_graphs,
        data_root=args.data_root,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
