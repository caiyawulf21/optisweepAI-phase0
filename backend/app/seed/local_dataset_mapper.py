from __future__ import annotations

import json
import re
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any


DATASET_PATHS = {
    "context_reference": Path("context/context_reference.json"),
    "canonical_incidents": Path("incidents/canonical_incidents.json"),
    "timeline_events": Path("timelines/timeline_events.json"),
    "raw_evidence_chunks": Path("evidence/raw_evidence_chunks.json"),
    "source_artifacts": Path("evidence/source_artifacts.json"),
    "procedure_candidates": Path("procedures/procedure_candidates.json"),
    "generated_procedure_candidates": Path("procedures/generated_procedure_candidates.json"),
    "reusable_procedures": Path("procedures/reusable_procedures.json"),
    "workflow_candidates": Path("workflows/workflow_candidates.json"),
    "generated_workflow_candidates": Path("workflows/generated_workflow_candidates.json"),
    "workflow_definitions": Path("workflows/workflow_definitions.json"),
    "workflow_procedure_links": Path("review/workflow_procedure_links.json"),
    "review_notes": Path("review/review_notes.json"),
    "sme_review_queue": Path("review/sme_review_queue.json"),
    "merge_audit_log": Path("review/merge_audit_log.json"),
    "candidate_incident_records": Path("curated/candidate_incident_records.json"),
}

MERGE_KEYS = {
    "context_reference": "id",
    "canonical_incidents": "incident_id",
    "timeline_events": "event_id",
    "raw_evidence_chunks": "chunk_id",
    "source_artifacts": "artifact_id",
    "procedure_candidates": "procedure_id",
    "generated_procedure_candidates": "procedure_id",
    "reusable_procedures": "procedure_id",
    "workflow_candidates": "workflow_id",
    "generated_workflow_candidates": "workflow_id",
    "workflow_definitions": "workflow_id",
    "workflow_procedure_links": "link_id",
    "review_notes": "note_id",
    "sme_review_queue": "review_item_id",
    "merge_audit_log": "merge_id",
    "candidate_incident_records": "record_id",
}


def load_json(path: Path) -> Any:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def clean_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()


def source_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def source_terms(value: Any) -> list[str]:
    return list(dict.fromkeys(term for term in (source_text(item) for item in as_list(value)) if term))


def evidence_refs(record: dict[str, Any], incident_id: str) -> list[dict[str, str]]:
    refs = []
    for value in as_list(record.get("evidence_refs") or record.get("supporting_evidence_chunks") or record.get("source_region_refs")):
        refs.append({"incident_id": incident_id, "evidence_id": str(value)})
    for value in as_list(record.get("source_artifact_ids")):
        refs.append({"incident_id": incident_id, "evidence_id": str(value), "source_artifact_id": str(value)})
    return refs


QUALITY_FIELDS = [
    "quality_tier",
    "fallback_only",
    "eligible_for_cross_incident_synthesis",
    "eligible_for_workflow_grouping",
    "fallback_reason",
    "requires_manual_reingestion",
    "synthesis_level",
    "synthesis_blockers",
    "pattern_candidate_notes",
    "comparable_signal_groups",
    "recurrence_evidence_refs",
]


def quality_metadata(record: dict[str, Any]) -> dict[str, Any]:
    return {field_name: record[field_name] for field_name in QUALITY_FIELDS if field_name in record}


def is_review_only_candidate(record: dict[str, Any]) -> bool:
    return record.get("quality_tier") == "fallback_review_only" or record.get("fallback_only") is True


def with_local_dataset_id(record: dict[str, Any], local_dataset_id: str, version: int = 1) -> dict[str, Any]:
    updated = deepcopy(record)
    updated["local_dataset_id"] = local_dataset_id
    updated["ingestion_version"] = version
    return updated


def procedure_steps(record: dict[str, Any]) -> list[dict[str, Any]]:
    steps = []
    raw_steps = as_list(record.get("steps") or record.get("procedure_steps"))
    for index, step in enumerate(raw_steps, start=1):
        if isinstance(step, dict):
            instruction = step.get("instruction") or step.get("operator_action") or step.get("step") or step.get("action") or step.get("description")
            step_id = step.get("step_id")
            steps.append(
                {
                    "step_id": clean_id(str(step_id)) if step_id else f"step_{index:02d}",
                    "instruction": source_text(instruction),
                    "validation_check": step.get("validation_check") or step.get("validation"),
                    "expected_outcome": step.get("expected_outcome") or step.get("expected_result") or step.get("outcome"),
                    "escalation_condition": step.get("escalation_condition") or step.get("escalation_boundary"),
                }
            )
        elif step:
            steps.append({"step_id": f"step_{index:02d}", "instruction": str(step)})
    return steps


def map_procedure_candidate(record: dict[str, Any], incident_id: str, index: int, metadata: dict[str, Any]) -> dict[str, Any] | None:
    if is_review_only_candidate(record):
        return None
    procedure_id = clean_id(str(record.get("procedure_id") or record.get("procedure_name") or record.get("title") or f"procedure_{incident_id}_{index:03d}"))
    title = record.get("title") or record.get("procedure_title") or record.get("procedure_name")
    candidate = {
        "local_dataset_id": procedure_id,
        "ingestion_version": 1,
        "procedure_id": procedure_id,
        "title": title,
        "issue_category": record.get("issue_category") or metadata.get("category"),
        "operational_intent": record.get("operational_intent") or record.get("procedure_goal") or record.get("procedure_summary"),
        "role_required": record.get("role_required"),
        "support_safe": record.get("support_safe"),
        "steps": procedure_steps(record),
        "validation_checks": source_terms(record.get("validation_checks")),
        "escalation_conditions": source_terms(record.get("escalation_conditions")),
        "related_incidents": [incident_id],
        "evidence_refs": evidence_refs(record, incident_id),
        "status": record.get("status") or record.get("validation_status"),
        **quality_metadata(record),
    }
    return {key: value for key, value in candidate.items() if value is not None}


def map_workflow_candidates(records: list[dict[str, Any]], incident_id: str, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, record in enumerate(records, start=1):
        if is_review_only_candidate(record):
            continue
        workflow_id = clean_id(str(record.get("candidate_workflow_name") or record.get("workflow_id") or f"workflow_{incident_id}_{index:03d}"))
        grouped[workflow_id].append(record)
    workflows = []
    for workflow_id, group in grouped.items():
        first = group[0]
        required_signals = []
        procedure_refs = []
        escalation_conditions = []
        refs = []
        for record in group:
            required_signals.extend(source_terms(record.get("required_signals") or record.get("initial_symptoms") or record.get("entry_conditions")))
            procedure_refs.extend(source_terms(record.get("procedure_refs") or record.get("next_procedure_refs")))
            escalation_conditions.extend(source_terms(record.get("escalation_conditions")))
            refs.extend(evidence_refs(record, incident_id))
        workflow = {
            "local_dataset_id": workflow_id,
            "ingestion_version": 1,
            "workflow_id": workflow_id,
            "title": first.get("title") or first.get("candidate_workflow_name"),
            "issue_category": first.get("issue_category") or metadata.get("category"),
            "operational_intent": first.get("operational_intent") or first.get("reason") or first.get("proposed_change"),
            "required_signals": list(dict.fromkeys(required_signals)),
            "procedure_refs": list(dict.fromkeys(procedure_refs)),
            "related_incidents": [incident_id],
            "evidence_refs": refs,
            "escalation_conditions": list(dict.fromkeys(escalation_conditions)),
            "status": first.get("status") or first.get("validation_status") or metadata.get("validation_status"),
            **quality_metadata(first),
        }
        workflows.append({key: value for key, value in workflow.items() if value is not None})
    return workflows


def map_candidate_incident_record(canonical: dict[str, Any], incident_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
    signals = []
    for field_name in ["observed_failure_signals", "diagnostic_signals", "action_signals", "recovery_validation_signals", "escalation_signals"]:
        signals.extend(source_terms(canonical.get(field_name)))
    record = {
        "local_dataset_id": f"candidate_incident_{incident_id}",
        "ingestion_version": 1,
        "record_id": f"candidate_incident_{incident_id}",
        "source_case_id": str(canonical.get("source_case_id") or incident_id),
        "data_source": "manual ingestion output",
        "source_type": "canonical_incident",
        "source_authority": float(canonical.get("confidence") or 0.5),
        "site": canonical.get("site") or canonical.get("customer"),
        "issue_category": canonical.get("issue_category") or metadata.get("category"),
        "failure_signature": canonical.get("title") or f"Candidate incident {incident_id}",
        "symptom_summary": canonical.get("symptom_summary") or canonical.get("retrieval_text") or canonical.get("title") or f"Candidate incident {incident_id}",
        "component": source_terms(canonical.get("component")),
        "observed_signals": list(dict.fromkeys(signals)),
        "root_cause_summary": None,
        "resolution_summary": canonical.get("resolution_summary"),
        "resolution_steps": [],
        "escalation_domains": source_terms(canonical.get("escalation_domains")),
        "escalation_notes": None,
        "resolution_status": canonical.get("resolution_status"),
        "validation_status": canonical.get("validation_status") or metadata.get("validation_status"),
        "source_notes": canonical.get("retrieval_text"),
        "notes": "Candidate record exported from manual ingestion output; not runtime-usable until approved.",
        **quality_metadata(canonical),
    }
    return {key: value for key, value in record.items() if value is not None}


def map_bundle_to_local_datasets(bundle: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    metadata = bundle.get("bundle_metadata", {})
    records = bundle.get("records", {})
    canonical = records.get("canonical_incident", {})
    incident_id = str(canonical.get("incident_id") or metadata.get("incident_id") or "unknown")
    return {
        "context_reference": [],
        "canonical_incidents": [with_local_dataset_id(canonical, incident_id)] if canonical else [],
        "timeline_events": [
            with_local_dataset_id(record, str(record.get("event_id") or record.get("id") or f"{incident_id}_event_{index:03d}"))
            for index, record in enumerate(records.get("timeline_events", []), start=1)
        ],
        "raw_evidence_chunks": [
            with_local_dataset_id(record, str(record.get("chunk_id") or record.get("id") or f"{incident_id}_chunk_{index:03d}"))
            for index, record in enumerate(records.get("raw_evidence_chunks", []), start=1)
        ],
        "source_artifacts": [
            with_local_dataset_id(record, str(record.get("artifact_id") or record.get("id") or f"{incident_id}_artifact_{index:03d}"))
            for index, record in enumerate(records.get("source_artifact_references", []), start=1)
        ],
        "procedure_candidates": [
            mapped
            for index, record in enumerate(records.get("procedure_candidates", []), start=1)
            if (mapped := map_procedure_candidate(record, incident_id, index, metadata)) is not None
        ],
        "generated_procedure_candidates": [],
        "reusable_procedures": [],
        "workflow_candidates": map_workflow_candidates(records.get("workflow_candidate_steps", []), incident_id, metadata),
        "generated_workflow_candidates": [],
        "workflow_definitions": [],
        "workflow_procedure_links": [],
        "review_notes": [],
        "sme_review_queue": [],
        "merge_audit_log": [],
        "candidate_incident_records": [map_candidate_incident_record(canonical, incident_id, metadata)] if canonical else [],
    }


def stable_record_key(record: dict[str, Any], key_name: str) -> str:
    for field_name in ["local_dataset_id", key_name, "id", "record_id", "incident_id", "event_id", "chunk_id", "artifact_id", "procedure_id", "workflow_id", "review_item_id", "merge_id"]:
        if record.get(field_name):
            return str(record[field_name])
    return ""


def comparable_record(record: dict[str, Any]) -> dict[str, Any]:
    ignored_fields = {
        "local_dataset_id",
        "ingestion_version",
        "supersedes_local_dataset_id",
        "version_reason",
    }
    return {key: value for key, value in record.items() if key not in ignored_fields}


def next_version_key(base_key: str, existing_keys: set[str]) -> tuple[str, int]:
    version = 2
    while f"{base_key}_v{version}" in existing_keys:
        version += 1
    return f"{base_key}_v{version}", version


def merge_records(existing: list[dict[str, Any]], incoming: list[dict[str, Any]], key_name: str) -> list[dict[str, Any]]:
    merged = {stable_record_key(record, key_name): record for record in existing}
    for record in incoming:
        key = stable_record_key(record, key_name)
        if not key or key == "None":
            continue
        if key not in merged:
            merged[key] = record
            continue
        if comparable_record(merged[key]) == comparable_record(record):
            continue
        if any(
            comparable_record(existing_record) == comparable_record(record)
            and (
                existing_key.startswith(f"{key}_v")
                or existing_record.get("supersedes_local_dataset_id") == key
            )
            for existing_key, existing_record in merged.items()
        ):
            continue
        version_key, version = next_version_key(key, set(merged))
        versioned = deepcopy(record)
        versioned["local_dataset_id"] = version_key
        versioned["ingestion_version"] = version
        versioned["supersedes_local_dataset_id"] = key
        versioned["version_reason"] = "same stable ingestion key with changed content"
        merged[version_key] = versioned
    return list(merged.values())


def ensure_local_dataset_files(data_root: Path) -> dict[str, int]:
    counts = {}
    for name, relative_path in DATASET_PATHS.items():
        path = data_root / relative_path
        records = load_json(path)
        if not isinstance(records, list):
            records = []
        write_json(path, records)
        counts[name] = len(records)
    return counts


def export_bundle_to_local(bundle_path: Path, data_root: Path = Path("data")) -> dict[str, int]:
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    ensure_local_dataset_files(data_root)
    mapped = map_bundle_to_local_datasets(bundle)
    counts = {}
    for name, incoming in mapped.items():
        path = data_root / DATASET_PATHS[name]
        existing = load_json(path)
        records = merge_records(existing if isinstance(existing, list) else [], incoming, MERGE_KEYS[name])
        write_json(path, records)
        counts[name] = len(records)
    return counts
