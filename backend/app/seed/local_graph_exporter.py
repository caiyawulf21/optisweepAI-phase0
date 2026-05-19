from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from backend.app.seed.local_dataset_mapper import DATASET_PATHS, load_json


DATASET_GRAPHS = {
    "context_reference": Path("context/graph.md"),
    "canonical_incidents": Path("incidents/graph.md"),
    "timeline_events": Path("timelines/graph.md"),
    "raw_evidence_chunks": Path("evidence/graph.md"),
    "cat1_records": Path("curated/graph.md"),
    "sme_review_queue": Path("review/graph.md"),
}


def node_id(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_")
    return normalized or "node"


def record_id(record: dict[str, Any], fallback: str) -> str:
    for field_name in ["id", "record_id", "incident_id", "event_id", "chunk_id", "artifact_id", "procedure_id", "workflow_id", "review_item_id"]:
        if record.get(field_name):
            return str(record[field_name])
    return fallback


def write_markdown(path: Path, title: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")


def dataset_graph(name: str, records: list[dict[str, Any]]) -> str:
    lines = ["```mermaid", "flowchart TD", f"  dataset[{node_id(name)}]"]
    for index, record in enumerate(records[:40], start=1):
        item_id = record_id(record, f"{name}_{index}")
        lines.append(f"  dataset --> {node_id(item_id)}[{item_id}]")
    if not records:
        lines.append("  dataset --> empty[empty]")
    lines.append("```")
    return "\n".join(lines)


def procedure_graph(record: dict[str, Any]) -> str:
    procedure_id = str(record.get("procedure_id") or record.get("id") or "procedure")
    lines = ["```mermaid", "flowchart TD", f"  start[{procedure_id}]"]
    previous = "start"
    for index, step in enumerate(record.get("steps", []), start=1):
        step_name = str(step.get("step_id") or f"step_{index:02d}") if isinstance(step, dict) else f"step_{index:02d}"
        current = node_id(step_name)
        lines.append(f"  {previous} --> {current}[{step_name}]")
        previous = current
    for incident in record.get("related_incidents", []):
        lines.append(f"  {node_id(str(incident))}[incident_{incident}] --> start")
    for ref in record.get("evidence_refs", []):
        evidence_id = ref.get("evidence_id") if isinstance(ref, dict) else str(ref)
        lines.append(f"  {node_id(str(evidence_id))}[evidence_{evidence_id}] --> start")
    lines.append("```")
    return "\n".join(lines)


def workflow_graph(record: dict[str, Any]) -> str:
    workflow_id = str(record.get("workflow_id") or record.get("id") or "workflow")
    lines = ["```mermaid", "flowchart TD", f"  workflow[{workflow_id}]"]
    for signal in record.get("required_signals", []):
        lines.append(f"  {node_id(str(signal))}[signal_{signal}] --> workflow")
    for procedure in record.get("procedure_refs", []):
        lines.append(f"  workflow --> {node_id(str(procedure))}[procedure_{procedure}]")
    for incident in record.get("related_incidents", []):
        lines.append(f"  {node_id(str(incident))}[incident_{incident}] --> workflow")
    for ref in record.get("evidence_refs", []):
        evidence_id = ref.get("evidence_id") if isinstance(ref, dict) else str(ref)
        lines.append(f"  {node_id(str(evidence_id))}[evidence_{evidence_id}] --> workflow")
    lines.append("```")
    return "\n".join(lines)


def export_graphs(data_root: Path = Path("data")) -> dict[str, int]:
    counts = {}
    for dataset_name, graph_path in DATASET_GRAPHS.items():
        records = load_json(data_root / DATASET_PATHS[dataset_name])
        records = records if isinstance(records, list) else []
        write_markdown(data_root / graph_path, dataset_name.replace("_", " ").title(), dataset_graph(dataset_name, records))
        counts[str(graph_path)] = len(records)

    procedure_records = []
    for dataset_name in ["procedure_candidates", "reusable_procedures"]:
        records = load_json(data_root / DATASET_PATHS[dataset_name])
        procedure_records.extend(records if isinstance(records, list) else [])
    for record in procedure_records:
        procedure_id = str(record.get("procedure_id") or record.get("id") or "procedure")
        write_markdown(data_root / "procedures" / "graphs" / f"{node_id(procedure_id)}.md", procedure_id, procedure_graph(record))

    workflow_records = []
    for dataset_name in ["workflow_candidates", "workflow_definitions"]:
        records = load_json(data_root / DATASET_PATHS[dataset_name])
        workflow_records.extend(records if isinstance(records, list) else [])
    for record in workflow_records:
        workflow_id = str(record.get("workflow_id") or record.get("id") or "workflow")
        write_markdown(data_root / "workflows" / "graphs" / f"{node_id(workflow_id)}.md", workflow_id, workflow_graph(record))

    counts["procedure_graphs"] = len(procedure_records)
    counts["workflow_graphs"] = len(workflow_records)
    return counts
