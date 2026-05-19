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
    "escalation_summaries": ContainerDefinition("escalation_summaries", "/incident_id"),
    "knowledge_relationships": ContainerDefinition("knowledge_relationships", "/from_id"),
    "ingestion_runs": ContainerDefinition("ingestion_runs", "/run_type"),
}
