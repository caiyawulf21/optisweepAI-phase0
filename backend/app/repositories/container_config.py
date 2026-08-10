from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContainerDefinition:
    name: str
    partition_key: str


CONTAINERS: dict[str, ContainerDefinition] = {
    "context_reference": ContainerDefinition("context_reference", "/context_type"),
    "incident_records": ContainerDefinition("incident_records", "/issue_category"),
    "timeline_events": ContainerDefinition("timeline_events", "/incident_id"),
    "workflow_definitions": ContainerDefinition("workflow_definitions", "/issue_category"),
    "workflow_candidates": ContainerDefinition("workflow_candidates", "/candidate_type"),
    "procedure_dictionary": ContainerDefinition("procedure_dictionary", "/procedure_type"),
    "raw_evidence_chunks": ContainerDefinition("raw_evidence_chunks", "/incident_id"),
    "source_artifacts": ContainerDefinition("source_artifacts", "/incident_id"),
    "canonical_images": ContainerDefinition("canonical_images", "/category"),
    "publish_canonical_images": ContainerDefinition(
        "publish_canonical_images", "/publish_version_id"
    ),
    "escalation_summaries": ContainerDefinition("escalation_summaries", "/incident_id"),
    "knowledge_relationships": ContainerDefinition("knowledge_relationships", "/from_id"),
    "canonical_procedure_dictionary": ContainerDefinition(
        "canonical_procedure_dictionary", "/procedure_type"
    ),
    "canonical_workflow_definitions": ContainerDefinition(
        "canonical_workflow_definitions", "/issue_category"
    ),
    "retrieval_vectors": ContainerDefinition("retrieval_vectors", "/record_type"),
    "workflow_sessions": ContainerDefinition("workflow_sessions", "/session_id"),
    "interaction_logs": ContainerDefinition("interaction_logs", "/session_id"),
}


PHASE1_RUNTIME_CONTAINER_NAMES: tuple[str, ...] = (
    "context_reference",
    "incident_records",
    "timeline_events",
    "workflow_definitions",
    "procedure_dictionary",
    "raw_evidence_chunks",
    "source_artifacts",
    "canonical_images",
    "escalation_summaries",
    "workflow_sessions",
    "interaction_logs",
)
