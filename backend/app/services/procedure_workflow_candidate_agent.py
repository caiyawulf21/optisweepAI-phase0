from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from backend.app.schemas.procedure import EvidenceReference, ProcedureCandidate, ProcedureStep
from backend.app.schemas.workflow_candidate import ReviewNote, WorkflowCandidate, WorkflowCandidateStep, WorkflowProcedureLink


ACTION_VERBS = {
    "add",
    "cancel",
    "capture",
    "check",
    "clear",
    "collect",
    "confirm",
    "document",
    "initialize",
    "inspect",
    "open",
    "record",
    "remove",
    "restart",
    "review",
    "reset",
    "resolve",
    "start",
    "stop",
    "validate",
    "verify",
}
UNSAFE_ACTION_TERMS = {
    "cancel",
    "clear",
    "delete",
    "estop",
    "e-stop",
    "force",
    "initialize",
    "remove",
    "reset",
    "restart",
    "shutdown",
    "start",
    "stop",
}
INFRASTRUCTURE_TERMS = {"database", "db", "event log", "server", "service", "sql", "windows"}
VISUAL_GUIDANCE_TERMS = {
    "agv",
    "alarm",
    "heartbeat",
    "hmi",
    "log",
    "mapping",
    "rms",
    "screen",
    "service",
    "task",
    "tote",
    "wcs",
}
OBSERVED_SIGNAL_FIELDS = [
    "observed_failure_signals",
    "diagnostic_signals",
    "action_signals",
    "recovery_validation_signals",
    "escalation_signals",
    "observed_signals",
]


class ProcedureWorkflowCandidateAgent:
    def __init__(
        self,
        data_root: str | Path = "data",
        taxonomy_path: str | Path | None = None,
        synthesis_client: Any | None = None,
        llm_config_path: str | Path | None = None,
    ) -> None:
        self.data_root = Path(data_root)
        self.taxonomy_path = Path(taxonomy_path) if taxonomy_path else self.data_root / "taxonomy" / "issue_taxonomy_v0.yaml"
        self.synthesis_client = synthesis_client
        self.llm_config_path = Path(llm_config_path) if llm_config_path else Path("config") / "azure_openai.local.json"

    def run(self) -> dict[str, int]:
        package = self._load_package()
        result = self.generate(package)
        self._write_outputs(result)
        return {key: len(value) for key, value in result.items()}

    def generate(self, package: dict[str, Any]) -> dict[str, list[Any]]:
        packet = self.build_synthesis_packet(package)
        synthesis = self._synthesize(packet)
        result = self._materialize_synthesis(synthesis, packet)
        self._validate_v2_outputs(result, packet)
        return result

    def _load_package(self) -> dict[str, Any]:
        return {
            "canonical_incidents": self._load_json(self.data_root / "incidents" / "canonical_incidents.json"),
            "timeline_events": self._load_json(self.data_root / "timelines" / "timeline_events.json"),
            "raw_evidence_chunks": self._load_json(self.data_root / "evidence" / "raw_evidence_chunks.json"),
            "source_artifacts": self._load_json(self.data_root / "evidence" / "source_artifacts.json"),
            "taxonomy": self._load_taxonomy(),
            "prior_procedure_candidates": self._load_json(self.data_root / "procedures" / "procedure_candidates.json"),
            "prior_workflow_candidates": self._load_json(self.data_root / "workflows" / "workflow_candidates.json"),
        }

    def _load_json(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else []

    def _load_taxonomy(self) -> dict[str, Any]:
        if not self.taxonomy_path.exists():
            return {}
        return yaml.safe_load(self.taxonomy_path.read_text(encoding="utf-8")) or {}

    def _write_outputs(self, result: dict[str, list[Any]]) -> None:
        output_paths = {
            "procedure_candidates": self.data_root / "procedures" / "generated_procedure_candidates.json",
            "workflow_candidates": self.data_root / "workflows" / "generated_workflow_candidates.json",
            "workflow_procedure_links": self.data_root / "review" / "workflow_procedure_links.json",
            "review_notes": self.data_root / "review" / "review_notes.json",
        }
        for key, path in output_paths.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = [item.model_dump(exclude_none=True) for item in result[key]]
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def build_synthesis_packet(self, package: dict[str, Any]) -> dict[str, Any]:
        incidents = {self._incident_id(record): record for record in package.get("canonical_incidents", []) if self._incident_id(record)}
        timeline_by_incident = self._group_by_incident(package.get("timeline_events", []))
        evidence_index = self._evidence_index(package)
        artifact_index = self._artifact_index(package.get("source_artifacts", []))
        procedures = [
            self._source_procedure_packet(record, incidents, evidence_index, artifact_index)
            for record in package.get("prior_procedure_candidates", [])
            if record.get("procedure_id")
        ]
        workflows = [
            self._source_workflow_packet(record, incidents, evidence_index, artifact_index)
            for record in package.get("prior_workflow_candidates", [])
            if record.get("workflow_id")
        ]
        return {
            "task": "Synthesize review-only reusable procedure and workflow candidates from normalized Optisweep incident records.",
            "hard_rules": [
                "Return strict JSON only with procedure_groups, workflow_groups, workflow_procedure_links, review_notes, and rejected_merge_groups.",
                "Return at most 8 procedure_groups, at most 6 workflow_groups, at most 20 workflow_procedure_links, at most 20 review_notes, and at most 20 rejected_merge_groups.",
                "Evidence refs in outputs must be compact objects with only incident_id, evidence_id, source_artifact_id, and excerpt when needed.",
                "Do not echo source evidence summaries, timeline summaries, or full source candidate records in the output.",
                "Do not copy case narrative into generated procedure titles, purposes, or instructions.",
                "Do not merge procedures unless action_type, target_system, operational_scope, role_required, support_safe, and validation_goal are compatible.",
                "Do not merge Restart service, Restart lane, Restart WCS web application, Restart robot, Restart HMI, Restart Ignition, or Restart Optisweep service unless evidence explicitly proves the same target and scope.",
                "Treat root causes as candidate/inferred unless source records explicitly validate them.",
                "All generated artifacts must remain validation_status needs_review; workflows must remain status draft.",
            ],
            "output_contract": {
                "procedure_groups": [
                    {
                        "canonical_procedure_id": "short_snake_case_v1",
                        "canonical_title": "Imperative English title",
                        "purpose": "General reusable purpose",
                        "issue_category": "optional",
                        "action_tuple": {
                            "action_type": "",
                            "target_system": "",
                            "target_component": "",
                            "operational_scope": "",
                            "role_required": "",
                            "support_safe": False,
                            "validation_goal": "",
                        },
                        "source_procedure_ids": [],
                        "related_incidents": [],
                        "preconditions": [],
                        "steps": [],
                        "do_not_do": [],
                        "escalation_conditions": [],
                        "evidence_refs": [],
                        "image_refs": [],
                        "confidence": 0.0,
                    }
                ],
                "workflow_groups": [],
                "workflow_procedure_links": [],
                "review_notes": [],
                "rejected_merge_groups": [],
            },
            "taxonomy": package.get("taxonomy", {}),
            "source_procedures": procedures,
            "source_workflows": workflows,
            "incidents": [
                self._incident_packet(incident, timeline_by_incident.get(incident_id, []))
                for incident_id, incident in sorted(incidents.items())
            ],
            "evidence_index": list(evidence_index.values()),
            "artifact_index": list(artifact_index.values()),
        }

    def _source_procedure_packet(
        self,
        record: dict[str, Any],
        incidents: dict[str, dict[str, Any]],
        evidence_index: dict[str, dict[str, Any]],
        artifact_index: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        related_incidents = self._as_string_list(record.get("related_incidents"))
        return {
            "source_procedure_id": record.get("procedure_id"),
            "title": record.get("title"),
            "issue_category": record.get("issue_category"),
            "purpose": record.get("purpose") or record.get("operational_intent"),
            "role_required": record.get("role_required"),
            "support_safe": record.get("support_safe"),
            "steps": record.get("steps", []),
            "validation_checks": self._as_string_list(record.get("validation_checks")),
            "escalation_conditions": self._as_string_list(record.get("escalation_conditions")),
            "related_incidents": related_incidents,
            "incident_context": [self._incident_brief(incidents[incident_id]) for incident_id in related_incidents if incident_id in incidents],
            "candidate_inferred_causes": self._candidate_causes(related_incidents, incidents),
            "resolution_behavior": self._resolution_behavior(related_incidents, incidents),
            "evidence_refs": self._evidence_refs_payload(record.get("evidence_refs"), related_incidents, evidence_index),
            "source_artifact_refs": self._artifact_refs_payload(record.get("source_artifacts"), artifact_index),
            "comparable_signal_groups": self._as_string_list(record.get("comparable_signal_groups")),
            "pattern_candidate_notes": record.get("pattern_candidate_notes"),
        }

    def _source_workflow_packet(
        self,
        record: dict[str, Any],
        incidents: dict[str, dict[str, Any]],
        evidence_index: dict[str, dict[str, Any]],
        artifact_index: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        related_incidents = self._as_string_list(record.get("related_incidents") or record.get("related_cases"))
        return {
            "source_workflow_id": record.get("workflow_id"),
            "title": record.get("title"),
            "issue_category": record.get("issue_category"),
            "operational_intent": record.get("operational_intent"),
            "required_signals": self._as_string_list(record.get("required_signals")),
            "entry_conditions": self._as_string_list(record.get("entry_conditions")),
            "procedure_refs": self._as_string_list(record.get("procedure_refs")),
            "escalation_conditions": self._as_string_list(record.get("escalation_conditions")),
            "related_incidents": related_incidents,
            "incident_context": [self._incident_brief(incidents[incident_id]) for incident_id in related_incidents if incident_id in incidents],
            "candidate_inferred_causes": self._candidate_causes(related_incidents, incidents),
            "resolution_behavior": self._resolution_behavior(related_incidents, incidents),
            "evidence_refs": self._evidence_refs_payload(record.get("evidence_refs"), related_incidents, evidence_index),
            "source_artifact_refs": self._artifact_refs_payload(record.get("image_refs") or record.get("source_artifacts"), artifact_index),
            "comparable_signal_groups": self._as_string_list(record.get("comparable_signal_groups")),
            "pattern_candidate_notes": record.get("pattern_candidate_notes"),
            "synthesis_blockers": self._as_string_list(record.get("synthesis_blockers")),
        }

    def _incident_packet(self, record: dict[str, Any], timeline_events: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "incident_id": self._incident_id(record),
            "issue_category": record.get("issue_category"),
            "title": record.get("title") or record.get("failure_signature"),
            "observed_signals": self._observed_signals(record),
            "candidate_inferred_causes": record.get("candidate_inferred_causes", []),
            "validated_root_cause": record.get("validated_root_cause"),
            "resolution_summary": record.get("resolution_summary"),
            "resolution_status": record.get("resolution_status"),
            "escalation_domains": self._as_string_list(record.get("escalation_domains")),
            "timeline_summary": [
                {
                    "event_id": event.get("event_id"),
                    "event_order": event.get("event_order"),
                    "event_type": event.get("event_type"),
                    "actor_role": event.get("actor_role"),
                    "event_summary": self._truncate(event.get("event_summary") or event.get("summary"), 260),
                    "action_taken": self._truncate(event.get("action_taken"), 180),
                    "outcome": self._truncate(event.get("outcome"), 180),
                }
                for event in sorted(timeline_events, key=self._event_order)[:12]
            ],
        }

    def _synthesize(self, packet: dict[str, Any]) -> dict[str, Any]:
        if self.synthesis_client is not None:
            return self.synthesis_client.synthesize(packet)
        config = self._load_llm_config()
        if not config:
            raise RuntimeError("Azure OpenAI config is required for ProcedureWorkflowCandidateAgent V2 synthesis")
        return self._call_azure_openai(config, packet)

    def _load_llm_config(self) -> dict[str, Any]:
        config_path = self.llm_config_path
        if config_path.exists():
            return json.loads(config_path.read_text(encoding="utf-8"))
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
        if not endpoint or not api_key or not deployment:
            return {}
        return {
            "endpoint": endpoint,
            "api_key": api_key,
            "deployment": deployment,
            "api_version": os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            "temperature": 0.1,
            "max_tokens": 12000,
        }

    def _call_azure_openai(self, config: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
        from openai import AzureOpenAI

        client = AzureOpenAI(
            azure_endpoint=config["endpoint"],
            api_key=config["api_key"],
            api_version=config.get("api_version", "2024-10-21"),
        )
        token_args = {"max_completion_tokens": config.get("max_tokens", 12000)}
        response = client.chat.completions.create(
            model=config["deployment"],
            temperature=config.get("temperature", 0.1),
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an Optisweep ingestion synthesis agent. Return only strict JSON. "
                        "Generate review-only candidates from structured evidence. Do not promote anything."
                    ),
                },
                {"role": "user", "content": json.dumps(packet, ensure_ascii=False)},
            ],
            **token_args,
        )
        finish_reason = getattr(response.choices[0], "finish_reason", None)
        if finish_reason == "length":
            raise ValueError("Azure OpenAI synthesis response was truncated before valid JSON could be returned")
        content = response.choices[0].message.content or "{}"
        return self._parse_json_response(content)

    def _materialize_synthesis(self, synthesis: dict[str, Any], packet: dict[str, Any]) -> dict[str, list[Any]]:
        source_procedures = {record["source_procedure_id"]: record for record in packet["source_procedures"]}
        source_workflows = {record["source_workflow_id"]: record for record in packet["source_workflows"]}
        procedures = [self._procedure_from_group(group, source_procedures) for group in synthesis.get("procedure_groups", [])]
        source_procedure_to_generated = {
            source_id: procedure.procedure_id
            for procedure in procedures
            for source_id in procedure.source_procedure_candidate_ids
        }
        workflows = [
            self._workflow_from_group(group, source_workflows, procedures, source_procedure_to_generated)
            for group in synthesis.get("workflow_groups", [])
        ]
        workflows, invalid_workflow_notes = self._filter_workflows(workflows)
        if not workflows:
            workflows = self._fallback_workflows_from_sources(packet, procedures, source_procedure_to_generated)
        workflows = self._enrich_workflows_from_sources(workflows, packet, source_procedure_to_generated)
        workflows.extend(self._supplement_multicase_workflows(workflows, procedures, packet, source_procedure_to_generated))
        links = [
            self._link_from_group(group, workflows, procedures, source_procedure_to_generated)
            for group in synthesis.get("workflow_procedure_links", [])
        ]
        links, invalid_link_notes = self._filter_links(links, workflows, procedures)
        links = self._ensure_links(links, workflows, procedures)
        notes = [self._note_from_group(note) for note in synthesis.get("review_notes", [])]
        notes.extend(invalid_workflow_notes)
        notes.extend(invalid_link_notes)
        notes.extend(self._notes_from_rejected_groups(synthesis.get("rejected_merge_groups", [])))
        notes.extend(self._quality_notes(procedures, workflows, links))
        return {
            "procedure_candidates": procedures,
            "workflow_candidates": workflows,
            "workflow_procedure_links": links,
            "review_notes": notes,
        }

    def _filter_workflows(self, workflows: list[WorkflowCandidate]) -> tuple[list[WorkflowCandidate], list[ReviewNote]]:
        valid = []
        notes = []
        for workflow in workflows:
            if workflow.procedure_refs:
                valid.append(workflow)
                continue
            notes.append(
                ReviewNote(
                    note_id=self._slug(f"note_orphan_workflow_{workflow.workflow_id}")[:120],
                    artifact_type="workflow",
                    artifact_id=workflow.workflow_id,
                    severity="warning",
                    note="Rejected generated workflow because it had no valid generated procedure linkage.",
                    recommended_review_owner="SME reviewer",
                    evidence_refs=workflow.evidence_refs,
                )
            )
        return valid, notes

    def _enrich_workflows_from_sources(
        self,
        workflows: list[WorkflowCandidate],
        packet: dict[str, Any],
        source_procedure_to_generated: dict[str, str],
    ) -> list[WorkflowCandidate]:
        for workflow in workflows:
            matching_sources = [
                source
                for source in packet["source_workflows"]
                if set(
                    source_procedure_to_generated.get(ref, ref)
                    for ref in source.get("procedure_refs", [])
                )
                & set(workflow.procedure_refs)
            ]
            if not workflow.source_workflow_candidate_ids:
                workflow.source_workflow_candidate_ids = [source["source_workflow_id"] for source in matching_sources]
            if not workflow.related_cases:
                workflow.related_cases = sorted({incident for source in matching_sources for incident in source.get("related_incidents", [])})
                workflow.related_incidents = workflow.related_cases
            if not workflow.required_signals:
                workflow.required_signals = list(dict.fromkeys(signal for source in matching_sources for signal in source.get("required_signals", [])))
            if not workflow.shared_signals:
                comparable_groups = [
                    signal
                    for source in matching_sources
                    for signal in (source.get("comparable_signal_groups") or source.get("required_signals", []))
                ]
                workflow.shared_signals = list(dict.fromkeys(comparable_groups))[:8]
            if not workflow.common_root_cause_hypotheses:
                workflow.common_root_cause_hypotheses = [
                    self._root_cause_text(cause)
                    for source in matching_sources
                    for cause in source.get("candidate_inferred_causes", [])
                ][:8]
        return workflows

    def _supplement_multicase_workflows(
        self,
        workflows: list[WorkflowCandidate],
        procedures: list[ProcedureCandidate],
        packet: dict[str, Any],
        source_procedure_to_generated: dict[str, str],
    ) -> list[WorkflowCandidate]:
        existing_multicase_procedures = {
            procedure_ref
            for workflow in workflows
            if len(workflow.related_cases or workflow.related_incidents) >= 2
            for procedure_ref in workflow.procedure_refs
        }
        supplements = []
        for procedure in procedures:
            if len(procedure.related_incidents) < 2 or procedure.procedure_id in existing_multicase_procedures:
                continue
            matching_sources = [
                source
                for source in packet["source_workflows"]
                if any(source_procedure_to_generated.get(ref, ref) == procedure.procedure_id for ref in source.get("procedure_refs", []))
            ]
            required_signals = list(dict.fromkeys(signal for source in matching_sources for signal in source.get("required_signals", [])))
            comparable_signals = list(
                dict.fromkeys(
                    signal
                    for source in matching_sources
                    for signal in (source.get("comparable_signal_groups") or source.get("required_signals", []))
                )
            )
            workflow_id = self._workflow_id(tuple((comparable_signals or required_signals)[:4]), [procedure.procedure_id])
            supplements.append(
                WorkflowCandidate(
                    workflow_id=workflow_id,
                    workflow_version="0.1",
                    title=self._title(workflow_id),
                    issue_category=procedure.issue_category,
                    operational_intent=f"Review recurring evidence-backed procedure pattern: {procedure.title}.",
                    source_workflow_candidate_ids=[source["source_workflow_id"] for source in matching_sources],
                    entry_conditions=comparable_signals[:6],
                    required_signals=required_signals or comparable_signals,
                    shared_signals=comparable_signals[:8],
                    common_root_cause_hypotheses=[
                        self._root_cause_text(cause)
                        for source in matching_sources
                        for cause in source.get("candidate_inferred_causes", [])
                    ][:8],
                    steps=[
                        WorkflowCandidateStep(
                            step_id="step_01",
                            step_type="diagnostic_check",
                            instruction=f"Use procedure {procedure.procedure_id}.",
                            procedure_refs=[procedure.procedure_id],
                            evidence_refs=procedure.evidence_refs,
                            image_refs=procedure.source_artifacts,
                        )
                    ],
                    procedure_refs=[procedure.procedure_id],
                    related_cases=procedure.related_incidents,
                    related_incidents=procedure.related_incidents,
                    evidence_refs=procedure.evidence_refs,
                    image_refs=procedure.source_artifacts,
                    confidence=procedure.confidence,
                    status="draft",
                    validation_status="needs_review",
                )
            )
            if len(supplements) >= 3:
                break
        return supplements

    def _root_cause_text(self, value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("cause_summary") or value.get("summary") or value)
        return str(value)

    def _fallback_workflows_from_sources(
        self,
        packet: dict[str, Any],
        procedures: list[ProcedureCandidate],
        source_procedure_to_generated: dict[str, str],
    ) -> list[WorkflowCandidate]:
        procedure_ids = {procedure.procedure_id for procedure in procedures}
        groups: list[dict[str, Any]] = []
        for source_workflow in packet["source_workflows"]:
            mapped_refs = [
                mapped
                for ref in source_workflow.get("procedure_refs", [])
                if (mapped := source_procedure_to_generated.get(ref, ref)) in procedure_ids
            ]
            if not mapped_refs:
                continue
            source_workflow = {**source_workflow, "mapped_procedure_refs": mapped_refs}
            signal_set = set(source_workflow.get("comparable_signal_groups") or source_workflow.get("required_signals")[:6])
            target_group = None
            for group in groups:
                overlap = len(signal_set & group["signals"])
                union = len(signal_set | group["signals"]) or 1
                if overlap >= 2 and overlap / union >= 0.35:
                    target_group = group
                    break
            if target_group is None:
                target_group = {"signals": set(signal_set), "items": []}
                groups.append(target_group)
            target_group["signals"].update(signal_set)
            target_group["items"].append(source_workflow)
        workflows = []
        sorted_groups = sorted(groups, key=lambda group: (-len(group["items"]), sorted(group["signals"])))
        for group in sorted_groups[:6]:
            source_group = group["items"]
            related_cases = sorted({incident for source in source_group for incident in source.get("related_incidents", [])})
            procedure_refs = list(dict.fromkeys(ref for source in source_group for ref in source.get("mapped_procedure_refs", [])))
            evidence_refs = self._dedupe_evidence(
                [
                    self._coerce_evidence_ref(ref, related_cases[0] if related_cases else "unknown")
                    for source in source_group
                    for ref in source.get("evidence_refs", [])
                ]
            )
            source_ids = [source["source_workflow_id"] for source in source_group]
            required_signals = list(dict.fromkeys(signal for source in source_group for signal in source.get("required_signals", [])))
            shared_signals = sorted(group["signals"])[:8]
            workflow_id = self._workflow_id(tuple(shared_signals[:4]), procedure_refs)
            steps = [
                WorkflowCandidateStep(
                    step_id=f"step_{index:02d}",
                    step_type="diagnostic_check",
                    instruction=f"Use procedure {procedure_id}.",
                    procedure_refs=[procedure_id],
                    evidence_refs=evidence_refs,
                )
                for index, procedure_id in enumerate(procedure_refs, start=1)
            ]
            workflows.append(
                WorkflowCandidate(
                    workflow_id=workflow_id,
                    workflow_version="0.1",
                    title=self._title(workflow_id),
                    issue_category=source_group[0].get("issue_category"),
                    operational_intent="Fallback workflow synthesized from source workflow candidates with validated generated procedure mappings.",
                    source_workflow_candidate_ids=source_ids,
                    entry_conditions=shared_signals,
                    required_signals=required_signals or shared_signals,
                    shared_signals=shared_signals,
                    common_root_cause_hypotheses=list(
                        dict.fromkeys(
                            self._root_cause_text(cause)
                            for source in source_group
                            for cause in source.get("candidate_inferred_causes", [])
                        )
                    )[:6],
                    steps=steps,
                    procedure_refs=procedure_refs,
                    related_cases=related_cases,
                    related_incidents=related_cases,
                    evidence_refs=evidence_refs,
                    image_refs=list(dict.fromkeys(artifact["artifact_id"] for source in source_group for artifact in source.get("source_artifact_refs", []) if artifact.get("artifact_id"))),
                    confidence=round(min(0.85, 0.45 + 0.1 * len(source_group) + 0.03 * len(evidence_refs)), 2),
                    status="draft",
                    validation_status="needs_review",
                )
            )
        return workflows

    def _filter_links(
        self,
        links: list[WorkflowProcedureLink],
        workflows: list[WorkflowCandidate],
        procedures: list[ProcedureCandidate],
    ) -> tuple[list[WorkflowProcedureLink], list[ReviewNote]]:
        workflow_ids = {workflow.workflow_id for workflow in workflows}
        procedure_ids = {procedure.procedure_id for procedure in procedures}
        valid_links = []
        notes = []
        for link in links:
            if link.workflow_id in workflow_ids and link.procedure_id in procedure_ids:
                valid_links.append(link)
                continue
            notes.append(
                ReviewNote(
                    note_id=self._slug(f"note_invalid_link_{link.link_id}")[:120],
                    artifact_type="workflow",
                    artifact_id=link.workflow_id or "unknown_workflow",
                    severity="warning",
                    note=f"Rejected invalid workflow/procedure link suggestion: {link.workflow_id} -> {link.procedure_id}.",
                    recommended_review_owner="SME reviewer",
                    evidence_refs=link.evidence_refs,
                )
            )
        return valid_links, notes

    def _ensure_links(
        self,
        links: list[WorkflowProcedureLink],
        workflows: list[WorkflowCandidate],
        procedures: list[ProcedureCandidate],
    ) -> list[WorkflowProcedureLink]:
        existing_pairs = {(link.workflow_id, link.procedure_id) for link in links}
        procedure_by_id = {procedure.procedure_id: procedure for procedure in procedures}
        ensured = list(links)
        for workflow in workflows:
            for procedure_id in workflow.procedure_refs:
                if (workflow.workflow_id, procedure_id) in existing_pairs or procedure_id not in procedure_by_id:
                    continue
                procedure = procedure_by_id[procedure_id]
                related_incidents = sorted(set(workflow.related_cases or workflow.related_incidents) | set(procedure.related_incidents))
                evidence_refs = self._dedupe_evidence([*workflow.evidence_refs, *procedure.evidence_refs])
                confidence = min(workflow.confidence or 0.0, procedure.confidence or 0.0)
                ensured.append(
                    WorkflowProcedureLink(
                        link_id=f"link_{workflow.workflow_id}_{procedure.procedure_id}",
                        workflow_id=workflow.workflow_id,
                        procedure_id=procedure.procedure_id,
                        step_ids=[step.step_id for step in workflow.steps if procedure.procedure_id in step.procedure_refs],
                        source_workflow_candidate_ids=workflow.source_workflow_candidate_ids,
                        source_procedure_candidate_ids=procedure.source_procedure_candidate_ids,
                        related_incidents=related_incidents,
                        shared_signals=workflow.shared_signals or workflow.required_signals,
                        shared_resolution_patterns=workflow.validation_checks,
                        similar_root_cause_hypotheses=workflow.common_root_cause_hypotheses,
                        evidence_refs=evidence_refs,
                        image_refs=sorted(set(workflow.image_refs) | set(procedure.source_artifacts)),
                        rationale="Deterministic link from validated generated workflow procedure_refs.",
                        merge_confidence=confidence,
                        merge_risk_notes=[],
                        confidence=confidence,
                        validation_status="needs_review",
                    )
                )
                existing_pairs.add((workflow.workflow_id, procedure_id))
        return ensured

    def _procedure_from_group(self, group: dict[str, Any], source_procedures: dict[str, dict[str, Any]]) -> ProcedureCandidate:
        source_ids = self._as_string_list(group.get("source_procedure_ids"))
        related_incidents = self._as_string_list(group.get("related_incidents")) or sorted(
            {incident for source_id in source_ids for incident in source_procedures.get(source_id, {}).get("related_incidents", [])}
        )
        evidence_refs = self._dedupe_evidence([self._coerce_evidence_ref(ref, related_incidents[0] if related_incidents else "unknown") for ref in self._as_list(group.get("evidence_refs"))])
        image_refs = self._as_string_list(group.get("image_refs"))
        action_tuple = group.get("action_tuple") or {}
        role_required = str(action_tuple.get("role_required") or group.get("role_required") or "SME reviewer")
        support_safe = bool(action_tuple.get("support_safe", group.get("support_safe", False)))
        steps = []
        for index, raw_step in enumerate(self._as_list(group.get("steps")), start=1):
            step_refs = self._dedupe_evidence([self._coerce_evidence_ref(ref, related_incidents[0] if related_incidents else "unknown") for ref in self._as_list(raw_step.get("evidence_refs") if isinstance(raw_step, dict) else [])])
            if not step_refs:
                step_refs = evidence_refs
            instruction = raw_step.get("instruction") if isinstance(raw_step, dict) else str(raw_step)
            steps.append(
                ProcedureStep(
                    step_number=int(raw_step.get("step_number") or index) if isinstance(raw_step, dict) else index,
                    instruction=str(instruction or group.get("canonical_title") or group.get("canonical_procedure_id")),
                    expected_result=raw_step.get("expected_result") if isinstance(raw_step, dict) else None,
                    validation_check=(raw_step.get("validation_check") if isinstance(raw_step, dict) else None) or str(action_tuple.get("validation_goal") or ""),
                    evidence_refs=step_refs,
                    image_refs=image_refs,
                    screenshot_required=bool(raw_step.get("screenshot_required", False)) if isinstance(raw_step, dict) else False,
                    risk_notes=raw_step.get("risk_notes") if isinstance(raw_step, dict) else None,
                )
            )
        if not steps:
            steps = [
                ProcedureStep(
                    step_number=1,
                    instruction=str(group.get("canonical_title") or group.get("canonical_procedure_id")),
                    validation_check=str(action_tuple.get("validation_goal") or "SME validates the evidence-backed action outcome."),
                    evidence_refs=evidence_refs,
                    image_refs=image_refs,
                    screenshot_required=self._needs_screenshot([json.dumps(group)]),
                )
            ]
        return ProcedureCandidate(
            procedure_id=self._versioned_id(str(group.get("canonical_procedure_id") or group.get("group_id") or "generated_procedure")),
            title=str(group.get("canonical_title") or self._title(str(group.get("canonical_procedure_id") or "Generated Procedure"))),
            issue_category=group.get("issue_category"),
            purpose=group.get("purpose") or group.get("semantic_action"),
            source_procedure_candidate_ids=source_ids,
            action_tuple=action_tuple,
            operational_intent=group.get("purpose") or group.get("semantic_action"),
            role_required=role_required,
            support_safe=support_safe,
            preconditions=self._as_string_list(group.get("preconditions")),
            steps=steps,
            do_not_do=self._as_string_list(group.get("do_not_do")) or ["Do not treat this candidate as approved runtime guidance until SME review is complete."],
            validation_checks=list(dict.fromkeys(step.validation_check for step in steps if step.validation_check)),
            escalation_conditions=self._as_string_list(group.get("escalation_conditions")) or ["Escalate if ownership, safety boundary, or evidence is unclear."],
            related_incidents=related_incidents,
            evidence_refs=evidence_refs,
            source_artifacts=image_refs,
            confidence=float(group.get("confidence") or 0.0),
            validation_status="needs_review",
        )

    def _workflow_from_group(
        self,
        group: dict[str, Any],
        source_workflows: dict[str, dict[str, Any]],
        procedures: list[ProcedureCandidate],
        source_procedure_to_generated: dict[str, str],
    ) -> WorkflowCandidate:
        procedure_ids = {procedure.procedure_id for procedure in procedures}
        source_workflow_ids = self._as_string_list(group.get("source_workflow_ids") or group.get("source_workflow_candidate_ids"))
        related_cases = self._as_string_list(group.get("related_cases") or group.get("related_incidents")) or sorted(
            {incident for source_id in source_workflow_ids for incident in source_workflows.get(source_id, {}).get("related_incidents", [])}
        )
        procedure_refs = [
            mapped
            for ref in self._as_string_list(group.get("procedure_refs"))
            if (mapped := source_procedure_to_generated.get(ref, ref)) in procedure_ids
        ]
        if not procedure_refs:
            procedure_refs = [
                mapped
                for source_workflow_id in source_workflow_ids
                for ref in source_workflows.get(source_workflow_id, {}).get("procedure_refs", [])
                if (mapped := source_procedure_to_generated.get(ref, ref)) in procedure_ids
            ]
            procedure_refs = list(dict.fromkeys(procedure_refs))
        source_required_signals = list(
            dict.fromkeys(
                signal
                for source_workflow_id in source_workflow_ids
                for signal in source_workflows.get(source_workflow_id, {}).get("required_signals", [])
            )
        )
        required_signals = self._as_string_list(group.get("required_signals") or group.get("shared_signals")) or source_required_signals
        shared_signals = self._as_string_list(group.get("shared_signals")) or source_required_signals[:6]
        evidence_refs = self._dedupe_evidence([self._coerce_evidence_ref(ref, related_cases[0] if related_cases else "unknown") for ref in self._as_list(group.get("evidence_refs"))])
        image_refs = self._as_string_list(group.get("image_refs"))
        steps = []
        for index, raw_step in enumerate(self._as_list(group.get("steps")), start=1):
            refs = [
                mapped
                for ref in self._as_string_list(raw_step.get("procedure_refs") if isinstance(raw_step, dict) else [])
                if (mapped := source_procedure_to_generated.get(ref, ref)) in procedure_ids
            ]
            if not refs and procedure_refs:
                refs = procedure_refs[:1]
            step_evidence = self._dedupe_evidence([self._coerce_evidence_ref(ref, related_cases[0] if related_cases else "unknown") for ref in self._as_list(raw_step.get("evidence_refs") if isinstance(raw_step, dict) else [])]) or evidence_refs
            steps.append(
                WorkflowCandidateStep(
                    step_id=str(raw_step.get("step_id") or f"step_{index:02d}") if isinstance(raw_step, dict) else f"step_{index:02d}",
                    step_type=str(raw_step.get("step_type") or "diagnostic_check") if isinstance(raw_step, dict) else "diagnostic_check",
                    question=raw_step.get("question") if isinstance(raw_step, dict) else None,
                    why_asked=raw_step.get("why_asked") if isinstance(raw_step, dict) else None,
                    instruction=str(raw_step.get("instruction") or "Use linked procedure candidate for this evidence-backed step.") if isinstance(raw_step, dict) else str(raw_step),
                    role_required=raw_step.get("role_required") if isinstance(raw_step, dict) else None,
                    support_safe=bool(raw_step.get("support_safe", True)) if isinstance(raw_step, dict) else True,
                    procedure_refs=refs,
                    image_refs=self._as_string_list(raw_step.get("image_refs")) if isinstance(raw_step, dict) else image_refs,
                    evidence_refs=step_evidence,
                    expected_outcome=raw_step.get("expected_outcome") if isinstance(raw_step, dict) else None,
                    branches=self._as_list(raw_step.get("branches")) if isinstance(raw_step, dict) else [],
                    escalation_conditions=self._as_string_list(raw_step.get("escalation_conditions")) if isinstance(raw_step, dict) else [],
                )
            )
        if not steps and procedure_refs:
            steps = [
                WorkflowCandidateStep(
                    step_id=f"step_{index:02d}",
                    step_type="diagnostic_check",
                    instruction=f"Use procedure {procedure_id}.",
                    procedure_refs=[procedure_id],
                    evidence_refs=evidence_refs,
                    image_refs=image_refs,
                )
                for index, procedure_id in enumerate(procedure_refs, start=1)
            ]
        return WorkflowCandidate(
            workflow_id=self._compact_workflow_id(str(group.get("canonical_workflow_id") or group.get("workflow_id") or "generated_workflow"), procedure_refs),
            workflow_version=str(group.get("workflow_version") or "0.1"),
            title=str(group.get("title") or self._title(str(group.get("canonical_workflow_id") or "Generated Workflow"))),
            issue_category=group.get("issue_category"),
            operational_intent=group.get("operational_intent"),
            source_workflow_candidate_ids=source_workflow_ids,
            entry_conditions=self._as_string_list(group.get("entry_conditions")),
            required_signals=required_signals,
            shared_signals=shared_signals,
            differing_signals=self._as_string_list(group.get("differing_signals")),
            common_root_cause_hypotheses=self._as_string_list(group.get("common_root_cause_hypotheses")),
            exclusion_conditions=self._as_string_list(group.get("exclusion_conditions")),
            minimum_confidence=float(group.get("minimum_confidence") or 0.75),
            roles_allowed=self._as_string_list(group.get("roles_allowed")),
            steps=steps,
            validation_checks=self._as_string_list(group.get("validation_checks")),
            procedure_refs=procedure_refs,
            related_cases=related_cases,
            related_incidents=related_cases,
            evidence_refs=evidence_refs,
            image_refs=image_refs,
            escalation_conditions=self._as_string_list(group.get("escalation_conditions")),
            confidence=float(group.get("confidence") or 0.0),
            status="draft",
            validation_status="needs_review",
        )

    def _compact_workflow_id(self, value: str, procedure_refs: list[str]) -> str:
        workflow_id = self._versioned_id(value)
        if len(workflow_id) <= 75:
            return workflow_id
        return self._workflow_id(tuple(workflow_id.replace("_v1", "").split("_")[:4]), procedure_refs)

    def _link_from_group(
        self,
        group: dict[str, Any],
        workflows: list[WorkflowCandidate],
        procedures: list[ProcedureCandidate],
        source_procedure_to_generated: dict[str, str],
    ) -> WorkflowProcedureLink:
        workflow_ids = {workflow.workflow_id for workflow in workflows}
        procedure_ids = {procedure.procedure_id for procedure in procedures}
        workflow_id = self._versioned_id(str(group.get("workflow_id") or ""))
        raw_procedure_id = str(group.get("procedure_id") or "")
        procedure_id = self._versioned_id(source_procedure_to_generated.get(raw_procedure_id, raw_procedure_id))
        if workflow_id not in workflow_ids:
            workflow_id = str(group.get("workflow_id") or "")
        if procedure_id not in procedure_ids:
            procedure_id = str(group.get("procedure_id") or "")
        incidents = self._as_string_list(group.get("related_incidents"))
        evidence_refs = self._dedupe_evidence([self._coerce_evidence_ref(ref, incidents[0] if incidents else "unknown") for ref in self._as_list(group.get("evidence_refs"))])
        confidence = float(group.get("merge_confidence") or group.get("confidence") or 0.0)
        return WorkflowProcedureLink(
            link_id=str(group.get("link_id") or f"link_{workflow_id}_{procedure_id}"),
            workflow_id=workflow_id,
            procedure_id=procedure_id,
            step_ids=self._as_string_list(group.get("step_ids")),
            source_workflow_candidate_ids=self._as_string_list(group.get("source_workflow_candidate_ids") or group.get("source_workflow_ids")),
            source_procedure_candidate_ids=self._as_string_list(group.get("source_procedure_candidate_ids") or group.get("source_procedure_ids")),
            related_incidents=incidents,
            shared_signals=self._as_string_list(group.get("shared_signals")),
            shared_resolution_patterns=self._as_string_list(group.get("shared_resolution_patterns")),
            similar_root_cause_hypotheses=self._as_string_list(group.get("similar_root_cause_hypotheses")),
            evidence_refs=evidence_refs,
            image_refs=self._as_string_list(group.get("image_refs")),
            rationale=group.get("rationale"),
            merge_confidence=confidence,
            merge_risk_notes=self._as_string_list(group.get("merge_risk_notes")),
            confidence=confidence,
            validation_status="needs_review",
        )

    def _note_from_group(self, note: dict[str, Any]) -> ReviewNote:
        if not isinstance(note, dict):
            note = {"note": str(note), "artifact_type": "workflow", "artifact_id": "synthesis_review", "severity": "info"}
        evidence_refs = [self._coerce_evidence_ref(ref, "unknown") for ref in self._as_list(note.get("evidence_refs"))]
        return ReviewNote(
            note_id=str(note.get("note_id") or self._slug(f"note_{note.get('artifact_type')}_{note.get('artifact_id')}_{note.get('note')}")[:120]),
            artifact_type=str(note.get("artifact_type") or "workflow"),
            artifact_id=str(note.get("artifact_id") or "unknown"),
            severity=str(note.get("severity") or "info"),
            note=str(note.get("note") or ""),
            recommended_review_owner=str(note.get("recommended_review_owner") or "SME reviewer"),
            evidence_refs=self._dedupe_evidence(evidence_refs),
        )

    def _notes_from_rejected_groups(self, rejected_groups: list[dict[str, Any]]) -> list[ReviewNote]:
        notes = []
        for group in rejected_groups:
            evidence_refs = [self._coerce_evidence_ref(ref, "unknown") for ref in self._as_list(group.get("evidence_refs"))]
            notes.append(
                ReviewNote(
                    note_id=self._slug(f"note_rejected_merge_{group.get('group_id') or group.get('reason') or len(notes)}")[:120],
                    artifact_type=str(group.get("artifact_type") or "procedure"),
                    artifact_id=str(group.get("artifact_id") or group.get("group_id") or "rejected_merge_group"),
                    severity=str(group.get("severity") or "warning"),
                    note=str(group.get("reason") or group.get("note") or "Rejected merge group requires SME review."),
                    recommended_review_owner=str(group.get("recommended_review_owner") or "SME reviewer"),
                    evidence_refs=self._dedupe_evidence(evidence_refs),
                )
            )
        return notes

    def _quality_notes(
        self,
        procedures: list[ProcedureCandidate],
        workflows: list[WorkflowCandidate],
        links: list[WorkflowProcedureLink],
    ) -> list[ReviewNote]:
        notes: list[ReviewNote] = []
        for procedure in procedures:
            if len(procedure.related_incidents) < 2:
                notes.append(self._review_note("procedure", procedure.procedure_id, "info", "Generated procedure has single-case support and needs SME review before reuse.", "SME reviewer", procedure.evidence_refs))
            if self._looks_like_copied_narrative(" ".join([procedure.title or "", procedure.purpose or "", *(step.instruction for step in procedure.steps)])):
                notes.append(self._review_note("procedure", procedure.procedure_id, "warning", "Generated procedure may contain copied case narrative rather than reusable runbook language.", "SME reviewer", procedure.evidence_refs))
        for workflow in workflows:
            if len(workflow.related_cases) < 2:
                notes.append(self._review_note("workflow", workflow.workflow_id, "info", "Generated workflow has single-case support and needs cross-case review before promotion.", "SME reviewer", workflow.evidence_refs))
            if len(workflow.workflow_id) > 80:
                notes.append(self._review_note("workflow", workflow.workflow_id, "warning", "Generated workflow ID is long and should be reviewed for concise symptom-driven naming.", "SME reviewer", workflow.evidence_refs))
        for link in links:
            if len(link.related_incidents) < 2:
                notes.append(self._review_note("workflow", link.workflow_id, "info", f"Workflow/procedure link for {link.procedure_id} has single-case support.", "SME reviewer", link.evidence_refs))
        return notes

    def _validate_v2_outputs(self, result: dict[str, list[Any]], packet: dict[str, Any]) -> None:
        source_procedure_ids = {record["source_procedure_id"] for record in packet["source_procedures"]}
        source_workflow_ids = {record["source_workflow_id"] for record in packet["source_workflows"]}
        evidence_ids = {record["evidence_id"] for record in packet["evidence_index"]} | {
            ref["evidence_id"]
            for record in packet["source_procedures"] + packet["source_workflows"]
            for ref in record.get("evidence_refs", [])
        }
        procedures: list[ProcedureCandidate] = result["procedure_candidates"]
        workflows: list[WorkflowCandidate] = result["workflow_candidates"]
        links: list[WorkflowProcedureLink] = result["workflow_procedure_links"]
        procedure_ids = {procedure.procedure_id for procedure in procedures}
        workflow_ids = {workflow.workflow_id for workflow in workflows}
        for procedure in procedures:
            if procedure.validation_status != "needs_review":
                raise ValueError(f"{procedure.procedure_id} must remain needs_review")
            if not procedure.action_tuple:
                raise ValueError(f"{procedure.procedure_id} is missing action_tuple")
            if not set(procedure.source_procedure_candidate_ids).issubset(source_procedure_ids):
                raise ValueError(f"{procedure.procedure_id} cites unknown source procedure")
            if self._contains_case_like_token(procedure.procedure_id):
                raise ValueError(f"{procedure.procedure_id} contains a case-like identifier")
            if not procedure.role_required:
                raise ValueError(f"{procedure.procedure_id} is missing role_required")
            for step in procedure.steps:
                if not step.evidence_refs:
                    raise ValueError(f"{procedure.procedure_id} has a step without evidence")
            self._validate_evidence_refs(procedure.procedure_id, procedure.evidence_refs, evidence_ids)
            self._validate_restart_group(procedure)
        for workflow in workflows:
            if workflow.status != "draft" or workflow.validation_status != "needs_review":
                raise ValueError(f"{workflow.workflow_id} must remain draft needs_review")
            if not set(workflow.source_workflow_candidate_ids).issubset(source_workflow_ids):
                raise ValueError(f"{workflow.workflow_id} cites unknown source workflow")
            if self._contains_case_like_token(workflow.workflow_id):
                raise ValueError(f"{workflow.workflow_id} contains a case-like identifier")
            if not workflow.procedure_refs or not set(workflow.procedure_refs).issubset(procedure_ids):
                raise ValueError(f"{workflow.workflow_id} lacks valid procedure linkage")
            for step in workflow.steps:
                if not step.evidence_refs:
                    raise ValueError(f"{workflow.workflow_id} has a step without evidence")
                if not step.procedure_refs:
                    raise ValueError(f"{workflow.workflow_id} has a step without procedure refs")
            self._validate_evidence_refs(workflow.workflow_id, workflow.evidence_refs, evidence_ids)
        for link in links:
            if link.workflow_id not in workflow_ids or link.procedure_id not in procedure_ids:
                raise ValueError(f"{link.link_id} links unknown workflow/procedure")
            if not set(link.source_workflow_candidate_ids).issubset(source_workflow_ids):
                raise ValueError(f"{link.link_id} cites unknown source workflow")
            if not set(link.source_procedure_candidate_ids).issubset(source_procedure_ids):
                raise ValueError(f"{link.link_id} cites unknown source procedure")
            self._validate_evidence_refs(link.link_id, link.evidence_refs, evidence_ids)

    def _validate_evidence_refs(self, artifact_id: str, refs: list[EvidenceReference], evidence_ids: set[str]) -> None:
        missing = [ref.evidence_id for ref in refs if ref.evidence_id not in evidence_ids]
        if missing:
            raise ValueError(f"{artifact_id} cites unknown evidence refs: {missing[:5]}")

    def _validate_restart_group(self, procedure: ProcedureCandidate) -> None:
        tuple_value = procedure.action_tuple
        action_type = self._normalize_text(tuple_value.get("action_type"))
        if action_type != "restart":
            return
        target = self._normalize_restart_target(tuple_value)
        source_targets = {
            self._normalize_restart_target(self._infer_action_tuple_from_text(source_id))
            for source_id in procedure.source_procedure_candidate_ids
        }
        source_targets.discard("")
        if len(source_targets) > 1:
            raise ValueError(f"{procedure.procedure_id} merges incompatible restart targets")

    def _normalize_restart_target(self, tuple_value: dict[str, Any]) -> str:
        text = self._normalize_text(" ".join(str(tuple_value.get(key) or "") for key in ["target_system", "target_component", "operational_scope"]))
        if "lane" in text:
            return "lane"
        if "wcs" in text and "web" in text:
            return "wcs_web_application"
        if "robot" in text or "agv" in text:
            return "robot"
        if "hmi" in text:
            return "hmi"
        if "ignition" in text:
            return "ignition"
        if "optisweep" in text and "service" in text:
            return "optisweep_service"
        if "service" in text:
            return "service_unspecified"
        return self._slug(text)

    def _infer_action_tuple_from_text(self, value: str) -> dict[str, Any]:
        normalized = self._normalize_text(value.replace("_", " "))
        action_type = "restart" if "restart" in normalized else ""
        return {
            "action_type": action_type,
            "target_system": normalized,
            "target_component": normalized,
            "operational_scope": normalized,
        }

    def _evidence_index(self, package: dict[str, Any]) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        for record in package.get("raw_evidence_chunks", []):
            evidence_id = str(record.get("chunk_id") or record.get("id") or "")
            if evidence_id:
                index[evidence_id] = {
                    "evidence_id": evidence_id,
                    "incident_id": self._incident_id(record),
                    "source_type": record.get("source_type") or record.get("evidence_type"),
                    "summary": self._truncate(record.get("chunk_text") or record.get("retrieval_text") or record.get("summary"), 280),
                }
        for record in package.get("source_artifacts", []):
            artifact_id = str(record.get("artifact_id") or record.get("id") or "")
            if artifact_id:
                index[artifact_id] = {
                    "evidence_id": artifact_id,
                    "incident_id": self._incident_id(record),
                    "source_type": record.get("artifact_type") or "source_artifact",
                    "summary": self._truncate(record.get("description") or record.get("retrieval_text") or record.get("file_name"), 220),
                }
        for collection_name in ["prior_procedure_candidates", "prior_workflow_candidates"]:
            for record in package.get(collection_name, []):
                incident_ids = self._as_string_list(record.get("related_incidents") or record.get("related_cases"))
                for ref in self._as_list(record.get("evidence_refs")):
                    evidence_ref = self._coerce_evidence_ref(ref, incident_ids[0] if incident_ids else "unknown")
                    if evidence_ref.evidence_id and evidence_ref.evidence_id not in index:
                        index[evidence_ref.evidence_id] = {
                            "evidence_id": evidence_ref.evidence_id,
                            "incident_id": evidence_ref.incident_id,
                            "source_type": "candidate_evidence_ref",
                            "summary": evidence_ref.excerpt,
                        }
        return index

    def _artifact_index(self, artifacts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        for record in artifacts:
            artifact_id = str(record.get("artifact_id") or record.get("id") or "")
            if artifact_id:
                index[artifact_id] = {
                    "artifact_id": artifact_id,
                    "incident_id": self._incident_id(record),
                    "artifact_type": record.get("artifact_type"),
                    "file_name": record.get("file_name"),
                    "description": self._truncate(record.get("description") or record.get("retrieval_text"), 220),
                }
        return index

    def _incident_brief(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "incident_id": self._incident_id(record),
            "issue_category": record.get("issue_category"),
            "title": record.get("title") or record.get("failure_signature"),
            "observed_signals": self._observed_signals(record),
            "candidate_inferred_causes": record.get("candidate_inferred_causes", []),
            "resolution_summary": record.get("resolution_summary"),
            "resolution_status": record.get("resolution_status"),
        }

    def _candidate_causes(self, incident_ids: list[str], incidents: dict[str, dict[str, Any]]) -> list[Any]:
        causes = []
        for incident_id in incident_ids:
            incident = incidents.get(incident_id, {})
            causes.extend(self._as_list(incident.get("candidate_inferred_causes")))
        return causes

    def _resolution_behavior(self, incident_ids: list[str], incidents: dict[str, dict[str, Any]]) -> list[str]:
        behavior = []
        for incident_id in incident_ids:
            incident = incidents.get(incident_id, {})
            for field_name in ["resolution_summary", "resolution_status"]:
                if incident.get(field_name):
                    behavior.append(str(incident[field_name]))
        return list(dict.fromkeys(behavior))

    def _evidence_refs_payload(
        self,
        raw_refs: Any,
        incident_ids: list[str],
        evidence_index: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        refs = []
        default_incident = incident_ids[0] if incident_ids else "unknown"
        for raw_ref in self._as_list(raw_refs):
            ref = self._coerce_evidence_ref(raw_ref, default_incident)
            if not ref.evidence_id:
                continue
            payload = ref.model_dump(exclude_none=True)
            if ref.evidence_id in evidence_index:
                payload["evidence_summary"] = evidence_index[ref.evidence_id].get("summary")
                payload["source_type"] = evidence_index[ref.evidence_id].get("source_type")
            refs.append(payload)
        return refs

    def _artifact_refs_payload(self, raw_refs: Any, artifact_index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        refs = []
        for raw_ref in self._as_string_list(raw_refs):
            payload = {"artifact_id": raw_ref}
            if raw_ref in artifact_index:
                payload.update(artifact_index[raw_ref])
            refs.append(payload)
        return refs

    def _parse_json_response(self, content: str) -> dict[str, Any]:
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                return json.loads(content[start : end + 1])
            raise

    def _looks_like_copied_narrative(self, value: str) -> bool:
        normalized = self._normalize_text(value)
        narrative_terms = [
            "support documented",
            "reported as",
            "communicated to stakeholders",
            "while still working through",
            "original issue",
            "case ",
            "incident ",
        ]
        return len(normalized) > 420 or any(term in normalized for term in narrative_terms)

    def _truncate(self, value: Any, limit: int) -> str | None:
        if value is None:
            return None
        text = re.sub(r"\s+", " ", str(value)).strip()
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."

    def _group_by_incident(self, records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            incident_id = self._incident_id(record)
            if incident_id:
                grouped[incident_id].append(record)
        return grouped

    def _taxonomy_signals(self, taxonomy: dict[str, Any]) -> set[str]:
        signals: set[str] = set()
        for category in taxonomy.get("categories", []):
            signals.update(str(signal) for signal in category.get("signals", []))
        return signals

    def _extract_action_groups(
        self,
        incidents: list[dict[str, Any]],
        events_by_incident: dict[str, list[dict[str, Any]]],
        evidence_by_incident: dict[str, list[dict[str, Any]]],
        artifacts_by_incident: dict[str, list[dict[str, Any]]],
        taxonomy_signals: set[str],
        prior_candidates: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for incident in incidents:
            incident_id = self._incident_id(incident)
            if not incident_id:
                continue
            for event in sorted(events_by_incident.get(incident_id, []), key=self._event_order):
                action_text = self._action_text(event)
                if not self._is_operational_action(action_text):
                    continue
                evidence_refs = self._event_evidence_refs(event, incident_id, evidence_by_incident.get(incident_id, []))
                if not evidence_refs:
                    event_id = event.get("event_id") or "unknown_event"
                    raise ValueError(f"{event_id} contains an operational action without evidence")
                image_refs = self._artifact_refs(event, artifacts_by_incident.get(incident_id, []))
                action_key = self._action_key(action_text, taxonomy_signals)
                groups[action_key].append(
                    {
                        "incident": incident,
                        "event": event,
                        "action_text": action_text,
                        "evidence_refs": evidence_refs,
                        "image_refs": image_refs,
                        "source_artifacts": image_refs,
                    }
                )
        for candidate in prior_candidates:
            action_text = str(candidate.get("purpose") or candidate.get("operational_intent") or candidate.get("title") or "")
            if not self._is_operational_action(action_text):
                continue
            incident_ids = [str(value) for value in self._as_list(candidate.get("related_incidents"))]
            evidence_refs = [self._coerce_evidence_ref(ref, incident_ids[0] if incident_ids else "unknown") for ref in self._as_list(candidate.get("evidence_refs"))]
            evidence_refs = [ref for ref in evidence_refs if ref.evidence_id]
            if not evidence_refs:
                continue
            groups[self._action_key(action_text, taxonomy_signals)].append(
                {
                    "incident": {"incident_id": incident_ids[0] if incident_ids else "unknown", "issue_category": candidate.get("issue_category")},
                    "event": {},
                    "action_text": action_text,
                    "evidence_refs": evidence_refs,
                    "image_refs": self._as_string_list(candidate.get("source_artifacts")),
                    "source_artifacts": self._as_string_list(candidate.get("source_artifacts")),
                }
            )
        return groups

    def _build_procedures(self, action_groups: dict[str, list[dict[str, Any]]]) -> tuple[list[ProcedureCandidate], list[ReviewNote]]:
        procedures: list[ProcedureCandidate] = []
        notes: list[ReviewNote] = []
        for action_key, items in sorted(action_groups.items()):
            first = items[0]
            action_texts = [item["action_text"] for item in items]
            title = self._title(action_key)
            related_incidents = sorted({self._incident_id(item["incident"]) for item in items if self._incident_id(item["incident"])})
            issue_categories = sorted({str(item["incident"].get("issue_category")) for item in items if item["incident"].get("issue_category")})
            role_required = self._role_required(action_texts, items)
            support_safe = not self._is_unsafe(action_texts, role_required)
            evidence_refs = self._dedupe_evidence([ref for item in items for ref in item["evidence_refs"]])
            image_refs = sorted({ref for item in items for ref in item["image_refs"]})
            source_artifacts = sorted({ref for item in items for ref in item["source_artifacts"]})
            screenshot_required = self._needs_screenshot(action_texts)
            step = ProcedureStep(
                step_number=1,
                instruction=self._instruction(first["action_text"]),
                expected_result=self._expected_result(first["action_text"]),
                validation_check=self._validation_check(first["action_text"]),
                evidence_refs=evidence_refs,
                image_refs=image_refs,
                screenshot_required=screenshot_required,
                risk_notes="Requires non-support role or explicit SME review before execution." if not support_safe else "",
            )
            procedure = ProcedureCandidate(
                procedure_id=self._versioned_id(action_key),
                title=title,
                issue_category=issue_categories[0] if len(issue_categories) == 1 else None,
                purpose=self._purpose(first["action_text"]),
                operational_intent=self._purpose(first["action_text"]),
                role_required=role_required,
                support_safe=support_safe,
                preconditions=self._preconditions(items),
                steps=[step],
                do_not_do=self._do_not_do(support_safe),
                validation_checks=[step.validation_check or ""],
                escalation_conditions=self._escalation_conditions(action_texts, support_safe),
                related_incidents=related_incidents,
                evidence_refs=evidence_refs,
                source_artifacts=source_artifacts,
                confidence=self._confidence(items, evidence_refs, image_refs),
                validation_status="needs_review",
            )
            procedures.append(procedure)
            if screenshot_required and not image_refs:
                notes.append(
                    self._review_note(
                        "procedure",
                        procedure.procedure_id,
                        "warning",
                        "Procedure likely needs screenshot guidance, but no screenshot/source artifact was linked.",
                        "SME reviewer",
                        evidence_refs,
                    )
                )
            if not support_safe:
                notes.append(
                    self._review_note(
                        "procedure",
                        procedure.procedure_id,
                        "warning",
                        "Procedure includes potentially unsafe or role-restricted operational action.",
                        role_required,
                        evidence_refs,
                    )
                )
        return procedures, notes

    def _build_workflows(
        self,
        incidents: list[dict[str, Any]],
        procedures: list[ProcedureCandidate],
        events_by_incident: dict[str, list[dict[str, Any]]],
    ) -> tuple[list[WorkflowCandidate], list[WorkflowProcedureLink], list[ReviewNote]]:
        procedure_by_incident: dict[str, list[ProcedureCandidate]] = defaultdict(list)
        for procedure in procedures:
            for incident_id in procedure.related_incidents:
                procedure_by_incident[incident_id].append(procedure)

        workflow_groups: dict[tuple[str | None, tuple[str, ...]], list[dict[str, Any]]] = defaultdict(list)
        for incident in incidents:
            incident_id = self._incident_id(incident)
            if not incident_id or not procedure_by_incident.get(incident_id):
                continue
            observed_signals = self._observed_signals(incident)
            signature = tuple(sorted(observed_signals[:4]))
            workflow_groups[(incident.get("issue_category"), signature)].append(incident)

        workflows: list[WorkflowCandidate] = []
        links: list[WorkflowProcedureLink] = []
        notes: list[ReviewNote] = []
        for (issue_category, signature), group in sorted(workflow_groups.items(), key=lambda item: (str(item[0][0]), item[0][1])):
            related_cases = sorted({self._incident_id(incident) for incident in group if self._incident_id(incident)})
            group_procedures = self._ordered_workflow_procedures(group, procedure_by_incident, events_by_incident)
            procedure_refs = list(dict.fromkeys(procedure.procedure_id for procedure in group_procedures))
            evidence_refs = self._dedupe_evidence([ref for procedure in group_procedures for ref in procedure.evidence_refs])
            image_refs = sorted({ref for procedure in group_procedures for ref in procedure.source_artifacts})
            workflow_id = self._workflow_id(signature, procedure_refs)
            steps = [
                WorkflowCandidateStep(
                    step_id=f"step_{index:02d}",
                    step_type=self._workflow_step_type(procedure),
                    question=self._workflow_question(procedure),
                    why_asked="This evidence-backed action appears in incidents with the same observable troubleshooting signature.",
                    instruction=f"Use procedure {procedure.procedure_id}.",
                    role_required=procedure.role_required,
                    support_safe=bool(procedure.support_safe),
                    procedure_refs=[procedure.procedure_id],
                    image_refs=procedure.source_artifacts,
                    evidence_refs=procedure.evidence_refs,
                    expected_outcome=procedure.steps[0].expected_result if procedure.steps else None,
                    branches=[],
                    escalation_conditions=procedure.escalation_conditions,
                )
                for index, procedure in enumerate(group_procedures, start=1)
            ]
            workflow = WorkflowCandidate(
                workflow_id=workflow_id,
                workflow_version="0.1",
                title=self._title(workflow_id),
                issue_category=str(issue_category) if issue_category else None,
                entry_conditions=list(signature),
                required_signals=list(signature),
                exclusion_conditions=[],
                minimum_confidence=0.75,
                roles_allowed=sorted({procedure.role_required for procedure in group_procedures if procedure.role_required}),
                steps=steps,
                validation_checks=[f"Review evidence-backed outcome for {procedure.procedure_id}." for procedure in group_procedures],
                escalation_conditions=sorted({condition for procedure in group_procedures for condition in procedure.escalation_conditions}),
                evidence_refs=evidence_refs,
                procedure_refs=procedure_refs,
                image_refs=image_refs,
                related_cases=related_cases,
                related_incidents=related_cases,
                confidence=self._workflow_confidence(group, group_procedures, evidence_refs),
                status="draft",
                validation_status="needs_review",
            )
            workflows.append(workflow)
            for procedure in group_procedures:
                step_ids = [step.step_id for step in steps if procedure.procedure_id in step.procedure_refs]
                links.append(
                    WorkflowProcedureLink(
                        link_id=f"link_{workflow.workflow_id}_{procedure.procedure_id}",
                        workflow_id=workflow.workflow_id,
                        procedure_id=procedure.procedure_id,
                        step_ids=step_ids,
                        related_incidents=related_cases,
                        evidence_refs=procedure.evidence_refs,
                        image_refs=procedure.source_artifacts,
                        rationale="Workflow step references a reusable procedure supported by incident evidence.",
                        confidence=min(workflow.confidence, procedure.confidence),
                        validation_status="needs_review",
                    )
                )
            if len(group) == 1:
                notes.append(
                    self._review_note(
                        "workflow",
                        workflow.workflow_id,
                        "info",
                        "Workflow candidate is based on a single incident signature and needs cross-incident SME review before promotion.",
                        "SME reviewer",
                        evidence_refs,
                    )
                )
        return workflows, links, notes

    def _ordered_workflow_procedures(
        self,
        incidents: list[dict[str, Any]],
        procedure_by_incident: dict[str, list[ProcedureCandidate]],
        events_by_incident: dict[str, list[dict[str, Any]]],
    ) -> list[ProcedureCandidate]:
        ordered: list[ProcedureCandidate] = []
        for incident in incidents:
            incident_id = self._incident_id(incident)
            event_texts = [self._action_key(self._action_text(event), set()) for event in sorted(events_by_incident.get(incident_id, []), key=self._event_order)]
            procedures = procedure_by_incident.get(incident_id, [])
            procedures = sorted(procedures, key=lambda procedure: self._procedure_order(procedure, event_texts))
            for procedure in procedures:
                if procedure.procedure_id not in {existing.procedure_id for existing in ordered}:
                    ordered.append(procedure)
        return ordered

    def _validate_outputs(
        self,
        procedures: list[ProcedureCandidate],
        workflows: list[WorkflowCandidate],
        links: list[WorkflowProcedureLink],
    ) -> None:
        for procedure in procedures:
            if procedure.validation_status != "needs_review":
                raise ValueError(f"{procedure.procedure_id} must remain needs_review")
            if not procedure.role_required:
                raise ValueError(f"{procedure.procedure_id} is missing role_required")
            for step in procedure.steps:
                if not step.evidence_refs:
                    raise ValueError(f"{procedure.procedure_id} has a step without evidence")
            if procedure.support_safe is False and not procedure.escalation_conditions:
                raise ValueError(f"{procedure.procedure_id} is missing escalation boundaries")
        procedure_ids = {procedure.procedure_id for procedure in procedures}
        for workflow in workflows:
            if workflow.validation_status != "needs_review" or workflow.status != "draft":
                raise ValueError(f"{workflow.workflow_id} must remain draft needs_review")
            if self._contains_case_like_token(workflow.workflow_id):
                raise ValueError(f"{workflow.workflow_id} contains a case-like identifier")
            if not workflow.procedure_refs or not set(workflow.procedure_refs).issubset(procedure_ids):
                raise ValueError(f"{workflow.workflow_id} lacks valid procedure linkage")
            for step in workflow.steps:
                if not step.evidence_refs:
                    raise ValueError(f"{workflow.workflow_id} has a step without evidence")
                if not step.procedure_refs:
                    raise ValueError(f"{workflow.workflow_id} has a step without procedure refs")
                if step.support_safe is False and not step.escalation_conditions:
                    raise ValueError(f"{workflow.workflow_id} has unsafe step without escalation boundary")
        link_pairs = {(link.workflow_id, link.procedure_id) for link in links}
        for workflow in workflows:
            for procedure_id in workflow.procedure_refs:
                if (workflow.workflow_id, procedure_id) not in link_pairs:
                    raise ValueError(f"{workflow.workflow_id} is missing link for {procedure_id}")

    def _event_evidence_refs(
        self,
        event: dict[str, Any],
        incident_id: str,
        evidence_records: list[dict[str, Any]],
    ) -> list[EvidenceReference]:
        refs = []
        for value in self._as_list(event.get("evidence_refs")):
            refs.append(self._coerce_evidence_ref(value, incident_id))
        for field_name in ["supporting_evidence_chunks", "source_region_refs"]:
            for value in self._as_list(event.get(field_name)):
                refs.append(EvidenceReference(incident_id=incident_id, evidence_id=str(value)))
        for value in self._as_list(event.get("source_artifact_ids")):
            refs.append(EvidenceReference(incident_id=incident_id, evidence_id=str(value), source_artifact_id=str(value)))
        if not refs:
            refs.extend(self._matching_evidence(event, incident_id, evidence_records))
        return self._dedupe_evidence(refs)

    def _matching_evidence(self, event: dict[str, Any], incident_id: str, evidence_records: list[dict[str, Any]]) -> list[EvidenceReference]:
        event_text = self._normalize_text(self._action_text(event))
        scored = []
        for record in evidence_records:
            evidence_id = str(record.get("chunk_id") or record.get("id") or "")
            text = self._normalize_text(record.get("chunk_text") or record.get("retrieval_text") or record.get("summary") or "")
            if evidence_id and (not event_text or self._token_overlap(event_text, text) > 0):
                scored.append((self._token_overlap(event_text, text), record))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            EvidenceReference(incident_id=incident_id, evidence_id=str(record.get("chunk_id") or record.get("id")))
            for _, record in scored[:2]
        ]

    def _artifact_refs(self, event: dict[str, Any], artifacts: list[dict[str, Any]]) -> list[str]:
        explicit = self._as_string_list(event.get("source_artifact_ids"))
        if explicit:
            return explicit
        action_text = self._normalize_text(self._action_text(event))
        refs = []
        for artifact in artifacts:
            artifact_id = str(artifact.get("artifact_id") or artifact.get("id") or "")
            if not artifact_id:
                continue
            haystack = self._normalize_text(" ".join(str(artifact.get(field) or "") for field in ["artifact_type", "file_name", "description", "retrieval_text"]))
            if self._is_image_artifact(artifact) and self._token_overlap(action_text, haystack) > 0:
                refs.append(artifact_id)
        return list(dict.fromkeys(refs))

    def _is_image_artifact(self, artifact: dict[str, Any]) -> bool:
        text = " ".join(str(artifact.get(field) or "") for field in ["artifact_type", "file_name", "file_path"]).lower()
        return any(term in text for term in ["image", "screenshot", ".png", ".jpg", ".jpeg", ".webp"])

    def _action_text(self, event: dict[str, Any]) -> str:
        values = [
            event.get("action_taken"),
            event.get("event_summary"),
            event.get("summary"),
            event.get("outcome"),
            event.get("next_action"),
        ]
        return ". ".join(str(value).strip() for value in values if str(value or "").strip())

    def _is_operational_action(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        return any(re.search(rf"\b{re.escape(verb)}\b", normalized) for verb in ACTION_VERBS)

    def _action_key(self, text: str, taxonomy_signals: set[str]) -> str:
        normalized = self._normalize_text(text)
        normalized = re.sub(r"\b(?:case|incident|agv|robot|tote)?\s*#?\d{4,}\b", " ", normalized)
        signal_terms = [signal for signal in taxonomy_signals if signal.replace("_", " ") in normalized]
        words = [word for word in re.findall(r"[a-z][a-z0-9]+", normalized) if word not in {"and", "the", "with", "from", "that", "then", "after", "before"}]
        if signal_terms:
            words.extend(signal_terms)
        verbs = [word for word in words if word in ACTION_VERBS]
        anchors = [word for word in words if word not in ACTION_VERBS][:5]
        key_words = (verbs[:2] or words[:2]) + anchors[:5]
        return self._slug("_".join(key_words[:7]) or "review_operational_evidence")

    def _workflow_id(self, signature: tuple[str, ...], procedure_refs: list[str]) -> str:
        terms = list(signature[:4]) or [ref.replace("_v1", "") for ref in procedure_refs[:2]]
        workflow_id = self._slug("_".join(terms))[:70].strip("_")
        return f"{workflow_id}_v1" if workflow_id and not workflow_id.endswith("_v1") else workflow_id or "candidate_workflow_v1"

    def _versioned_id(self, value: str) -> str:
        slug = self._slug(value)
        return slug if slug.endswith("_v1") else f"{slug}_v1"

    def _title(self, value: str) -> str:
        return self._slug(value).replace("_", " ").title()

    def _slug(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")

    def _normalize_text(self, value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "").lower()).strip()

    def _token_overlap(self, left: str, right: str) -> int:
        left_tokens = {token for token in re.findall(r"[a-z0-9]+", left) if len(token) > 2}
        right_tokens = {token for token in re.findall(r"[a-z0-9]+", right) if len(token) > 2}
        return len(left_tokens & right_tokens)

    def _instruction(self, action_text: str) -> str:
        return action_text.strip().rstrip(".") + "."

    def _purpose(self, action_text: str) -> str:
        return f"Perform the evidence-backed operational action: {action_text.strip().rstrip('.')}."

    def _expected_result(self, action_text: str) -> str:
        if any(term in self._normalize_text(action_text) for term in ["confirm", "validate", "verify", "check", "review"]):
            return "The observed operational state is documented and can be compared with expected behavior."
        return "The action outcome is documented with evidence for SME review."

    def _validation_check(self, action_text: str) -> str:
        if any(term in self._normalize_text(action_text) for term in ["restart", "reset", "start", "stop"]):
            return "Confirm the affected service or system returns to the expected running state."
        return "Confirm the captured evidence supports the action and resulting state."

    def _role_required(self, action_texts: list[str], items: list[dict[str, Any]]) -> str:
        roles = [str(item["event"].get("actor_role") or "").strip() for item in items if item.get("event")]
        normalized_roles = [role for role in roles if role]
        text = self._normalize_text(" ".join(action_texts + normalized_roles))
        if any(term in text for term in ["engineer", "field", "controls", "project team"]):
            return "engineer"
        if any(term in text for term in INFRASTRUCTURE_TERMS):
            return "infrastructure"
        return "support"

    def _is_unsafe(self, action_texts: list[str], role_required: str) -> bool:
        text = self._normalize_text(" ".join(action_texts))
        return role_required != "support" or any(term in text for term in UNSAFE_ACTION_TERMS)

    def _needs_screenshot(self, action_texts: list[str]) -> bool:
        text = self._normalize_text(" ".join(action_texts))
        return any(term in text for term in VISUAL_GUIDANCE_TERMS)

    def _preconditions(self, items: list[dict[str, Any]]) -> list[str]:
        signals = []
        for item in items:
            signals.extend(self._observed_signals(item["incident"]))
        return list(dict.fromkeys(signals[:6]))

    def _do_not_do(self, support_safe: bool) -> list[str]:
        if support_safe:
            return ["Do not treat this candidate as approved runtime guidance until SME review is complete."]
        return [
            "Do not execute this action from support-only access.",
            "Do not treat this candidate as approved runtime guidance until SME review is complete.",
        ]

    def _escalation_conditions(self, action_texts: list[str], support_safe: bool) -> list[str]:
        conditions = ["Escalate if evidence does not confirm the expected state or the action boundary is unclear."]
        if not support_safe:
            conditions.append("Escalate to the required operational owner before execution.")
        return conditions

    def _workflow_step_type(self, procedure: ProcedureCandidate) -> str:
        text = self._normalize_text(" ".join(step.instruction for step in procedure.steps))
        if any(term in text for term in ["confirm", "review", "verify", "check", "inspect", "collect", "capture"]):
            return "diagnostic_check"
        if procedure.support_safe is False:
            return "escalation"
        return "action"

    def _workflow_question(self, procedure: ProcedureCandidate) -> str:
        return f"Does the current evidence support running {procedure.title}?"

    def _confidence(self, items: list[dict[str, Any]], evidence_refs: list[EvidenceReference], image_refs: list[str]) -> float:
        incident_count = len({self._incident_id(item["incident"]) for item in items if self._incident_id(item["incident"])})
        score = 0.35 + min(0.25, 0.08 * incident_count) + min(0.25, 0.04 * len(evidence_refs)) + (0.15 if image_refs else 0.0)
        return round(min(score, 0.95), 2)

    def _workflow_confidence(
        self,
        incidents: list[dict[str, Any]],
        procedures: list[ProcedureCandidate],
        evidence_refs: list[EvidenceReference],
    ) -> float:
        score = 0.35 + min(0.25, 0.08 * len(incidents)) + min(0.2, 0.05 * len(procedures)) + min(0.2, 0.03 * len(evidence_refs))
        return round(min(score, 0.95), 2)

    def _duplicate_notes(self, procedures: list[ProcedureCandidate], workflows: list[WorkflowCandidate]) -> list[ReviewNote]:
        notes: list[ReviewNote] = []
        procedures_by_title: dict[str, list[ProcedureCandidate]] = defaultdict(list)
        workflows_by_signals: dict[tuple[str, ...], list[WorkflowCandidate]] = defaultdict(list)
        for procedure in procedures:
            procedures_by_title[self._slug(procedure.title or procedure.procedure_id)].append(procedure)
        for workflow in workflows:
            workflows_by_signals[tuple(sorted(workflow.required_signals))].append(workflow)
        for duplicates in procedures_by_title.values():
            if len(duplicates) > 1:
                for procedure in duplicates:
                    notes.append(self._review_note("procedure", procedure.procedure_id, "info", "Procedure overlaps with another candidate and should be reviewed for duplication.", "SME reviewer", procedure.evidence_refs))
        for duplicates in workflows_by_signals.values():
            if len(duplicates) > 1:
                for workflow in duplicates:
                    notes.append(self._review_note("workflow", workflow.workflow_id, "info", "Workflow overlaps with another candidate signature and should be reviewed for consolidation.", "SME reviewer", workflow.evidence_refs))
        return notes

    def _review_note(
        self,
        artifact_type: str,
        artifact_id: str,
        severity: str,
        note: str,
        owner: str,
        evidence_refs: list[EvidenceReference],
    ) -> ReviewNote:
        note_id = self._slug(f"note_{artifact_type}_{artifact_id}_{severity}_{note}")[:120]
        return ReviewNote(
            note_id=note_id,
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            severity=severity,
            note=note,
            recommended_review_owner=owner,
            evidence_refs=evidence_refs,
        )

    def _observed_signals(self, record: dict[str, Any]) -> list[str]:
        signals = []
        for field_name in OBSERVED_SIGNAL_FIELDS:
            signals.extend(self._as_string_list(record.get(field_name)))
        return list(dict.fromkeys(signal for signal in signals if signal))

    def _event_order(self, event: dict[str, Any]) -> tuple[int, str]:
        raw_order = event.get("event_order") or event.get("sequence") or 0
        try:
            order = int(raw_order)
        except (TypeError, ValueError):
            order = 0
        return order, str(event.get("event_id") or "")

    def _procedure_order(self, procedure: ProcedureCandidate, event_keys: list[str]) -> int:
        target = procedure.procedure_id.replace("_v1", "")
        for index, event_key in enumerate(event_keys):
            if target in event_key or event_key in target:
                return index
        return len(event_keys)

    def _contains_case_like_token(self, value: str) -> bool:
        return bool(re.search(r"(?:case|incident|site|customer)_?\d{4,}|\b\d{5,}\b", value.lower()))

    def _coerce_evidence_ref(self, value: Any, incident_id: str) -> EvidenceReference:
        if isinstance(value, EvidenceReference):
            return value
        if isinstance(value, dict):
            return EvidenceReference(
                incident_id=str(value.get("incident_id") or incident_id),
                evidence_id=str(value.get("evidence_id") or value.get("chunk_id") or value.get("artifact_id") or ""),
                source_artifact_id=value.get("source_artifact_id"),
                excerpt=value.get("excerpt"),
            )
        return EvidenceReference(incident_id=incident_id, evidence_id=str(value))

    def _dedupe_evidence(self, refs: list[EvidenceReference]) -> list[EvidenceReference]:
        seen: set[tuple[str, str, str | None]] = set()
        deduped: list[EvidenceReference] = []
        for ref in refs:
            key = (ref.incident_id, ref.evidence_id, ref.source_artifact_id)
            if ref.evidence_id and key not in seen:
                seen.add(key)
                deduped.append(ref)
        return deduped

    def _incident_id(self, record: dict[str, Any] | None) -> str:
        if not record:
            return ""
        return str(record.get("incident_id") or record.get("source_case_id") or record.get("case_id") or "").strip()

    def _as_list(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    def _as_string_list(self, value: Any) -> list[str]:
        values = []
        for item in self._as_list(value):
            if isinstance(item, dict):
                for field_name in ["artifact_id", "source_artifact_id", "evidence_id", "id"]:
                    if item.get(field_name):
                        values.append(str(item[field_name]))
                        break
                continue
            if str(item or "").strip():
                values.append(str(item))
        return values
