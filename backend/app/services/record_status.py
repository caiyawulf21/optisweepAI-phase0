from __future__ import annotations

from typing import Any


RETRIEVAL_APPROVED_STATUSES = {"approved_for_retrieval", "sme_reviewed", "approved"}
WORKFLOW_APPROVED_STATUSES = {"approved_for_workflow", "sme_reviewed", "approved"}
BLOCKED_STATUSES = {"rejected", "deprecated"}
CANDIDATE_CONTAINERS = {"workflow_candidates"}


def normalized_status(record: Any, *field_names: str) -> str:
    for field_name in field_names or ("validation_status", "status", "review_status"):
        if isinstance(record, dict):
            value = record.get(field_name)
        else:
            value = getattr(record, field_name, None)
        if value:
            return str(value).strip().lower()
    return ""


def has_blocked_status(record: Any) -> bool:
    statuses = {
        normalized_status(record, "validation_status"),
        normalized_status(record, "status"),
        normalized_status(record, "review_status"),
    }
    return bool(statuses.intersection(BLOCKED_STATUSES))


def is_runtime_retrieval_record(record: Any) -> bool:
    if has_blocked_status(record):
        return False
    statuses = {
        normalized_status(record, "validation_status"),
        normalized_status(record, "status"),
    }
    return bool(statuses.intersection(RETRIEVAL_APPROVED_STATUSES))


def is_runtime_workflow_record(record: Any, allow_draft: bool = False) -> bool:
    if has_blocked_status(record):
        return False
    status = normalized_status(record, "status", "validation_status")
    if status in WORKFLOW_APPROVED_STATUSES:
        return True
    return allow_draft and status in {"proposed", "draft"}


def is_search_indexable_record(container_name: str, record: dict[str, Any]) -> bool:
    if has_blocked_status(record):
        return False
    if container_name in CANDIDATE_CONTAINERS:
        return False
    if container_name == "workflow_definitions":
        return is_runtime_workflow_record(record)
    if container_name == "procedure_dictionary":
        return is_runtime_workflow_record(record)
    return is_runtime_retrieval_record(record)
