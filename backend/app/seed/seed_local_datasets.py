from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.app.repositories.artifact_repository import ArtifactRepository
from backend.app.repositories.evidence_repository import EvidenceRepository
from backend.app.repositories.incident_repository import IncidentRepository
from backend.app.repositories.timeline_repository import TimelineRepository
from backend.app.seed.local_dataset_mapper import DATASET_PATHS, load_json
from backend.app.seed.seed_reusable_assets import reusable_procedure_documents, reusable_workflow_documents, seed_documents


REPOSITORIES = {
    "canonical_incidents": IncidentRepository,
    "timeline_events": TimelineRepository,
    "raw_evidence_chunks": EvidenceRepository,
    "source_artifacts": ArtifactRepository,
}


def local_documents(data_root: Path) -> dict[str, list[dict[str, Any]]]:
    documents = {}
    for name in REPOSITORIES:
        records = load_json(data_root / DATASET_PATHS[name])
        documents[name] = records if isinstance(records, list) else []
    return documents


def persist_local_documents(documents: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    counts = {}
    for name, records in documents.items():
        repository = REPOSITORIES[name]()
        for record in records:
            if "id" in record:
                repository.upsert(record)
        counts[name] = len(records)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-runtime-asset-seed", action="store_true")
    args = parser.parse_args()

    data_root = Path(args.data_root)
    documents = local_documents(data_root)
    workflow_documents = []
    procedure_documents = []
    if args.allow_runtime_asset_seed:
        workflow_documents = reusable_workflow_documents(data_root / DATASET_PATHS["workflow_definitions"])
        procedure_documents = reusable_procedure_documents(data_root / DATASET_PATHS["reusable_procedures"])
    result: dict[str, Any] = {
        "dry_run": args.dry_run,
        "documents": {name: len(records) for name, records in documents.items()},
        "runtime_asset_seed": {
            "enabled": args.allow_runtime_asset_seed,
        },
        "reusable_assets": {
            "workflow_definitions": len(workflow_documents),
            "procedure_dictionary": len(procedure_documents),
        },
    }
    if args.dry_run:
        result["mapped_documents"] = documents
        result["mapped_reusable_assets"] = {
            "workflow_definitions": workflow_documents,
            "procedure_dictionary": procedure_documents,
        }
    else:
        result["upserted"] = persist_local_documents(documents)
        result["upserted_reusable_assets"] = (
            seed_documents(workflow_documents, procedure_documents, allow_runtime_asset_seed=True)
            if args.allow_runtime_asset_seed
            else {"workflow_definitions": 0, "procedure_dictionary": 0}
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
