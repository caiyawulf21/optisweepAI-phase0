from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


ALLOWED_VISUAL_ELEMENT_TYPES = {
    "screenshot",
    "diagram",
    "table",
    "flow",
    "ui_screen",
    "database_schema",
    "architecture_diagram",
    "photo",
    "icon",
    "unknown",
}
ALLOWED_UNIT_TYPES = {
    "system_behavior",
    "ui_concept",
    "operational_process",
    "state_transition",
    "routing_rule",
    "queueing_rule",
    "diagnostic_concept",
    "architecture_relationship",
    "database_model_reference",
    "api_capability",
    "glossary_definition",
}
ALLOWED_CONTEXT_TYPES = {
    "technology_reference",
    "product_description",
    "product_behavior",
    "ui_reference",
    "operational_concept",
    "glossary",
    "process_definition",
    "architecture_reference",
    "database_reference",
    "api_reference",
}
ALLOWED_PROCEDURE_TYPES = {
    "navigation",
    "diagnostic_check",
    "operational_action",
    "validation_check",
    "recovery_action",
    "configuration_action",
    "service_restart",
    "api_action",
    "unknown",
}
ALLOWED_ROLES = {
    "operator",
    "L1_technical_support",
    "L2_L3_software_support",
    "L2_L3_infrastructure",
    "L2_L3_controls",
    "DBA",
    "DevOps",
    "project_team",
    "software_engineering",
    "unknown",
}
ALLOWED_SUPPORT_SAFE = {"yes", "no", "unknown"}
ACTION_TERMS = {
    "add",
    "cancel",
    "check",
    "click",
    "confirm",
    "disable",
    "enable",
    "enter",
    "exchange",
    "initialize",
    "log",
    "open",
    "rdp",
    "remove",
    "reset",
    "restart",
    "select",
    "start",
    "stop",
    "validate",
    "verify",
}
VAGUE_STEP_PHRASES = {
    "do it",
    "handle it",
    "use the api",
    "use apis",
    "check it",
    "fix it",
    "perform action",
    "take action",
}
BROAD_TOPIC_TITLE_PATTERN = re.compile(
    r"^(agv|agvs|api|apis|database|models|robot|robots|rms|tipping|tipper|tippers|architecture|overview|training slide reference|agv training slide reference)$",
    re.IGNORECASE,
)
PROMPT_VERSION = "slide_knowledge_extraction_v3"


class SlideKnowledgeError(RuntimeError):
    pass


@dataclass
class LoadedSlide:
    slide_number: int
    text_lines: list[str]
    image_path: str
    page_size: dict[str, float]
    ocr_lines: list[str] = field(default_factory=list)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any, force: bool = False) -> None:
    if path.exists() and not force:
        raise SlideKnowledgeError(f"Refusing to overwrite existing output without --force: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def unique_strings(values: Any) -> list[str]:
    result: list[str] = []
    for value in as_list(values):
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return result


def unique_values(values: Any) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in as_list(values):
        marker = json.dumps(value, sort_keys=True, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
        if marker not in seen:
            seen.add(marker)
            result.append(value)
    return result


def text_blob(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if isinstance(value, list):
            parts.extend(str(item).strip() for item in value if str(item).strip())
        elif value is not None and str(value).strip():
            parts.append(str(value).strip())
    return " ".join(parts)


def truncate_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def azure_openai_token_args(config: dict[str, Any]) -> dict[str, int]:
    token_budget = int(config.get("max_completion_tokens") or config.get("max_tokens") or 4000)
    model_name = str(config.get("deployment") or config.get("model") or "").lower()
    if model_name.startswith("gpt-5") or config.get("use_max_completion_tokens"):
        return {"max_completion_tokens": token_budget}
    return {"max_tokens": token_budget}


def openai_generation_args(config: dict[str, Any]) -> dict[str, Any]:
    model_name = str(config.get("deployment") or config.get("model") or "").lower()
    args: dict[str, Any] = {}
    if not model_name.startswith("gpt-5"):
        args["temperature"] = config.get("temperature", 0.1)
    args.update(azure_openai_token_args(config))
    return args


def llm_stage_config(config: dict[str, Any], stage: str) -> dict[str, Any]:
    stage_config = config.get(stage)
    if isinstance(stage_config, dict):
        merged = dict(config)
        merged.update(stage_config)
        return merged
    return config


class SlideDeckLoader:
    def __init__(
        self,
        source_pdf: Path,
        image_dir: Path,
        limit_slides: int | None = None,
        start_slide: int | None = None,
        end_slide: int | None = None,
        enable_ocr: bool = False,
    ) -> None:
        self.source_pdf = source_pdf
        self.image_dir = image_dir
        self.limit_slides = limit_slides
        self.start_slide = start_slide
        self.end_slide = end_slide
        self.enable_ocr = enable_ocr

    def load(self) -> list[LoadedSlide]:
        if not self.source_pdf.exists():
            raise SlideKnowledgeError(f"Source PDF does not exist: {self.source_pdf}")
        try:
            import fitz
        except ImportError as exc:
            raise SlideKnowledgeError("PyMuPDF is required for PDF slide extraction. Install requirements-ocr.txt.") from exc
        self.image_dir.mkdir(parents=True, exist_ok=True)
        slides: list[LoadedSlide] = []
        with fitz.open(self.source_pdf) as document:
            total = len(document)
            start_index = max(0, (self.start_slide or 1) - 1)
            end_index = min(total, self.end_slide or total)
            if self.limit_slides:
                end_index = min(end_index, start_index + self.limit_slides)
            for index in range(start_index, end_index):
                page = document[index]
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image_path = self.image_dir / f"slide_{index + 1:04d}.png"
                pixmap.save(str(image_path))
                text_lines = self._text_lines(page.get_text("text"))
                ocr_lines = self._ocr_lines(image_path)
                slides.append(
                    LoadedSlide(
                        slide_number=index + 1,
                        text_lines=text_lines,
                        image_path=str(image_path),
                        page_size={"width": float(page.rect.width), "height": float(page.rect.height)},
                        ocr_lines=ocr_lines,
                    )
                )
        return slides

    def _text_lines(self, raw_text: str) -> list[str]:
        return unique_strings([line.strip() for line in raw_text.splitlines() if line.strip()])

    def _ocr_lines(self, image_path: Path) -> list[str]:
        if not self.enable_ocr:
            return []
        try:
            import pytesseract
            from PIL import Image
        except ImportError:
            return []
        tesseract_path = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        if tesseract_path.exists():
            pytesseract.pytesseract.tesseract_cmd = str(tesseract_path)
        try:
            raw_text = pytesseract.image_to_string(Image.open(image_path))
        except Exception:
            return []
        return self._text_lines(raw_text)


class SlideArtifactBuilder:
    def build(self, deck_id: str, source_file: Path, slides: list[LoadedSlide]) -> list[dict[str, Any]]:
        artifacts: list[dict[str, Any]] = []
        for slide in slides:
            title_lines = self._meaningful_lines(slide.text_lines)
            title = self._slide_title(title_lines, slide.slide_number)
            combined_text = unique_strings(slide.text_lines + slide.ocr_lines)
            evidence_hints = self._evidence_hints(combined_text)
            artifact_id = f"slide_artifact_{clean_id(deck_id)}_{slide.slide_number:04d}"
            source_refs = [f"deck:{deck_id}", f"slide:{slide.slide_number}", f"artifact:{artifact_id}"]
            artifacts.append(
                {
                    "artifact_id": artifact_id,
                    "deck_id": deck_id,
                    "source_file": str(source_file),
                    "slide_number": slide.slide_number,
                    "slide_title": title,
                    "section": title_lines[0] if title_lines else "",
                    "visible_text": slide.text_lines,
                    "ocr_text": slide.ocr_lines,
                    "image_path": slide.image_path,
                    "visual_summary": self._visual_summary(title, combined_text),
                    "visual_elements": [
                        {
                            "element_type": self._visual_element_type(evidence_hints),
                            "description": "Rendered slide screenshot is available as this artifact; labels come from PDF text and optional OCR.",
                            "visible_labels": combined_text[:20],
                            "systems_or_components": self._systems_or_components(combined_text),
                        }
                    ],
                    "candidate_record_types": evidence_hints["candidate_record_types"],
                    "evidence_hints": evidence_hints,
                    "source_refs": source_refs,
                    "validation_status": "needs_review",
                }
            )
        return artifacts

    def _slide_title(self, meaningful_lines: list[str], slide_number: int) -> str:
        if meaningful_lines:
            return truncate_text(" / ".join(meaningful_lines[:2]), 140)
        return f"Slide {slide_number}"

    def _meaningful_lines(self, text_lines: list[str]) -> list[str]:
        return [line for line in [re.sub(r"\s+", " ", value).strip() for value in text_lines] if self._is_meaningful_title_line(line)]

    def _is_meaningful_title_line(self, line: str) -> bool:
        if not line:
            return False
        lower = line.lower()
        if lower.startswith("©") or "all rights reserved" in lower or "confidential" in lower:
            return False
        if re.fullmatch(r"\d+\.?", line):
            return False
        if re.fullmatch(r"[•\-\u25e6]?", line) or line.startswith(("•", "◦")):
            return False
        return True

    def _visual_summary(self, title: str, text_lines: list[str]) -> str:
        body = " ".join(text_lines[1:5])
        return truncate_text(text_blob(title, body), 400)

    def _evidence_hints(self, text_lines: list[str]) -> dict[str, Any]:
        text = "\n".join(text_lines)
        lower = text.lower()
        has_numbered_steps = bool(re.search(r"(?:^|\n)\s*\d+\.\s+\S+", text))
        has_action_terms = any(term in lower for term in ACTION_TERMS)
        has_api_names = bool(re.search(r"\b[A-Z][A-Za-z0-9]+(?:Command|AGV|Stats|State|Startup|Shutdown|Chutes|Out)\b", text)) or "api" in lower
        has_database_terms = any(term in lower for term in ["database", "model", "table", "sortguid", "sql"])
        has_state_terms = any(term in lower for term in ["state", "startup", "shutdown", "running", "requested", "staged"])
        has_ui_terms = any(term in lower for term in ["click", "button", "screen", "page", "menu", "select", "field"])
        has_process_terms = any(term in lower for term in ["round-robin", "queue", "assigned", "lifecycle", "heartbeat", "recover", "fault"])
        candidate_record_types = []
        if has_numbered_steps and has_action_terms:
            candidate_record_types.append("procedure")
        if has_api_names:
            candidate_record_types.append("api_reference")
        if has_database_terms:
            candidate_record_types.append("database_reference")
        if has_ui_terms:
            candidate_record_types.append("ui_reference")
        if has_state_terms or has_process_terms:
            candidate_record_types.append("operational_knowledge_unit")
        return {
            "has_numbered_steps": has_numbered_steps,
            "has_action_terms": has_action_terms,
            "has_api_names": has_api_names,
            "has_database_terms": has_database_terms,
            "has_state_terms": has_state_terms,
            "has_ui_terms": has_ui_terms,
            "has_process_terms": has_process_terms,
            "candidate_record_types": unique_strings(candidate_record_types),
        }

    def _visual_element_type(self, evidence_hints: dict[str, Any]) -> str:
        if evidence_hints.get("has_database_terms"):
            return "database_schema"
        if evidence_hints.get("has_ui_terms"):
            return "ui_screen"
        if evidence_hints.get("has_state_terms") or evidence_hints.get("has_process_terms"):
            return "flow"
        return "unknown"

    def _systems_or_components(self, text_lines: list[str]) -> list[str]:
        known = ["OptiSweep", "Geek+ RMS", "AGV", "Aveva", "HMI", "Ignition", "Stunnel", "SQL Server", "Tipper", "Hospital", "Robot", "Tote"]
        lower = "\n".join(text_lines).lower()
        return [value for value in known if value.lower() in lower]


class LLMSlideKnowledgeExtractor:
    def __init__(
        self,
        config_path: Path | None,
        cache_dir: Path,
        allow_local_fallback: bool = False,
        mode: str = "full",
    ) -> None:
        self.config_path = config_path
        self.cache_dir = cache_dir
        self.allow_local_fallback = allow_local_fallback
        self.mode = mode
        self.llm_status = "not_configured"
        self.llm_error = ""

    def extract(self, deck_id: str, artifacts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        extracted = {"operational_knowledge_units": [], "procedure_candidate_attempts": [], "discarded_candidates": []}
        for index, artifact in enumerate(artifacts, start=1):
            print(f"LLM extracting slide {index}/{len(artifacts)}: {artifact.get('slide_title')}", flush=True)
            result = self.extract_slide(deck_id, artifact)
            for key in extracted:
                extracted[key].extend(as_list(result.get(key)))
            delay = 0.0
            if self.config_path and self.config_path.exists():
                delay = float(llm_stage_config(read_json(self.config_path), "slide_knowledge_extractor").get("request_delay_seconds", 0))
            if delay > 0:
                time.sleep(delay)
        return extracted

    def extract_slide(self, deck_id: str, artifact: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        if not self._has_llm_config():
            if not self.allow_local_fallback:
                raise SlideKnowledgeError("LLM slide extraction requires --llm-config or available Azure/OpenAI config. Use --allow-local-fallback only for explicit non-LLM dry runs.")
            self.llm_status = "local_fallback_empty"
            return {"operational_knowledge_units": [], "procedure_candidate_attempts": [], "discarded_candidates": []}
        return self._cached_or_extract_slide(deck_id, artifact)

    def _has_llm_config(self) -> bool:
        return bool(self.config_path and self.config_path.exists())

    def _cached_or_extract_slide(self, deck_id: str, artifact: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        config = llm_stage_config(read_json(self.config_path or Path()), "slide_knowledge_extractor")
        cache_path = self._cache_path(config, artifact)
        if cache_path.exists():
            cached = read_json(cache_path)
            if self._valid_payload(cached):
                self.llm_status = self._provider(config)
                return cached
        result = self._extract_slide_with_llm(deck_id, artifact, config)
        if not self._valid_payload(result):
            raise SlideKnowledgeError(f"LLM slide extraction returned an invalid response for slide {artifact.get('slide_number')}")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        return result

    def _cache_path(self, config: dict[str, Any], artifact: dict[str, Any]) -> Path:
        model = clean_id(str(config.get("model") or config.get("deployment") or "unknown_model"))
        cache_id = f"{artifact.get('artifact_id')}_{stable_hash(self._compact_artifact(artifact))[:12]}"
        return self.cache_dir / "slide_knowledge" / model / PROMPT_VERSION / f"{cache_id}.json"

    def _valid_payload(self, payload: Any) -> bool:
        return isinstance(payload, dict) and (
            "operational_knowledge_units" in payload or "procedure_candidate_attempts" in payload or "procedure_candidates" in payload
        )

    def _extract_slide_with_llm(self, deck_id: str, artifact: dict[str, Any], config: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        client, model, provider = self._llm_client(config)
        packet = self._evidence_packet(deck_id, artifact, config)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the Phase 0 Slide Knowledge Extraction Agent. Use reasoning over slide text and visual evidence "
                    "to identify bounded operational knowledge units and procedure candidates. Do not use keyword buckets, "
                    "static slide-title mappings, or invented operational steps. Return only JSON."
                ),
            },
            {"role": "user", "content": json.dumps(packet, ensure_ascii=False)},
        ]
        response = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=messages,
            **openai_generation_args(config),
        )
        self.llm_status = provider
        content = response.choices[0].message.content or "{}"
        payload = json.loads(content)
        return {
            "operational_knowledge_units": as_list(payload.get("operational_knowledge_units") or payload.get("knowledge_units")),
            "procedure_candidate_attempts": as_list(payload.get("procedure_candidate_attempts") or payload.get("procedure_candidates")),
            "discarded_candidates": as_list(payload.get("discarded_candidates") or payload.get("discard_report")),
        }

    def _evidence_packet(self, deck_id: str, artifact: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        packet = {
            "task": "phase0_slide_knowledge_extraction",
            "deck_id": deck_id,
            "mode": self.mode,
            "prompt_version": PROMPT_VERSION,
            "slide_artifact": self._compact_artifact(artifact),
            "rules": [
                "Preserve slide evidence and source refs.",
                "Prefer fewer, higher-quality procedure candidates.",
                "Procedures are more important than context.",
                "Context should support procedures and retrieval.",
                "Do not invent missing operational steps.",
                "If a slide gives API capability but not exact action sequence, create API context, not a procedure.",
                "Keep support_safe unknown unless the slide explicitly states safety.",
                "Keep role_required unknown unless clear from slide context.",
                "All outputs are candidates and require validation_status needs_review.",
                "Create procedures only when explicit reusable action guidance is present.",
                "Reject architecture explanations, state lists, API lists, UI screenshots, and overview slides as procedures unless they include action steps.",
                "If a slide is not a procedure but contains operational behavior, API capability, database models, system states, routing rules, UI references, or diagnostic concepts, create operational_knowledge_units.",
                "Only return all-empty arrays for pure title, agenda, legal, blank, or filler slides.",
                "If candidate_record_types or evidence_hints indicate operational content and you still emit no knowledge units or procedures, add a discarded_candidates entry explaining why.",
                "Procedure screenshot refs must point to slide_artifact_records.json artifact IDs, not raw image paths.",
                "Use slide-level screenshots first; cropped screenshots are not required for Phase 0.",
                "When a step visually refers to a UI element, button, field, menu, or screen area, include screenshot_refs and visual_region_hint.",
            ],
            "required_output_keys": ["operational_knowledge_units", "procedure_candidate_attempts"],
            "allowed_unit_types": sorted(ALLOWED_UNIT_TYPES),
            "allowed_procedure_types": sorted(ALLOWED_PROCEDURE_TYPES),
            "allowed_roles": sorted(ALLOWED_ROLES),
            "output_contract": {
                "operational_knowledge_units": [
                    "knowledge_unit_id",
                    "deck_id",
                    "source_slide_numbers",
                    "artifact_refs",
                    "unit_type",
                    "title",
                    "systems",
                    "components",
                    "summary",
                    "observed_evidence",
                    "relationships",
                    "retrieval_text",
                    "validation_status",
                ],
                "procedure_candidate_attempts": [
                    "procedure_id",
                    "title",
                    "procedure_type",
                    "source_deck",
                    "source_slide_numbers",
                    "systems",
                    "components",
                    "role_required",
                    "support_safe",
                    "preconditions",
                    "procedure_screenshot_refs",
                    "procedure_visual_summary",
                    "steps",
                    "warnings",
                    "related_context_refs",
                    "validation_status",
                    "retrieval_text",
                ],
                "procedure_step_required_keys": [
                    "step_order",
                    "instruction",
                    "expected_outcome",
                    "validation_check",
                    "source_refs",
                    "artifact_refs",
                    "screenshot_refs",
                    "visual_region_hint",
                ],
            },
        }
        image_b64 = self._image_b64(artifact.get("image_path")) if config.get("include_slide_image_base64") else ""
        if image_b64:
            packet["slide_image"] = {"mime_type": "image/png", "base64": image_b64}
        return packet

    def _compact_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        return {
            "artifact_id": artifact.get("artifact_id"),
            "deck_id": artifact.get("deck_id"),
            "source_file": artifact.get("source_file"),
            "slide_number": artifact.get("slide_number"),
            "slide_title": artifact.get("slide_title"),
            "section": artifact.get("section"),
            "visible_text": unique_strings(artifact.get("visible_text"))[:80],
            "ocr_text": unique_strings(artifact.get("ocr_text"))[:80],
            "image_path": artifact.get("image_path"),
            "visual_summary": artifact.get("visual_summary"),
            "visual_elements": artifact.get("visual_elements", []),
            "candidate_record_types": artifact.get("candidate_record_types", []),
            "evidence_hints": artifact.get("evidence_hints", {}),
            "source_refs": artifact.get("source_refs", []),
        }

    def _image_b64(self, image_path: Any) -> str:
        path = Path(str(image_path or ""))
        if not path.exists():
            return ""
        return base64.b64encode(path.read_bytes()).decode("ascii")

    def _provider(self, config: dict[str, Any]) -> str:
        return str(config.get("provider") or ("azure_openai" if config.get("endpoint") else "openai")).lower()

    def _llm_client(self, config: dict[str, Any]) -> tuple[Any, str, str]:
        provider = self._provider(config)
        if provider == "openai":
            from openai import OpenAI

            required = ["api_key", "model"]
            missing = [field_name for field_name in required if not config.get(field_name)]
            if missing:
                raise SlideKnowledgeError(f"OpenAI config missing required fields: {', '.join(missing)}")
            if str(config.get("api_key")).startswith("PASTE_"):
                raise SlideKnowledgeError("OpenAI config still contains the placeholder API key.")
            return (
                OpenAI(
                    api_key=config["api_key"],
                    timeout=float(config.get("request_timeout_seconds", 180)),
                    max_retries=int(config.get("max_retries", 2)),
                ),
                config["model"],
                "openai",
            )
        if provider == "azure_openai":
            from openai import AzureOpenAI

            required = ["endpoint", "api_key", "api_version", "deployment"]
            missing = [field_name for field_name in required if not config.get(field_name)]
            if missing:
                raise SlideKnowledgeError(f"Azure OpenAI config missing required fields: {', '.join(missing)}")
            return (
                AzureOpenAI(
                    azure_endpoint=config["endpoint"],
                    api_key=config["api_key"],
                    api_version=config["api_version"],
                    timeout=float(config.get("request_timeout_seconds", 180)),
                    max_retries=int(config.get("max_retries", 2)),
                ),
                config["deployment"],
                "azure_openai",
            )
        raise SlideKnowledgeError(f"Unsupported LLM provider: {provider}")


class ProcedureCandidateBuilder:
    def build(self, deck_id: str, records: list[dict[str, Any]], slide_artifacts: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        built: list[dict[str, Any]] = []
        artifacts_by_slide = {artifact.get("slide_number"): artifact for artifact in as_list(slide_artifacts)}
        for index, record in enumerate(records, start=1):
            source_slide_numbers = self._slide_numbers(record)
            slide_artifact_refs = unique_strings([artifacts_by_slide[number]["artifact_id"] for number in source_slide_numbers if number in artifacts_by_slide])
            artifact_refs = self._artifact_ids(as_list(record.get("artifact_refs")) + slide_artifact_refs)
            procedure_screenshot_refs = self._artifact_ids(as_list(record.get("procedure_screenshot_refs")) + artifact_refs)
            warnings = unique_strings(record.get("warnings"))
            if not procedure_screenshot_refs and "no_visual_artifact_available" not in warnings:
                warnings.append("no_visual_artifact_available")
            visual_summary = record.get("procedure_visual_summary") or self._visual_summary(source_slide_numbers, artifacts_by_slide)
            procedure_id = record.get("procedure_id") or f"proc_{clean_id(deck_id)}_{index:06d}"
            built.append(
                {
                    "procedure_id": procedure_id,
                    "title": str(record.get("title") or f"Slide procedure candidate {index}").strip(),
                    "procedure_type": record.get("procedure_type") if record.get("procedure_type") in ALLOWED_PROCEDURE_TYPES else "unknown",
                    "source_deck": record.get("source_deck") or deck_id,
                    "source_slide_numbers": source_slide_numbers,
                    "systems": unique_strings(record.get("systems")),
                    "components": unique_strings(record.get("components")),
                    "role_required": record.get("role_required") if record.get("role_required") in ALLOWED_ROLES else "unknown",
                    "support_safe": record.get("support_safe") if record.get("support_safe") in ALLOWED_SUPPORT_SAFE else "unknown",
                    "preconditions": unique_strings(record.get("preconditions")),
                    "procedure_screenshot_refs": procedure_screenshot_refs,
                    "procedure_visual_summary": visual_summary,
                    "steps": self._steps(record.get("steps"), source_slide_numbers, artifact_refs, procedure_screenshot_refs),
                    "warnings": warnings,
                    "related_context_refs": unique_strings(record.get("related_context_refs")),
                    "validation_status": "needs_review",
                    "retrieval_text": record.get("retrieval_text") or "",
                }
            )
        return built

    def _slide_numbers(self, record: dict[str, Any]) -> list[int]:
        numbers: list[int] = []
        for value in as_list(record.get("source_slide_numbers")):
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            if number > 0 and number not in numbers:
                numbers.append(number)
        return numbers

    def _visual_summary(self, source_slide_numbers: list[int], artifacts_by_slide: dict[Any, dict[str, Any]]) -> str:
        summaries = [artifacts_by_slide[number].get("visual_summary") for number in source_slide_numbers if number in artifacts_by_slide]
        return truncate_text(text_blob(summaries), 600)

    def _artifact_ids(self, values: Any) -> list[str]:
        result: list[str] = []
        for value in as_list(values):
            text = str(value or "").strip()
            if text.startswith("artifact:"):
                text = text.split("artifact:", 1)[1]
            if text.startswith("slide_artifact_") and text not in result:
                result.append(text)
        return result

    def _steps(self, raw_steps: Any, source_slide_numbers: list[int], artifact_refs: list[str], procedure_screenshot_refs: list[str]) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = []
        source_refs = [f"slide:{number}" for number in source_slide_numbers]
        for index, step in enumerate(as_list(raw_steps), start=1):
            if not isinstance(step, dict):
                step = {"instruction": str(step)}
            instruction = str(step.get("instruction") or step.get("action") or "").strip()
            source_evidence = str(step.get("observed_evidence") or "").strip()
            expected_outcome = str(step.get("expected_outcome") or "").strip()
            validation_check = str(step.get("validation_check") or "").strip()
            if not validation_check and source_evidence:
                validation_check = source_evidence
            if not expected_outcome and validation_check:
                expected_outcome = "The action completes as described by the source slide evidence."
            step_artifacts = self._artifact_ids(as_list(step.get("artifact_refs")) or artifact_refs)
            screenshot_refs = self._artifact_ids(as_list(step.get("screenshot_refs")) or step_artifacts or procedure_screenshot_refs)
            steps.append(
                {
                    "step_order": int(step.get("step_order") or step.get("step_number") or index),
                    "instruction": instruction,
                    "expected_outcome": expected_outcome,
                    "validation_check": validation_check,
                    "source_refs": unique_strings(as_list(step.get("source_refs")) or source_refs),
                    "artifact_refs": step_artifacts,
                    "screenshot_refs": screenshot_refs,
                    "visual_region_hint": str(step.get("visual_region_hint") or "").strip(),
                }
            )
        return steps


class ContextCandidateBuilder:
    def build(self, deck_id: str, knowledge_units: list[dict[str, Any]]) -> list[dict[str, Any]]:
        contexts: list[dict[str, Any]] = []
        for index, unit in enumerate(knowledge_units, start=1):
            context_id = f"ctx_{clean_id(deck_id)}_{clean_id(unit.get('knowledge_unit_id') or str(index))}"
            source_refs = unique_strings(unit.get("source_refs")) or [f"slide:{number}" for number in unit.get("source_slide_numbers", [])]
            contexts.append(
                {
                    "context_id": unit.get("context_id") or context_id,
                    "container_id": "phase0_context_reference",
                    "source_deck": deck_id,
                    "context_type": self._context_type(unit),
                    "title": unit.get("title") or f"Slide context candidate {index}",
                    "applies_to": unique_strings(as_list(unit.get("systems")) + as_list(unit.get("components"))),
                    "source_refs": source_refs,
                    "artifact_refs": unique_strings(unit.get("artifact_refs")),
                    "knowledge_unit_refs": unique_strings([unit.get("knowledge_unit_id")]),
                    "source_authority": "training_slides",
                    "summary": unit.get("summary") or "",
                    "observed_evidence": as_list(unit.get("observed_evidence")),
                    "relationships": as_list(unit.get("relationships")),
                    "validation_status": "needs_review",
                    "retrieval_text": unit.get("retrieval_text") or text_blob(unit.get("title"), unit.get("summary"), unit.get("observed_evidence")),
                }
            )
        return contexts

    def _context_type(self, unit: dict[str, Any]) -> str:
        unit_type = unit.get("unit_type")
        if unit_type == "api_capability":
            return "api_reference"
        if unit_type == "database_model_reference":
            return "database_reference"
        if unit_type == "architecture_relationship":
            return "architecture_reference"
        if unit_type == "ui_concept":
            return "ui_reference"
        if unit_type == "glossary_definition":
            return "glossary"
        if unit_type in {"operational_process", "routing_rule", "queueing_rule", "state_transition", "diagnostic_concept"}:
            return "operational_concept"
        if unit_type == "system_behavior":
            return "product_behavior"
        return "operational_concept"


class SlideKnowledgeValidator:
    def validate_all(
        self,
        review_dir: Path,
        knowledge_units: list[dict[str, Any]],
        context_candidates: list[dict[str, Any]],
        procedure_candidates: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        self._reject_dataset0_paths(review_dir)
        valid_units, unit_discards = self._validate_knowledge_units(knowledge_units)
        valid_context, context_discards = self._validate_context(context_candidates)
        valid_procedures, procedure_discards = self._validate_procedures(procedure_candidates)
        return valid_units, valid_context, valid_procedures, unit_discards + context_discards + procedure_discards

    def _reject_dataset0_paths(self, review_dir: Path) -> None:
        resolved = review_dir.resolve()
        prohibited = [
            (ROOT / "data" / "context" / "context_reference.json").resolve(),
            (ROOT / "data" / "procedures" / "procedure_dictionary.json").resolve(),
        ]
        if resolved in prohibited:
            raise SlideKnowledgeError("Slide extraction cannot write directly to Dataset 0 production files.")

    def _validate_knowledge_units(self, records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        accepted: list[dict[str, Any]] = []
        discarded: list[dict[str, Any]] = []
        for record in records:
            normalized = self._normalize_knowledge_unit(record)
            failed = self._knowledge_unit_failed_rules(normalized)
            if failed:
                discarded.append(self._discard(normalized.get("knowledge_unit_id"), "knowledge_unit", normalized.get("source_slide_numbers"), failed, normalized.get("summary") or normalized.get("title")))
            else:
                accepted.append(normalized)
        return accepted, discarded

    def _normalize_knowledge_unit(self, record: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(record)
        normalized["knowledge_unit_id"] = normalized.get("knowledge_unit_id") or f"ku_{stable_hash(record)[:12]}"
        normalized["source_slide_numbers"] = self._numbers(normalized.get("source_slide_numbers"))
        normalized["artifact_refs"] = unique_strings(normalized.get("artifact_refs"))
        normalized["systems"] = unique_strings(normalized.get("systems"))
        normalized["components"] = unique_strings(normalized.get("components"))
        normalized["observed_evidence"] = as_list(normalized.get("observed_evidence"))
        normalized["relationships"] = as_list(normalized.get("relationships"))
        normalized["source_refs"] = unique_strings(normalized.get("source_refs")) or [f"slide:{number}" for number in normalized["source_slide_numbers"]]
        normalized["validation_status"] = "needs_review"
        return normalized

    def _knowledge_unit_failed_rules(self, record: dict[str, Any]) -> list[str]:
        failed: list[str] = []
        if record.get("unit_type") not in ALLOWED_UNIT_TYPES:
            failed.append("invalid_unit_type")
        if self._broad_title(record.get("title", "")):
            failed.append("broad_topic_title")
        if not record.get("summary"):
            failed.append("missing_summary")
        if not record.get("retrieval_text"):
            failed.append("missing_retrieval_text")
        if not record.get("source_slide_numbers"):
            failed.append("missing_source_slide_numbers")
        if record.get("validation_status") != "needs_review":
            failed.append("invalid_validation_status")
        return failed

    def _validate_context(self, records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        accepted: list[dict[str, Any]] = []
        discarded: list[dict[str, Any]] = []
        for record in records:
            normalized = dict(record)
            normalized["validation_status"] = "needs_review"
            failed = self._context_failed_rules(normalized)
            if failed:
                discarded.append(self._discard(normalized.get("context_id"), "context", self._slide_numbers_from_refs(normalized.get("source_refs")), failed, normalized.get("summary") or normalized.get("title")))
            else:
                accepted.append(normalized)
        return accepted, discarded

    def _context_failed_rules(self, record: dict[str, Any]) -> list[str]:
        failed: list[str] = []
        if record.get("context_type") not in ALLOWED_CONTEXT_TYPES:
            failed.append("invalid_context_type")
        if self._broad_title(record.get("title", "")):
            failed.append("broad_topic_title")
        if not record.get("retrieval_text"):
            failed.append("missing_retrieval_text")
        if not record.get("source_refs"):
            failed.append("missing_source_refs")
        if record.get("validation_status") != "needs_review":
            failed.append("invalid_validation_status")
        return failed

    def _validate_procedures(self, records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        accepted: list[dict[str, Any]] = []
        discarded: list[dict[str, Any]] = []
        for record in records:
            normalized = dict(record)
            normalized["validation_status"] = "needs_review"
            failed = self._procedure_failed_rules(normalized)
            if failed:
                discarded.append(self._discard(normalized.get("procedure_id"), "procedure", normalized.get("source_slide_numbers"), failed, normalized.get("title") or self._step_summary(normalized)))
            else:
                if not normalized.get("retrieval_text"):
                    normalized["retrieval_text"] = text_blob(normalized.get("title"), [step.get("instruction") for step in normalized.get("steps", [])])
                accepted.append(normalized)
        return accepted, discarded

    def _procedure_failed_rules(self, record: dict[str, Any]) -> list[str]:
        failed: list[str] = []
        steps = as_list(record.get("steps"))
        if record.get("procedure_type") not in ALLOWED_PROCEDURE_TYPES:
            failed.append("invalid_procedure_type")
        if self._broad_title(record.get("title", "")):
            failed.append("broad_topic_title")
        if not steps:
            failed.append("missing_steps")
            return failed
        if not record.get("source_slide_numbers"):
            failed.append("missing_source_slide_refs")
        if not record.get("systems") and not record.get("components"):
            failed.append("missing_target_system_or_component")
        if record.get("validation_status") != "needs_review":
            failed.append("invalid_validation_status")
        concrete_steps = [step for step in steps if self._concrete_step(step)]
        if not concrete_steps:
            failed.append("no_concrete_action_steps")
        if any(self._vague_step(step) for step in steps):
            failed.append("vague_steps")
        if any(not step.get("source_refs") for step in steps):
            failed.append("step_missing_source_refs")
        if any(not step.get("artifact_refs") for step in steps):
            failed.append("step_missing_artifact_refs")
        if not record.get("procedure_screenshot_refs") and "no_visual_artifact_available" not in record.get("warnings", []):
            failed.append("missing_procedure_screenshot_refs")
        if record.get("procedure_screenshot_refs") and any(not step.get("screenshot_refs") for step in steps):
            failed.append("step_missing_screenshot_refs")
        if any(not (step.get("expected_outcome") or step.get("validation_check")) for step in steps):
            failed.append("step_missing_expected_outcome_or_validation_check")
        if not any(step.get("expected_outcome") or step.get("validation_check") for step in steps):
            failed.append("procedure_missing_expected_outcome_or_validation_check")
        return unique_strings(failed)

    def _numbers(self, values: Any) -> list[int]:
        result: list[int] = []
        for value in as_list(values):
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            if number > 0 and number not in result:
                result.append(number)
        return result

    def _slide_numbers_from_refs(self, refs: Any) -> list[int]:
        numbers: list[int] = []
        for ref in as_list(refs):
            match = re.search(r"slide:(\d+)", str(ref))
            if match:
                number = int(match.group(1))
                if number not in numbers:
                    numbers.append(number)
        return numbers

    def _broad_title(self, title: Any) -> bool:
        cleaned = re.sub(r"\s+", " ", str(title or "")).strip()
        if not cleaned:
            return True
        if BROAD_TOPIC_TITLE_PATTERN.match(cleaned):
            return True
        return cleaned.lower().endswith("training slide reference")

    def _concrete_step(self, step: dict[str, Any]) -> bool:
        instruction = str(step.get("instruction") or "").lower()
        return any(term in instruction for term in ACTION_TERMS)

    def _vague_step(self, step: dict[str, Any]) -> bool:
        text = re.sub(r"\s+", " ", str(step.get("instruction") or "")).strip().lower()
        if len(text.split()) < 3 and not (self._concrete_step(step) and (step.get("screenshot_refs") or step.get("visual_region_hint"))):
            return True
        return any(phrase in text for phrase in VAGUE_STEP_PHRASES)

    def _looks_like_generic_ui_capability(self, record: dict[str, Any]) -> bool:
        title = str(record.get("title") or "").lower()
        instructions = [str(step.get("instruction") or "").lower() for step in as_list(record.get("steps"))]
        text = " ".join([title] + instructions)
        source_action_count = sum(
            1
            for step in as_list(record.get("steps"))
            for ref in as_list(step.get("source_refs"))
            if self._source_ref_has_numbered_step(ref)
        )
        has_source_numbered_sequence = source_action_count >= 2
        if has_source_numbered_sequence:
            return False
        if any(value in title for value in ["add ", "remove ", "restart", "go-to", "go to", "initialize", "exchange", "reset", "shutdown", "startup"]):
            return False
        weak_phrases = [
            "use the available",
            "as needed",
            "open or view",
            "review the displayed",
            "select a robot in robot selection to view details",
            "quick select options",
            "message panel",
            "find a tote",
        ]
        return any(phrase in text for phrase in weak_phrases)

    def _source_ref_has_numbered_step(self, ref: Any) -> bool:
        text = str(ref or "").lower()
        return bool(re.search(r"(?:visible text|step|source):\s*['\"]?\d+\.", text))

    def _step_summary(self, record: dict[str, Any]) -> str:
        return text_blob([step.get("instruction") for step in record.get("steps", [])])[:240]

    def _discard(self, candidate_id: Any, candidate_type: str, source_slide_numbers: Any, failed_rules: list[str], summary: Any) -> dict[str, Any]:
        return {
            "candidate_id": str(candidate_id or f"discarded_{stable_hash(summary)[:12]}"),
            "candidate_type": candidate_type,
            "source_slide_numbers": self._numbers(source_slide_numbers),
            "discard_reasons": [rule.replace("_", " ") for rule in failed_rules],
            "failed_rules": failed_rules,
            "original_candidate_summary": truncate_text(summary, 300),
        }


class SlideExtractionReporter:
    def build_report(
        self,
        deck_id: str,
        source_file: Path,
        slide_artifacts: list[dict[str, Any]],
        knowledge_units: list[dict[str, Any]],
        context_candidates: list[dict[str, Any]],
        procedure_candidates: list[dict[str, Any]],
        discard_report: list[dict[str, Any]],
        warnings: list[str],
        llm_status: str,
    ) -> dict[str, Any]:
        return {
            "deck_id": deck_id,
            "source_file": str(source_file),
            "slides_processed": len(slide_artifacts),
            "total_slides": len(slide_artifacts),
            "last_completed_slide": slide_artifacts[-1]["slide_number"] if slide_artifacts else 0,
            "current_slide": None,
            "slide_artifacts_created": len(slide_artifacts),
            "knowledge_units_created": len(knowledge_units),
            "context_candidates_created": len(context_candidates),
            "procedure_candidates_created": len(procedure_candidates),
            "discarded_candidates": len(discard_report),
            "warnings": warnings,
            "llm_status": llm_status,
            "validation_status": "needs_review",
        }

    def build_failure_report(self, deck_id: str, source_file: Path, slides_processed: int, error: str) -> dict[str, Any]:
        return {
            "deck_id": deck_id,
            "source_file": str(source_file),
            "slides_processed": slides_processed,
            "total_slides": slides_processed,
            "last_completed_slide": 0,
            "current_slide": None,
            "slide_artifacts_created": 0,
            "knowledge_units_created": 0,
            "context_candidates_created": 0,
            "procedure_candidates_created": 0,
            "discarded_candidates": 0,
            "warnings": [error],
            "llm_status": "failed",
            "validation_status": "needs_review",
        }

    def build_running_report(
        self,
        deck_id: str,
        source_file: Path,
        total_slides: int,
        last_completed_slide: int,
        current_slide: int | None,
        slide_artifacts: list[dict[str, Any]],
        knowledge_units: list[dict[str, Any]],
        context_candidates: list[dict[str, Any]],
        procedure_candidates: list[dict[str, Any]],
        discard_report: list[dict[str, Any]],
        warnings: list[str],
        llm_status: str,
    ) -> dict[str, Any]:
        return {
            "deck_id": deck_id,
            "source_file": str(source_file),
            "slides_processed": last_completed_slide,
            "total_slides": total_slides,
            "last_completed_slide": last_completed_slide,
            "current_slide": current_slide,
            "slide_artifacts_created": len(slide_artifacts),
            "knowledge_units_created": len(knowledge_units),
            "context_candidates_created": len(context_candidates),
            "procedure_candidates_created": len(procedure_candidates),
            "discarded_candidates": len(discard_report),
            "warnings": warnings,
            "llm_status": llm_status,
            "validation_status": "needs_review",
        }

    def build_partial_failure_report(
        self,
        deck_id: str,
        source_file: Path,
        total_slides: int,
        last_completed_slide: int,
        failed_slide_number: int,
        slide_artifacts: list[dict[str, Any]],
        knowledge_units: list[dict[str, Any]],
        context_candidates: list[dict[str, Any]],
        procedure_candidates: list[dict[str, Any]],
        discard_report: list[dict[str, Any]],
        error: str,
    ) -> dict[str, Any]:
        report = self.build_running_report(
            deck_id,
            source_file,
            total_slides,
            last_completed_slide,
            failed_slide_number,
            slide_artifacts,
            knowledge_units,
            context_candidates,
            procedure_candidates,
            discard_report,
            [error],
            "failed",
        )
        report["failed_slide_number"] = failed_slide_number
        report["failure_message"] = error
        return report

    def build_manifest(
        self,
        deck_id: str,
        knowledge_units: list[dict[str, Any]],
        context_candidates: list[dict[str, Any]],
        procedure_candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "deck_id": deck_id,
            "promotion_allowed": False,
            "promotion_rule": "Slide extraction outputs require human review before becoming Dataset 0 context records or procedure dictionary records.",
            "review_required_for": {
                "operational_knowledge_units": [record.get("knowledge_unit_id") for record in knowledge_units],
                "context_record_candidates": [record.get("context_id") for record in context_candidates],
                "procedure_dictionary_candidates": [record.get("procedure_id") for record in procedure_candidates],
            },
            "target_dataset0_context_file": "data/context/context_reference.json",
            "target_dataset0_procedure_file": "data/procedures/procedure_dictionary.json",
            "dataset0_write_ran": False,
        }


class SlideKnowledgeAgent:
    def __init__(
        self,
        source_pdf: Path,
        deck_id: str,
        review_dir: Path,
        mode: str = "full",
        limit_slides: int | None = None,
        start_slide: int | None = None,
        end_slide: int | None = None,
        enable_ocr: bool = False,
        llm_config: Path | None = None,
        allow_local_fallback: bool = False,
        force: bool = False,
    ) -> None:
        self.source_pdf = source_pdf
        self.deck_id = deck_id
        self.review_dir = review_dir
        self.mode = mode
        self.limit_slides = limit_slides
        self.start_slide = start_slide
        self.end_slide = end_slide
        self.enable_ocr = enable_ocr
        self.llm_config = llm_config
        self.allow_local_fallback = allow_local_fallback
        self.force = force

    def run(self) -> dict[str, Any]:
        validator = SlideKnowledgeValidator()
        validator._reject_dataset0_paths(self.review_dir)
        image_dir = self.review_dir / "images"
        slides = SlideDeckLoader(self.source_pdf, image_dir, self.limit_slides, self.start_slide, self.end_slide, self.enable_ocr).load()
        slide_artifacts = SlideArtifactBuilder().build(self.deck_id, self.source_pdf, slides)
        extractor = LLMSlideKnowledgeExtractor(self.llm_config, self.review_dir / "_cache", self.allow_local_fallback, self.mode)
        reporter = SlideExtractionReporter()
        self._ensure_outputs_writable()
        extracted = {"operational_knowledge_units": [], "procedure_candidate_attempts": [], "discarded_candidates": []}
        knowledge_units: list[dict[str, Any]] = []
        context_candidates: list[dict[str, Any]] = []
        procedure_candidates: list[dict[str, Any]] = []
        discard_report: list[dict[str, Any]] = []
        initial_report = reporter.build_running_report(
            self.deck_id,
            self.source_pdf,
            len(slide_artifacts),
            0,
            slide_artifacts[0]["slide_number"] if slide_artifacts else None,
            slide_artifacts,
            knowledge_units,
            context_candidates,
            procedure_candidates,
            discard_report,
            self._warnings(extractor, slide_artifacts),
            "running",
        )
        initial_manifest = reporter.build_manifest(self.deck_id, knowledge_units, context_candidates, procedure_candidates)
        self._write_outputs(slide_artifacts, knowledge_units, context_candidates, procedure_candidates, discard_report, initial_report, initial_manifest)
        last_completed_slide = 0
        for index, artifact in enumerate(slide_artifacts, start=1):
            print(f"LLM extracting slide {index}/{len(slide_artifacts)}: {artifact.get('slide_title')}", flush=True)
            try:
                if hasattr(extractor, "extract_slide"):
                    slide_result = extractor.extract_slide(self.deck_id, artifact)
                else:
                    slide_result = extractor.extract(self.deck_id, [artifact])
            except Exception as exc:
                failure_report = reporter.build_partial_failure_report(
                    self.deck_id,
                    self.source_pdf,
                    len(slide_artifacts),
                    last_completed_slide,
                    int(artifact.get("slide_number") or index),
                    slide_artifacts,
                    knowledge_units,
                    context_candidates,
                    procedure_candidates,
                    discard_report,
                    str(exc),
                )
                failure_manifest = reporter.build_manifest(self.deck_id, knowledge_units, context_candidates, procedure_candidates)
                self._write_outputs(slide_artifacts, knowledge_units, context_candidates, procedure_candidates, discard_report, failure_report, failure_manifest)
                raise
            slide_result = self._with_empty_output_discard(slide_result, artifact)
            for key in extracted:
                extracted[key].extend(as_list(slide_result.get(key)))
            knowledge_units, context_candidates, procedure_candidates, discard_report = self._build_review_outputs(extracted, slide_artifacts, validator)
            last_completed_slide = int(artifact.get("slide_number") or index)
            next_slide = slide_artifacts[index]["slide_number"] if index < len(slide_artifacts) else None
            running_report = reporter.build_running_report(
                self.deck_id,
                self.source_pdf,
                len(slide_artifacts),
                last_completed_slide,
                next_slide,
                slide_artifacts,
                knowledge_units,
                context_candidates,
                procedure_candidates,
                discard_report,
                self._warnings(extractor, slide_artifacts),
                "running",
            )
            running_manifest = reporter.build_manifest(self.deck_id, knowledge_units, context_candidates, procedure_candidates)
            self._write_outputs(slide_artifacts, knowledge_units, context_candidates, procedure_candidates, discard_report, running_report, running_manifest)
            delay = self._request_delay()
            if delay > 0:
                time.sleep(delay)
        report = reporter.build_report(
            self.deck_id,
            self.source_pdf,
            slide_artifacts,
            knowledge_units,
            context_candidates,
            procedure_candidates,
            discard_report,
            self._warnings(extractor, slide_artifacts),
            extractor.llm_status,
        )
        manifest = reporter.build_manifest(self.deck_id, knowledge_units, context_candidates, procedure_candidates)
        self._write_outputs(slide_artifacts, knowledge_units, context_candidates, procedure_candidates, discard_report, report, manifest)
        return {
            "deck_id": self.deck_id,
            "review_dir": str(self.review_dir),
            "slides_processed": len(slide_artifacts),
            "knowledge_units_created": len(knowledge_units),
            "context_candidates_created": len(context_candidates),
            "procedure_candidates_created": len(procedure_candidates),
            "discarded_candidates": len(discard_report),
            "llm_status": extractor.llm_status,
            "dataset0_write_ran": False,
            "completed_at": utc_now(),
        }

    def _with_empty_output_discard(self, slide_result: dict[str, list[dict[str, Any]]], artifact: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        if as_list(slide_result.get("operational_knowledge_units")) or as_list(slide_result.get("procedure_candidate_attempts")) or as_list(slide_result.get("discarded_candidates")):
            return slide_result
        candidate_types = as_list(artifact.get("candidate_record_types"))
        if not candidate_types:
            return slide_result
        normalized = dict(slide_result)
        normalized["discarded_candidates"] = [
            {
                "candidate_id": f"discard_empty_{artifact.get('artifact_id')}",
                "candidate_type": "knowledge_unit",
                "source_slide_numbers": [artifact.get("slide_number")],
                "discard_reasons": ["LLM returned no candidates for a slide with operational evidence hints."],
                "failed_rules": ["llm_empty_output_for_operational_hints"],
                "original_candidate_summary": artifact.get("visual_summary") or artifact.get("slide_title"),
            }
        ]
        return normalized

    def _build_review_outputs(
        self,
        extracted: dict[str, list[dict[str, Any]]],
        slide_artifacts: list[dict[str, Any]],
        validator: SlideKnowledgeValidator,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        knowledge_units = self._enrich_knowledge_units(extracted.get("operational_knowledge_units", []), slide_artifacts)
        procedure_candidates = ProcedureCandidateBuilder().build(self.deck_id, extracted.get("procedure_candidate_attempts", []), slide_artifacts)
        context_candidates = ContextCandidateBuilder().build(self.deck_id, knowledge_units)
        knowledge_units, context_candidates, procedure_candidates, discard_report = validator.validate_all(
            self.review_dir,
            knowledge_units,
            context_candidates,
            procedure_candidates,
        )
        discard_report.extend(self._normalize_llm_discards(extracted.get("discarded_candidates", [])))
        return knowledge_units, context_candidates, procedure_candidates, discard_report

    def _request_delay(self) -> float:
        if not self.llm_config or not self.llm_config.exists():
            return 0.0
        try:
            config = llm_stage_config(read_json(self.llm_config), "slide_knowledge_extractor")
        except (OSError, json.JSONDecodeError):
            return 0.0
        return float(config.get("request_delay_seconds", 0))

    def _enrich_knowledge_units(self, units: list[dict[str, Any]], artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        artifacts_by_slide = {artifact["slide_number"]: artifact for artifact in artifacts}
        enriched: list[dict[str, Any]] = []
        for index, unit in enumerate(units, start=1):
            normalized = dict(unit)
            normalized["knowledge_unit_id"] = normalized.get("knowledge_unit_id") or f"ku_{clean_id(self.deck_id)}_{index:06d}"
            normalized["deck_id"] = normalized.get("deck_id") or self.deck_id
            slide_numbers = []
            for value in as_list(normalized.get("source_slide_numbers")):
                try:
                    slide_numbers.append(int(value))
                except (TypeError, ValueError):
                    pass
            normalized["source_slide_numbers"] = sorted(set(number for number in slide_numbers if number > 0))
            slide_artifacts = [artifacts_by_slide[number] for number in normalized["source_slide_numbers"] if number in artifacts_by_slide]
            normalized["artifact_refs"] = unique_strings(as_list(normalized.get("artifact_refs")) + [artifact["artifact_id"] for artifact in slide_artifacts])
            normalized["source_refs"] = unique_strings(as_list(normalized.get("source_refs")) + [f"slide:{number}" for number in normalized["source_slide_numbers"]])
            normalized["validation_status"] = "needs_review"
            enriched.append(normalized)
        return enriched

    def _normalize_llm_discards(self, discards: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for discard in discards:
            normalized.append(
                {
                    "candidate_id": str(discard.get("candidate_id") or f"llm_discard_{stable_hash(discard)[:12]}"),
                    "candidate_type": discard.get("candidate_type") if discard.get("candidate_type") in {"procedure", "context", "knowledge_unit"} else "knowledge_unit",
                    "source_slide_numbers": [int(value) for value in as_list(discard.get("source_slide_numbers")) if str(value).isdigit()],
                    "discard_reasons": unique_strings(discard.get("discard_reasons")),
                    "failed_rules": unique_strings(discard.get("failed_rules")),
                    "original_candidate_summary": truncate_text(discard.get("original_candidate_summary"), 300),
                }
            )
        return normalized

    def _warnings(self, extractor: LLMSlideKnowledgeExtractor, slide_artifacts: list[dict[str, Any]] | None = None) -> list[str]:
        warnings: list[str] = []
        if extractor.llm_error:
            warnings.append(extractor.llm_error)
        if extractor.llm_status == "local_fallback_empty":
            warnings.append("Local fallback ran explicitly; no LLM-authored knowledge candidates were produced.")
        if self.enable_ocr and slide_artifacts is not None and not any(artifact.get("ocr_text") for artifact in slide_artifacts):
            warnings.append("OCR was requested but produced no OCR text; check local Tesseract/Pillow OCR setup.")
        return warnings

    def _write_outputs(
        self,
        slide_artifacts: list[dict[str, Any]],
        knowledge_units: list[dict[str, Any]],
        context_candidates: list[dict[str, Any]],
        procedure_candidates: list[dict[str, Any]],
        discard_report: list[dict[str, Any]],
        report: dict[str, Any],
        manifest: dict[str, Any],
    ) -> None:
        write_json(self.review_dir / "slide_artifact_records.json", slide_artifacts, True)
        write_json(self.review_dir / "operational_knowledge_unit_candidates.json", knowledge_units, True)
        write_json(self.review_dir / "context_record_candidates.json", context_candidates, True)
        write_json(self.review_dir / "procedure_dictionary_candidates.json", procedure_candidates, True)
        write_json(self.review_dir / "discard_report.json", discard_report, True)
        write_json(self.review_dir / "extraction_report.json", report, True)
        write_json(self.review_dir / "promotion_review_manifest.json", manifest, True)

    def _ensure_outputs_writable(self) -> None:
        if self.force:
            return
        existing = [path for path in self._output_paths() if path.exists()]
        if existing:
            raise SlideKnowledgeError(f"Refusing to overwrite existing output without --force: {existing[0]}")

    def _output_paths(self) -> list[Path]:
        return [
            self.review_dir / "slide_artifact_records.json",
            self.review_dir / "operational_knowledge_unit_candidates.json",
            self.review_dir / "context_record_candidates.json",
            self.review_dir / "procedure_dictionary_candidates.json",
            self.review_dir / "discard_report.json",
            self.review_dir / "extraction_report.json",
            self.review_dir / "promotion_review_manifest.json",
        ]


def run_slide_knowledge_extraction(
    source_pdf: Path,
    deck_id: str,
    review_dir: Path,
    mode: str = "full",
    limit_slides: int | None = None,
    start_slide: int | None = None,
    end_slide: int | None = None,
    enable_ocr: bool = False,
    llm_config: Path | None = None,
    allow_local_fallback: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    return SlideKnowledgeAgent(
        source_pdf=source_pdf,
        deck_id=deck_id,
        review_dir=review_dir,
        mode=mode,
        limit_slides=limit_slides,
        start_slide=start_slide,
        end_slide=end_slide,
        enable_ocr=enable_ocr,
        llm_config=llm_config,
        allow_local_fallback=allow_local_fallback,
        force=force,
    ).run()


def default_llm_config() -> Path | None:
    configured = os.getenv("PHASE0_SLIDE_LLM_CONFIG") or os.getenv("PHASE0_VIDEO_LLM_CONFIG")
    if configured:
        return Path(configured)
    for relative in ["config/azure_openai.local.json", "config/openai.local.json"]:
        path = ROOT / relative
        if path.exists():
            return path
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract Phase 0 review-ready knowledge candidates from training slide decks.")
    parser.add_argument("--source-pdf", required=True, type=Path)
    parser.add_argument("--deck-id", required=True)
    parser.add_argument("--review-dir", required=True, type=Path)
    parser.add_argument("--mode", choices=["quick", "full"], default="full")
    parser.add_argument("--limit-slides", type=int)
    parser.add_argument("--start-slide", type=int)
    parser.add_argument("--end-slide", type=int)
    parser.add_argument("--ocr", action="store_true", help="Run OCR on rendered slide images and include OCR text in evidence packets.")
    parser.add_argument("--llm-config", type=Path, default=default_llm_config())
    parser.add_argument("--allow-local-fallback", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run_slide_knowledge_extraction(
        source_pdf=args.source_pdf,
        deck_id=args.deck_id,
        review_dir=args.review_dir,
        mode=args.mode,
        limit_slides=args.limit_slides,
        start_slide=args.start_slide,
        end_slide=args.end_slide,
        enable_ocr=args.ocr,
        llm_config=args.llm_config,
        allow_local_fallback=args.allow_local_fallback,
        force=args.force,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
