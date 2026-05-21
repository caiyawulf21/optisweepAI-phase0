from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.app.models.base import model_to_dict
from backend.app.models.procedure import Procedure
from backend.app.models.workflow_definition import WorkflowDefinition
from backend.app.repositories.procedure_repository import ProcedureRepository
from backend.app.repositories.workflow_repository import WorkflowRepository


def load_json(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def evidence_ref_ids(refs: list[Any]) -> list[str]:
    values = []
    for index, ref in enumerate(refs, start=1):
        if isinstance(ref, dict):
            values.append(str(ref.get("evidence_id") or ref.get("source_artifact_id") or ref.get("incident_id") or index))
        else:
            values.append(str(ref))
    return list(dict.fromkeys(values))


def reusable_workflow_documents(path: Path) -> list[dict[str, Any]]:
    documents = []
    for record in load_json(path):
        workflow_id = record["workflow_id"]
        evidence_refs = evidence_ref_ids(record.get("evidence_refs", []))
        related_incidents = [str(value) for value in record.get("related_incidents", [])]
        doc = WorkflowDefinition(
            id=record.get("id") or f"wf_{workflow_id}_{str(record.get('version') or record.get('workflow_version') or '1_0').replace('.', '_')}",
            workflow_id=workflow_id,
            workflow_version=str(record.get("workflow_version") or record.get("version") or "1.0"),
            status=record.get("status") or "draft",
            issue_category=record.get("issue_category"),
            title=record.get("title") or record.get("name"),
            operational_intent=record.get("operational_intent"),
            required_signals=[str(value) for value in record.get("required_signals", [])],
            procedure_refs=[str(value) for value in record.get("procedure_refs", [])],
            escalation_conditions=[str(value) for value in record.get("escalation_conditions", [])],
            evidence_refs=evidence_refs,
            related_cases=related_incidents,
            related_incidents=related_incidents,
            source_candidate_ids=[str(value) for value in record.get("source_candidate_ids", [])],
            retrieval_text=record.get("retrieval_text") or record.get("operational_intent") or record.get("title"),
            source_refs=evidence_refs,
            requires_manual_review=record.get("status") not in {"approved_for_workflow", "sme_reviewed", "approved"},
        )
        documents.append(model_to_dict(doc))
    return documents


def reusable_procedure_documents(path: Path) -> list[dict[str, Any]]:
    documents = []
    for record in load_json(path):
        procedure_id = record["procedure_id"]
        evidence_refs = evidence_ref_ids(record.get("evidence_refs", []))
        doc = Procedure(
            id=record.get("id") or f"proc_{procedure_id}",
            procedure_id=procedure_id,
            procedure_version=str(record.get("procedure_version") or record.get("version") or "1.0"),
            procedure_type=record.get("procedure_type") or record.get("operational_intent"),
            title=record.get("title") or procedure_id.replace("_", " ").title(),
            role_required=record.get("role_required"),
            support_safe=record.get("support_safe"),
            steps=record.get("steps", []),
            expected_outcome=record.get("expected_outcome") or record.get("operational_intent"),
            escalation_conditions=[str(value) for value in record.get("escalation_conditions", [])],
            evidence_refs=evidence_refs,
            supporting_evidence_chunks=evidence_refs,
            status=record.get("status") if record.get("status") in {"draft", "approved_for_workflow", "sme_reviewed", "approved", "deprecated"} else "draft",
            retrieval_text=record.get("retrieval_text") or record.get("operational_intent") or record.get("title"),
            source_refs=evidence_refs,
            requires_manual_review=record.get("status") not in {"approved_for_workflow", "sme_reviewed", "approved"},
            metadata={
                "related_incidents": record.get("related_incidents", []),
                "source_candidate_ids": record.get("source_candidate_ids", []),
            },
        )
        documents.append(model_to_dict(doc))
    return documents


def seed_documents(workflow_documents: list[dict[str, Any]], procedure_documents: list[dict[str, Any]], allow_runtime_asset_seed: bool = False) -> dict[str, int]:
    if not allow_runtime_asset_seed:
        raise RuntimeError("Runtime asset seeding is disabled by default. Pass --allow-runtime-asset-seed to create workflow definitions or reusable procedures.")
    workflow_repository = WorkflowRepository()
    procedure_repository = ProcedureRepository()
    for document in workflow_documents:
        workflow_repository.upsert(document)
    for document in procedure_documents:
        procedure_repository.upsert(document)
    return {"workflow_definitions": len(workflow_documents), "procedure_dictionary": len(procedure_documents)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-path", default="data/workflows/workflow_definitions.json")
    parser.add_argument("--procedure-path", default="data/procedures/reusable_procedures.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-runtime-asset-seed", action="store_true")
    args = parser.parse_args()
    workflow_documents = reusable_workflow_documents(Path(args.workflow_path))
    procedure_documents = reusable_procedure_documents(Path(args.procedure_path))
    result: dict[str, Any] = {
        "dry_run": args.dry_run,
        "documents": {
            "workflow_definitions": len(workflow_documents),
            "procedure_dictionary": len(procedure_documents),
        },
    }
    if args.dry_run:
        result["mapped_documents"] = {
            "workflow_definitions": workflow_documents,
            "procedure_dictionary": procedure_documents,
        }
    else:
        result["upserted"] = seed_documents(workflow_documents, procedure_documents, allow_runtime_asset_seed=args.allow_runtime_asset_seed)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
