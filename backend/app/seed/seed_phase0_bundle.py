from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.app.repositories.artifact_repository import ArtifactRepository
from backend.app.repositories.escalation_repository import EscalationRepository
from backend.app.repositories.evidence_repository import EvidenceRepository
from backend.app.repositories.incident_repository import IncidentRepository
from backend.app.repositories.ingestion_run_repository import IngestionRunRepository
from backend.app.repositories.relationship_repository import RelationshipRepository
from backend.app.repositories.timeline_repository import TimelineRepository
from backend.app.repositories.workflow_candidate_repository import WorkflowCandidateRepository
from backend.app.seed.bundle_mapper import document_counts, map_phase0_bundle


REPOSITORIES = {
    "incident_records": IncidentRepository,
    "timeline_events": TimelineRepository,
    "raw_evidence_chunks": EvidenceRepository,
    "source_artifacts": ArtifactRepository,
    "workflow_candidates": WorkflowCandidateRepository,
    "escalation_summaries": EscalationRepository,
    "knowledge_relationships": RelationshipRepository,
    "ingestion_runs": IngestionRunRepository,
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def persist_documents(documents: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    counts = {}
    for container_name, records in documents.items():
        repository = REPOSITORIES[container_name]()
        for record in records:
            repository.upsert(record)
        counts[container_name] = len(records)
    return counts


def import_bundle(bundle_path: Path, trace_path: Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    bundle = load_json(bundle_path)
    run_trace = load_json(trace_path) if trace_path and trace_path.exists() else None
    documents = map_phase0_bundle(bundle, run_trace)
    result = {"dry_run": dry_run, "documents": document_counts(documents)}
    if dry_run:
        result["mapped_documents"] = documents
        return result
    result["upserted"] = persist_documents(documents)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle_path")
    parser.add_argument("--trace-path")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = import_bundle(
        Path(args.bundle_path),
        Path(args.trace_path) if args.trace_path else None,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
