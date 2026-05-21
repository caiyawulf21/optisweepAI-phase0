from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from backend.app.models import (
    EscalationSummary,
    IncidentRecord,
    IngestionRun,
    KnowledgeRelationship,
    RawEvidenceChunk,
    SourceArtifact,
    TimelineEvent,
    WorkflowCandidate,
)
from backend.app.models.base import model_to_dict


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()


def short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def as_string_list(value: Any) -> list[str]:
    values = []
    for item in as_list(value):
        if isinstance(item, str):
            values.append(item)
        elif isinstance(item, dict):
            values.append(json.dumps(item, sort_keys=True, ensure_ascii=False))
        else:
            values.append(str(item))
    return values


def record_source_refs(record: dict[str, Any]) -> list[str]:
    refs = []
    for field_name in ["source_ref", "source_file"]:
        if record.get(field_name):
            refs.append(str(record[field_name]))
    refs.extend(str(value) for value in as_list(record.get("source_region_refs")))
    refs.extend(str(value) for value in as_list(record.get("source_artifact_ids")))
    return list(dict.fromkeys(refs))


def record_metadata(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_page": record.get("source_page"),
        "source_section": record.get("source_section"),
        "confidence": record.get("confidence"),
        "missing_fields": record.get("missing_fields", []),
        "extraction_notes": record.get("extraction_notes", []),
        "linked_relationships": record.get("linked_relationships", []),
    }


def document_id(prefix: str, preferred: str | None, fallback: str) -> str:
    value = preferred or fallback
    return value if value.startswith(prefix) else f"{prefix}{clean_id(value)}"


def map_incident(bundle: dict[str, Any]) -> dict[str, Any]:
    metadata = bundle.get("bundle_metadata", {})
    record = bundle["records"]["canonical_incident"]
    incident_id = str(record.get("incident_id") or metadata.get("incident_id"))
    doc = IncidentRecord(
        id=document_id("inc_", incident_id, incident_id),
        incident_id=incident_id,
        source_case_id=str(record.get("source_case_id") or incident_id),
        issue_category=record.get("issue_category") or metadata.get("category"),
        site=record.get("site"),
        customer=record.get("customer"),
        priority=record.get("priority"),
        failure_signature=as_list(record.get("failure_signature")),
        symptom_summary=record.get("symptom_summary") or record.get("title"),
        component=as_list(record.get("component")),
        observed_failure_signals=as_list(record.get("observed_failure_signals")),
        diagnostic_signals=as_list(record.get("diagnostic_signals")),
        action_signals=as_list(record.get("action_signals")),
        recovery_validation_signals=as_list(record.get("recovery_validation_signals")),
        escalation_signals=as_list(record.get("escalation_signals")),
        candidate_inferred_causes=as_list(record.get("candidate_inferred_causes")),
        validated_root_cause=bool(record.get("validated_root_cause", False)),
        resolution_summary=record.get("resolution_summary"),
        escalated=record.get("escalated"),
        escalation_domains=as_list(record.get("escalation_domains")),
        workflow_candidate=record.get("workflow_candidate"),
        resolution_status=record.get("resolution_status"),
        retrieval_text=record.get("retrieval_text") or record.get("symptom_summary") or record.get("title"),
        source_refs=record_source_refs(record),
        source_authority=record.get("source_authority"),
        validation_status=record.get("validation_status") or metadata.get("validation_status"),
        requires_manual_review=record.get("requires_manual_review", metadata.get("requires_manual_review")),
        metadata=record_metadata(record),
    )
    return model_to_dict(doc)


def map_timeline_events(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = bundle.get("bundle_metadata", {})
    incident_id = str(metadata.get("incident_id") or bundle["records"]["canonical_incident"].get("incident_id"))
    docs = []
    for index, record in enumerate(bundle["records"].get("timeline_events", []), start=1):
        event_id = record.get("event_id") or f"evt_{incident_id}_{index:03d}"
        doc = TimelineEvent(
            id=document_id("evt_", event_id, f"{incident_id}_{index:03d}"),
            incident_id=incident_id,
            event_id=event_id,
            event_order=int(record.get("event_order") or index),
            event_type=record.get("event_type") or "operational_event",
            actor_role=record.get("actor_role"),
            event_summary=record.get("event_summary") or record.get("summary") or record.get("retrieval_text") or "Candidate timeline event",
            event_occurred_at=record.get("event_occurred_at"),
            event_documented_at=record.get("event_documented_at"),
            observed_failure_signals=as_list(record.get("observed_failure_signals")),
            diagnostic_signals=as_list(record.get("diagnostic_signals")),
            action_signals=as_list(record.get("action_signals")),
            recovery_validation_signals=as_list(record.get("recovery_validation_signals")),
            escalation_signals=as_list(record.get("escalation_signals")),
            action_taken=record.get("action_taken"),
            outcome=record.get("outcome"),
            next_action=record.get("next_action"),
            source_ref=record.get("source_ref"),
            source_region_refs=as_list(record.get("source_region_refs")),
            source_artifact_ids=as_list(record.get("source_artifact_ids")),
            retrieval_text=record.get("retrieval_text") or record.get("event_summary"),
            source_refs=record_source_refs(record),
            validation_status=record.get("validation_status"),
            requires_manual_review=record.get("requires_manual_review"),
            metadata=record_metadata(record),
        )
        docs.append(model_to_dict(doc))
    return docs


def map_evidence_chunks(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = bundle.get("bundle_metadata", {})
    incident_id = str(metadata.get("incident_id") or bundle["records"]["canonical_incident"].get("incident_id"))
    docs = []
    for index, record in enumerate(bundle["records"].get("raw_evidence_chunks", []), start=1):
        chunk_id = record.get("chunk_id") or f"evidence_{incident_id}_{index:03d}"
        text = record.get("chunk_text") or record.get("evidence_text") or record.get("retrieval_text") or ""
        doc = RawEvidenceChunk(
            id=document_id("evidence_", chunk_id, f"{incident_id}_{index:03d}"),
            incident_id=incident_id,
            source_case_id=str(record.get("source_case_id") or incident_id),
            chunk_id=chunk_id,
            source_type=record.get("source_type"),
            raw_source_type=record.get("raw_source_type"),
            evidence_type=record.get("evidence_type"),
            source_ref=record.get("source_ref"),
            chunk_order=record.get("chunk_order") or index,
            chunk_text=text,
            observed_failure_signals=as_list(record.get("observed_failure_signals")),
            diagnostic_signals=as_list(record.get("diagnostic_signals")),
            action_signals=as_list(record.get("action_signals")),
            recovery_validation_signals=as_list(record.get("recovery_validation_signals")),
            escalation_signals=as_list(record.get("escalation_signals")),
            linked_records=as_list(record.get("linked_records")),
            source_region_refs=as_list(record.get("source_region_refs")),
            source_artifact_ids=as_list(record.get("source_artifact_ids")),
            retrieval_text=record.get("retrieval_text") or text,
            source_refs=record_source_refs(record),
            validation_status=record.get("validation_status"),
            requires_manual_review=record.get("requires_manual_review"),
            metadata=record_metadata(record),
        )
        docs.append(model_to_dict(doc))
    return docs


def map_artifacts(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = bundle.get("bundle_metadata", {})
    incident_id = str(metadata.get("incident_id") or bundle["records"]["canonical_incident"].get("incident_id"))
    docs = []
    for index, record in enumerate(bundle["records"].get("source_artifact_references", []), start=1):
        artifact_id = record.get("artifact_id") or f"artifact_{incident_id}_{index:03d}"
        file_path = record.get("artifact_path") or record.get("file_path") or record.get("source_artifact_path")
        file_name = record.get("file_name") or (str(file_path).replace("\\", "/").split("/")[-1] if file_path else artifact_id)
        doc = SourceArtifact(
            id=document_id("artifact_", artifact_id, f"{incident_id}_{index:03d}"),
            incident_id=incident_id,
            artifact_id=artifact_id,
            artifact_type=record.get("artifact_type") or record.get("raw_source_type") or "source_artifact",
            artifact_role=record.get("artifact_role"),
            artifact_role_status=record.get("artifact_role_status"),
            source_system=record.get("source_system"),
            file_name=file_name,
            file_path=file_path,
            blob_container=record.get("blob_container"),
            blob_path=record.get("blob_path"),
            description=record.get("description") or record.get("visual_evidence_summary"),
            linked_record_ids=as_list(record.get("linked_record_ids")),
            retrieval_text=record.get("retrieval_text") or record.get("description") or record.get("visual_evidence_summary"),
            source_refs=record_source_refs(record),
            validation_status=record.get("validation_status"),
            requires_manual_review=record.get("requires_manual_review"),
            metadata=record_metadata(record),
        )
        docs.append(model_to_dict(doc))
    return docs


def procedure_candidate_refs(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    refs = []
    for index, record in enumerate(bundle["records"].get("procedure_candidates", []), start=1):
        procedure_id = str(record.get("procedure_id") or record.get("procedure_name") or record.get("title") or f"procedure_candidate_{index:03d}")
        refs.append(
            {
                "id": procedure_id,
                "evidence_refs": as_string_list(record.get("evidence_refs") or record.get("supporting_evidence_chunks")),
            }
        )
    return refs


def candidate_type(record: dict[str, Any]) -> str:
    if record.get("target_workflow_id") or record.get("existing_workflow_id"):
        return "refinement"
    return record.get("candidate_type") or "proposed"


def map_workflow_candidates(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = bundle.get("bundle_metadata", {})
    incident_id = str(metadata.get("incident_id") or bundle["records"]["canonical_incident"].get("incident_id"))
    docs = []
    for index, record in enumerate(bundle["records"].get("workflow_candidate_steps", []), start=1):
        workflow_step_id = record.get("workflow_step_id") or f"workflow_candidate_{incident_id}_{index:03d}"
        candidate_name = record.get("candidate_workflow_name") or workflow_step_id
        entry_points = as_list(record.get("entry_conditions")) or as_list(record.get("observed_failure_signals"))
        diagnoses = as_list(record.get("diagnostic_signals")) or as_list(record.get("required_signals"))
        target_workflow_id = record.get("target_workflow_id") or record.get("existing_workflow_id")
        doc = WorkflowCandidate(
            id=document_id("wfc_", record.get("workflow_candidate_id") or workflow_step_id, f"{incident_id}_{index:03d}"),
            candidate_type=candidate_type(record),
            source_incident_ids=as_list(record.get("source_incident_ids")) or [incident_id],
            target_workflow_id=target_workflow_id,
            candidate_workflow_name=candidate_name,
            proposed_change=record.get("proposed_change") or record.get("candidate_step"),
            reason=record.get("reason") or record.get("why_asked") or record.get("retrieval_text"),
            issue_category=record.get("issue_category") or metadata.get("category"),
            workflow_step_id=workflow_step_id,
            step_type=record.get("step_type"),
            node_type=record.get("node_type"),
            decision_question=record.get("decision_question") or record.get("question"),
            question=record.get("question"),
            why_asked=record.get("why_asked"),
            candidate_step=record.get("candidate_step"),
            entry_points=entry_points,
            initial_symptoms=as_list(record.get("initial_symptoms")) or entry_points,
            diagnoses=diagnoses,
            entry_conditions=entry_points,
            required_signals=as_list(record.get("required_signals")),
            negative_signals=as_list(record.get("negative_signals")),
            exclusion_conditions=as_list(record.get("negative_signals")),
            role_constraints=as_list(record.get("role_constraints")) or as_list(record.get("roles_allowed")),
            next_procedure_refs=as_list(record.get("next_procedure_refs")) or as_list(record.get("procedure_refs")),
            procedure_refs=as_list(record.get("next_procedure_refs")) or as_list(record.get("procedure_refs")),
            success_routes=as_string_list(record.get("success_routes")),
            failure_routes=as_string_list(record.get("failure_routes")),
            escalation_conditions=as_string_list(record.get("escalation_conditions")),
            evidence_refs=as_string_list(record.get("evidence_refs")),
            image_refs=as_string_list(record.get("image_refs")),
            region_ids=as_string_list(record.get("region_ids")),
            status=record.get("relationship_status") if record.get("relationship_status") in {"candidate", "validated", "rejected"} else "candidate",
            review_status=record.get("review_status") if record.get("review_status") in {"needs_review", "in_review", "accepted", "rejected", "promoted"} else "needs_review",
            retrieval_text=record.get("retrieval_text") or record.get("decision_question") or record.get("candidate_step"),
            source_refs=record_source_refs(record),
            validation_status=record.get("validation_status"),
            requires_manual_review=record.get("requires_manual_review", True),
            metadata={**record_metadata(record), "source_dataset_role": "workflow_candidate"},
        )
        docs.append(model_to_dict(doc))
    return docs


def map_escalation(bundle: dict[str, Any]) -> dict[str, Any]:
    metadata = bundle.get("bundle_metadata", {})
    record = bundle["records"]["escalation_summary_template"]
    incident_id = str(record.get("incident_id") or metadata.get("incident_id"))
    doc = EscalationSummary(
        id=document_id("esc_", record.get("escalation_summary_id"), f"{incident_id}_summary"),
        incident_id=incident_id,
        template=bool(record.get("template", True)),
        issue_category=record.get("issue_category") or metadata.get("category"),
        escalation_domain=record.get("escalation_domain"),
        priority=record.get("priority"),
        trigger_reason=record.get("trigger_reason"),
        symptoms=as_list(record.get("symptoms")),
        steps_attempted=as_list(record.get("steps_attempted")),
        known_facts=as_list(record.get("known_facts")),
        actions_taken=as_list(record.get("actions_taken")),
        evidence_available=as_list(record.get("evidence_available")),
        open_questions=as_list(record.get("open_questions")),
        follow_up_owners=as_list(record.get("follow_up_owners")),
        evidence_refs=as_list(record.get("evidence_refs")),
        recommended_owner=record.get("recommended_owner"),
        handoff_summary=record.get("handoff_summary") or record.get("retrieval_text"),
        retrieval_text=record.get("retrieval_text") or record.get("handoff_summary"),
        source_refs=record_source_refs(record),
        validation_status=record.get("validation_status"),
        requires_manual_review=record.get("requires_manual_review"),
        metadata=record_metadata(record),
    )
    return model_to_dict(doc)


def relationship_doc(relationship_type: str, from_id: str, from_type: str, to_id: str, to_type: str, evidence_refs: list[str] | None = None, confidence: float | None = None, notes: str | None = None, status: str = "candidate") -> dict[str, Any]:
    raw_id = f"{relationship_type}:{from_id}:{to_id}:{','.join(evidence_refs or [])}"
    doc = KnowledgeRelationship(
        id=f"rel_{short_hash(raw_id)}",
        relationship_type=relationship_type,
        from_id=from_id,
        from_type=from_type,
        to_id=to_id,
        to_type=to_type,
        confidence=confidence,
        status=status if status in {"candidate", "validated", "rejected"} else "candidate",
        evidence_refs=evidence_refs or [],
        notes=notes,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    return model_to_dict(doc)


def map_relationships(documents: dict[str, Any], bundle: dict[str, Any]) -> list[dict[str, Any]]:
    incident_id = documents["incident_records"][0]["id"]
    relationships = []
    for procedure in procedure_candidate_refs(bundle):
        relationships.append(
            relationship_doc(
                "INCIDENT_HAS_PROCEDURE_CANDIDATE",
                incident_id,
                "incident",
                procedure["id"],
                "procedure_candidate",
                procedure.get("evidence_refs", []),
                None,
                "Incident evidence includes a local procedure candidate for SME review.",
            )
        )
    for candidate in documents["workflow_candidates"]:
        target_workflow_id = candidate.get("target_workflow_id")
        if target_workflow_id:
            relationships.append(relationship_doc("WORKFLOW_CANDIDATE_REFINES_WORKFLOW", candidate["id"], "workflow_candidate", target_workflow_id, "workflow_definition", candidate.get("evidence_refs", [])))
        else:
            relationships.append(relationship_doc("INCIDENT_HAS_WORKFLOW_CANDIDATE", incident_id, "incident", candidate["id"], "workflow_candidate", candidate.get("evidence_refs", []), None, "Incident evidence includes a workflow candidate for SME review."))
        for procedure_ref in candidate.get("procedure_refs", []):
            relationships.append(relationship_doc("WORKFLOW_CANDIDATE_REFERENCES_PROCEDURE_CANDIDATE", candidate["id"], "workflow_candidate", procedure_ref, "procedure_candidate", candidate.get("evidence_refs", [])))
    seen = set()
    unique = []
    for relationship in relationships:
        if relationship["id"] not in seen:
            unique.append(relationship)
            seen.add(relationship["id"])
    return unique


def map_phase0_bundle(bundle: dict[str, Any], run_trace: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
    documents = {
        "incident_records": [map_incident(bundle)],
        "timeline_events": map_timeline_events(bundle),
        "raw_evidence_chunks": map_evidence_chunks(bundle),
        "source_artifacts": map_artifacts(bundle),
        "workflow_candidates": map_workflow_candidates(bundle),
        "escalation_summaries": [map_escalation(bundle)],
    }
    documents["knowledge_relationships"] = map_relationships(documents, bundle)
    documents["ingestion_runs"] = [map_ingestion_run(bundle, documents, run_trace)]
    return documents


def map_ingestion_run(bundle: dict[str, Any], documents: dict[str, list[dict[str, Any]]], run_trace: dict[str, Any] | None) -> dict[str, Any]:
    metadata = bundle.get("bundle_metadata", {})
    incident_id = str(metadata.get("incident_id", "unknown"))
    created_at = metadata.get("created_at") or utc_now()
    doc = IngestionRun(
        id=f"ingest_run_{clean_id(incident_id)}_{short_hash(created_at)}",
        run_type="manual_phase0",
        input_files=as_list(metadata.get("source_files")),
        records_created={name: len(records) for name, records in documents.items()},
        status="completed",
        errors=[],
        started_at=run_trace.get("nodes", [{}])[0].get("started_at") if run_trace else None,
        completed_at=utc_now(),
        source_refs=as_list(metadata.get("source_files")),
        validation_status=metadata.get("validation_status"),
        requires_manual_review=metadata.get("requires_manual_review"),
        metadata={"agent_trace": run_trace or {}, "bundle_metadata": metadata},
    )
    return model_to_dict(doc)


def document_counts(documents: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    return {name: len(records) for name, records in documents.items()}
