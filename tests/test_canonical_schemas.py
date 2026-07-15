from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.schemas.canonical import (
    AgentProvenance,
    CanonicalEvidenceReference,
    CanonicalProcedure,
    CanonicalStep,
    CanonicalSubprocedure,
    RelationshipEdge,
    RelationshipTracking,
    Signal,
    StepRelationshipTracking,
    StepVisualEvidence,
    SubprocedureRelationshipTracking,
    VisualEvidence,
    WorkflowNode,
)


EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "backend" / "app" / "schemas" / "canonical" / "examples"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES_DIR / name).read_text(encoding="utf-8"))


def test_procedure_example_parses():
    payload = _load("procedure_example.json")

    procedure = CanonicalProcedure.model_validate(payload)

    assert procedure.procedure_id == "check_tipper_heartbeat_v1"
    assert procedure.procedure_type == "diagnostic_check"
    assert procedure.relationship_tracking.requires_role == "support"
    assert "tipper" in procedure.relationship_tracking.affects_components
    assert procedure.visual_evidence.screenshot_required is True
    assert procedure.provenance.validation_status == "needs_review"


def test_subprocedure_example_parses():
    payload = _load("subprocedure_example.json")

    sub = CanonicalSubprocedure.model_validate(payload)

    assert sub.subprocedure_id == "read_tipper_heartbeat_values_v1"
    assert sub.relationship_tracking.parent_procedure_id == "check_tipper_heartbeat_v1"
    assert "tipper_heartbeat_values_observed" in sub.relationship_tracking.produces_signals
    assert sub.visual_evidence.screenshot_required is True


def test_step_example_parses():
    payload = _load("step_example.json")

    step = CanonicalStep.model_validate(payload)

    assert step.step_id == "step_01"
    assert step.relationship_tracking.parent_subprocedure_id == "read_tipper_heartbeat_values_v1"
    assert step.visual_evidence.screenshot_required is True
    assert step.visual_evidence.visual_region_hint == "Heartbeat values table or panel"


def test_workflow_node_example_parses():
    payload = _load("workflow_node_example.json")

    node = WorkflowNode.model_validate(payload)

    assert node.node_id == "heartbeat_timeout_question"
    assert node.node_type == "question"
    assert node.procedure_ref == "check_tipper_heartbeat_v1"
    assert len(node.branches) == 2
    assert node.branches[0].condition_signal == "tipper_heartbeat_timeout"
    assert node.branches[0].next_node == "coordinate_estop"


def test_procedure_round_trip_equality():
    payload = _load("procedure_example.json")

    procedure = CanonicalProcedure.model_validate(payload)
    dumped = procedure.model_dump()
    reparsed = CanonicalProcedure.model_validate(dumped)

    assert reparsed.model_dump() == procedure.model_dump()


def test_procedure_missing_relationship_tracking_fails():
    payload = _load("procedure_example.json")
    payload.pop("relationship_tracking")

    with pytest.raises(ValidationError):
        CanonicalProcedure.model_validate(payload)


def test_procedure_missing_visual_evidence_fails():
    payload = _load("procedure_example.json")
    payload.pop("visual_evidence")

    with pytest.raises(ValidationError):
        CanonicalProcedure.model_validate(payload)


def test_procedure_missing_provenance_fails():
    payload = _load("procedure_example.json")
    payload.pop("provenance")

    with pytest.raises(ValidationError):
        CanonicalProcedure.model_validate(payload)


def test_subprocedure_missing_relationship_tracking_fails():
    payload = _load("subprocedure_example.json")
    payload.pop("relationship_tracking")

    with pytest.raises(ValidationError):
        CanonicalSubprocedure.model_validate(payload)


def test_step_missing_visual_evidence_fails():
    payload = _load("step_example.json")
    payload.pop("visual_evidence")

    with pytest.raises(ValidationError):
        CanonicalStep.model_validate(payload)


def test_workflow_node_missing_visual_evidence_fails():
    payload = _load("workflow_node_example.json")
    payload.pop("visual_evidence")

    with pytest.raises(ValidationError):
        WorkflowNode.model_validate(payload)


def test_workflow_node_missing_relationship_tracking_fails():
    payload = _load("workflow_node_example.json")
    payload.pop("relationship_tracking")

    with pytest.raises(ValidationError):
        WorkflowNode.model_validate(payload)


def test_relationship_tracking_defaults_are_empty():
    tracking = RelationshipTracking()

    assert tracking.parent_workflow_nodes == []
    assert tracking.produces_signals == []
    assert tracking.requires_role is None


def test_visual_evidence_defaults_are_empty():
    visual = VisualEvidence()

    assert visual.primary_screenshot_refs == []
    assert visual.required_screenshot_types == []
    assert visual.screenshot_required is False


def test_step_visual_evidence_defaults():
    visual = StepVisualEvidence()

    assert visual.screenshot_refs == []
    assert visual.screenshot_required is False
    assert visual.visual_region_hint is None


def test_canonical_procedure_minimal_construction():
    procedure = CanonicalProcedure(
        procedure_id="minimal_v1",
        canonical_title="Minimal",
        procedure_type="diagnostic_check",
        relationship_tracking=RelationshipTracking(),
        visual_evidence=VisualEvidence(),
        provenance=AgentProvenance(prompt_id="procedure_normalization"),
    )

    assert procedure.procedure_id == "minimal_v1"
    assert procedure.relationship_tracking.affects_components == []
    assert procedure.visual_evidence.screenshot_required is False
    assert procedure.provenance.created_by_agent == "workflow_procedure_architecture_agent"
    assert procedure.provenance.validation_status == "needs_review"


def test_relationship_edge_requires_provenance_and_supports_signal_evidence():
    edge = RelationshipEdge(
        edge_id="edge_check_tipper_heartbeat_v1_PRODUCES_SIGNAL_tipper_heartbeat_timeout_or_zero",
        source_type="procedure",
        source_id="check_tipper_heartbeat_v1",
        relation="PRODUCES_SIGNAL",
        target_type="signal",
        target_id="tipper_heartbeat_timeout_or_zero",
        evidence_refs=[
            CanonicalEvidenceReference(incident_id="229374", evidence_id="case_229374_docx_artifact_23")
        ],
        source_artifacts=["case_229374_docx_artifact_23"],
        provenance=AgentProvenance(prompt_id="relationship_mapping"),
    )

    assert edge.relation == "PRODUCES_SIGNAL"
    assert edge.evidence_refs[0].incident_id == "229374"
    assert edge.provenance.validation_status == "needs_review"


def test_signal_requires_provenance():
    with pytest.raises(ValidationError):
        Signal.model_validate(
            {
                "signal_id": "tipper_heartbeat_timeout_or_zero",
                "name": "Tipper heartbeat timeout or zero",
            }
        )

    signal = Signal(
        signal_id="tipper_heartbeat_timeout_or_zero",
        name="Tipper heartbeat timeout or zero",
        signal_type="diagnostic",
        produced_by=["check_tipper_heartbeat_v1"],
        provenance=AgentProvenance(prompt_id="relationship_mapping"),
    )

    assert signal.signal_type == "diagnostic"
