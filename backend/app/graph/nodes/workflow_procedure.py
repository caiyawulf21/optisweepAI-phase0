from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.schemas.procedure import ProcedureCandidate, SmeReviewQueueItem
from backend.app.schemas.workflow_candidate import WorkflowCandidate
from backend.app.services.procedure_merge_service import ProcedureMergeService
from backend.app.services.workflow_candidate_service import WorkflowCandidateService


def workflow_procedure_node(state: dict[str, Any] | None = None) -> dict[str, Any]:
    data_root = Path((state or {}).get("data_root", "data"))
    procedure_candidates = _load_models(data_root / "procedures" / "procedure_candidates.json", ProcedureCandidate)
    workflow_candidates = _load_models(data_root / "workflows" / "workflow_candidates.json", WorkflowCandidate)

    reusable_procedures, merge_reports = ProcedureMergeService().merge_candidates(procedure_candidates)
    workflow_definitions = WorkflowCandidateService().merge_candidates(workflow_candidates)
    review_items = [
        SmeReviewQueueItem(
            review_item_id=f"review_procedure_{procedure.procedure_id}",
            item_type="procedure",
            item_id=procedure.procedure_id,
            related_incidents=procedure.related_incidents,
            evidence_refs=procedure.evidence_refs,
        )
        for procedure in reusable_procedures
    ] + [
        SmeReviewQueueItem(
            review_item_id=f"review_workflow_{workflow.workflow_id}",
            item_type="workflow",
            item_id=workflow.workflow_id,
            related_incidents=workflow.related_incidents,
            evidence_refs=workflow.evidence_refs,
        )
        for workflow in workflow_definitions
    ]

    _write_models(data_root / "procedures" / "reusable_procedures.json", reusable_procedures)
    _write_models(data_root / "workflows" / "workflow_definitions.json", workflow_definitions)
    _write_models(data_root / "review" / "sme_review_queue.json", review_items)
    _write_models(data_root / "review" / "merge_audit_log.json", merge_reports)

    return {
        "reusable_procedure_count": len(reusable_procedures),
        "workflow_definition_count": len(workflow_definitions),
        "sme_review_queue_count": len(review_items),
        "merge_report_count": len(merge_reports),
    }


def _load_models(path: Path, model: type) -> list[Any]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [model(**item) for item in raw]


def _write_models(path: Path, models: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [model.model_dump() for model in models]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
