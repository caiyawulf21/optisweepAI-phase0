from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContainerDefinition:
    name: str
    partition_key: str
    deprecated: bool = False
    replacement: str | None = None


CONTAINERS: dict[str, ContainerDefinition] = {
    "context_reference": ContainerDefinition(
        "context_reference", "/context_type", deprecated=True
    ),
    "incident_records": ContainerDefinition(
        "incident_records", "/issue_category", deprecated=True
    ),
    "timeline_events": ContainerDefinition(
        "timeline_events", "/incident_id", deprecated=True
    ),
    "workflow_definitions": ContainerDefinition(
        "workflow_definitions",
        "/issue_category",
        deprecated=True,
        replacement="playbooks_prompt_a / playbooks_prompt_b",
    ),
    "workflow_candidates": ContainerDefinition(
        "workflow_candidates", "/candidate_type", deprecated=True
    ),
    "procedure_dictionary": ContainerDefinition(
        "procedure_dictionary",
        "/procedure_type",
        deprecated=True,
        replacement="runbooks",
    ),
    "raw_evidence_chunks": ContainerDefinition(
        "raw_evidence_chunks", "/incident_id", deprecated=True
    ),
    "source_artifacts": ContainerDefinition("source_artifacts", "/incident_id"),
    "canonical_images": ContainerDefinition(
        "canonical_images",
        "/category",
        deprecated=True,
        replacement="publish_canonical_images",
    ),
    "publish_canonical_images": ContainerDefinition(
        "publish_canonical_images", "/publish_version_id"
    ),
    "escalation_summaries": ContainerDefinition(
        "escalation_summaries", "/incident_id", deprecated=True
    ),
    "knowledge_relationships": ContainerDefinition(
        "knowledge_relationships",
        "/from_id",
        deprecated=True,
        replacement="relationship_links",
    ),
    "canonical_procedure_dictionary": ContainerDefinition(
        "canonical_procedure_dictionary",
        "/procedure_type",
        deprecated=True,
        replacement="runbooks",
    ),
    "canonical_workflow_definitions": ContainerDefinition(
        "canonical_workflow_definitions",
        "/issue_category",
        deprecated=True,
        replacement="playbooks_prompt_a / playbooks_prompt_b",
    ),
    "retrieval_vectors": ContainerDefinition(
        "retrieval_vectors", "/record_type", deprecated=True
    ),
    "workflow_sessions": ContainerDefinition("workflow_sessions", "/session_id"),
    "interaction_logs": ContainerDefinition("interaction_logs", "/session_id"),
    "feedback_events": ContainerDefinition("feedback_events", "/session_id"),
}


DEPRECATED_CONTAINER_NAMES: tuple[str, ...] = tuple(
    sorted(name for name, item in CONTAINERS.items() if item.deprecated)
)


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
    "feedback_events",
)
