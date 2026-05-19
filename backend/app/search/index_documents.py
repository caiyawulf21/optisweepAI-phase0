from __future__ import annotations

import hashlib
import re
from typing import Any

from backend.app.seed.bundle_mapper import map_phase0_bundle
from backend.app.services.record_status import is_search_indexable_record


INDEXED_CONTAINERS = {
    "context_reference",
    "incident_records",
    "timeline_events",
    "workflow_definitions",
    "workflow_candidates",
    "procedure_dictionary",
    "raw_evidence_chunks",
    "escalation_summaries",
}


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


def search_document(container_name: str, record: dict[str, Any]) -> dict[str, Any] | None:
    if container_name not in INDEXED_CONTAINERS:
        return None
    if not is_search_indexable_record(container_name, record):
        return None
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


def search_documents_from_bundle(bundle: dict[str, Any], run_trace: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return search_documents_from_container_documents(map_phase0_bundle(bundle, run_trace))
