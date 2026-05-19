from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.app.seed.video_context_mapper import export_video_context_bundle_to_local, map_video_context_bundle


class VideoTrainingIngestionError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    if path.suffix.lower() != ".json":
        raise VideoTrainingIngestionError(
            f"Expected a pre-extracted video context JSON bundle, got '{path.suffix or 'no extension'}'. "
            "Raw video files are not processed by this Phase 0 scaffold."
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise VideoTrainingIngestionError(f"Invalid JSON video context bundle: {path}") from exc


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def run_video_training_ingestion(
    source: Path,
    data_root: Path = Path("data"),
    dry_run_cosmos: bool = False,
    dry_run_output: Path | None = None,
) -> dict[str, Any]:
    bundle = load_json(source)
    documents = map_video_context_bundle(bundle)
    exported = export_video_context_bundle_to_local(source, data_root)
    result: dict[str, Any] = {
        "source": str(source),
        "local_dataset_files_updated": [str(data_root / "context" / "context_reference.json")],
        "records_exported_by_dataset": exported,
        "cosmos_dry_run": dry_run_cosmos,
        "guardrails": {
            "video_ocr_ran": False,
            "video_frame_extraction_ran": False,
            "workflow_procedure_mining_ran": False,
            "azure_cosmos_sync_ran": False,
            "azure_search_sync_ran": False,
            "blob_upload_ran": False,
            "runtime_retrieval_promotion_ran": False,
            "incident_evidence_records_created": False,
        },
    }
    if dry_run_cosmos:
        result["cosmos_dry_run_documents"] = {"context_reference": documents}
        if dry_run_output:
            write_json(dry_run_output, result["cosmos_dry_run_documents"])
            result["cosmos_dry_run_output"] = str(dry_run_output)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Export pre-extracted Optisweep training video context records to Dataset 0.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--dry-run-cosmos", action="store_true")
    parser.add_argument("--dry-run-output", type=Path)
    args = parser.parse_args()
    try:
        result = run_video_training_ingestion(
            args.source,
            data_root=args.data_root,
            dry_run_cosmos=args.dry_run_cosmos,
            dry_run_output=args.dry_run_output,
        )
    except VideoTrainingIngestionError as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
