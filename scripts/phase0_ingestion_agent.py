from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree as ET

import phase0_case_229716_v2 as toolkit


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUTPUT_DIR = ROOT / "output" / "phase0" / "case_229716_docx_agent"
EXTRACTED_DIR = OUTPUT_DIR / "extracted"
ARTIFACT_DIR = OUTPUT_DIR / "artifacts" / "docx_media"
EMBEDDED_ARTIFACT_DIR = OUTPUT_DIR / "artifacts" / "embedded_regions"
INTERPRETATION_ENGINE = "phase0_agent_cached_llm_v1"
AZURE_OPENAI_CONFIG_PATH = ROOT / "config" / "azure_openai.local.json"
INGESTION_EXAMPLES_PATH = ROOT / "prompts" / "phase0_ingestion_examples.json"
L4_SUPPORT_TIER = "L4_engineering_project_team"
L4_ESCALATION_SIGNAL = "l4_project_team_escalation"
AGENT_LLM_CONTEXT_OVERLAY = {
    "overlay_id": "l4_project_team_overlay",
    "overlay_type": "user_provided_context",
    "overlay_summary": "User indicated project team escalation occurred for the active case.",
    "applies_conditionally": True,
    "validation_status": "unverified_overlay",
    "case_id": "229716",
    "escalation_target": L4_SUPPORT_TIER,
    "overlay_source": "user_message",
    "applies_to": ["canonical_incident", "teams_derived_records", "escalation_summary_template"],
}
ALLOWED_ARTIFACT_ROLES = {
    "diagnostic_visual",
    "recovery_visual",
    "service_restart_visual",
    "heartbeat_visual",
    "operational_context",
    "escalation_attachment",
    "log_collection_visual",
    "validation_visual",
    "rms_state_visual",
}
ROLE_TO_ORGANIZATIONAL_ROLE = {
    "L1_technical_support": "technical_support",
    "L2_L3_software_support": "software_support",
    "L2_L3_infrastructure_controls_dba_devops": "infrastructure_support",
    "remote_service_access": "software_support",
    "service_restart_access": "software_support",
    "log_access": "infrastructure_support",
    "remote_visual_access": "software_support",
}
SOURCE_FILES = [
    "prompts/phase0_system_prompt.txt",
    "docs/Phase0 Cat1 Dataset Seed Records V1.docx",
    "docs/Optisweep Issue Categories.docx",
    toolkit.ACTIVE_SOURCE_FILE,
]

SYNTHESIS_POLICY = {
    "canonical_incident": "HIGH",
    "timeline_event": "MEDIUM_HIGH",
    "raw_evidence_chunk": "LOW_MEDIUM",
    "source_artifact_reference": "LOW",
    "procedure_candidate": "HIGH_WHEN_EVIDENCE_SUPPORTS",
    "workflow_candidate_step": "HIGH",
    "escalation_summary_template": "HIGH",
    "candidate_incident_record": "HIGH_SUMMARY_PROJECTION",
    "context_reference": "CURATED_CONTEXT_ONLY",
}

FALLBACK_QUALITY_TIER = "fallback_review_only"
LLM_QUALITY_TIER = "llm_operational_synthesis"


def qn(local_name: str) -> str:
    return "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}" + local_name


@dataclass
class Phase0AgentState:
    case_id: str = "229716"
    active_source_file: str = toolkit.ACTIVE_SOURCE_FILE
    source_docx_path: Path | None = None
    source_kind: str = "docx"
    output_prefix: str = "case_229716"
    use_generic_interpretation: bool = False
    source_ocr_path: Path = toolkit.SOURCE_OCR_PATH
    reference_extraction_path: Path = toolkit.REFERENCE_EXTRACTION_PATH
    prompt_path: Path = toolkit.PHASE0_PROMPT_PATH
    output_dir: Path = OUTPUT_DIR
    extracted_dir: Path = EXTRACTED_DIR
    artifact_dir: Path = ARTIFACT_DIR
    embedded_artifact_dir: Path = EMBEDDED_ARTIFACT_DIR
    llm_config_path: Path | None = AZURE_OPENAI_CONFIG_PATH
    llm_provider: str = "not_configured"
    llm_deployment: str | None = None
    llm_status: str = "not_started"
    llm_error: str | None = None
    llm_usage: dict[str, Any] = field(default_factory=dict)
    llm_input_path: Path | None = None
    persist_to_knowledge_store: bool = False
    knowledge_store_dry_run: bool = False
    sync_search: bool = False
    upload_artifacts: bool = False
    knowledge_store_report: dict[str, Any] = field(default_factory=lambda: {"status": "not_requested"})
    ocr_data: dict[str, Any] | None = None
    prompt_text: str | None = None
    reference: dict[str, Any] | None = None
    layout_blocks: dict[str, Any] | None = None
    semantic_regions: dict[str, Any] | None = None
    interpretations: dict[str, Any] | None = None
    records: dict[str, Any] | None = None
    bundle: dict[str, Any] | None = None
    validation_report: dict[str, Any] | None = None
    contextual_overlays: list[dict[str, Any]] = field(default_factory=lambda: [copy.deepcopy(AGENT_LLM_CONTEXT_OVERLAY)])
    run_trace: list[dict[str, Any]] = field(default_factory=list)
    halted: bool = False
    halt_reason: str | None = None


Node = Callable[[Phase0AgentState], Phase0AgentState]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def configure_toolkit_paths(state: Phase0AgentState) -> None:
    toolkit.OUTPUT_DIR = state.output_dir
    toolkit.EXTRACTED_DIR = state.extracted_dir
    toolkit.ARTIFACT_DIR = state.artifact_dir
    toolkit.EMBEDDED_ARTIFACT_DIR = state.embedded_artifact_dir


def append_unique(values: list[Any], item: Any) -> list[Any]:
    if item not in values:
        values.append(item)
    return values


def remove_item(values: list[Any], item: Any) -> list[Any]:
    return [value for value in values if value != item]


def flat_records(records: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        records["canonical_incident"],
        *records["timeline_events"],
        *records["raw_evidence_chunks"],
        *records["source_artifact_references"],
        *records["procedure_candidates"],
        *records["workflow_candidate_steps"],
        records["escalation_summary_template"],
    ]


def record_identifier(record: dict[str, Any]) -> str:
    for field_name in ["event_id", "chunk_id", "procedure_id", "workflow_step_id", "artifact_id", "case_id", "incident_id"]:
        if record.get(field_name):
            return record[field_name]
    return record.get("record_type", "unknown_record")


def is_teams_derived(record: dict[str, Any]) -> bool:
    return (
        record.get("record_type") in {"canonical_incident", "escalation_summary_template"}
        or record.get("escalation_source") == "teams_chat"
        or "Teams" in str(record.get("source_section", ""))
        or any(str(ref).startswith("region_teams") for ref in record.get("source_region_refs", []))
    )


def state_outputs(state: Phase0AgentState) -> dict[str, Any]:
    return {
        "ocr_pages": len(state.ocr_data.get("pages", [])) if state.ocr_data else 0,
        "layout_pages": len(state.layout_blocks.get("pages", [])) if state.layout_blocks else 0,
        "semantic_regions": len(state.semantic_regions.get("regions", [])) if state.semantic_regions else 0,
        "has_interpretations": state.interpretations is not None,
        "llm_status": state.llm_status,
        "knowledge_store_status": state.knowledge_store_report.get("status"),
        "record_groups": sorted(state.records.keys()) if state.records else [],
        "validation_status": state.validation_report.get("validation_status") if state.validation_report else None,
    }


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def relative_path(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def load_ingestion_examples() -> dict[str, Any]:
    if not INGESTION_EXAMPLES_PATH.exists():
        return {
            "examples_source": relative_path(INGESTION_EXAMPLES_PATH),
            "examples_used": False,
        }
    examples = json.loads(INGESTION_EXAMPLES_PATH.read_text(encoding="utf-8"))
    return {
        "examples_source": relative_path(INGESTION_EXAMPLES_PATH),
        "examples_version": examples.get("examples_version"),
        "examples_used": True,
        "examples": examples,
    }


def compact_ingestion_examples(examples_context: dict[str, Any]) -> dict[str, Any]:
    if not examples_context.get("examples_used"):
        return examples_context
    examples = examples_context.get("examples", {})
    return {
        "examples_source": examples_context.get("examples_source"),
        "examples_version": examples_context.get("examples_version"),
        "examples_used": True,
        "good_canonical_incident_example": examples.get("good_canonical_incident_example"),
        "good_procedure_candidate_example": examples.get("good_procedure_candidate_example"),
        "good_workflow_candidate_example": examples.get("good_workflow_candidate_example"),
        "bad_examples": examples.get("bad_examples", []),
    }


def relationship_targets(archive: zipfile.ZipFile) -> dict[str, str]:
    rels_path = "word/_rels/document.xml.rels"
    if rels_path not in archive.namelist():
        return {}
    root = ET.fromstring(archive.read(rels_path))
    rels = {}
    for rel in root:
        rel_id = rel.attrib.get("Id")
        target = rel.attrib.get("Target")
        if rel_id and target:
            rels[rel_id] = "word/" + target.lstrip("/")
    return rels


def paragraph_text(para: ET.Element) -> str:
    parts = []
    for node in para.iter():
        if node.tag == qn("t") and node.text:
            parts.append(node.text)
        elif node.tag == qn("tab"):
            parts.append("\t")
        elif node.tag == qn("br"):
            parts.append("\n")
    return clean_text("".join(parts))


def embedded_relationship_ids(para: ET.Element) -> list[str]:
    ids = []
    for node in para.iter():
        if node.tag.endswith("}blip"):
            rel_id = node.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
            if rel_id:
                ids.append(rel_id)
    return ids


def section_from_heading(text: str, current_section: str) -> str:
    normalized = clean_text(text).lower()
    if "salesforce" in normalized and "case" in normalized:
        return "Salesforce Case Data"
    if "teams" in normalized or "support chat" in normalized:
        return "Teams Chat Data"
    if "rca" in normalized:
        return "RCA Evidence"
    return current_section


def make_ocr():
    from paddleocr import PaddleOCR

    return PaddleOCR(
        text_detection_model_name="PP-OCRv5_server_det",
        text_recognition_model_name="PP-OCRv5_server_rec",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=True,
        text_det_limit_side_len=2400,
        text_det_limit_type="max",
    )


def normalize_poly(poly: Any) -> list[list[float]] | None:
    if poly is None:
        return None
    try:
        return [[float(point[0]), float(point[1])] for point in poly]
    except Exception:
        return None


def run_ocr(ocr: Any, image: Any) -> list[dict[str, Any]]:
    results = list(ocr.predict(image))
    lines = []
    for result in results:
        if not hasattr(result, "get"):
            continue
        texts = result.get("rec_texts", []) or []
        scores = result.get("rec_scores", []) or []
        polys = result.get("rec_polys", []) or result.get("dt_polys", []) or []
        for index, text in enumerate(texts):
            item = {
                "text": clean_text(text),
                "confidence": float(scores[index]) if index < len(scores) else None,
                "polygon": normalize_poly(polys[index]) if index < len(polys) else None,
            }
            if item["text"]:
                lines.append(item)
    return lines


def extract_docx_ocr(state: Phase0AgentState) -> dict[str, Any]:
    import numpy as np
    from PIL import Image

    state.artifact_dir.mkdir(parents=True, exist_ok=True)
    ocr = make_ocr()
    pages = []
    current_section = "Unknown Evidence"
    try:
        with zipfile.ZipFile(state.source_docx_path) as archive:
            rels = relationship_targets(archive)
            root = ET.fromstring(archive.read("word/document.xml"))
            body = root.find(qn("body"))
            if body is not None:
                for child in body:
                    if child.tag != qn("p"):
                        continue
                    text = paragraph_text(child)
                    if text:
                        current_section = section_from_heading(text, current_section)
                    for rel_id in embedded_relationship_ids(child):
                        target = rels.get(rel_id)
                        if not target or target not in archive.namelist():
                            continue
                        media_index = len(pages) + 1
                        suffix = Path(target).suffix or ".png"
                        image_path = state.artifact_dir / f"case_{state.case_id}_docx_image_{media_index:02d}{suffix}"
                        image_path.write_bytes(archive.read(target))
                        with Image.open(image_path) as image:
                            width, height = image.size
                            image_array = np.array(image.convert("RGB"))
                        print(f"OCR DOCX media {media_index}: {Path(target).name}", flush=True)
                        pages.append(
                            {
                                "page": media_index,
                                "source_section": current_section,
                                "native_text": text,
                                "ocr_lines": run_ocr(ocr, image_array),
                                "artifact_path": relative_path(image_path),
                                "source_ref": f"{Path(state.active_source_file).name}#media={Path(target).name}",
                                "artifact_type": "docx_embedded_image",
                                "width": width,
                                "height": height,
                            }
                        )
    finally:
        ocr.close()
    return {
        "source_file": state.active_source_file,
        "source_kind": "docx",
        "artifact_count": len(pages),
        "pages": pages,
    }


def load_inputs_node(state: Phase0AgentState) -> Phase0AgentState:
    state.output_dir.mkdir(parents=True, exist_ok=True)
    state.extracted_dir.mkdir(parents=True, exist_ok=True)
    configure_toolkit_paths(state)
    if state.source_docx_path and not state.source_ocr_path.exists():
        state.ocr_data = extract_docx_ocr(state)
        write_json(state.source_ocr_path, state.ocr_data)
    else:
        state.ocr_data = json.loads(state.source_ocr_path.read_text(encoding="utf-8"))
    state.prompt_text = state.prompt_path.read_text(encoding="utf-8")
    state.reference = json.loads(state.reference_extraction_path.read_text(encoding="utf-8"))
    return state


def copy_artifacts_node(state: Phase0AgentState) -> Phase0AgentState:
    if state.use_generic_interpretation:
        return state
    state.ocr_data = toolkit.copy_artifacts(copy.deepcopy(state.ocr_data))
    return state


def reconstruct_layout_node(state: Phase0AgentState) -> Phase0AgentState:
    state.layout_blocks = reconstruct_generic_layout_blocks(state) if state.use_generic_interpretation else toolkit.reconstruct_layout_blocks(state.ocr_data)
    return state


def classify_regions_node(state: Phase0AgentState) -> Phase0AgentState:
    if state.use_generic_interpretation:
        state.semantic_regions = classify_generic_regions(state)
        return state
    state.semantic_regions = toolkit.classify_regions(state.ocr_data)
    return state


def create_embedded_artifacts_node(state: Phase0AgentState) -> Phase0AgentState:
    if state.use_generic_interpretation:
        return state
    state.semantic_regions = toolkit.create_embedded_region_artifacts(state.semantic_regions)
    return state


def interpret_regions_node(state: Phase0AgentState) -> Phase0AgentState:
    if state.use_generic_interpretation:
        state.interpretations = interpret_with_llm_or_fallback(state)
    else:
        state.interpretations = toolkit.build_interpretations(
            state.semantic_regions["regions"],
            state.prompt_text,
            state.reference,
        )
    apply_agent_context_overlay(state)
    state.interpretations["metadata"].setdefault("interpreter", INTERPRETATION_ENGINE)
    state.interpretations["metadata"]["agent_node"] = "interpret_regions"
    return state


def apply_agent_context_overlay(state: Phase0AgentState) -> None:
    for dataset_context in [
        state.interpretations.get("dataset_context_used"),
        state.interpretations.get("metadata", {}).get("dataset_context_used"),
    ]:
        if not dataset_context:
            continue
        dataset_context["contextual_overlays"] = copy.deepcopy(state.contextual_overlays)
    state.interpretations["metadata"]["contextual_overlays"] = copy.deepcopy(state.contextual_overlays)


def page_text(page: dict[str, Any]) -> str:
    return clean_text(" ".join([page.get("native_text", ""), " ".join(line.get("text", "") for line in page.get("ocr_lines", []))]))


def average_confidence(lines: list[dict[str, Any]]) -> float:
    scores = [line["confidence"] for line in lines if line.get("confidence") is not None]
    return round(sum(scores) / len(scores), 4) if scores else 0.0


def generic_region_type(section: str, text: str) -> str:
    normalized = f"{section} {text}".lower()
    if "teams" in normalized or "chat" in normalized:
        return "teams_message_thread"
    if "salesforce" in normalized or "case" in normalized:
        return "salesforce_case_update"
    if "log" in normalized:
        return "log_collection_context"
    return "embedded_operational_screenshot"


def evidence_type(text: str) -> str:
    normalized = text.lower()
    if any(term in normalized for term in ["restart", "reset", "estop", "e-stop"]):
        return "action"
    if any(term in normalized for term in ["operational", "working", "moving", "confirmed", "resolved"]):
        return "validation"
    if any(term in normalized for term in ["log", "event viewer", "ignition"]):
        return "log_collection"
    if any(term in normalized for term in ["escalat", "l2", "l3", "l4", "teams"]):
        return "escalation"
    if any(term in normalized for term in ["timeout", "fault", "alarm", "stopped", "down", "error", "no path"]):
        return "symptom"
    return "context"


def raw_source_type(region_type: str) -> str:
    if region_type == "teams_message_thread":
        return "teams_chat"
    if region_type == "salesforce_case_update":
        return "salesforce_case"
    if region_type == "log_collection_context":
        return "log_file"
    return "visual_artifact"


def generic_signals(text: str) -> dict[str, list[str]]:
    normalized = text.lower()
    signals = toolkit.signal_buckets()
    if "no path" in normalized:
        signals["observed_failure_signals"].append("no_path_reported")
    if "tipper" in normalized:
        signals["observed_failure_signals"].append("tipper_issue_reported")
    if "heartbeat" in normalized:
        signals["observed_failure_signals"].append("heartbeat_issue_reported")
    if any(term in normalized for term in ["stopped", "down", "not moving"]):
        signals["observed_failure_signals"].append("system_stopped_or_down")
    if any(term in normalized for term in ["fault", "alarm", "timeout"]):
        signals["diagnostic_signals"].append("fault_alarm_or_timeout_reported")
    if any(term in normalized for term in ["restart", "reset", "estop", "e-stop"]):
        signals["action_signals"].append("restart_or_reset_action_discussed")
    if any(term in normalized for term in ["log", "event viewer", "ignition"]):
        signals["diagnostic_signals"].append("logs_or_diagnostics_requested")
    if any(term in normalized for term in ["operational", "working", "moving", "confirmed", "resolved"]):
        signals["recovery_validation_signals"].append("recovery_or_operation_confirmed")
    if any(term in normalized for term in ["teams", "escalat", "l2", "l3"]):
        signals["escalation_signals"].append("support_escalation_context")
    return signals


def classify_generic_regions(state: Phase0AgentState) -> dict[str, Any]:
    regions = []
    for page in state.ocr_data["pages"]:
        text = page_text(page)
        region_type = generic_region_type(page.get("source_section", ""), text)
        region_id = f"region_{state.case_id}_{page['page']:03d}"
        regions.append(
            {
                "region_id": region_id,
                "region_type": region_type,
                "title": f"{page.get('source_section', 'Unknown Evidence')} media {page['page']}",
                "role": "primary_evidence",
                "source_file": state.active_source_file,
                "source_section": page.get("source_section"),
                "source_page": page["page"],
                "source_ref": page.get("source_ref"),
                "artifact_id": f"case_{state.case_id}_docx_artifact_{page['page']:02d}",
                "artifact_path": page["artifact_path"],
                "bbox": None,
                "text": text,
                "ocr_line_refs": [f"ocr_line={index}" for index, _ in enumerate(page.get("ocr_lines", []), start=1)],
                "confidence": average_confidence(page.get("ocr_lines", [])),
                "noise_score": 0.0,
                "visual_evidence": True,
                "visual_evidence_summary": clean_text(text)[:500],
            }
        )
    return {"source_file": state.active_source_file, "regions": regions}


def reconstruct_generic_layout_blocks(state: Phase0AgentState) -> dict[str, Any]:
    pages = []
    for page in state.ocr_data["pages"]:
        rows = []
        sorted_lines = sorted(enumerate(page["ocr_lines"], start=1), key=lambda item: (toolkit.line_center(item[1])[0], toolkit.line_center(item[1])[1]))
        for line_index, line in sorted_lines:
            y_center, _ = toolkit.line_center(line)
            box = toolkit.bbox_from_poly(line.get("polygon"))
            for row in rows:
                if abs(row["y_center"] - y_center) <= 12:
                    row["items"].append((line_index, line, box))
                    centers = [toolkit.line_center(item[1])[0] for item in row["items"]]
                    row["y_center"] = sum(centers) / len(centers)
                    break
            else:
                rows.append({"y_center": y_center, "items": [(line_index, line, box)]})
        blocks = []
        for row_index, row in enumerate(rows, start=1):
            items = sorted(row["items"], key=lambda item: toolkit.line_center(item[1])[1])
            text = clean_text(" ".join(item[1]["text"] for item in items))
            confidences = [item[1].get("confidence") or 0 for item in items]
            blocks.append(
                {
                    "block_id": f"layout_{page['page']:02d}_{row_index:03d}",
                    "artifact_id": f"case_{state.case_id}_docx_artifact_{page['page']:02d}",
                    "artifact_path": page["artifact_path"],
                    "source_section": page["source_section"],
                    "source_page": page["page"],
                    "bbox": toolkit.merge_bbox([item[2] for item in items]),
                    "text": text,
                    "ocr_line_refs": [f"ocr_line={item[0]}" for item in items],
                    "confidence": round(sum(confidences) / max(1, len(confidences)), 4),
                    "noise_score": toolkit.noise_score(text, sum(confidences) / max(1, len(confidences))),
                }
            )
        pages.append(
            {
                "source_page": page["page"],
                "source_section": page["source_section"],
                "artifact_id": f"case_{state.case_id}_docx_artifact_{page['page']:02d}",
                "artifact_path": page["artifact_path"],
                "blocks": blocks,
            }
        )
    return {"source_file": state.active_source_file, "pages": pages}


def refs_for_generic(regions: list[dict[str, Any]], ids: list[str]) -> dict[str, Any]:
    ids = normalize_ref_list(ids)
    selected = [region for region in regions if region["region_id"] in ids]
    return {
        "source_artifact_ids": sorted({region["artifact_id"] for region in selected}),
        "source_artifact_paths": sorted({region["artifact_path"] for region in selected}),
        "embedded_artifact_ids": [],
        "embedded_artifact_paths": [],
        "source_region_refs": [region["region_id"] for region in selected],
        "source_pages": sorted({region["source_page"] for region in selected}),
        "confidence": round(sum(region.get("confidence", 0) for region in selected) / max(1, len(selected)), 4),
        "escalated": any(region["region_type"] == "teams_message_thread" for region in selected),
    }


def normalize_ref_list(values: Any) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        values = [values]
    normalized = []
    for value in values:
        if isinstance(value, dict):
            for field_name in ["region_id", "artifact_id", "event_id", "chunk_id", "procedure_candidate_id", "workflow_step_id", "id", "source_ref"]:
                if value.get(field_name):
                    normalized.append(str(value[field_name]))
                    break
        elif value is not None:
            normalized.append(str(value))
    return normalized


def load_azure_openai_config(state: Phase0AgentState) -> dict[str, Any]:
    if not state.llm_config_path or not state.llm_config_path.exists():
        raise FileNotFoundError(f"Azure OpenAI config not found at {state.llm_config_path}")
    config = json.loads(state.llm_config_path.read_text(encoding="utf-8-sig"))
    required_fields = ["endpoint", "api_key", "api_version", "deployment"]
    missing = [field_name for field_name in required_fields if not config.get(field_name)]
    if missing:
        raise ValueError(f"Azure OpenAI config missing required fields: {', '.join(missing)}")
    placeholders = [
        field_name
        for field_name in required_fields
        if "YOUR" in str(config.get(field_name, "")).upper() or "<" in str(config.get(field_name, ""))
    ]
    if placeholders:
        raise ValueError(f"Azure OpenAI config contains placeholder values: {', '.join(placeholders)}")
    return config


def azure_openai_token_args(config: dict[str, Any], token_budget: int | None = None) -> dict[str, int]:
    deployment = str(config.get("deployment", "")).lower()
    token_budget = int(token_budget or config.get("max_completion_tokens") or config.get("max_tokens") or 12000)
    if deployment.startswith("gpt-5") or config.get("use_max_completion_tokens"):
        return {"max_completion_tokens": token_budget}
    return {"max_tokens": token_budget}


def config_metadata(config: dict[str, Any]) -> dict[str, Any]:
    endpoint = config.get("endpoint", "")
    endpoint_host = endpoint.replace("https://", "").replace("http://", "").strip("/").split("/")[0]
    token_args = azure_openai_token_args(config)
    return {
        "provider": "azure_openai",
        "endpoint_host": endpoint_host,
        "api_version": config.get("api_version"),
        "deployment": config.get("deployment"),
        "temperature": config.get("temperature", 0.1),
        "token_parameter": next(iter(token_args)),
        "token_budget": next(iter(token_args.values())),
    }


def truncate_text(value: str | None, limit: int) -> str:
    value = clean_text(value)
    if len(value) <= limit:
        return value
    return value[: limit - 24] + " ... [truncated]"


def compact_ocr_page(page: dict[str, Any]) -> dict[str, Any]:
    lines = []
    for index, line in enumerate(page.get("ocr_lines", [])[:90], start=1):
        lines.append(
            {
                "line": index,
                "text": truncate_text(line.get("text"), 180),
                "confidence": line.get("confidence"),
            }
        )
    return {
        "page": page.get("page"),
        "source_section": page.get("source_section"),
        "native_text": truncate_text(page.get("native_text"), 600),
        "artifact_path": page.get("artifact_path"),
        "source_ref": page.get("source_ref"),
        "ocr_line_count": len(page.get("ocr_lines", [])),
        "ocr_lines_sample": lines,
    }


def compact_layout_page(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_page": page.get("source_page"),
        "source_section": page.get("source_section"),
        "artifact_id": page.get("artifact_id"),
        "artifact_path": page.get("artifact_path"),
        "blocks": [
            {
                "block_id": block.get("block_id"),
                "text": truncate_text(block.get("text"), 220),
                "confidence": block.get("confidence"),
                "ocr_line_refs": block.get("ocr_line_refs", [])[:8],
            }
            for block in page.get("blocks", [])[:60]
        ],
    }


def compact_region(region: dict[str, Any]) -> dict[str, Any]:
    return {
        "region_id": region.get("region_id"),
        "region_type": region.get("region_type"),
        "title": region.get("title"),
        "source_section": region.get("source_section"),
        "source_page": region.get("source_page"),
        "source_ref": region.get("source_ref"),
        "artifact_id": region.get("artifact_id"),
        "artifact_path": region.get("artifact_path"),
        "confidence": region.get("confidence"),
        "text": truncate_text(region.get("text"), 1200),
        "ocr_line_refs": region.get("ocr_line_refs", [])[:20],
        "visual_evidence_summary": truncate_text(region.get("visual_evidence_summary"), 500),
    }


def llm_output_contract(state: Phase0AgentState) -> dict[str, Any]:
    signal_buckets = toolkit.SIGNAL_BUCKETS
    return {
        "synthesis_policy": SYNTHESIS_POLICY,
        "top_level_keys": [
            "canonical_incident",
            "semantic_chunks",
            "timeline_events",
            "procedure_candidates",
            "workflow_candidate_steps",
            "escalation_summary_template",
        ],
        "hard_rules": [
            "Return valid JSON only.",
            "Do not create timeline events or chunks one-to-one from screenshots unless the screenshot is itself one coherent evidence unit.",
            "Create 8 to 12 operational timeline events for the incident.",
            "Group evidence chunks by operational meaning rather than raw screenshot count.",
            "All intelligence remains candidate_extracted and requires_manual_review.",
            "Do not claim validated root cause.",
            "Use only supplied OCR/layout/region evidence and reference context.",
            "workflow_candidate_steps represent incidence workflow definitions for the current incident, not approved runtime workflow definitions.",
            "Name incidence workflows by entry points, initial symptoms, and candidate diagnoses so a later LangGraph workflow-builder agent can group similar incidents.",
            "Preserve source symptom and classification language. OCR corrections may be captured beside raw terms, but do not convert source language into hardcoded operational labels.",
            "Procedure candidates must include detailed, screenshot-linked steps when evidence supports them. If a step cannot be grounded in this case, record it as a refinement gap instead of inventing details.",
            "Evidence collection procedures must identify tool/system, visible screen or view, evidence to capture, data fields to preserve, validation check, screenshot_artifact_ids, and source_region_refs when available.",
            "Do not emit procedure steps with instruction, operator_action, or action equal to 'None'.",
            "If procedure evidence is weak, emit a skeletal refinement placeholder with procedure_steps: [] and candidate_refinement_questions.",
            "Non-fallback workflow names must be symptom-driven and must not start with case_<case_id>.",
            "Fallback output is review-only and not eligible for workflow grouping or cross-incident synthesis.",
        ],
        "canonical_incident_required": [
            "container_id",
            "dataset_record_type",
            "case_id",
            "source_case_id",
            "title",
            "retrieval_text",
            "validated_root_cause",
            "candidate_inferred_causes",
            *signal_buckets,
            "raw_terms",
            "normalized_terms",
            "normalization_confidence",
        ],
        "candidate_inferred_cause_shape": [
            "cause_summary",
            "basis",
            "confidence",
            "validation_status",
            "requires_manual_review",
        ],
        "semantic_chunk_required": [
            "chunk_id",
            "title",
            "summary",
            "raw_source_type",
            "evidence_type",
            *signal_buckets,
            "region_ids",
        ],
        "timeline_event_required": [
            "event_id",
            "container_id",
            "timestamp_raw",
            "event_occurred_at",
            "event_documented_at",
            "timestamp_basis",
            "actor",
            "actor_role",
            "event_type",
            "event_summary",
            *signal_buckets,
            "action_taken",
            "outcome",
            "region_ids",
        ],
        "procedure_candidate_required": [
            "procedure_candidate_id",
            "procedure_name",
            "procedure_category",
            "candidate_maturity",
            "related_cases",
            "related_components",
            "related_workflows",
            "related_escalation_patterns",
            "known_failure_modes",
            "procedure_summary",
            "procedure_goal",
            "required_tools_or_systems",
            "role_requirements",
            "required_permissions",
            "preconditions",
            "validation_checks",
            "validation_evidence",
            "recovery_outcomes",
            "known_risks",
            "escalation_conditions",
            "supporting_evidence_chunks",
            "supporting_timeline_events",
            "supporting_artifacts",
            "refinement_opportunities",
            "procedure_steps",
            "procedure_detail_level",
            "procedure_refinement_status",
            "missing_operational_details",
            "required_screenshot_examples",
            "candidate_refinement_questions",
            "region_ids",
            "procedure_category_status",
            "promotion_blockers",
            "quality_tier",
            "eligible_for_cross_incident_synthesis",
            "eligible_for_workflow_grouping",
            "synthesis_blockers",
            "pattern_candidate_notes",
            "comparable_signal_groups",
            "recurrence_evidence_refs",
        ],
        "procedure_step_required": [
            "step_number",
            "step_name",
            "step_goal",
            "operator_action",
            "system_or_tool",
            "navigation_path",
            "screen_or_view_name",
            "evidence_to_capture",
            "data_fields_to_record",
            "expected_visual_indicators",
            "validation_check",
            "screenshot_artifact_ids",
            "source_region_refs",
            "evidence_quality",
            "evidence_quality_notes",
            "requires_sme_validation",
            "refinement_gap_notes",
        ],
        "workflow_step_required": [
            "workflow_step_id",
            "container_id",
            "candidate_workflow_name",
            "step_type",
            "question",
            "why_asked",
            "candidate_step",
            "entry_conditions",
            "required_signals",
            "negative_signals",
            "procedure_refs",
            "evidence_refs",
            "image_refs",
            "status",
            "region_ids",
            "role_constraints",
            "required_permissions",
            "requires_role_review",
            "quality_tier",
            "eligible_for_cross_incident_synthesis",
            "eligible_for_workflow_grouping",
            "synthesis_blockers",
            "pattern_candidate_notes",
            "comparable_signal_groups",
            "recurrence_evidence_refs",
        ],
        "escalation_summary_required": [
            "trigger_reason",
            "symptoms",
            "steps_attempted",
            "steps_not_attempted",
            "evidence_refs",
            "logs_collected",
            "source_artifacts",
            "known_facts",
            "actions_taken",
            "evidence_available",
            "open_questions",
            "follow_up_owners",
            "recommended_owner",
            "handoff_summary",
            *signal_buckets,
        ],
        "allowed_values": {
            "raw_source_type": sorted(toolkit.ALLOWED_RAW_SOURCE_TYPES),
            "evidence_type": sorted(toolkit.ALLOWED_EVIDENCE_TYPES),
            "procedure_category": sorted(toolkit.ALLOWED_PROCEDURE_CATEGORIES),
            "case_id": state.case_id,
        },
    }


def build_llm_input_packet(state: Phase0AgentState) -> dict[str, Any]:
    artifact_refs = [
        {
            "artifact_id": region.get("artifact_id"),
            "artifact_path": region.get("artifact_path"),
            "source_page": region.get("source_page"),
            "source_section": region.get("source_section"),
            "source_ref": region.get("source_ref"),
        }
        for region in state.semantic_regions.get("regions", [])
    ]
    packet = {
        "task": "Interpret Phase 0 incident evidence into candidate operational incident intelligence using source-provided category context.",
        "case_id": state.case_id,
        "source_file": state.active_source_file,
        "phase0_system_prompt": state.prompt_text,
        "dataset_context": toolkit.dataset_context_packet(state.reference),
        "dataset_synthesis_policy": SYNTHESIS_POLICY,
        "ingestion_examples": load_ingestion_examples(),
        "ocr_pages": [compact_ocr_page(page) for page in state.ocr_data.get("pages", [])],
        "layout_blocks": [compact_layout_page(page) for page in state.layout_blocks.get("pages", [])],
        "semantic_regions": [compact_region(region) for region in state.semantic_regions.get("regions", [])],
        "artifact_refs": artifact_refs,
        "contextual_overlays": copy.deepcopy(state.contextual_overlays),
        "required_output_contract": llm_output_contract(state),
    }
    state.llm_input_path = state.extracted_dir / f"{state.output_prefix}_llm_input_packet.json"
    write_json(state.llm_input_path, packet)
    return packet


def parse_json_response(content: str) -> dict[str, Any]:
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


def llm_stage_specs() -> list[dict[str, Any]]:
    return [
        {
            "stage": "incident_timeline",
            "output_keys": ["canonical_incident", "timeline_events", "escalation_summary_template"],
            "instruction": (
                "Synthesize only the canonical incident, 8 to 12 operational timeline events, "
                "and escalation summary template. Do not emit evidence chunks, procedures, or workflows."
            ),
        },
        {
            "stage": "evidence_chunks",
            "output_keys": ["semantic_chunks"],
            "instruction": (
                "Create semantic raw evidence chunks grouped by operational meaning. "
                "Do not create chunks one-to-one from screenshots unless a screenshot is one coherent evidence unit."
            ),
        },
        {
            "stage": "procedure_candidates",
            "output_keys": ["procedure_candidates"],
            "instruction": (
                "Create 3 to 5 specific reusable procedure candidates. Keep each procedure concise: "
                "no more than 8 procedure_steps, and preserve source region/artifact refs. "
                "Each procedure step must include detailed operational action, system/tool, screen/view, evidence to capture, "
                "data fields to record, validation check, screenshot_artifact_ids, source_region_refs, SME validation flag, and refinement gaps. "
                "For database timeout evidence, describe the visible WCS server/application/event evidence collection steps as specifically as the case supports."
            ),
        },
        {
            "stage": "workflow_candidate_steps",
            "output_keys": ["workflow_candidate_steps"],
            "instruction": (
                "Create 3 to 5 incidence workflow definition steps. Workflows orchestrate procedure applicability, "
                "entry points, initial symptoms, candidate diagnoses, and SME-review routing. Do not emit full procedures."
            ),
        },
    ]


def llm_stage_contract(state: Phase0AgentState, output_keys: list[str]) -> dict[str, Any]:
    full_contract = llm_output_contract(state)
    contract = {
        "top_level_keys": output_keys,
        "hard_rules": full_contract["hard_rules"],
        "allowed_values": full_contract["allowed_values"],
    }
    field_map = {
        "canonical_incident": ["canonical_incident_required", "candidate_inferred_cause_shape"],
        "semantic_chunks": ["semantic_chunk_required"],
        "timeline_events": ["timeline_event_required"],
        "procedure_candidates": ["procedure_candidate_required", "procedure_step_required"],
        "workflow_candidate_steps": ["workflow_step_required"],
        "escalation_summary_template": ["escalation_summary_required"],
    }
    for output_key in output_keys:
        for contract_key in field_map.get(output_key, []):
            contract[contract_key] = full_contract[contract_key]
    return contract


def compact_region_manifest(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "region_id": region.get("region_id"),
            "region_type": region.get("region_type"),
            "source_page": region.get("source_page"),
            "source_section": region.get("source_section"),
            "artifact_id": region.get("artifact_id"),
            "text": truncate_text(region.get("text"), 450),
        }
        for region in regions
    ]


def build_llm_stage_packet(base_packet: dict[str, Any], state: Phase0AgentState, spec: dict[str, Any], partial_results: dict[str, Any]) -> dict[str, Any]:
    use_slim_source = spec["stage"] in {"procedure_candidates", "workflow_candidate_steps"}
    return {
        "task": base_packet["task"],
        "stage": spec["stage"],
        "stage_instruction": spec["instruction"],
        "case_id": base_packet["case_id"],
        "source_file": base_packet["source_file"],
        "phase0_system_prompt": truncate_text(base_packet.get("phase0_system_prompt"), 14000),
        "dataset_context": base_packet["dataset_context"],
        "dataset_synthesis_policy": base_packet["dataset_synthesis_policy"],
        "ingestion_examples": compact_ingestion_examples(base_packet["ingestion_examples"]),
        "ocr_pages": [] if use_slim_source else base_packet["ocr_pages"],
        "layout_blocks": [] if use_slim_source else base_packet["layout_blocks"],
        "semantic_regions": compact_region_manifest(base_packet["semantic_regions"]) if use_slim_source else base_packet["semantic_regions"],
        "artifact_refs": base_packet["artifact_refs"],
        "contextual_overlays": base_packet["contextual_overlays"],
        "previous_stage_outputs": partial_results,
        "required_output_contract": llm_stage_contract(state, spec["output_keys"]),
        "response_rules": [
            f"Return exactly these top-level keys: {', '.join(spec['output_keys'])}.",
            "Do not return explanatory prose.",
            "Do not include top-level keys assigned to other stages.",
            "All source refs, artifact refs, region refs, validation_status, and requires_manual_review fields must be preserved.",
        ],
    }


def usage_to_dict(usage: Any) -> dict[str, Any]:
    if not usage:
        return {}
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


def merge_llm_usage(stage_usages: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        "prompt_tokens": sum(usage.get("prompt_tokens") or 0 for usage in stage_usages),
        "completion_tokens": sum(usage.get("completion_tokens") or 0 for usage in stage_usages),
        "total_tokens": sum(usage.get("total_tokens") or 0 for usage in stage_usages),
    }
    totals["stages"] = stage_usages
    return totals


def call_azure_openai_stage(client: Any, config: dict[str, Any], stage_packet: dict[str, Any], raw_response_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    response = client.chat.completions.create(
        model=config["deployment"],
        temperature=config.get("temperature", 0.1),
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are the Phase 0 Ingestion Agent staged interpretation node. "
                    "Return only valid JSON matching this stage's required output contract. "
                    "All outputs are candidate-level and require manual review."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(stage_packet, ensure_ascii=False),
            },
        ],
        **azure_openai_token_args(config),
    )
    choice = response.choices[0]
    content = choice.message.content or ""
    usage = usage_to_dict(getattr(response, "usage", None))
    finish_reason = getattr(choice, "finish_reason", None)
    write_json(
        raw_response_path,
        {
            "stage": stage_packet["stage"],
            "finish_reason": finish_reason,
            "content_length": len(content),
            "usage": usage,
            "content": content,
        },
    )
    if finish_reason == "length":
        raise ValueError(f"LLM stage {stage_packet['stage']} response was truncated at {raw_response_path}")
    return parse_json_response(content), usage


def call_azure_openai_stage_repair(
    client: Any,
    config: dict[str, Any],
    stage_packet: dict[str, Any],
    validation_errors: list[str],
    raw_response_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    repair_packet = {
        "repair_task": "Repair only the failed stage JSON. Return no prose.",
        "stage": stage_packet["stage"],
        "validation_errors": validation_errors,
        "required_output_contract": stage_packet["required_output_contract"],
        "previous_stage_outputs": stage_packet.get("previous_stage_outputs", {}),
        "stage_instruction": stage_packet["stage_instruction"],
        "dataset_synthesis_policy": stage_packet.get("dataset_synthesis_policy"),
        "ingestion_examples": stage_packet.get("ingestion_examples"),
        "semantic_regions": stage_packet.get("semantic_regions", []),
        "artifact_refs": stage_packet.get("artifact_refs", []),
        "allowed_region_ids": [
            region.get("region_id")
            for region in stage_packet.get("semantic_regions", [])
            if region.get("region_id")
        ],
    }
    return call_azure_openai_stage(client, config, repair_packet, raw_response_path)


def normalize_llm_procedure_values(interpretations: dict[str, Any]) -> None:
    detail_values = {"high", "medium", "low", "skeletal"}
    status_values = {"case_derived", "needs_multi_incident_refinement", "ready_for_sme_review"}
    for procedure in interpretations.get("procedure_candidates", []):
        detail = procedure.get("procedure_detail_level")
        if detail not in detail_values:
            procedure["original_procedure_detail_level"] = detail
            has_step_screenshots = any(step.get("screenshot_artifact_ids") for step in procedure.get("procedure_steps", []))
            procedure["procedure_detail_level"] = "medium" if has_step_screenshots else "skeletal"
        status = procedure.get("procedure_refinement_status")
        if status not in status_values:
            procedure["original_procedure_refinement_status"] = status
            procedure["procedure_refinement_status"] = "needs_multi_incident_refinement" if status in {"needs_sme_review", "case-grounded_draft", "draft"} else "case_derived"


def is_case_named_workflow(name: str | None, case_id: str) -> bool:
    return bool(name and re.match(rf"^case_{re.escape(str(case_id))}(?:_|$)", name))


def validate_procedure_candidate_shape(procedure: dict[str, Any], index: int) -> list[str]:
    errors = []
    steps = procedure.get("procedure_steps", [])
    detail_level = procedure.get("procedure_detail_level")
    quality_tier = procedure.get("quality_tier")
    if detail_level == "skeletal" and steps and quality_tier != FALLBACK_QUALITY_TIER:
        errors.append(f"procedure_candidates[{index}] skeletal procedure must be review-only or use procedure_steps: []")
    for step_index, step in enumerate(steps, start=1):
        instruction = step.get("instruction") or step.get("operator_action") or step.get("action")
        if str(instruction).strip().lower() == "none":
            errors.append(f"procedure_candidates[{index}].procedure_steps[{step_index}] instruction must not be None")
        operator_action = step.get("operator_action")
        gap_notes = step.get("refinement_gap_notes")
        if not operator_action and not gap_notes:
            errors.append(f"procedure_candidates[{index}].procedure_steps[{step_index}] missing operator_action and refinement_gap_notes")
    return errors


def validate_workflow_candidate_shape(workflow: dict[str, Any], index: int, case_id: str) -> list[str]:
    errors = []
    name = workflow.get("candidate_workflow_name") or workflow.get("workflow_id")
    is_fallback = workflow.get("fallback_only") is True or workflow.get("quality_tier") == FALLBACK_QUALITY_TIER
    if is_case_named_workflow(name, case_id) and not is_fallback:
        errors.append(f"workflow_candidate_steps[{index}] non-fallback workflow name is case-number driven")
    if not is_fallback:
        for field_name in ["entry_conditions", "required_signals", "evidence_refs", "procedure_refs"]:
            if not workflow.get(field_name):
                errors.append(f"workflow_candidate_steps[{index}] missing {field_name}")
    return errors


def validate_stage_output(stage_output: dict[str, Any], spec: dict[str, Any], state: Phase0AgentState) -> list[str]:
    errors = [f"missing {key}" for key in spec["output_keys"] if key not in stage_output]
    contract = llm_stage_contract(state, spec["output_keys"])
    region_ids = {region["region_id"] for region in state.semantic_regions.get("regions", [])}
    required_by_collection = {
        "semantic_chunks": contract.get("semantic_chunk_required", []),
        "timeline_events": contract.get("timeline_event_required", []),
        "procedure_candidates": contract.get("procedure_candidate_required", []),
        "workflow_candidate_steps": contract.get("workflow_step_required", []),
    }
    for field_name in contract.get("canonical_incident_required", []):
        if "canonical_incident" in stage_output and field_name not in stage_output["canonical_incident"]:
            errors.append(f"canonical_incident missing {field_name}")
    for field_name in contract.get("escalation_summary_required", []):
        if "escalation_summary_template" in stage_output and field_name not in stage_output["escalation_summary_template"]:
            errors.append(f"escalation_summary_template missing {field_name}")
    for collection_name, required_fields in required_by_collection.items():
        if collection_name not in stage_output:
            continue
        collection = stage_output.get(collection_name)
        if not isinstance(collection, list) or not collection:
            errors.append(f"{collection_name} must be a non-empty list")
            continue
        for index, item in enumerate(collection, start=1):
            for field_name in required_fields:
                if field_name not in item:
                    errors.append(f"{collection_name}[{index}] missing {field_name}")
            item_regions = item.get("region_ids", [])
            if not isinstance(item_regions, list) or not item_regions:
                errors.append(f"{collection_name}[{index}] missing region_ids")
            elif not set(item_regions).issubset(region_ids):
                errors.append(f"{collection_name}[{index}] has unknown region_ids")
    for index, procedure in enumerate(stage_output.get("procedure_candidates", []), start=1):
        errors.extend(validate_procedure_candidate_shape(procedure, index))
        for step_index, step in enumerate(procedure.get("procedure_steps", []), start=1):
            for field_name in contract.get("procedure_step_required", []):
                if field_name not in step:
                    errors.append(f"procedure_candidates[{index}].procedure_steps[{step_index}] missing {field_name}")
            if step.get("evidence_quality") not in {"high", "medium", "low"}:
                errors.append(f"procedure_candidates[{index}].procedure_steps[{step_index}] invalid evidence_quality")
            if not isinstance(step.get("screenshot_artifact_ids"), list):
                errors.append(f"procedure_candidates[{index}].procedure_steps[{step_index}] screenshot_artifact_ids must be a list")
            if not isinstance(step.get("source_region_refs"), list):
                errors.append(f"procedure_candidates[{index}].procedure_steps[{step_index}] source_region_refs must be a list")
    for index, workflow in enumerate(stage_output.get("workflow_candidate_steps", []), start=1):
        errors.extend(validate_workflow_candidate_shape(workflow, index, state.case_id))
    return errors


def fallback_quality_fields(reason: str | None) -> dict[str, Any]:
    return {
        "quality_tier": FALLBACK_QUALITY_TIER,
        "fallback_only": True,
        "eligible_for_cross_incident_synthesis": False,
        "eligible_for_workflow_grouping": False,
        "fallback_reason": reason,
        "requires_manual_reingestion": True,
        "synthesis_blockers": ["fallback_generic_output"],
        "pattern_candidate_notes": "Fallback output is retained for debugging and manual review only.",
        "comparable_signal_groups": [],
        "recurrence_evidence_refs": [],
    }


def apply_fallback_markers_to_interpretations(interpretations: dict[str, Any], reason: str | None) -> None:
    fields = fallback_quality_fields(reason)
    for key in ["canonical_incident", "escalation_summary_template"]:
        if isinstance(interpretations.get(key), dict):
            interpretations[key].update(fields)
    for key in ["semantic_chunks", "timeline_events", "procedure_candidates", "workflow_candidate_steps"]:
        for record in interpretations.get(key, []):
            if isinstance(record, dict):
                record.update(fields)


def interpret_with_llm_or_fallback(state: Phase0AgentState) -> dict[str, Any]:
    try:
        interpretations = interpret_semantic_regions_with_llm(state)
        validation_errors = validate_llm_interpretation(interpretations, state)
        if validation_errors:
            raise ValueError("; ".join(validation_errors))
        state.llm_status = "azure_openai"
        return interpretations
    except Exception as exc:
        state.llm_status = "fallback_generic"
        state.llm_error = str(exc)
        fallback = build_generic_interpretations(state)
        apply_fallback_markers_to_interpretations(fallback, state.llm_error)
        fallback.setdefault("metadata", {})
        fallback["metadata"].update(
            {
                "interpreter": "fallback_generic_keyword_structuring",
                "llm_status": state.llm_status,
                "llm_fallback_reason": state.llm_error,
                "llm_provider": state.llm_provider,
                "llm_deployment": state.llm_deployment,
            }
        )
        return fallback


def interpret_semantic_regions_with_llm(state: Phase0AgentState) -> dict[str, Any]:
    from openai import AzureOpenAI

    packet = build_llm_input_packet(state)
    config = load_azure_openai_config(state)
    metadata = config_metadata(config)
    state.llm_provider = metadata["provider"]
    state.llm_deployment = metadata["deployment"]
    client = AzureOpenAI(
        api_key=config["api_key"],
        api_version=config["api_version"],
        azure_endpoint=config["endpoint"],
    )
    interpretations: dict[str, Any] = {}
    stage_usages = []
    stage_raw_response_paths = []
    stage_input_paths = []
    retry_metadata = []
    for spec in llm_stage_specs():
        stage_packet = build_llm_stage_packet(packet, state, spec, interpretations)
        stage_input_path = state.extracted_dir / f"{state.output_prefix}_llm_input_packet_{spec['stage']}.json"
        raw_response_path = state.extracted_dir / f"{state.output_prefix}_llm_raw_response_{spec['stage']}.json"
        write_json(stage_input_path, stage_packet)
        stage_output, stage_usage = call_azure_openai_stage(client, config, stage_packet, raw_response_path)
        stage_errors = validate_stage_output(stage_output, spec, state)
        if stage_errors:
            retry_raw_response_path = state.extracted_dir / f"{state.output_prefix}_llm_raw_response_{spec['stage']}_retry.json"
            retry_metadata.append(
                {
                    "stage": spec["stage"],
                    "llm_retry_attempted": True,
                    "llm_retry_reason": "; ".join(stage_errors),
                    "llm_retry_succeeded": False,
                }
            )
            stage_output, retry_usage = call_azure_openai_stage_repair(client, config, stage_packet, stage_errors, retry_raw_response_path)
            stage_usage = {
                "prompt_tokens": (stage_usage.get("prompt_tokens") or 0) + (retry_usage.get("prompt_tokens") or 0),
                "completion_tokens": (stage_usage.get("completion_tokens") or 0) + (retry_usage.get("completion_tokens") or 0),
                "total_tokens": (stage_usage.get("total_tokens") or 0) + (retry_usage.get("total_tokens") or 0),
            }
            stage_errors = validate_stage_output(stage_output, spec, state)
            retry_metadata[-1]["llm_retry_succeeded"] = not stage_errors
            stage_raw_response_paths.append(relative_path(retry_raw_response_path))
        if stage_errors:
            raise ValueError(f"LLM stage {spec['stage']} failed validation after retry: {'; '.join(stage_errors)}")
        interpretations.update({key: stage_output[key] for key in spec["output_keys"]})
        stage_usages.append({"stage": spec["stage"], **stage_usage})
        state.llm_usage = merge_llm_usage(stage_usages)
        stage_raw_response_paths.append(relative_path(raw_response_path))
        stage_input_paths.append(relative_path(stage_input_path))
    state.llm_usage = merge_llm_usage(stage_usages)
    normalize_llm_procedure_values(interpretations)
    interpretations.setdefault("metadata", {})
    interpretations["metadata"].update(
        {
            "interpreter": "azure_openai_staged_semantic_interpreter",
            "llm_status": "azure_openai",
            "llm_provider": metadata["provider"],
            "llm_deployment": metadata["deployment"],
            "llm_api_version": metadata["api_version"],
            "llm_endpoint_host": metadata["endpoint_host"],
            "llm_usage": state.llm_usage,
            "llm_input_packet_path": relative_path(state.llm_input_path) if state.llm_input_path else None,
            "llm_stage_input_paths": stage_input_paths,
            "llm_stage_raw_response_paths": stage_raw_response_paths,
            "llm_stage_count": len(stage_raw_response_paths),
            "llm_retry_attempted": any(item["llm_retry_attempted"] for item in retry_metadata),
            "llm_retry_metadata": retry_metadata,
            "examples_source": packet["ingestion_examples"].get("examples_source"),
            "examples_version": packet["ingestion_examples"].get("examples_version"),
            "examples_used": packet["ingestion_examples"].get("examples_used", False),
        }
    )
    interpretations.setdefault("dataset_context_used", packet["dataset_context"])
    return interpretations


def validate_llm_interpretation(interpretations: dict[str, Any], state: Phase0AgentState) -> list[str]:
    errors = []
    contract = llm_output_contract(state)
    for key in ["canonical_incident", "semantic_chunks", "timeline_events", "procedure_candidates", "workflow_candidate_steps", "escalation_summary_template"]:
        if key not in interpretations:
            errors.append(f"missing {key}")
    if errors:
        return errors
    for field_name in contract["canonical_incident_required"]:
        if field_name not in interpretations["canonical_incident"]:
            errors.append(f"canonical_incident missing {field_name}")
    if not isinstance(interpretations["semantic_chunks"], list) or not interpretations["semantic_chunks"]:
        errors.append("semantic_chunks must be a non-empty list")
    if not isinstance(interpretations["timeline_events"], list):
        errors.append("timeline_events must be a list")
    elif not 8 <= len(interpretations["timeline_events"]) <= 12:
        errors.append("timeline_events must contain 8 to 12 operational events")
    if not isinstance(interpretations["procedure_candidates"], list) or not interpretations["procedure_candidates"]:
        errors.append("procedure_candidates must be a non-empty list")
    if not isinstance(interpretations["workflow_candidate_steps"], list) or not interpretations["workflow_candidate_steps"]:
        errors.append("workflow_candidate_steps must be a non-empty list")
    canonical = interpretations.get("canonical_incident", {})
    causes = canonical.get("candidate_inferred_causes", [])
    if not isinstance(causes, list):
        errors.append("candidate_inferred_causes must be a list")
    elif not causes:
        errors.append("candidate_inferred_causes must include at least one candidate cause object")
    else:
        for index, cause in enumerate(causes, start=1):
            for field_name in ["cause_summary", "basis", "confidence", "validation_status", "requires_manual_review"]:
                if field_name not in cause:
                    errors.append(f"candidate_inferred_causes[{index}] missing {field_name}")
    for bucket in toolkit.SIGNAL_BUCKETS:
        if not isinstance(canonical.get(bucket, []), list):
            errors.append(f"canonical_incident.{bucket} must be a list")
    region_ids = {region["region_id"] for region in state.semantic_regions.get("regions", [])}
    for collection_name in ["semantic_chunks", "timeline_events", "procedure_candidates", "workflow_candidate_steps"]:
        required_fields = {
            "semantic_chunks": contract["semantic_chunk_required"],
            "timeline_events": contract["timeline_event_required"],
            "procedure_candidates": contract["procedure_candidate_required"],
            "workflow_candidate_steps": contract["workflow_step_required"],
        }[collection_name]
        for index, item in enumerate(interpretations.get(collection_name, []), start=1):
            for field_name in required_fields:
                if field_name not in item:
                    errors.append(f"{collection_name}[{index}] missing {field_name}")
            item_regions = item.get("region_ids", [])
            if not isinstance(item_regions, list) or not item_regions:
                errors.append(f"{collection_name}[{index}] missing region_ids")
            elif not set(item_regions).issubset(region_ids):
                errors.append(f"{collection_name}[{index}] has unknown region_ids")
            for bucket in toolkit.SIGNAL_BUCKETS:
                if bucket in item and not isinstance(item[bucket], list):
                    errors.append(f"{collection_name}[{index}].{bucket} must be a list")
    for field_name in contract["escalation_summary_required"]:
        if field_name not in interpretations["escalation_summary_template"]:
            errors.append(f"escalation_summary_template missing {field_name}")
    for index, procedure in enumerate(interpretations.get("procedure_candidates", []), start=1):
        errors.extend(validate_procedure_candidate_shape(procedure, index))
        if procedure.get("procedure_detail_level") not in {"high", "medium", "low", "skeletal"}:
            errors.append(f"procedure_candidates[{index}] invalid procedure_detail_level")
        if procedure.get("procedure_refinement_status") not in {"case_derived", "needs_multi_incident_refinement", "ready_for_sme_review"}:
            errors.append(f"procedure_candidates[{index}] invalid procedure_refinement_status")
        if not isinstance(procedure.get("missing_operational_details"), list):
            errors.append(f"procedure_candidates[{index}] missing_operational_details must be a list")
        if not isinstance(procedure.get("required_screenshot_examples"), list):
            errors.append(f"procedure_candidates[{index}] required_screenshot_examples must be a list")
        if not isinstance(procedure.get("candidate_refinement_questions"), list):
            errors.append(f"procedure_candidates[{index}] candidate_refinement_questions must be a list")
        for step_index, step in enumerate(procedure.get("procedure_steps", []), start=1):
            for field_name in contract["procedure_step_required"]:
                if field_name not in step:
                    errors.append(f"procedure_candidates[{index}].procedure_steps[{step_index}] missing {field_name}")
            if step.get("evidence_quality") not in {"high", "medium", "low"}:
                errors.append(f"procedure_candidates[{index}].procedure_steps[{step_index}] invalid evidence_quality")
            if not isinstance(step.get("screenshot_artifact_ids"), list):
                errors.append(f"procedure_candidates[{index}].procedure_steps[{step_index}] screenshot_artifact_ids must be a list")
            if not isinstance(step.get("source_region_refs"), list):
                errors.append(f"procedure_candidates[{index}].procedure_steps[{step_index}] source_region_refs must be a list")
    for index, workflow in enumerate(interpretations.get("workflow_candidate_steps", []), start=1):
        errors.extend(validate_workflow_candidate_shape(workflow, index, state.case_id))
    if len(interpretations.get("semantic_chunks", [])) >= len(state.semantic_regions.get("regions", [])) and len(state.semantic_regions.get("regions", [])) > 12:
        errors.append("semantic_chunks appear one-to-one with screenshots instead of meaningfully grouped")
    return errors


def build_generic_interpretations(state: Phase0AgentState) -> dict[str, Any]:
    regions = state.semantic_regions["regions"]
    all_text = clean_text(" ".join(region.get("text", "") for region in regions))
    all_signals = generic_signals(all_text)
    semantic_chunks = []
    timeline_events = []
    for index, region in enumerate(regions, start=1):
        text = region.get("text", "")
        region_signals = generic_signals(text)
        chunk_id = f"case_{state.case_id}_chunk_{index:03d}"
        semantic_chunks.append(
            {
                "chunk_id": chunk_id,
                "title": region["title"],
                "summary": clean_text(text)[:900] or "OCR produced limited readable text; retain screenshot as visual evidence.",
                "raw_source_type": raw_source_type(region["region_type"]),
                "evidence_type": evidence_type(text),
                **region_signals,
                "region_ids": [region["region_id"]],
            }
        )
        timeline_events.append(
            {
                "event_id": f"case_{state.case_id}_event_{index:03d}",
                "container_id": f"case_{state.case_id}_timeline",
                "timestamp_raw": None,
                "event_occurred_at": None,
                "event_documented_at": None,
                "timestamp_basis": "not_extracted_from_source",
                "actor": "unknown_from_ocr",
                "actor_role": "unknown",
                "event_type": evidence_type(text),
                "event_summary": clean_text(text)[:600] or "Candidate timeline event from screenshot media.",
                **region_signals,
                "action_taken": "candidate_from_ocr",
                "outcome": "requires_manual_review",
                "region_ids": [region["region_id"]],
            }
        )
    procedures = generic_procedures(state, semantic_chunks, timeline_events, all_text)
    workflows = generic_workflows(state, procedures, semantic_chunks)
    return {
        "metadata": {
            **toolkit.interpretation_payload(state.prompt_text, state.reference),
            "created_at": utc_now(),
            "source_file": state.active_source_file,
            "notes": f"Generic agent interpretation for Case {state.case_id}. Records are OCR-derived candidates and require SME review.",
        },
        "dataset_context_used": toolkit.dataset_context_packet(state.reference),
        "canonical_incident": {
            "container_id": "phase0_candidate_incident",
            "dataset_record_type": "incident_summary",
            "case_id": state.case_id,
            "source_case_id": state.case_id,
            "title": f"Case {state.case_id} - Candidate operational incident from DOCX screenshot evidence",
            "retrieval_text": all_text[:2000],
            "validated_root_cause": False,
            "candidate_inferred_causes": [],
            **all_signals,
            "raw_terms": [],
            "normalized_terms": [],
            "normalization_confidence": 0.0,
        },
        "semantic_chunks": semantic_chunks,
        "timeline_events": timeline_events,
        "procedure_candidates": procedures,
        "workflow_candidate_steps": workflows,
        "escalation_summary_template": {
            "trigger_reason": "Candidate escalation context extracted from DOCX screenshots.",
            "symptoms": all_signals["observed_failure_signals"],
            "steps_attempted": all_signals["action_signals"],
            "steps_not_attempted": [],
            "evidence_refs": [chunk["chunk_id"] for chunk in semantic_chunks[:8]],
            "logs_collected": [],
            "source_artifacts": [region["artifact_id"] for region in regions[:8]],
            "known_facts": ["OCR and screenshot evidence extracted for manual review."],
            "actions_taken": all_signals["action_signals"],
            "evidence_available": ["DOCX embedded screenshots", "OCR text lines"],
            "open_questions": ["Manual review is required to validate operational sequence, ownership, and procedure candidates."],
            "follow_up_owners": [{"item": "case_review", "owner": "SME reviewer", "status": "needs_review"}],
            "recommended_owner": "L2_L3_software_support",
            "handoff_summary": f"Case {state.case_id} was ingested from DOCX screenshot evidence. The generated record is candidate-level and requires manual review.",
            **all_signals,
        },
    }


def generic_procedures(state: Phase0AgentState, chunks: list[dict[str, Any]], events: list[dict[str, Any]], all_text: str) -> list[dict[str, Any]]:
    normalized = all_text.lower()
    procedure_specs = [
        ("inspect_operational_status_candidate", "Inspect Operational Status", "diagnostic_check", "Capture visible operational state before action selection.", ["fault_alarm_or_timeout_reported"]),
    ]
    if any(term in normalized for term in ["restart", "reset", "estop", "e-stop"]):
        procedure_specs.append(("restart_or_reset_service_candidate", "Restart Or Reset Service", "service_restart", "Candidate recovery action when source evidence documents restart/reset discussion.", ["restart_or_reset_action_discussed"]))
    if "log" in normalized:
        procedure_specs.append(("collect_incident_logs_candidate", "Collect Incident Logs", "log_collection", "Collect logs or diagnostic artifacts referenced in source evidence.", ["logs_or_diagnostics_requested"]))
    if any(term in normalized for term in ["operational", "working", "moving", "confirmed", "resolved"]):
        procedure_specs.append(("validate_recovery_candidate", "Validate Recovery", "recovery_validation", "Confirm operational recovery after candidate actions.", ["recovery_or_operation_confirmed"]))
    procedures = []
    evidence_chunks = [chunk["chunk_id"] for chunk in chunks[:6]]
    evidence_events = [event["event_id"] for event in events[:6]]
    artifact_ids = [f"case_{state.case_id}_docx_artifact_{index:02d}" for index in range(1, min(6, len(chunks)) + 1)]
    for procedure_id, name, category, goal, signals in procedure_specs:
        procedures.append(
            {
                "procedure_candidate_id": procedure_id,
                "procedure_name": name,
                "procedure_category": category,
                "candidate_maturity": "single_case_candidate",
                "related_cases": [state.case_id],
                "related_components": [],
                "related_workflows": [f"case_{state.case_id}_candidate_triage_flow_v1"],
                "related_escalation_patterns": ["support_escalation_context"],
                "known_failure_modes": signals,
                "procedure_summary": goal,
                "procedure_goal": goal,
                "required_tools_or_systems": ["source screenshots", "case record"],
                "role_requirements": ["L2_L3_software_support"],
                "required_permissions": ["case_review_access"],
                "preconditions": ["Source evidence has been OCR extracted."],
                "validation_checks": ["SME reviewed source screenshot and OCR evidence."],
                "validation_evidence": artifact_ids[:2],
                "recovery_outcomes": [],
                "known_risks": ["OCR-derived procedure candidates may omit visual context or misread screenshot text."],
                "escalation_conditions": ["Escalate if operational ownership or safe action boundary is unclear."],
                "supporting_evidence_chunks": evidence_chunks,
                "supporting_timeline_events": evidence_events,
                "supporting_artifacts": artifact_ids,
                "refinement_opportunities": ["Review against additional source-classified incidents before promotion."],
                "procedure_detail_level": "skeletal",
                "procedure_refinement_status": "needs_multi_incident_refinement",
                "missing_operational_details": ["Exact system navigation and screenshots must be reviewed by an SME before promotion."],
                "required_screenshot_examples": ["Screenshot showing the relevant system/view before action.", "Screenshot showing the captured evidence or validation state."],
                "candidate_refinement_questions": ["Which exact screen, menu, log path, or evidence export method should be used for this procedure?"],
                "procedure_steps": [],
                "quality_tier": FALLBACK_QUALITY_TIER,
                "eligible_for_cross_incident_synthesis": False,
                "eligible_for_workflow_grouping": False,
                "region_ids": [f"region_{state.case_id}_{index:03d}" for index in range(1, min(6, len(chunks)) + 1)],
                "procedure_category_status": "candidate",
                "promotion_blockers": ["Requires SME review before promotion.", "Requires repeated incident evidence before multi-case maturity."],
            }
        )
    return procedures


def generic_workflows(state: Phase0AgentState, procedures: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    workflows = []
    for index, procedure in enumerate(procedures, start=1):
        workflows.append(
            {
                "workflow_step_id": f"case_{state.case_id}_workflow_step_{index:03d}",
                "container_id": "phase0_workflow_candidates",
                "candidate_workflow_name": f"case_{state.case_id}_candidate_triage_flow_v1",
                "fallback_only": True,
                "quality_tier": FALLBACK_QUALITY_TIER,
                "eligible_for_cross_incident_synthesis": False,
                "eligible_for_workflow_grouping": False,
                "step_type": "decision",
                "question": f"Does the source evidence support routing to {procedure['procedure_name']}?",
                "why_asked": "Workflow routing remains candidate-level until reviewed.",
                "candidate_step": "Decision node for routing to referenced candidate procedures; operational execution remains in procedure candidates.",
                "entry_conditions": procedure.get("known_failure_modes", []),
                "required_signals": procedure.get("known_failure_modes", []),
                "negative_signals": [],
                "procedure_refs": [procedure["procedure_candidate_id"]],
                "evidence_refs": [chunk["chunk_id"] for chunk in chunks[:3]],
                "image_refs": procedure.get("supporting_artifacts", [])[:2],
                "status": "draft",
                "region_ids": procedure.get("region_ids", []),
                **toolkit.review_fields(["L2_L3_software_support"], []),
            }
        )
    return workflows


def apply_contextual_overlays_to_records(state: Phase0AgentState) -> None:
    records = state.records
    for record in flat_records(records):
        strip_overlay_promotions(record)
        relevant = is_teams_derived(record)
        record["overlay_applied"] = relevant
        record["contextual_overlays"] = copy.deepcopy(state.contextual_overlays) if relevant else []
        record["overlay_application_reason"] = (
            "Conditional user-provided context is attached because the record summarizes the incident, escalation handoff, or Teams-derived evidence."
            if relevant
            else ""
        )
        if relevant:
            append_unique(record.setdefault("escalation_targets", []), L4_SUPPORT_TIER)


def strip_overlay_promotions(record: dict[str, Any]) -> None:
    for field_name in ["support_tiers_involved", "role_constraints", "role_requirements"]:
        if isinstance(record.get(field_name), list):
            record[field_name] = remove_item(record[field_name], L4_SUPPORT_TIER)
    if isinstance(record.get("escalation_signals"), list):
        record["escalation_signals"] = remove_item(record["escalation_signals"], L4_ESCALATION_SIGNAL)
    if isinstance(record.get("known_facts"), list):
        record["known_facts"] = [
            fact for fact in record["known_facts"] if not (isinstance(fact, str) and "escalated to L4" in fact)
        ]
    if isinstance(record.get("follow_up_owners"), list):
        record["follow_up_owners"] = remove_item(record["follow_up_owners"], L4_SUPPORT_TIER)
    if record.get("recommended_owner") == L4_SUPPORT_TIER:
        record["recommended_owner"] = "L2_L3_software_support"
    if isinstance(record.get("retrieval_text"), str):
        record["retrieval_text"] = record["retrieval_text"].replace(
            " Case 229716 is user-contexted as escalated to L4 through Teams chat/project team involvement.",
            "",
        )


def apply_role_separation(records: dict[str, Any]) -> None:
    for record in flat_records(records):
        support_tiers = record.setdefault("support_tiers_involved", [])
        if L4_SUPPORT_TIER in support_tiers:
            record["support_tiers_involved"] = remove_item(support_tiers, L4_SUPPORT_TIER)
        role_inputs = [
            *record.get("support_tiers_involved", []),
            *record.get("role_constraints", []),
            *record.get("role_requirements", []),
            *record.get("required_permissions", []),
        ]
        organizational_roles = []
        for role_input in role_inputs:
            mapped = ROLE_TO_ORGANIZATIONAL_ROLE.get(role_input)
            if mapped:
                append_unique(organizational_roles, mapped)
        record["organizational_roles"] = organizational_roles
        record.setdefault("escalation_targets", [])
        if record.get("overlay_applied"):
            append_unique(record["escalation_targets"], L4_SUPPORT_TIER)
    escalation = records["escalation_summary_template"]
    if escalation.get("recommended_owner") == L4_SUPPORT_TIER:
        escalation["recommended_owner"] = "L2_L3_software_support"


def prune_relationship_links(records: dict[str, Any]) -> None:
    timeline = records["timeline_events"]
    chunks = records["raw_evidence_chunks"]
    procedures = records["procedure_candidates"]
    workflows = records["workflow_candidate_steps"]
    artifacts = records["source_artifact_references"]
    events_by_id = {event["event_id"]: event for event in timeline}
    chunks_by_id = {chunk["chunk_id"]: chunk for chunk in chunks}

    for chunk in chunks:
        chunk_id = chunk["chunk_id"]
        chunk["linked_procedure_ids"] = [
            procedure["procedure_id"]
            for procedure in procedures
            if chunk_id in procedure.get("supporting_evidence_chunks", [])
        ]
        chunk["linked_workflow_ids"] = [
            workflow["candidate_workflow_name"]
            for workflow in workflows
            if chunk_id in workflow.get("evidence_refs", [])
        ]

    for event in timeline:
        event_id = event["event_id"]
        event["linked_procedure_ids"] = [
            procedure["procedure_id"]
            for procedure in procedures
            if event_id in procedure.get("supporting_timeline_events", [])
        ]
        linked_chunks = event.get("linked_chunk_ids", [])
        event["linked_workflow_ids"] = [
            workflow["candidate_workflow_name"]
            for workflow in workflows
            if set(workflow.get("evidence_refs", [])).intersection(linked_chunks)
            or set(workflow.get("procedure_refs", [])).intersection(event["linked_procedure_ids"])
        ]

    for procedure in procedures:
        procedure["linked_event_ids"] = [
            event_id for event_id in procedure.get("supporting_timeline_events", []) if event_id in events_by_id
        ]
        procedure["linked_chunk_ids"] = [
            chunk_id for chunk_id in procedure.get("supporting_evidence_chunks", []) if chunk_id in chunks_by_id
        ]
        procedure["linked_artifact_ids"] = sorted(
            set(procedure.get("supporting_artifacts", []) + procedure.get("validation_evidence", []))
        )

    for workflow in workflows:
        workflow["linked_chunk_ids"] = [
            chunk_id for chunk_id in workflow.get("evidence_refs", []) if chunk_id in chunks_by_id
        ]
        workflow["linked_procedure_ids"] = [
            procedure_id
            for procedure_id in workflow.get("procedure_refs", [])
            if any(procedure["procedure_id"] == procedure_id for procedure in procedures)
        ]
        workflow["linked_artifact_ids"] = workflow.get("image_refs", [])

    escalation = records["escalation_summary_template"]
    escalation_evidence_refs = set(escalation.get("evidence_refs", []))
    escalation_artifacts = set(escalation.get("source_artifacts", []))
    escalation["linked_chunk_ids"] = [chunk_id for chunk_id in escalation.get("evidence_refs", []) if chunk_id in chunks_by_id]
    escalation["linked_procedure_ids"] = [
        procedure["procedure_id"]
        for procedure in procedures
        if escalation_evidence_refs.intersection(procedure.get("supporting_evidence_chunks", []))
        or escalation_artifacts.intersection(procedure.get("supporting_artifacts", []))
    ]
    escalation["linked_workflow_ids"] = [
        workflow["candidate_workflow_name"]
        for workflow in workflows
        if escalation_evidence_refs.intersection(workflow.get("evidence_refs", []))
        or set(workflow.get("procedure_refs", [])).intersection(escalation["linked_procedure_ids"])
    ]

    artifact_by_id = {artifact["artifact_id"]: artifact for artifact in artifacts}
    for artifact in artifacts:
        artifact_id = artifact["artifact_id"]
        artifact["linked_procedure_ids"] = [
            procedure["procedure_id"]
            for procedure in procedures
            if artifact_id in procedure.get("supporting_artifacts", [])
            or artifact_id in procedure.get("validation_evidence", [])
        ]
        artifact["linked_workflow_ids"] = [
            workflow["candidate_workflow_name"]
            for workflow in workflows
            if artifact_id in workflow.get("image_refs", [])
        ]
        artifact["linked_artifact_ids"] = [artifact_id]
        if artifact.get("parent_artifact_id") in artifact_by_id:
            append_unique(artifact["linked_artifact_ids"], artifact["parent_artifact_id"])

    records["canonical_incident"]["linked_procedure_ids"] = []
    records["canonical_incident"]["linked_workflow_ids"] = []
    add_relationship_metadata(records)


def add_relationship_metadata(records: dict[str, Any]) -> None:
    for record in flat_records(records):
        source_id = record_identifier(record)
        relationships = []
        relationship_specs = [
            ("linked_event_ids", "references", 0.72),
            ("linked_chunk_ids", "supports", 0.8),
            ("linked_artifact_ids", "references", 0.82),
            ("linked_procedure_ids", "supports", 0.86),
            ("linked_workflow_ids", "related_to", 0.68),
        ]
        for field_name, relationship_type, confidence in relationship_specs:
            for target_id in record.get(field_name, []):
                if target_id != source_id:
                    relationships.append(
                        {
                            "target_id": target_id,
                            "relationship_type": relationship_type,
                            "relationship_confidence": confidence,
                        }
                    )
        record["linked_relationships"] = relationships


def apply_workflow_node_shape(records: dict[str, Any]) -> None:
    workflows = records["workflow_candidate_steps"]
    workflow_ids = [workflow["candidate_workflow_name"] for workflow in workflows]
    for index, workflow in enumerate(workflows):
        workflow["container_id"] = "phase0_workflow_candidates"
        workflow["dataset_record_type"] = "workflow_candidate"
        workflow["source_incident_ids"] = workflow.get("source_incident_ids") or [workflow.get("incident_id")]
        workflow["entry_points"] = workflow.get("entry_points") or workflow.get("entry_conditions", [])
        workflow["initial_symptoms"] = workflow.get("initial_symptoms") or workflow.get("entry_conditions", [])
        workflow["diagnoses"] = workflow.get("diagnoses") or workflow.get("diagnostic_signals", []) or workflow.get("required_signals", [])
        workflow["review_status"] = workflow.get("review_status") or "needs_review"
        workflow["step_type"] = "decision"
        workflow["node_type"] = "decision"
        workflow["decision_question"] = workflow.get("question") or "Should this candidate workflow route to the referenced procedure candidates?"
        workflow["next_procedure_refs"] = workflow.get("procedure_refs", [])
        workflow["next_node_refs"] = workflow_ids[index + 1 : index + 2]
        workflow["success_routes"] = [
            {
                "condition": "required_signals_present",
                "next_procedure_refs": workflow["next_procedure_refs"],
                "route_status": "candidate",
            }
        ]
        workflow["failure_routes"] = [
            {
                "condition": "negative_signals_present_or_required_signals_missing",
                "next_node_refs": workflow["next_node_refs"],
                "route_status": "candidate",
            }
        ]
        workflow["candidate_step"] = "Decision node for routing to referenced candidate procedures; operational execution remains in procedure candidates."


def artifact_role(record: dict[str, Any]) -> str:
    artifact_id = record.get("artifact_id", "")
    source_region = record.get("source_region_ref", "")
    regions = " ".join(record.get("regions", []))
    text = " ".join([artifact_id, source_region, regions, record.get("visual_evidence_summary", "")]).lower()
    if "windows_services" in text or "services_window" in text:
        return "service_restart_visual"
    if "hb_statistics" in text or "heartbeat" in text or "tipper_alarms" in text:
        return "heartbeat_visual"
    if "saved_logs" in text or "log_collection" in text:
        return "log_collection_visual"
    if "performance_monitor" in text or "opc_noise" in text:
        return "diagnostic_visual"
    if "rms_map" in text:
        return "rms_state_visual"
    if "recovery" in text or "resolution" in text:
        return "recovery_visual"
    if "teams" in str(record.get("source_section", "")).lower():
        return "escalation_attachment"
    return "operational_context"


def apply_artifact_roles(records: dict[str, Any]) -> None:
    for record in records["source_artifact_references"]:
        role = artifact_role(record)
        record["artifact_role"] = role if role in ALLOWED_ARTIFACT_ROLES else "operational_context"
        record["artifact_role_status"] = "candidate"


def apply_initial_quality_metadata(state: Phase0AgentState) -> None:
    fallback = state.llm_status == "fallback_generic"
    for record in flat_records(state.records):
        record.setdefault("quality_tier", FALLBACK_QUALITY_TIER if fallback else LLM_QUALITY_TIER)
        record.setdefault("eligible_for_cross_incident_synthesis", False)
        record.setdefault("eligible_for_workflow_grouping", False)
        record.setdefault("synthesis_blockers", [])
        record.setdefault("pattern_candidate_notes", "")
        record.setdefault("comparable_signal_groups", [])
        record.setdefault("recurrence_evidence_refs", [])
        if fallback:
            record.update(fallback_quality_fields(state.llm_error))


def apply_agent_refinements(state: Phase0AgentState) -> None:
    normalize_case_relationship_ids(state.records, state.case_id)
    apply_contextual_overlays_to_records(state)
    apply_role_separation(state.records)
    prune_relationship_links(state.records)
    apply_workflow_node_shape(state.records)
    apply_artifact_roles(state.records)
    apply_initial_quality_metadata(state)


def normalize_case_relationship_ids(records: dict[str, Any], case_id: str) -> None:
    for record in flat_records(records):
        if record.get("incident_id"):
            record["incident_id"] = case_id
        if record.get("case_id"):
            record["case_id"] = case_id
        if isinstance(record.get("linked_incident_ids"), list):
            record["linked_incident_ids"] = [case_id if value == "229716" else value for value in record["linked_incident_ids"]]


def base_record(state: Phase0AgentState, record_type: str, section: Any, page: Any, source_ref: str, confidence: float, missing_fields: list[str], notes: list[str]) -> dict[str, Any]:
    return {
        "record_type": record_type,
        "synthesis_level": SYNTHESIS_POLICY.get(record_type, "UNSPECIFIED"),
        "incident_id": state.case_id,
        "source_file": state.active_source_file,
        "source_section": section,
        "source_page": page,
        "source_ref": source_ref,
        "confidence": confidence,
        "validation_status": "candidate_extracted",
        "requires_manual_review": True,
        "missing_fields": missing_fields,
        "extraction_notes": notes,
    }


def build_generic_artifact_records(state: Phase0AgentState, regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for region in regions:
        records.append(
            {
                **base_record(
                    state,
                    "source_artifact_reference",
                    region["source_section"],
                    region["source_page"],
                    region["source_ref"],
                    1.0,
                    [],
                    ["DOCX embedded screenshot retained for source traceability."],
                ),
                "artifact_id": region["artifact_id"],
                "artifact_type": "docx_embedded_image",
                "artifact_path": region["artifact_path"],
                "regions": [region["region_id"]],
            }
        )
    return records


def ensure_detailed_procedure_contract(proc: dict[str, Any]) -> dict[str, Any]:
    proc.setdefault("procedure_detail_level", "skeletal")
    proc.setdefault("procedure_refinement_status", "needs_multi_incident_refinement")
    proc.setdefault("missing_operational_details", [])
    proc.setdefault("required_screenshot_examples", [])
    proc.setdefault("candidate_refinement_questions", [])
    supporting_artifacts = normalize_ref_list(proc.get("supporting_artifacts"))
    region_ids = normalize_ref_list(proc.get("region_ids"))
    for index, step in enumerate(proc.get("procedure_steps", []), start=1):
        step_number = step.get("step_number") or step.get("step_order") or index
        action = step.get("operator_action") or step.get("procedure_step") or step.get("instruction") or ""
        screenshot_ids = normalize_ref_list(step.get("screenshot_artifact_ids") or step.get("related_artifacts") or supporting_artifacts[:1])
        source_region_refs = normalize_ref_list(step.get("source_region_refs") or region_ids)
        step["step_number"] = step_number
        step.setdefault("step_name", f"Step {step_number}")
        step.setdefault("step_goal", step.get("expected_result") or action or "Preserve source-backed procedure evidence for SME review.")
        step.setdefault("operator_action", action or "Review source evidence and capture the case-supported operational detail.")
        step.setdefault("system_or_tool", step.get("system_or_tool") or ", ".join(normalize_ref_list(proc.get("required_tools_or_systems"))) or "source evidence")
        step.setdefault("navigation_path", None)
        step.setdefault("screen_or_view_name", None)
        step.setdefault("evidence_to_capture", step.get("evidence_to_capture") or normalize_ref_list(proc.get("validation_evidence")) or screenshot_ids)
        step.setdefault("data_fields_to_record", [])
        step.setdefault("expected_visual_indicators", [])
        step.setdefault("validation_check", step.get("validation_check") or step.get("expected_result") or "SME confirms the captured evidence supports this procedure step.")
        step["screenshot_artifact_ids"] = screenshot_ids
        step["source_region_refs"] = source_region_refs
        step.setdefault("evidence_quality", "medium" if screenshot_ids or source_region_refs else "low")
        step.setdefault("evidence_quality_notes", "Step requires SME review before promotion.")
        step.setdefault("requires_sme_validation", True)
        step.setdefault("refinement_gap_notes", [])
    return proc


def build_generic_records(state: Phase0AgentState) -> dict[str, Any]:
    regions = state.semantic_regions["regions"]
    interpretations = state.interpretations
    canonical_refs = refs_for_generic(regions, [region["region_id"] for region in regions])
    canonical = {
        **base_record(state, "canonical_incident", "All Source Sections", None, f"{Path(state.active_source_file).name}#mixed-screenshot-regions", 0.65, ["validated_root_cause"], ["Generic OCR-derived candidate incident summary."]),
        **interpretations["canonical_incident"],
        **canonical_refs,
        **toolkit.review_fields(["L2_L3_software_support"], ["case_review_access"]),
        "workflow_candidate": True,
    }
    chunks = []
    for chunk in interpretations["semantic_chunks"]:
        refs = refs_for_generic(regions, chunk.get("region_ids", []))
        chunk_record = {
            **base_record(state, "raw_evidence_chunk", "Mixed Screenshot Evidence", refs["source_pages"], ",".join(refs["source_region_refs"]), refs["confidence"], [], ["Generic semantic chunk from OCR/media region."]),
            "chunk_id": chunk["chunk_id"],
            "title": chunk["title"],
            "content": chunk["summary"],
            "raw_source_type": chunk["raw_source_type"],
            "evidence_type": chunk["evidence_type"],
            **{bucket: chunk.get(bucket, []) for bucket in toolkit.SIGNAL_BUCKETS},
            "source_artifact_ids": refs["source_artifact_ids"],
            "source_artifact_paths": refs["source_artifact_paths"],
            "embedded_artifact_ids": refs["embedded_artifact_ids"],
            "embedded_artifact_paths": refs["embedded_artifact_paths"],
            "source_region_refs": refs["source_region_refs"],
            "visual_evidence_summary": "DOCX media screenshot retained as source evidence.",
        }
        if refs["escalated"]:
            chunk_record.update({"escalated": True, "escalation_source": "teams_chat", "support_tiers_involved": ["L1_technical_support", "L2_L3_software_support"]})
        chunks.append(chunk_record)
    timeline = []
    for index, event in enumerate(interpretations["timeline_events"], start=1):
        refs = refs_for_generic(regions, event.get("region_ids", []))
        event_record = {
            **base_record(state, "timeline_event", "Mixed Screenshot Evidence", refs["source_pages"], ",".join(refs["source_region_refs"]), refs["confidence"], ["normalized_timestamp"], ["Timeline event is OCR/media-order derived and requires manual review."]),
            **event,
            "event_order": index,
            **{bucket: event.get(bucket, []) for bucket in toolkit.SIGNAL_BUCKETS},
            "source_artifact_ids": refs["source_artifact_ids"],
            "source_artifact_paths": refs["source_artifact_paths"],
            "embedded_artifact_ids": refs["embedded_artifact_ids"],
            "embedded_artifact_paths": refs["embedded_artifact_paths"],
            "source_region_refs": refs["source_region_refs"],
        }
        if refs["escalated"]:
            event_record.update({"escalated": True, "escalation_source": "teams_chat", "support_tiers_involved": ["L1_technical_support", "L2_L3_software_support"]})
        timeline.append(event_record)
    procedures = []
    for proc in interpretations["procedure_candidates"]:
        refs = refs_for_generic(regions, proc.get("region_ids", []))
        detailed_proc = ensure_detailed_procedure_contract(proc)
        proc_record = {
            **base_record(state, "procedure_candidate", "Mixed Screenshot Evidence", refs["source_pages"], ",".join(refs["source_region_refs"]), refs["confidence"], ["approval_status"], ["Generic procedure candidate from OCR evidence."]),
            **toolkit.ensure_procedure_contract(detailed_proc),
            "procedure_id": detailed_proc["procedure_candidate_id"],
            "container_id": "phase0_procedure_candidates",
            **toolkit.review_fields(detailed_proc.get("role_requirements", []), detailed_proc.get("required_permissions", [])),
            "source_artifact_ids": refs["source_artifact_ids"],
            "source_artifact_paths": refs["source_artifact_paths"],
            "embedded_artifact_ids": refs["embedded_artifact_ids"],
            "embedded_artifact_paths": refs["embedded_artifact_paths"],
            "source_region_refs": refs["source_region_refs"],
        }
        if refs["escalated"]:
            proc_record.update({"escalated": True, "escalation_source": "teams_chat", "support_tiers_involved": ["L1_technical_support", "L2_L3_software_support"]})
        procedures.append(proc_record)
    workflows = []
    for workflow in interpretations["workflow_candidate_steps"]:
        refs = refs_for_generic(regions, workflow.get("region_ids", []))
        workflows.append(
            {
                **base_record(state, "workflow_candidate_step", "Mixed Screenshot Evidence", refs["source_pages"], ",".join(refs["source_region_refs"]), refs["confidence"], ["approved_owner"], ["Generic workflow node candidate from OCR evidence."]),
                **workflow,
                "workflow_candidate": True,
                "source_artifact_ids": refs["source_artifact_ids"],
                "source_artifact_paths": refs["source_artifact_paths"],
                "embedded_artifact_ids": refs["embedded_artifact_ids"],
                "embedded_artifact_paths": refs["embedded_artifact_paths"],
                "source_region_refs": refs["source_region_refs"],
            }
        )
    escalation_data = interpretations["escalation_summary_template"]
    records = {
        "canonical_incident": canonical,
        "timeline_events": timeline,
        "raw_evidence_chunks": chunks,
        "source_artifact_references": build_generic_artifact_records(state, regions),
        "procedure_candidates": procedures,
        "workflow_candidate_steps": workflows,
        "escalation_summary_template": {
            **base_record(state, "escalation_summary_template", "Mixed Screenshot Evidence", None, f"{Path(state.active_source_file).name}#mixed-screenshot-regions", 0.65, ["validated_owner"], ["Generic escalation template from OCR evidence."]),
            **escalation_data,
            "case_id": state.case_id,
            "escalation_trigger": escalation_data["trigger_reason"],
            "current_state": "Requires manual review.",
            "actions_taken": escalation_data["steps_attempted"],
            "source_artifacts": canonical_refs["source_artifact_ids"],
            "evidence_refs": normalize_ref_list(escalation_data.get("evidence_refs")),
            **toolkit.review_fields(["L2_L3_software_support"], ["case_review_access"]),
            "escalated": any(region["region_type"] == "teams_message_thread" for region in regions),
            "escalation_source": "teams_chat" if any(region["region_type"] == "teams_message_thread" for region in regions) else "unknown",
            "support_tiers_involved": ["L1_technical_support", "L2_L3_software_support"] if any(region["region_type"] == "teams_message_thread" for region in regions) else [],
            "source_artifact_ids": canonical_refs["source_artifact_ids"],
            "source_artifact_paths": canonical_refs["source_artifact_paths"],
            "embedded_artifact_ids": [],
            "embedded_artifact_paths": [],
            "source_region_refs": canonical_refs["source_region_refs"],
        },
    }
    return toolkit.add_relationship_ids(records)


def build_records_node(state: Phase0AgentState) -> Phase0AgentState:
    state.records = build_generic_records(state) if state.use_generic_interpretation else toolkit.build_records(state.semantic_regions, state.interpretations)
    apply_agent_refinements(state)
    state.bundle = {
        "bundle_metadata": {
            "incident_id": state.case_id,
            "phase": "0",
            "category": state.records.get("canonical_incident", {}).get("issue_category") or toolkit.dataset_context_packet(state.reference).get("deterministic_issue_category"),
            "created_at": utc_now(),
            "source_files": [
                "prompts/phase0_system_prompt.txt",
                "docs/Phase0 Cat1 Dataset Seed Records V1.docx",
                "docs/Optisweep Issue Categories.docx",
                state.active_source_file,
            ],
            "ocr_engine": "PaddleOCR 3.5.0 / PaddlePaddle 3.2.2 / PP-OCRv5 server det+rec",
            "interpretation_engine": INTERPRETATION_ENGINE,
            "llm_status": state.llm_status,
            "llm_provider": state.llm_provider,
            "llm_deployment": state.llm_deployment,
            "llm_fallback_reason": state.llm_error,
            "agent_name": "Phase 0 Ingestion Agent",
            "agent_version": "phase0_ingestion_agent_v1",
            "contextual_overlays": copy.deepcopy(state.contextual_overlays),
            "synthesis_policy": SYNTHESIS_POLICY,
            "validation_status": "candidate_extracted",
            "requires_manual_review": True,
        },
        "records": state.records,
    }
    return state


def validate_records_node(state: Phase0AgentState) -> Phase0AgentState:
    state.validation_report = validate_generic_records(state) if state.use_generic_interpretation else toolkit.validate_records(state.records, state.interpretations)
    apply_agent_validation_checks(state)
    apply_final_synthesis_eligibility(state)
    if state.validation_report.get("validation_status") != "passed":
        state.halted = True
        state.halt_reason = "validation_failed"
    return state


def validate_generic_records(state: Phase0AgentState) -> dict[str, Any]:
    records = state.records
    all_records = flat_records(records)
    issues = []
    required = ["record_type", "incident_id", "source_file", "confidence", "validation_status", "requires_manual_review", "missing_fields", "extraction_notes"]
    for index, record in enumerate(all_records, start=1):
        for field_name in required:
            if field_name not in record:
                issues.append({"record_index": index, "record_type": record.get("record_type"), "issue": f"missing {field_name}"})
        if record.get("validation_status") != "candidate_extracted":
            issues.append({"record_index": index, "record_type": record.get("record_type"), "issue": "invalid validation_status"})
        if record.get("requires_manual_review") is not True:
            issues.append({"record_index": index, "record_type": record.get("record_type"), "issue": "requires_manual_review must be true"})
        for path in record.get("source_artifact_paths", []):
            if not (ROOT / path).exists():
                issues.append({"record_index": index, "record_type": record.get("record_type"), "issue": f"missing artifact path {path}"})
    return {
        "validation_status": "passed" if not issues else "failed",
        "record_count": len(all_records),
        "issues": issues,
        "interpretation_engine": state.llm_status,
        "llm_provider": state.llm_provider,
        "llm_deployment": state.llm_deployment,
        "llm_fallback_reason": state.llm_error,
        "llm_usage": state.llm_usage,
        "quality_checks": {
            "generic_docx_ocr_pages_present": len(state.ocr_data.get("pages", [])) > 0,
            "generic_regions_present": len(records["raw_evidence_chunks"]) > 0,
            "candidate_procedures_present": len(records["procedure_candidates"]) > 0,
            "candidate_workflows_present": len(records["workflow_candidate_steps"]) > 0,
            "records_link_images_directly": all(record.get("source_artifact_paths") for record in [*records["timeline_events"], *records["raw_evidence_chunks"]]),
            "candidate_status_preserved": all(record.get("validation_status") == "candidate_extracted" and record.get("requires_manual_review") is True for record in all_records),
        },
    }


def apply_agent_validation_checks(state: Phase0AgentState) -> None:
    records = state.records
    all_records = flat_records(records)
    procedures = records["procedure_candidates"]
    canonical = records["canonical_incident"]
    llm_checks = {}
    if state.llm_status == "azure_openai":
        llm_checks = {
            "llm_timeline_event_count_8_to_12": 8 <= len(records["timeline_events"]) <= 12,
            "llm_chunks_grouped_below_region_count": len(records["raw_evidence_chunks"]) < len(state.semantic_regions.get("regions", [])),
            "llm_canonical_has_synthesized_retrieval_text": bool(canonical.get("retrieval_text")) and len(canonical.get("retrieval_text", "")) > 250,
            "llm_candidate_inferred_causes_structured": all(
                all(field_name in cause for field_name in ["cause_summary", "basis", "confidence", "validation_status", "requires_manual_review"])
                for cause in canonical.get("candidate_inferred_causes", [])
            ),
            "llm_records_include_source_artifact_region_refs": all(
                record.get("source_artifact_ids") is not None and record.get("source_region_refs") is not None
                for record in [*records["timeline_events"], *records["raw_evidence_chunks"], *records["procedure_candidates"], *records["workflow_candidate_steps"]]
            ),
        }
    checks = {
        "contextual_overlays_are_conditional": all(
            overlay.get("validation_status") == "unverified_overlay" and overlay.get("applies_conditionally") is True
            for overlay in state.contextual_overlays
        ),
        "overlay_not_promoted_to_operational_signals": not any(
            L4_ESCALATION_SIGNAL in record.get(bucket, [])
            for record in all_records
            for bucket in [
                "observed_failure_signals",
                "diagnostic_signals",
                "action_signals",
                "recovery_validation_signals",
                "escalation_signals",
            ]
        ),
        "overlay_not_promoted_to_active_support_or_owner": not any(
            L4_SUPPORT_TIER in record.get("support_tiers_involved", []) or record.get("recommended_owner") == L4_SUPPORT_TIER
            for record in all_records
        ),
        "role_separation_fields_present": all(
            "organizational_roles" in record and "escalation_targets" in record for record in all_records
        ),
        "relationship_metadata_present": all("linked_relationships" in record for record in all_records),
        "relationship_links_reduced": all(
            all(
                event["event_id"] in procedure.get("supporting_timeline_events", [])
                for procedure_id in event.get("linked_procedure_ids", [])
                for procedure in procedures
                if procedure["procedure_id"] == procedure_id
            )
            for event in records["timeline_events"]
        )
        and all(
            all(
                chunk["chunk_id"] in procedure.get("supporting_evidence_chunks", [])
                for procedure_id in chunk.get("linked_procedure_ids", [])
                for procedure in procedures
                if procedure["procedure_id"] == procedure_id
            )
            for chunk in records["raw_evidence_chunks"]
        ),
        "workflow_steps_are_node_like": all(
            workflow.get("node_type") in {"decision", "orchestration"}
            and workflow.get("decision_question")
            and isinstance(workflow.get("next_procedure_refs"), list)
            and isinstance(workflow.get("success_routes"), list)
            and isinstance(workflow.get("failure_routes"), list)
            for workflow in records["workflow_candidate_steps"]
        ),
        "artifact_roles_present": all(
            artifact.get("artifact_role") in ALLOWED_ARTIFACT_ROLES
            and artifact.get("artifact_role_status") == "candidate"
            for artifact in records["source_artifact_references"]
        ),
        "candidate_status_preserved": all(
            record.get("validation_status") == "candidate_extracted" and record.get("requires_manual_review") is True
            for record in all_records
        ),
        **llm_checks,
    }
    state.validation_report.setdefault("quality_checks", {}).update(checks)
    failed_checks = [name for name, passed in checks.items() if not passed]
    for check_name in failed_checks:
        state.validation_report.setdefault("issues", []).append(
            {"record_index": None, "record_type": "agent_refinement", "issue": f"failed {check_name}"}
        )
    if failed_checks:
        state.validation_report["validation_status"] = "failed"


def has_source_refs(record: dict[str, Any]) -> bool:
    return bool(record.get("source_ref") or record.get("source_region_refs") or record.get("source_artifact_ids") or record.get("evidence_refs"))


def has_signal_bucket(record: dict[str, Any]) -> bool:
    return any(record.get(bucket) for bucket in toolkit.SIGNAL_BUCKETS)


def apply_final_synthesis_eligibility(state: Phase0AgentState) -> None:
    passed = state.validation_report.get("validation_status") == "passed"
    for record in flat_records(state.records):
        fallback = record.get("quality_tier") == FALLBACK_QUALITY_TIER or state.llm_status == "fallback_generic"
        skeletal = record.get("procedure_detail_level") == "skeletal"
        eligible = (
            passed
            and not fallback
            and has_source_refs(record)
            and has_signal_bucket(record)
            and not skeletal
        )
        if record.get("record_type") in {"raw_evidence_chunk", "source_artifact_reference", "timeline_event"}:
            eligible = False
        record["eligible_for_cross_incident_synthesis"] = eligible
        record["eligible_for_workflow_grouping"] = eligible and record.get("record_type") == "workflow_candidate_step"
        blockers = list(record.get("synthesis_blockers", []))
        if not passed:
            blockers.append("validation_not_passed")
        if fallback:
            blockers.append("fallback_review_only")
        if skeletal:
            blockers.append("skeletal_candidate")
        if not has_source_refs(record):
            blockers.append("missing_source_refs")
        if not has_signal_bucket(record):
            blockers.append("missing_signal_buckets")
        record["synthesis_blockers"] = list(dict.fromkeys(blockers))


def write_outputs_node(state: Phase0AgentState) -> Phase0AgentState:
    write_json(state.extracted_dir / f"{state.output_prefix}_docx_ocr.json", state.ocr_data)
    write_json(state.extracted_dir / f"{state.output_prefix}_layout_blocks.json", state.layout_blocks)
    write_json(state.extracted_dir / f"{state.output_prefix}_semantic_regions.json", state.semantic_regions)
    write_json(state.extracted_dir / f"{state.output_prefix}_agent_llm_context.json", state.interpretations.get("dataset_context_used"))
    write_json(state.extracted_dir / f"{state.output_prefix}_llm_interpretations.json", state.interpretations)
    write_json(state.output_dir / "seed_records.json", state.bundle)
    write_json(state.output_dir / "validation_report.json", state.validation_report)
    return state


def persist_knowledge_store_node(state: Phase0AgentState) -> Phase0AgentState:
    if not any([state.persist_to_knowledge_store, state.knowledge_store_dry_run, state.sync_search, state.upload_artifacts]):
        state.knowledge_store_report = {"status": "skipped", "reason": "not_requested"}
        return state
    if state.validation_report and state.validation_report.get("validation_status") != "passed":
        state.knowledge_store_report = {"status": "skipped", "reason": "validation_not_passed"}
        state.validation_report["knowledge_store"] = state.knowledge_store_report
        write_json(state.output_dir / "validation_report.json", state.validation_report)
        return state
    try:
        from backend.app.seed.bundle_mapper import document_counts, map_phase0_bundle
        from backend.app.seed.seed_phase0_bundle import persist_documents
        from backend.app.search.index_documents import search_documents_from_container_documents
        from backend.app.search.search_client import search_client
        from backend.app.storage.blob_client import upload_artifact

        documents = map_phase0_bundle(state.bundle, build_trace_payload(state))
        report = {
            "status": "dry_run" if state.knowledge_store_dry_run else "completed",
            "dry_run": state.knowledge_store_dry_run,
            "documents": document_counts(documents),
            "persist_requested": state.persist_to_knowledge_store,
            "search_sync_requested": state.sync_search,
            "artifact_upload_requested": state.upload_artifacts,
            "search_documents": 0,
            "uploaded_artifacts": 0,
        }
        if state.upload_artifacts:
            artifact_records = documents.get("source_artifacts", [])
            uploadable = [record for record in artifact_records if record.get("file_path")]
            report["uploaded_artifacts"] = len(uploadable)
            if not state.knowledge_store_dry_run:
                for record in uploadable:
                    upload_result = upload_artifact(ROOT / record["file_path"], state.case_id, category="screenshots")
                    record.update(upload_result)
        if state.sync_search:
            search_documents = search_documents_from_container_documents(documents)
            report["search_documents"] = len(search_documents)
        if state.persist_to_knowledge_store and not state.knowledge_store_dry_run:
            report["upserted"] = persist_documents(documents)
        if state.sync_search and not state.knowledge_store_dry_run:
            upload_result = search_client().upload_documents(search_documents_from_container_documents(documents))
            report["search_upload"] = {
                "submitted": len(upload_result),
                "succeeded": sum(1 for item in upload_result if item.succeeded),
                "failed": sum(1 for item in upload_result if not item.succeeded),
            }
        state.knowledge_store_report = report
    except Exception as exc:
        state.knowledge_store_report = {
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "dry_run": state.knowledge_store_dry_run,
            "persist_requested": state.persist_to_knowledge_store,
            "search_sync_requested": state.sync_search,
            "artifact_upload_requested": state.upload_artifacts,
        }
        state.halted = True
        state.halt_reason = "knowledge_store_persistence_failed"
    state.validation_report["knowledge_store"] = state.knowledge_store_report
    write_json(state.output_dir / "validation_report.json", state.validation_report)
    return state


def build_trace_payload(state: Phase0AgentState) -> dict[str, Any]:
    return {
        "agent_name": "Phase 0 Ingestion Agent",
        "agent_version": "phase0_ingestion_agent_v1",
        "interpretation_engine": INTERPRETATION_ENGINE,
        "llm_status": state.llm_status,
        "llm_provider": state.llm_provider,
        "llm_deployment": state.llm_deployment,
        "llm_fallback_reason": state.llm_error,
        "llm_usage": state.llm_usage,
        "llm_input_packet_path": relative_path(state.llm_input_path) if state.llm_input_path else None,
        "source_files": [
            "prompts/phase0_system_prompt.txt",
            "docs/Phase0 Cat1 Dataset Seed Records V1.docx",
            "docs/Optisweep Issue Categories.docx",
            state.active_source_file,
        ],
        "contextual_overlays": copy.deepcopy(state.contextual_overlays),
        "knowledge_store": state.knowledge_store_report,
        "output_dir": str(state.output_dir.relative_to(ROOT)).replace("\\", "/"),
        "halted": state.halted,
        "halt_reason": state.halt_reason,
        "validation_summary": {
            "validation_status": state.validation_report.get("validation_status") if state.validation_report else None,
            "issue_count": len(state.validation_report.get("issues", [])) if state.validation_report else None,
            "record_count": state.validation_report.get("record_count") if state.validation_report else None,
        },
        "nodes": state.run_trace,
    }


def run_agent_graph(state: Phase0AgentState, nodes: list[tuple[str, Node]]) -> Phase0AgentState:
    for node_name, node in nodes:
        started_at = utc_now()
        started = time.perf_counter()
        status = "completed"
        error = None
        try:
            state = node(state)
        except Exception as exc:
            status = "failed"
            error = f"{type(exc).__name__}: {exc}"
            state.halted = True
            state.halt_reason = error
        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        state.run_trace.append(
            {
                "node": node_name,
                "started_at": started_at,
                "ended_at": utc_now(),
                "duration_ms": duration_ms,
                "status": status,
                "error": error,
                "outputs": state_outputs(state),
            }
        )
        if node_name in {"write_outputs", "persist_knowledge_store"} and status == "completed":
            write_json(state.output_dir / "agent_run_trace.json", build_trace_payload(state))
        if status == "failed":
            break
    return state


def graph_nodes() -> list[tuple[str, Node]]:
    return [
        ("load_inputs", load_inputs_node),
        ("copy_artifacts", copy_artifacts_node),
        ("reconstruct_layout", reconstruct_layout_node),
        ("classify_regions", classify_regions_node),
        ("create_embedded_artifacts", create_embedded_artifacts_node),
        ("interpret_regions", interpret_regions_node),
        ("build_records", build_records_node),
        ("validate_records", validate_records_node),
        ("write_outputs", write_outputs_node),
        ("persist_knowledge_store", persist_knowledge_store_node),
    ]


def contextual_overlays_for_case(case_id: str) -> list[dict[str, Any]]:
    overlay = copy.deepcopy(AGENT_LLM_CONTEXT_OVERLAY)
    overlay["case_id"] = case_id
    return [overlay]


def state_for_args(args: argparse.Namespace) -> Phase0AgentState:
    llm_config_path = Path(args.llm_config) if args.llm_config else AZURE_OPENAI_CONFIG_PATH
    if not llm_config_path.is_absolute():
        llm_config_path = ROOT / llm_config_path
    if not args.source_docx:
        return Phase0AgentState(
            llm_config_path=llm_config_path,
            persist_to_knowledge_store=args.persist_to_knowledge_store,
            knowledge_store_dry_run=args.knowledge_store_dry_run,
            sync_search=args.sync_search,
            upload_artifacts=args.upload_artifacts,
        )
    source_docx_path = Path(args.source_docx)
    if not source_docx_path.is_absolute():
        source_docx_path = ROOT / source_docx_path
    case_id = args.case_id or infer_case_id(source_docx_path)
    output_prefix = f"case_{case_id}"
    output_dir = ROOT / "output" / "phase0" / f"case_{case_id}_docx_agent"
    active_source_file = relative_path(source_docx_path)
    return Phase0AgentState(
        case_id=case_id,
        active_source_file=active_source_file,
        source_docx_path=source_docx_path,
        output_prefix=output_prefix,
        use_generic_interpretation=True,
        source_ocr_path=output_dir / "extracted" / f"{output_prefix}_docx_ocr.json",
        output_dir=output_dir,
        extracted_dir=output_dir / "extracted",
        artifact_dir=output_dir / "artifacts" / "docx_media",
        embedded_artifact_dir=output_dir / "artifacts" / "embedded_regions",
        llm_config_path=llm_config_path,
        contextual_overlays=contextual_overlays_for_case(case_id),
        persist_to_knowledge_store=args.persist_to_knowledge_store,
        knowledge_store_dry_run=args.knowledge_store_dry_run,
        sync_search=args.sync_search,
        upload_artifacts=args.upload_artifacts,
    )


def infer_case_id(path: Path) -> str:
    match = re.search(r"(\d{5,})", path.name)
    if not match:
        raise ValueError(f"Could not infer case id from {path}")
    return match.group(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-docx")
    parser.add_argument("--case-id")
    parser.add_argument("--llm-config", default=str(AZURE_OPENAI_CONFIG_PATH))
    parser.add_argument("--persist-to-knowledge-store", action="store_true")
    parser.add_argument("--knowledge-store-dry-run", action="store_true")
    parser.add_argument("--sync-search", action="store_true")
    parser.add_argument("--upload-artifacts", action="store_true")
    args = parser.parse_args()
    state = run_agent_graph(state_for_args(args), graph_nodes())
    summary = {
        "output_dir": str(state.output_dir),
        "trace_path": str(state.output_dir / "agent_run_trace.json"),
        "halted": state.halted,
        "halt_reason": state.halt_reason,
        "knowledge_store": state.knowledge_store_report,
        **(state.validation_report or {"validation_status": "failed"}),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if state.halted and state.halt_reason != "validation_failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
