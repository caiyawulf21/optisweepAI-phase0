"""Phase 6 acceptance criteria as a reusable, side-effect-free evaluator.

The Phase 6 human approval checklist is documented prose in README.md and was
originally encoded as pytest assertions in
``tests/test_canonical_workflow_acceptance.py``. The Phase 10 promotion gate
needs the same checks, but as a structured pass/fail result it can include in
its audit record. This module is the single source of truth for the criteria;
both the test file and the promotion CLI import :func:`evaluate` from here.

Adding or changing a criterion: update :data:`CRITERION_IDS`, the matching
``_criterion_*`` function, and the dispatch in :func:`evaluate`. Update
``tests/test_canonical_workflow_acceptance.py`` only if the user-visible
behavior of the test changes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from backend.app.schemas.canonical import CanonicalProcedure, CanonicalWorkflow
from backend.app.tools.workflow_graph_builder import (
    DEFAULT_COMPOSITION_MAPPING,
    CompositionMapping,
    load_composition_mapping,
)


PROCEDURE_BACKED_NODE_TYPES = frozenset({"diagnostic_check", "action", "validation"})
NON_BRANCHING_NODE_TYPES = frozenset({"terminal", "escalation"})

CAT_TAXONOMY_PATTERN = re.compile(r"\bCAT[-_ ]?\d+\b", re.IGNORECASE)


CRITERION_IDS: tuple[str, ...] = (
    "workflow_marked_approved_for_workflow",
    "workflow_ready_flag_set",
    "every_node_has_relationship_tracking",
    "every_node_has_visual_evidence_block",
    "every_non_terminal_node_has_non_empty_question",
    "every_non_terminal_node_has_at_least_one_branch",
    "procedure_backed_nodes_resolve_to_canonical_procedure",
    "every_edge_condition_signal_is_in_required_signals",
    "procedure_refs_are_subset_of_composition_entry",
    "referenced_procedures_have_relationship_and_visual_evidence",
    "screenshot_required_procedures_have_screenshot_refs_or_types",
    "no_developer_taxonomy_codes_in_user_facing_fields",
)


@dataclass(frozen=True)
class CriterionFailure:
    criterion_id: str
    subject_type: str
    subject_id: str
    message: str


@dataclass(frozen=True)
class Phase6AcceptanceResult:
    workflow_id: str
    is_accepted: bool
    failures: tuple[CriterionFailure, ...]
    passed_criteria: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "workflow_id": self.workflow_id,
            "is_accepted": self.is_accepted,
            "failures": [
                {
                    "criterion_id": f.criterion_id,
                    "subject_type": f.subject_type,
                    "subject_id": f.subject_id,
                    "message": f.message,
                }
                for f in self.failures
            ],
            "passed_criteria": list(self.passed_criteria),
        }


def evaluate(
    workflow: CanonicalWorkflow,
    procedures: dict[str, CanonicalProcedure],
    composition_mapping: CompositionMapping | None = None,
    *,
    composition_mapping_path: Path = DEFAULT_COMPOSITION_MAPPING,
) -> Phase6AcceptanceResult:
    """Evaluate every Phase 6 acceptance criterion against ``workflow``.

    The function is referentially transparent: it returns a result and never
    mutates inputs or touches disk except optionally to load the composition
    mapping (which is cached by the caller via the ``composition_mapping``
    argument).
    """
    mapping = composition_mapping or load_composition_mapping(composition_mapping_path)
    failures: list[CriterionFailure] = []
    fired: set[str] = set()

    failures.extend(_criterion_workflow_marked_approved(workflow, fired))
    failures.extend(_criterion_workflow_ready(workflow, fired))
    failures.extend(_criterion_every_node_has_relationship_tracking(workflow, fired))
    failures.extend(_criterion_every_node_has_visual_evidence_block(workflow, fired))
    failures.extend(_criterion_every_non_terminal_node_has_question(workflow, fired))
    failures.extend(_criterion_every_non_terminal_node_has_branch(workflow, fired))
    failures.extend(
        _criterion_procedure_backed_nodes_resolve(workflow, procedures, fired)
    )
    failures.extend(_criterion_edge_condition_signals(workflow, fired))
    failures.extend(_criterion_procedure_refs_subset(workflow, mapping, fired))
    failures.extend(
        _criterion_referenced_procedures_have_tracking(workflow, procedures, fired)
    )
    failures.extend(
        _criterion_screenshot_required_procedures(workflow, procedures, fired)
    )
    failures.extend(_criterion_no_developer_taxonomy(workflow, fired))

    passed = tuple(c for c in CRITERION_IDS if c not in fired)
    return Phase6AcceptanceResult(
        workflow_id=workflow.workflow_id,
        is_accepted=not failures,
        failures=tuple(failures),
        passed_criteria=passed,
    )


def _criterion_workflow_marked_approved(
    workflow: CanonicalWorkflow, fired: set[str]
) -> Iterable[CriterionFailure]:
    if workflow.provenance.validation_status != "approved_for_workflow":
        fired.add("workflow_marked_approved_for_workflow")
        return [
            CriterionFailure(
                criterion_id="workflow_marked_approved_for_workflow",
                subject_type="workflow",
                subject_id=workflow.workflow_id,
                message=(
                    "Workflow must carry provenance.validation_status == "
                    "'approved_for_workflow' to satisfy Phase 6."
                ),
            )
        ]
    return []


def _criterion_workflow_ready(
    workflow: CanonicalWorkflow, fired: set[str]
) -> Iterable[CriterionFailure]:
    if not workflow.graph_readiness.workflow_ready:
        fired.add("workflow_ready_flag_set")
        return [
            CriterionFailure(
                criterion_id="workflow_ready_flag_set",
                subject_type="workflow",
                subject_id=workflow.workflow_id,
                message="graph_readiness.workflow_ready must be True.",
            )
        ]
    return []


def _criterion_every_node_has_relationship_tracking(
    workflow: CanonicalWorkflow, fired: set[str]
) -> Iterable[CriterionFailure]:
    out: list[CriterionFailure] = []
    for node in workflow.nodes:
        if node.relationship_tracking is None:
            fired.add("every_node_has_relationship_tracking")
            out.append(
                CriterionFailure(
                    criterion_id="every_node_has_relationship_tracking",
                    subject_type="workflow_node",
                    subject_id=f"{workflow.workflow_id}#{node.node_id}",
                    message="Node has no relationship_tracking block.",
                )
            )
    return out


def _criterion_every_node_has_visual_evidence_block(
    workflow: CanonicalWorkflow, fired: set[str]
) -> Iterable[CriterionFailure]:
    out: list[CriterionFailure] = []
    for node in workflow.nodes:
        if node.visual_evidence is None:
            fired.add("every_node_has_visual_evidence_block")
            out.append(
                CriterionFailure(
                    criterion_id="every_node_has_visual_evidence_block",
                    subject_type="workflow_node",
                    subject_id=f"{workflow.workflow_id}#{node.node_id}",
                    message="Node has no visual_evidence block.",
                )
            )
    return out


def _criterion_every_non_terminal_node_has_question(
    workflow: CanonicalWorkflow, fired: set[str]
) -> Iterable[CriterionFailure]:
    out: list[CriterionFailure] = []
    for node in workflow.nodes:
        if node.node_type in NON_BRANCHING_NODE_TYPES:
            continue
        if not (node.question and node.question.strip()):
            fired.add("every_non_terminal_node_has_non_empty_question")
            out.append(
                CriterionFailure(
                    criterion_id="every_non_terminal_node_has_non_empty_question",
                    subject_type="workflow_node",
                    subject_id=f"{workflow.workflow_id}#{node.node_id}",
                    message="Non-terminal/escalation node must have a non-empty question.",
                )
            )
    return out


def _criterion_every_non_terminal_node_has_branch(
    workflow: CanonicalWorkflow, fired: set[str]
) -> Iterable[CriterionFailure]:
    out: list[CriterionFailure] = []
    for node in workflow.nodes:
        if node.node_type in NON_BRANCHING_NODE_TYPES:
            continue
        if not node.branches:
            fired.add("every_non_terminal_node_has_at_least_one_branch")
            out.append(
                CriterionFailure(
                    criterion_id="every_non_terminal_node_has_at_least_one_branch",
                    subject_type="workflow_node",
                    subject_id=f"{workflow.workflow_id}#{node.node_id}",
                    message="Non-terminal/escalation node must declare at least one branch.",
                )
            )
    return out


def _criterion_procedure_backed_nodes_resolve(
    workflow: CanonicalWorkflow,
    procedures: dict[str, CanonicalProcedure],
    fired: set[str],
) -> Iterable[CriterionFailure]:
    out: list[CriterionFailure] = []
    for node in workflow.nodes:
        if node.node_type not in PROCEDURE_BACKED_NODE_TYPES:
            continue
        if not node.procedure_ref:
            fired.add("procedure_backed_nodes_resolve_to_canonical_procedure")
            out.append(
                CriterionFailure(
                    criterion_id="procedure_backed_nodes_resolve_to_canonical_procedure",
                    subject_type="workflow_node",
                    subject_id=f"{workflow.workflow_id}#{node.node_id}",
                    message=f"{node.node_type} node must declare a procedure_ref.",
                )
            )
            continue
        if node.procedure_ref not in procedures:
            fired.add("procedure_backed_nodes_resolve_to_canonical_procedure")
            out.append(
                CriterionFailure(
                    criterion_id="procedure_backed_nodes_resolve_to_canonical_procedure",
                    subject_type="workflow_node",
                    subject_id=f"{workflow.workflow_id}#{node.node_id}",
                    message=(
                        f"procedure_ref {node.procedure_ref!r} does not resolve "
                        "in the canonical procedure dictionary."
                    ),
                )
            )
    return out


def _criterion_edge_condition_signals(
    workflow: CanonicalWorkflow, fired: set[str]
) -> Iterable[CriterionFailure]:
    out: list[CriterionFailure] = []
    required = set(workflow.required_signals)
    for edge in workflow.edges:
        if not edge.condition_signal:
            fired.add("every_edge_condition_signal_is_in_required_signals")
            out.append(
                CriterionFailure(
                    criterion_id="every_edge_condition_signal_is_in_required_signals",
                    subject_type="workflow_edge",
                    subject_id=f"{edge.source_node_id}->{edge.target_node_id}",
                    message="Edge must declare a non-empty condition_signal.",
                )
            )
            continue
        if edge.condition_signal not in required:
            fired.add("every_edge_condition_signal_is_in_required_signals")
            out.append(
                CriterionFailure(
                    criterion_id="every_edge_condition_signal_is_in_required_signals",
                    subject_type="workflow_edge",
                    subject_id=f"{edge.source_node_id}->{edge.target_node_id}",
                    message=(
                        f"condition_signal {edge.condition_signal!r} is not in "
                        "workflow.required_signals."
                    ),
                )
            )
    return out


def _criterion_procedure_refs_subset(
    workflow: CanonicalWorkflow,
    mapping: CompositionMapping,
    fired: set[str],
) -> Iterable[CriterionFailure]:
    entry = mapping.entries.get(workflow.workflow_id)
    if entry is None:
        fired.add("procedure_refs_are_subset_of_composition_entry")
        return [
            CriterionFailure(
                criterion_id="procedure_refs_are_subset_of_composition_entry",
                subject_type="workflow",
                subject_id=workflow.workflow_id,
                message="Workflow has no composition entry to scope procedure_refs.",
            )
        ]
    used = {n.procedure_ref for n in workflow.nodes if n.procedure_ref}
    allowed = set(entry.assigned_canonical_procedure_refs)
    leaks = used - allowed
    if leaks:
        fired.add("procedure_refs_are_subset_of_composition_entry")
        return [
            CriterionFailure(
                criterion_id="procedure_refs_are_subset_of_composition_entry",
                subject_type="workflow",
                subject_id=workflow.workflow_id,
                message=(
                    "Workflow references procedure_refs outside its composition "
                    f"entry: {sorted(leaks)}"
                ),
            )
        ]
    return []


def _criterion_referenced_procedures_have_tracking(
    workflow: CanonicalWorkflow,
    procedures: dict[str, CanonicalProcedure],
    fired: set[str],
) -> Iterable[CriterionFailure]:
    out: list[CriterionFailure] = []
    for node in workflow.nodes:
        if not node.procedure_ref:
            continue
        proc = procedures.get(node.procedure_ref)
        if proc is None:
            continue
        if proc.relationship_tracking is None or proc.visual_evidence is None:
            fired.add("referenced_procedures_have_relationship_and_visual_evidence")
            out.append(
                CriterionFailure(
                    criterion_id="referenced_procedures_have_relationship_and_visual_evidence",
                    subject_type="procedure",
                    subject_id=proc.procedure_id,
                    message=(
                        "Referenced canonical procedure lacks relationship_tracking "
                        "or visual_evidence."
                    ),
                )
            )
    return out


def _criterion_screenshot_required_procedures(
    workflow: CanonicalWorkflow,
    procedures: dict[str, CanonicalProcedure],
    fired: set[str],
) -> Iterable[CriterionFailure]:
    out: list[CriterionFailure] = []
    for node in workflow.nodes:
        if not node.procedure_ref:
            continue
        proc = procedures.get(node.procedure_ref)
        if proc is None:
            continue
        ve = proc.visual_evidence
        if not ve.screenshot_required:
            continue
        if not ve.primary_screenshot_refs and not ve.required_screenshot_types:
            fired.add("screenshot_required_procedures_have_screenshot_refs_or_types")
            out.append(
                CriterionFailure(
                    criterion_id="screenshot_required_procedures_have_screenshot_refs_or_types",
                    subject_type="procedure",
                    subject_id=proc.procedure_id,
                    message=(
                        "screenshot_required procedure has neither "
                        "primary_screenshot_refs nor required_screenshot_types."
                    ),
                )
            )
    return out


def _criterion_no_developer_taxonomy(
    workflow: CanonicalWorkflow, fired: set[str]
) -> Iterable[CriterionFailure]:
    offenders: list[CriterionFailure] = []
    for field_name in ("canonical_title", "issue_category"):
        value = getattr(workflow, field_name, None)
        if isinstance(value, str) and CAT_TAXONOMY_PATTERN.search(value):
            offenders.append(
                CriterionFailure(
                    criterion_id="no_developer_taxonomy_codes_in_user_facing_fields",
                    subject_type="workflow",
                    subject_id=workflow.workflow_id,
                    message=f"workflow.{field_name}={value!r} contains a CAT-* taxonomy code.",
                )
            )
    for field_name in ("entry_conditions", "escalation_conditions"):
        for idx, value in enumerate(getattr(workflow, field_name, []) or []):
            if isinstance(value, str) and CAT_TAXONOMY_PATTERN.search(value):
                offenders.append(
                    CriterionFailure(
                        criterion_id="no_developer_taxonomy_codes_in_user_facing_fields",
                        subject_type="workflow",
                        subject_id=workflow.workflow_id,
                        message=(
                            f"workflow.{field_name}[{idx}]={value!r} contains a "
                            "CAT-* taxonomy code."
                        ),
                    )
                )
    for node in workflow.nodes:
        for field_name in ("question", "instruction"):
            value = getattr(node, field_name, None)
            if isinstance(value, str) and CAT_TAXONOMY_PATTERN.search(value):
                offenders.append(
                    CriterionFailure(
                        criterion_id="no_developer_taxonomy_codes_in_user_facing_fields",
                        subject_type="workflow_node",
                        subject_id=f"{workflow.workflow_id}#{node.node_id}",
                        message=(
                            f"node.{field_name}={value!r} contains a CAT-* "
                            "taxonomy code."
                        ),
                    )
                )
    if offenders:
        fired.add("no_developer_taxonomy_codes_in_user_facing_fields")
    return offenders
