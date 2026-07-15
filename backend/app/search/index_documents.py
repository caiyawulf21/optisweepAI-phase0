from __future__ import annotations

import hashlib
import re
from typing import Any

from backend.app.services.record_status import is_search_indexable_record


CANONICAL_INDEXED_CONTAINERS = {
    "canonical_procedure_dictionary",
    "canonical_workflow_definitions",
}


INDEXED_CONTAINERS = {
    "context_reference",
    "incident_records",
    "timeline_events",
    "workflow_definitions",
    "workflow_candidates",
    "procedure_dictionary",
    "raw_evidence_chunks",
    "escalation_summaries",
} | CANONICAL_INDEXED_CONTAINERS


def clean_key(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_=-]+", "_", value).strip("_")
    return normalized[:900]


def search_document_id(container_name: str, source_id: str) -> str:
    raw = f"{container_name}:{source_id}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    return clean_key(f"{container_name}_{source_id}_{digest}")


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def symptoms(record: dict[str, Any]) -> list[str]:
    values = []
    for field_name in ["failure_signature", "observed_failure_signals", "diagnostic_signals", "action_signals", "recovery_validation_signals", "escalation_signals", "symptoms", "required_signals", "initial_symptoms"]:
        values.extend(str(value) for value in as_list(record.get(field_name)))
    return list(dict.fromkeys(values))


def _canonical_procedure_retrieval_text(payload: dict[str, Any]) -> str | None:
    parts: list[str] = []
    title = payload.get("canonical_title")
    if isinstance(title, str) and title.strip():
        parts.append(title.strip())
    for subprocedure in payload.get("subprocedures") or []:
        sub_title = subprocedure.get("canonical_title")
        if isinstance(sub_title, str) and sub_title.strip():
            parts.append(sub_title.strip())
        for step in subprocedure.get("steps") or []:
            instruction = step.get("instruction")
            if isinstance(instruction, str) and instruction.strip():
                parts.append(instruction.strip())
    text = " | ".join(parts).strip()
    return text or None


def _canonical_workflow_retrieval_text(payload: dict[str, Any]) -> str | None:
    parts: list[str] = []
    title = payload.get("canonical_title")
    if isinstance(title, str) and title.strip():
        parts.append(title.strip())
    for ec in payload.get("entry_conditions") or []:
        if isinstance(ec, str) and ec.strip():
            parts.append(ec.strip())
    for node in payload.get("nodes") or []:
        question = node.get("question")
        if isinstance(question, str) and question.strip():
            parts.append(question.strip())
    text = " | ".join(parts).strip()
    return text or None


def _canonical_record_enrichments(
    container_name: str, record: dict[str, Any]
) -> dict[str, Any]:
    payload = record.get("canonical_payload") or {}
    if container_name == "canonical_procedure_dictionary":
        return {
            "retrieval_text": _canonical_procedure_retrieval_text(payload),
            "title": payload.get("canonical_title"),
            "procedure_id": payload.get("procedure_id") or record.get("procedure_id"),
            "support_safe": _support_safe_from_canonical_procedure(payload),
        }
    if container_name == "canonical_workflow_definitions":
        return {
            "retrieval_text": _canonical_workflow_retrieval_text(payload),
            "title": payload.get("canonical_title"),
            "workflow_id": payload.get("workflow_id") or record.get("workflow_id"),
            "issue_category": payload.get("issue_category")
            or record.get("issue_category"),
        }
    return {}


def _support_safe_from_canonical_procedure(payload: dict[str, Any]) -> bool | None:
    rt = payload.get("relationship_tracking") or {}
    role = rt.get("requires_role")
    if role and isinstance(role, str) and role.lower() == "engineer":
        return False
    if role and isinstance(role, str) and role.lower() == "support":
        return True
    return None


def search_document(container_name: str, record: dict[str, Any]) -> dict[str, Any] | None:
    if container_name not in INDEXED_CONTAINERS:
        return None
    if not is_search_indexable_record(container_name, record):
        return None
    if container_name in CANONICAL_INDEXED_CONTAINERS:
        record = {**record, **_canonical_record_enrichments(container_name, record)}
    source_id = str(record.get("id"))
    retrieval_text = first_text(
        record.get("retrieval_text"),
        record.get("symptom_summary"),
        record.get("event_summary"),
        record.get("chunk_text"),
        record.get("expected_outcome"),
        record.get("handoff_summary"),
        record.get("operational_intent"),
        record.get("candidate_step"),
        record.get("proposed_change"),
        record.get("reason"),
        " ".join(record.get("missing_steps", [])) if isinstance(record.get("missing_steps"), list) else None,
    )
    if not retrieval_text:
        return None
    return {
        "id": search_document_id(container_name, source_id),
        "record_type": record.get("record_type") or container_name,
        "dataset": record.get("dataset"),
        "container_name": container_name,
        "source_cosmos_id": source_id,
        "incident_id": record.get("incident_id"),
        "issue_category": record.get("issue_category"),
        "site": record.get("site"),
        "component": [str(value) for value in as_list(record.get("component"))],
        "symptoms": symptoms(record),
        "workflow_id": record.get("workflow_id") or record.get("target_workflow_id") or record.get("workflow_step_id"),
        "procedure_id": record.get("procedure_id"),
        "source_refs": [str(value) for value in as_list(record.get("source_refs"))],
        "source_authority": record.get("source_authority"),
        "support_safe": record.get("support_safe"),
        "resolution_status": record.get("resolution_status"),
        "title": record.get("title") or record.get("event_type") or record.get("procedure_type") or record.get("candidate_workflow_name") or record.get("candidate_type"),
        "retrieval_text": retrieval_text,
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at") or record.get("created_at"),
    }


def search_documents_from_container_documents(documents: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    results = []
    for container_name, records in documents.items():
        for record in records:
            document = search_document(container_name, record)
            if document:
                results.append(document)
    return results
