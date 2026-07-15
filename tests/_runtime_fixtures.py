"""Shared fixture builders for dynamic procedure-guidance tests.

These helpers build minimal in-memory ``CanonicalProcedure`` records the
loader / selector / path assembler tests can ingest without touching the
on-disk dictionary. Keeping them in a single module avoids drift between
the per-feature unit tests and the end-to-end acceptance tests.
"""
from __future__ import annotations

from typing import Iterable

from backend.app.schemas.canonical import (
    AgentProvenance,
    CanonicalEvidenceReference,
    CanonicalProcedure,
    CanonicalStep,
    CanonicalSubprocedure,
    GraphReadiness,
    RelationshipTracking,
    StepRelationshipTracking,
    StepVisualEvidence,
    SubprocedureRelationshipTracking,
    VisualEvidence,
)


def make_provenance(
    *,
    validation_status: str = "approved",
    prompt_id: str = "test_prompt",
) -> AgentProvenance:
    return AgentProvenance(
        prompt_id=prompt_id,
        validation_status=validation_status,  # type: ignore[arg-type]
    )


def make_visual_evidence() -> VisualEvidence:
    return VisualEvidence(
        primary_screenshot_refs=[],
        supporting_screenshot_refs=[],
        required_screenshot_types=[],
        visual_region_hints=[],
        screenshot_required=False,
    )


def make_step_visual_evidence() -> StepVisualEvidence:
    return StepVisualEvidence(
        screenshot_required=False,
        screenshot_refs=[],
        visual_region_hint=None,
    )


def make_step(
    *,
    step_id: str,
    instruction: str = "Run the diagnostic",
    requires_signals: Iterable[str] = (),
    produces_signals: Iterable[str] = (),
    role_required: str | None = None,
    support_safe: bool | None = None,
    evidence_refs: Iterable[CanonicalEvidenceReference] = (),
) -> CanonicalStep:
    return CanonicalStep(
        step_id=step_id,
        instruction=instruction,
        relationship_tracking=StepRelationshipTracking(
            requires_signals=list(requires_signals),
            produces_signals=list(produces_signals),
        ),
        visual_evidence=make_step_visual_evidence(),
        evidence_refs=list(evidence_refs),
        role_required=role_required,
        support_safe=support_safe,
    )


def make_subprocedure(
    *,
    subprocedure_id: str,
    parent_procedure_id: str,
    canonical_title: str | None = None,
    requires_role: str | None = None,
    steps: Iterable[CanonicalStep] = (),
    evidence_refs: Iterable[CanonicalEvidenceReference] = (),
    source_artifacts: Iterable[str] = (),
) -> CanonicalSubprocedure:
    return CanonicalSubprocedure(
        subprocedure_id=subprocedure_id,
        canonical_title=canonical_title or subprocedure_id,
        parent_procedure_id=parent_procedure_id,
        relationship_tracking=SubprocedureRelationshipTracking(
            parent_procedure_id=parent_procedure_id,
            requires_role=requires_role,
        ),
        visual_evidence=make_visual_evidence(),
        steps=list(steps),
        evidence_refs=list(evidence_refs),
        source_artifacts=list(source_artifacts),
    )


def make_procedure(
    *,
    procedure_id: str,
    canonical_title: str | None = None,
    requires_role: str | None = "support",
    requires_signals: Iterable[str] = (),
    produces_signals: Iterable[str] = (),
    confirms_signals: Iterable[str] = (),
    rules_out_signals: Iterable[str] = (),
    affects_components: Iterable[str] = (),
    validated_by_incidents: Iterable[str] = (),
    parent_workflow_nodes: Iterable[str] = (),
    evidence_refs: Iterable[CanonicalEvidenceReference] = (),
    source_artifacts: Iterable[str] = (),
    subprocedures: Iterable[CanonicalSubprocedure] = (),
    validation_status: str = "approved",
    procedure_type: str = "diagnostic_check",
) -> CanonicalProcedure:
    return CanonicalProcedure(
        procedure_id=procedure_id,
        canonical_title=canonical_title or procedure_id,
        procedure_type=procedure_type,  # type: ignore[arg-type]
        relationship_tracking=RelationshipTracking(
            requires_signals=list(requires_signals),
            produces_signals=list(produces_signals),
            confirms_signals=list(confirms_signals),
            rules_out_signals=list(rules_out_signals),
            affects_components=list(affects_components),
            validated_by_incidents=list(validated_by_incidents),
            parent_workflow_nodes=list(parent_workflow_nodes),
            requires_role=requires_role,
        ),
        visual_evidence=make_visual_evidence(),
        evidence_refs=list(evidence_refs),
        source_artifacts=list(source_artifacts),
        subprocedures=list(subprocedures),
        provenance=make_provenance(validation_status=validation_status),
        graph_readiness=GraphReadiness(),
    )


def make_evidence_ref(
    *,
    incident_id: str,
    evidence_id: str,
    source_artifact_id: str | None = None,
    excerpt: str | None = None,
) -> CanonicalEvidenceReference:
    return CanonicalEvidenceReference(
        incident_id=incident_id,
        evidence_id=evidence_id,
        source_artifact_id=source_artifact_id,
        excerpt=excerpt,
    )


__all__ = [
    "make_evidence_ref",
    "make_procedure",
    "make_provenance",
    "make_step",
    "make_step_visual_evidence",
    "make_subprocedure",
    "make_visual_evidence",
]
