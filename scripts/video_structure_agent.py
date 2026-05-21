from __future__ import annotations

import argparse
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

try:
    import cv2  # type: ignore
    import numpy as np
except ImportError:
    cv2 = None
    np = None


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_WINDOW_SECONDS = 60
DEFAULT_SCENE_MAX_SECONDS = 90
ALLOWED_CONTEXT_TYPES = {
    "technology_reference",
    "product_description",
    "product_behavior",
    "ui_reference",
    "operational_concept",
    "glossary",
    "process_definition",
}
ALLOWED_PROCEDURE_TYPES = {
    "navigation",
    "diagnostic_check",
    "operational_action",
    "validation_check",
    "recovery_action",
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
    "glossary_definition",
}
PROCEDURE_ELIGIBLE_INTENTS = {
    "operator_action",
    "support_action",
    "recovery_action",
    "configuration_behavior",
    "diagnostic_behavior",
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
SYSTEM_KEYWORDS = {
    "Optisweep": ["optisweep", "opti sweep"],
    "WCS": ["wcs", "warehouse control"],
    "RMS": ["rms"],
    "Ignition": ["ignition"],
    "AGV": ["agv", "agvs"],
    "Tipper": ["tipper", "tippers"],
    "Hospital": ["hospital"],
    "HMI": ["hmi"],
    "OPC-UA": ["opc", "opc-ua", "opc ua"],
}
COMPONENT_KEYWORDS = {
    "RMS map": ["rms map", "map"],
    "heartbeat": ["heartbeat"],
    "alarm": ["alarm"],
    "dashboard": ["dashboard"],
    "menu": ["menu"],
    "station": ["station"],
    "service": ["service"],
    "tote": ["tote"],
}
ACTION_TERMS = [
    "click",
    "select",
    "open",
    "check",
    "verify",
    "restart",
    "start",
    "stop",
    "navigate",
    "go to",
    "enable",
    "disable",
    "add",
    "remove",
    "confirm",
    "look at",
    "enter",
    "acknowledge",
    "reset",
]
ORDER_TERMS = ["first", "then", "next", "after", "before", "step", "finally"]
VAGUE_PROCEDURE_TEXT = ["all right", "we'll get started", "you know", "kind of", "basically", "stuff", "things"]
LEGACY_WINDOW_PATTERN = re.compile(r"_(window|win)_\d{3,}|_window_\d{3,}")
BROAD_TOPIC_TITLE_PATTERN = re.compile(r"^(agv|rms|tipper|hospital|tote|wcs|ignition|optisweep)( training video reference)?$", re.IGNORECASE)
PROMPT_VERSION = "video_structuring_v4_llm_scene_candidate_refs"
ALLOWED_KNOWLEDGE_STRATEGIES = {"context_only", "procedure_candidate_allowed", "artifact_only", "ignore"}


class VideoStructuringError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()


def write_json(path: Path, payload: Any, force: bool = False) -> None:
    if path.exists() and not force:
        raise VideoStructuringError(f"Refusing to overwrite existing output without --force: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def first_existing(base: Path, names: list[str]) -> Path | None:
    for name in names:
        path = base / name
        if path.exists():
            return path
    return None


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def unique_strings(values: list[Any]) -> list[str]:
    result = []
    for value in values:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return result


def unique_values(values: list[Any]) -> list[Any]:
    result = []
    seen = set()
    for value in values:
        marker = json.dumps(value, sort_keys=True, ensure_ascii=False) if isinstance(value, dict | list) else str(value)
        if marker not in seen:
            seen.add(marker)
            result.append(value)
    return result


def timestamp_to_seconds(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    parts = text.replace(",", ".").split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        if len(parts) == 2:
            minutes, seconds = parts
            return int(minutes) * 60 + float(seconds)
    except ValueError:
        return None
    return None


def seconds_to_timestamp(seconds: float) -> str:
    millis = int(round((seconds - int(seconds)) * 1000))
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def valid_timestamp(value: Any) -> bool:
    return timestamp_to_seconds(value) is not None


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
    stage_config = dict(config)
    model_key = f"{stage}_model"
    deployment_key = f"{stage}_deployment"
    max_tokens_key = f"{stage}_max_tokens"
    max_completion_tokens_key = f"{stage}_max_completion_tokens"
    delay_key = f"{stage}_request_delay_seconds"
    if config.get(model_key):
        stage_config["model"] = config[model_key]
    if config.get(deployment_key):
        stage_config["deployment"] = config[deployment_key]
    if config.get(max_tokens_key):
        stage_config["max_tokens"] = config[max_tokens_key]
        stage_config.pop("max_completion_tokens", None)
    if config.get(max_completion_tokens_key):
        stage_config["max_completion_tokens"] = config[max_completion_tokens_key]
    if config.get(delay_key) is not None:
        stage_config["request_delay_seconds"] = config[delay_key]
    return stage_config


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def text_blob(*values: Any) -> str:
    parts = []
    for value in values:
        if isinstance(value, list):
            parts.extend(str(item) for item in value if str(item).strip())
        elif value is not None and str(value).strip():
            parts.append(str(value))
    return " ".join(parts)


def truncate_text(value: Any, limit: int = 600) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def detect_terms(text: str, mapping: dict[str, list[str]]) -> list[str]:
    lowered = text.lower()
    return [name for name, terms in mapping.items() if any(term in lowered for term in terms)]


def observed_signals(text: str) -> list[str]:
    signals = []
    lowered = text.lower()
    for term in ["alarm", "heartbeat", "timeout", "stopped", "error", "offline", "restart", "hospital", "tipper"]:
        if term in lowered:
            signals.append(term)
    return signals


def candidate_context_types(text: str, components: list[str], systems: list[str]) -> list[str]:
    lowered = text.lower()
    types = []
    if "what is" in lowered or "called" in lowered or "means" in lowered:
        types.append("glossary")
    if any(system in {"Optisweep", "WCS", "RMS", "Ignition", "OPC-UA"} for system in systems):
        types.append("technology_reference")
    if any(component in {"dashboard", "menu", "RMS map"} for component in components):
        types.append("ui_reference")
    if any(term in lowered for term in ["flow", "sequence", "process", "route"]):
        types.append("process_definition")
    if not types and (components or systems):
        types.append("operational_concept")
    return unique_strings(types)


@dataclass
class EvidenceBundle:
    video_id: str
    input_dir: Path
    video_metadata: dict[str, Any] = field(default_factory=dict)
    transcript_segments: list[dict[str, Any]] = field(default_factory=list)
    frame_artifacts: list[dict[str, Any]] = field(default_factory=list)
    ocr_records: list[dict[str, Any]] = field(default_factory=list)
    alignment_records: list[dict[str, Any]] = field(default_factory=list)
    visual_summary_artifacts: list[dict[str, Any]] = field(default_factory=list)
    source_report: dict[str, Any] = field(default_factory=dict)


class EvidenceBundleLoader:
    def __init__(self, video_id: str, input_dir: Path) -> None:
        self.video_id = video_id
        self.input_dir = input_dir

    def load(self) -> EvidenceBundle:
        if not self.input_dir.exists():
            raise VideoStructuringError(f"Input directory not found: {self.input_dir}")
        bundle_path = first_existing(self.input_dir, ["video_evidence_bundle.json"])
        if bundle_path:
            raw_bundle = read_json(bundle_path)
            records = raw_bundle.get("records", {})
            return EvidenceBundle(
                video_id=self.video_id,
                input_dir=self.input_dir,
                video_metadata=raw_bundle.get("video_metadata", {"video_id": self.video_id}),
                transcript_segments=as_list(records.get("video_transcript_segments")),
                frame_artifacts=as_list(records.get("video_frame_artifacts")),
                ocr_records=as_list(records.get("video_ocr_artifacts")),
                alignment_records=as_list(records.get("video_alignment_records")),
                visual_summary_artifacts=as_list(records.get("video_visual_summary_artifacts")),
                source_report=raw_bundle.get("extraction_report", {}),
            )
        return EvidenceBundle(
            video_id=self.video_id,
            input_dir=self.input_dir,
            video_metadata={"video_id": self.video_id},
            transcript_segments=self._load_any(["transcript_segments.json", "video_transcript_segments.json"]),
            frame_artifacts=self._load_any(["frame_index.json", "frame_artifacts.json", "video_frame_artifacts.json"]),
            ocr_records=self._load_any(["ocr_segments.json", "ocr_artifacts.json", "video_ocr_artifacts.json"]),
            alignment_records=self._load_any(["alignment.json", "frame_transcript_alignment.json", "video_alignment_records.json"]),
            visual_summary_artifacts=self._load_any(["visual_summary_artifacts.json", "video_visual_summary_artifacts.json"]),
            source_report=self._load_report(),
        )

    def _load_any(self, names: list[str]) -> list[dict[str, Any]]:
        path = first_existing(self.input_dir, names)
        if not path:
            return []
        payload = read_json(path)
        if isinstance(payload, dict):
            for key in ["records", "segments", "items", "frames"]:
                if isinstance(payload.get(key), list):
                    return payload[key]
            return [payload]
        return as_list(payload)

    def _load_report(self) -> dict[str, Any]:
        path = first_existing(self.input_dir, ["extraction_report.json"])
        if not path:
            return {}
        payload = read_json(path)
        return payload if isinstance(payload, dict) else {}


class TranscriptVisualAligner:
    def __init__(self, bundle: EvidenceBundle) -> None:
        self.bundle = bundle
        self.frames_by_id = {frame.get("artifact_id"): frame for frame in bundle.frame_artifacts if frame.get("artifact_id")}
        self.ocr_by_frame_id = self._ocr_by_frame_id(bundle.ocr_records)
        self.visual_by_frame_id = self._visual_by_frame_id(bundle.visual_summary_artifacts)

    def aligned_segments(self) -> list[dict[str, Any]]:
        if self.bundle.alignment_records:
            return [self._from_alignment(record) for record in self.bundle.alignment_records]
        return [self._from_segment(segment) for segment in self.bundle.transcript_segments]

    def _from_alignment(self, alignment: dict[str, Any]) -> dict[str, Any]:
        frame_ids = unique_strings(as_list(alignment.get("frame_artifact_ids")))
        frames = alignment.get("aligned_frames") or [self.frames_by_id.get(frame_id, {"artifact_id": frame_id}) for frame_id in frame_ids]
        segment = self._segment_by_id(alignment.get("segment_id"))
        return self._aligned_record(alignment, segment, frame_ids, frames)

    def _from_segment(self, segment: dict[str, Any]) -> dict[str, Any]:
        frame_ids = unique_strings(as_list(segment.get("aligned_frame_ids")))
        frames = [self.frames_by_id.get(frame_id, {"artifact_id": frame_id}) for frame_id in frame_ids]
        return self._aligned_record(segment, segment, frame_ids, frames)

    def _aligned_record(self, source: dict[str, Any], segment: dict[str, Any], frame_ids: list[str], frames: list[dict[str, Any]]) -> dict[str, Any]:
        ocr_records = [ocr for frame_id in frame_ids for ocr in self.ocr_by_frame_id.get(frame_id, [])]
        visual_records = [visual for frame_id in frame_ids for visual in self.visual_by_frame_id.get(frame_id, [])]
        return {
            "segment_id": source.get("segment_id") or segment.get("segment_id"),
            "timestamp_start": source.get("timestamp_start") or segment.get("timestamp_start"),
            "timestamp_end": source.get("timestamp_end") or segment.get("timestamp_end"),
            "transcript_text": source.get("transcript_text") or segment.get("transcript_text") or "",
            "transcript_status": source.get("transcript_status") or segment.get("transcript_status") or "unknown",
            "speaker": source.get("speaker") or segment.get("speaker") or "unknown",
            "frame_ids": frame_ids,
            "frames": frames,
            "ocr_records": ocr_records,
            "visual_records": visual_records,
            "source_refs": unique_values(as_list(source.get("source_refs")) + as_list(segment.get("source_refs"))),
            "alignment_method": source.get("alignment_method"),
            "alignment_quality": source.get("alignment_quality"),
        }

    def _segment_by_id(self, segment_id: Any) -> dict[str, Any]:
        for segment in self.bundle.transcript_segments:
            if segment.get("segment_id") == segment_id:
                return segment
        return {}

    def _ocr_by_frame_id(self, ocr_records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for record in ocr_records:
            frame_id = record.get("frame_artifact_id") or record.get("frame_id")
            if frame_id:
                grouped.setdefault(str(frame_id), []).append(record)
        return grouped

    def _visual_by_frame_id(self, visual_records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for record in visual_records:
            frame_id = record.get("frame_artifact_id") or record.get("frame_id")
            if frame_id:
                grouped.setdefault(str(frame_id), []).append(record)
        return grouped


class EvidenceChunkBuilder:
    def build(self, video_id: str, aligned_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        chunks = []
        for index, segment in enumerate(aligned_segments, start=1):
            ocr_text = unique_strings(
                [
                    record.get("extracted_text") or record.get("ocr_text") or record.get("text")
                    for record in segment["ocr_records"]
                    if record.get("extracted_text") or record.get("ocr_text") or record.get("text")
                ]
            )
            visual_summary = self._visual_summary(segment)
            combined_text = text_blob(segment["transcript_text"], ocr_text, visual_summary)
            systems = detect_terms(combined_text, SYSTEM_KEYWORDS)
            components = detect_terms(combined_text, COMPONENT_KEYWORDS)
            chunk_id = f"vec_{video_id}_{index:06d}"
            source_refs = self._source_refs(video_id, segment)
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "video_id": video_id,
                    "timestamp_start": segment["timestamp_start"],
                    "timestamp_end": segment["timestamp_end"],
                    "transcript_segment_ids": unique_strings([segment.get("segment_id")]),
                    "speaker": segment.get("speaker", "unknown"),
                    "frame_ids": segment["frame_ids"],
                    "artifact_ids": segment["frame_ids"],
                    "transcript_text": segment["transcript_text"],
                    "ocr_text": ocr_text,
                    "visual_summary": visual_summary,
                    "components": components,
                    "systems": systems,
                    "observed_signals": observed_signals(combined_text),
                    "inferred_interpretations": [],
                    "candidate_context_types": candidate_context_types(combined_text, components, systems),
                    "candidate_procedure_refs": [],
                    "speaker_candidates": [],
                    "speaker_attribution_method": "not_available",
                    "speaker_confidence": 0.0,
                    "speaker_frame_refs": [],
                    "speaker_evidence_refs": [],
                    "source_refs": source_refs,
                    "validation_status": "needs_review",
                    "retrieval_text": self._retrieval_text(segment["transcript_text"], ocr_text, visual_summary, components, systems),
                }
            )
        return chunks

    def _visual_summary(self, segment: dict[str, Any]) -> str:
        summaries = [
            record.get("visual_summary")
            for record in segment["visual_records"]
            if record.get("visual_summary")
        ]
        if summaries:
            return " ".join(unique_strings(summaries))
        if segment["frames"]:
            timestamps = unique_strings([frame.get("timestamp") for frame in segment["frames"] if frame.get("timestamp")])
            return f"Aligned video frame evidence at {', '.join(timestamps)}."
        return "No aligned frame summary available."

    def _source_refs(self, video_id: str, segment: dict[str, Any]) -> list[Any]:
        refs: list[Any] = []
        refs.extend(as_list(segment.get("source_refs")))
        if segment.get("segment_id"):
            refs.append(f"transcript_segment:{segment['segment_id']}")
        for frame_id in segment["frame_ids"]:
            refs.append(f"frame_artifact:{frame_id}")
        refs.append(f"video:{video_id}")
        return unique_values(refs)

    def _retrieval_text(self, transcript: str, ocr_text: list[str], visual_summary: str, components: list[str], systems: list[str]) -> str:
        return text_blob(transcript, ocr_text, visual_summary, "Components: " + ", ".join(components), "Systems: " + ", ".join(systems)).strip()


class TeamsSpeakerAttributionExtractor:
    def enrich(self, evidence_chunks: list[dict[str, Any]], aligned_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        segments_by_id = {segment.get("segment_id"): segment for segment in aligned_segments}
        for chunk in evidence_chunks:
            segment = self._segment_for_chunk(chunk, segments_by_id)
            speaker_candidates = []
            speaker_frame_refs = []
            speaker_evidence_refs = []
            confidence = 0.0
            for frame in segment.get("frames", []):
                image_path = frame.get("image_path") or frame.get("frame_path")
                if not image_path:
                    continue
                detection = self._detect_purple_speaker_indicator(Path(image_path))
                if detection["detected"]:
                    speaker_frame_refs.append(frame.get("artifact_id"))
                    speaker_evidence_refs.extend(frame.get("source_refs", []))
                    confidence = max(confidence, detection["confidence"])
            transcript_speaker = segment.get("speaker")
            if speaker_frame_refs and transcript_speaker and transcript_speaker != "unknown":
                speaker_candidates.append(transcript_speaker)
            chunk["speaker_candidates"] = unique_strings(speaker_candidates)
            chunk["speaker_attribution_method"] = "teams_purple_indicator" if speaker_frame_refs else "not_available"
            chunk["speaker_confidence"] = round(confidence, 3)
            chunk["speaker_frame_refs"] = unique_strings(speaker_frame_refs)
            chunk["speaker_evidence_refs"] = unique_values(speaker_evidence_refs)
        return evidence_chunks

    def _segment_for_chunk(self, chunk: dict[str, Any], segments_by_id: dict[Any, dict[str, Any]]) -> dict[str, Any]:
        for segment_id in chunk.get("transcript_segment_ids", []):
            if segment_id in segments_by_id:
                return segments_by_id[segment_id]
        return {}

    def _detect_purple_speaker_indicator(self, image_path: Path) -> dict[str, Any]:
        if cv2 is None or np is None or not image_path.exists():
            return {"detected": False, "confidence": 0.0}
        image = cv2.imread(str(image_path))
        if image is None:
            return {"detected": False, "confidence": 0.0}
        height, width = image.shape[:2]
        region = image[int(height * 0.65):height, 0:int(width * 0.45)]
        if region.size == 0:
            return {"detected": False, "confidence": 0.0}
        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        lower = np.array([125, 40, 40])
        upper = np.array([165, 255, 255])
        mask = cv2.inRange(hsv, lower, upper)
        ratio = float(cv2.countNonZero(mask)) / float(mask.size)
        detected = ratio >= 0.002
        return {"detected": detected, "confidence": min(0.95, ratio * 80) if detected else 0.0}


class OperationalSceneBuilder:
    def __init__(self, max_scene_seconds: int = DEFAULT_SCENE_MAX_SECONDS) -> None:
        self.max_scene_seconds = max_scene_seconds

    def build(self, video_id: str, evidence_chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not evidence_chunks:
            return []
        scenes = []
        current: list[dict[str, Any]] = []
        current_start: float | None = None
        current_type: str | None = None
        for chunk in evidence_chunks:
            chunk_start = timestamp_to_seconds(chunk.get("timestamp_start")) or 0.0
            chunk_type = self._scene_type_for_chunks([chunk])
            if current and self._starts_new_scene(current, current_start or chunk_start, current_type, chunk, chunk_type):
                scenes.append(self._scene_record(video_id, len(scenes) + 1, current))
                current = []
                current_start = chunk_start
                current_type = chunk_type
            if not current:
                current_start = chunk_start
                current_type = chunk_type
            current.append(chunk)
        if current:
            scenes.append(self._scene_record(video_id, len(scenes) + 1, current))
        return scenes

    def _starts_new_scene(
        self,
        current: list[dict[str, Any]],
        current_start: float,
        current_type: str | None,
        chunk: dict[str, Any],
        chunk_type: str,
    ) -> bool:
        last_end = timestamp_to_seconds(current[-1].get("timestamp_end")) or current_start
        chunk_start = timestamp_to_seconds(chunk.get("timestamp_start")) or last_end
        if chunk_start - last_end > 12:
            return True
        if chunk_start - current_start >= self.max_scene_seconds:
            return True
        if current_type and chunk_type != current_type and {current_type, chunk_type} & {"reusable_procedure", "ui_walkthrough"}:
            if {current_type, chunk_type} == {"reusable_procedure", "ui_walkthrough"}:
                return False
            return True
        return len(current) >= 18

    def _scene_record(self, video_id: str, index: int, chunks: list[dict[str, Any]]) -> dict[str, Any]:
        scene_type = self._scene_type_for_chunks(chunks)
        scene_id = f"scene_{video_id}_{index:06d}"
        systems = unique_strings([system for chunk in chunks for system in chunk.get("systems", [])])
        components = unique_strings([component for chunk in chunks for component in chunk.get("components", [])])
        observed = unique_strings([signal for chunk in chunks for signal in chunk.get("observed_signals", [])])
        frame_refs = unique_strings([frame_id for chunk in chunks for frame_id in chunk.get("frame_ids", [])])
        speaker_candidates = unique_strings([speaker for chunk in chunks for speaker in chunk.get("speaker_candidates", [])])
        speaker_confidence = max([float(chunk.get("speaker_confidence") or 0.0) for chunk in chunks] or [0.0])
        speaker_methods = unique_strings([chunk.get("speaker_attribution_method") for chunk in chunks if chunk.get("speaker_attribution_method")])
        transcript = text_blob(*[chunk.get("transcript_text") for chunk in chunks])
        intents = self._operational_intents(scene_type)
        primary_intent = intents[0] if intents else "conceptual_only"
        eligibility = self._eligibility(scene_type, primary_intent)
        return {
            "scene_id": scene_id,
            "video_id": video_id,
            "timestamp_start": chunks[0].get("timestamp_start"),
            "timestamp_end": chunks[-1].get("timestamp_end"),
            "scene_title": self._scene_title(scene_type, systems, components, index),
            "scene_type": scene_type,
            "transcript_segment_refs": unique_strings([segment_id for chunk in chunks for segment_id in chunk.get("transcript_segment_ids", [])]),
            "evidence_chunk_refs": [chunk["chunk_id"] for chunk in chunks],
            "frame_refs": frame_refs,
            "artifact_refs": unique_strings([artifact_id for chunk in chunks for artifact_id in chunk.get("artifact_ids", [])]),
            "systems": systems,
            "components": components,
            "observed_signals": observed,
            "operational_intents": intents,
            "primary_intent": primary_intent,
            "knowledge_extraction_strategy": eligibility["knowledge_extraction_strategy"],
            "why_this_strategy": eligibility["reason"],
            "speaker_candidates": speaker_candidates,
            "speaker_attribution_method": "teams_purple_indicator" if "teams_purple_indicator" in speaker_methods else "not_available",
            "speaker_confidence": round(speaker_confidence, 3),
            "scene_summary": self._scene_summary(scene_type, transcript, systems, components),
            "extraction_eligibility": eligibility,
            "validation_status": "needs_review",
        }

    def _scene_type_for_chunks(self, chunks: list[dict[str, Any]]) -> str:
        text = text_blob(*[chunk.get("transcript_text") for chunk in chunks]).lower()
        systems = unique_strings([system for chunk in chunks for system in chunk.get("systems", [])])
        components = unique_strings([component for chunk in chunks for component in chunk.get("components", [])])
        action_count = sum(1 for term in ACTION_TERMS if term in text)
        ordered = any(term in text for term in ORDER_TERMS)
        if not text.strip() or any(text.strip().startswith(value) for value in ["thanks", "thank you", "all right"]):
            return "filler"
        if ordered and action_count >= 2:
            return "reusable_procedure"
        if action_count >= 1 and components:
            return "ui_walkthrough"
        if any(term in text for term in ["flow", "process", "sequence", "how it works", "goes from"]):
            return "operational_process"
        if systems and any(term in text for term in ["is", "are", "means", "called", "overview"]):
            return "system_overview"
        if systems or components:
            return "conceptual_explanation"
        return "unknown"

    def _operational_intents(self, scene_type: str) -> list[str]:
        mapping = {
            "conceptual_explanation": ["conceptual_only"],
            "system_overview": ["system_architecture"],
            "ui_walkthrough": ["ui_walkthrough"],
            "operational_process": ["operational_behavior"],
            "reusable_procedure": ["operator_action"],
            "filler": ["filler"],
            "unknown": ["conceptual_only"],
        }
        return mapping.get(scene_type, ["conceptual_only"])

    def _eligibility(self, scene_type: str, primary_intent: str) -> dict[str, Any]:
        procedure_allowed = primary_intent in PROCEDURE_ELIGIBLE_INTENTS
        reason = "explicit reusable action sequence" if procedure_allowed else f"{scene_type} scenes are not eligible for procedure extraction"
        return {
            "context_candidate_allowed": scene_type not in {"filler", "unknown"},
            "procedure_candidate_allowed": procedure_allowed,
            "knowledge_extraction_strategy": "procedure_candidate_allowed" if procedure_allowed else ("context_only" if scene_type not in {"filler", "unknown"} else "ignore"),
            "reason": reason,
        }

    def _scene_title(self, scene_type: str, systems: list[str], components: list[str], index: int) -> str:
        subject = ", ".join(systems or components) or "training evidence"
        return f"{scene_type.replace('_', ' ').title()} {index}: {subject}"

    def _scene_summary(self, scene_type: str, transcript: str, systems: list[str], components: list[str]) -> str:
        summary = transcript[:240].strip()
        if summary:
            return summary
        return text_blob(scene_type, systems, components) or "Scene requires review."


class SlideScreenSegmentBuilder:
    def __init__(self, max_unknown_segment_seconds: int = 180, max_unknown_transcript_segments: int = 80) -> None:
        self.max_unknown_segment_seconds = max_unknown_segment_seconds
        self.max_unknown_transcript_segments = max_unknown_transcript_segments

    def build(self, video_id: str, aligned_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        segments = []
        current: dict[str, Any] | None = None
        current_key = ""
        for segment in aligned_segments:
            visible_text = self._ocr_text(segment)
            visual_summaries = unique_strings(
                [record.get("visual_summary") for record in segment.get("visual_records", []) if record.get("visual_summary")]
            )
            key = clean_id(text_blob(visible_text, visual_summaries)[:160])
            if current and key == current_key and not self._has_large_gap(current, segment):
                self._extend_segment(current, segment, visible_text, visual_summaries)
                continue
            if current:
                segments.append(current)
            current_key = key
            current = self._new_segment(video_id, len(segments) + 1, segment, visible_text, visual_summaries)
        if current:
            segments.append(current)
        return segments

    def _new_segment(
        self,
        video_id: str,
        index: int,
        segment: dict[str, Any],
        ocr_text: list[str],
        visual_summaries: list[str],
    ) -> dict[str, Any]:
        frame_refs = unique_strings([frame.get("artifact_id") for frame in segment.get("frames", [])])
        text = text_blob(segment.get("transcript_text"), ocr_text, visual_summaries)
        segment_type = self._segment_type(text, ocr_text)
        return {
            "slide_screen_segment_id": f"sss_{video_id}_{index:06d}",
            "video_id": video_id,
            "timestamp_start": segment.get("timestamp_start"),
            "timestamp_end": segment.get("timestamp_end"),
            "segment_type": segment_type,
            "representative_frame_ref": frame_refs[0] if frame_refs else "",
            "additional_frame_refs": [],
            "slide_title": self._slide_title(ocr_text, segment_type, index),
            "visible_text": ocr_text,
            "ocr_text": ocr_text,
            "visual_summary": text_blob(visual_summaries) or "Slide/screen evidence requires review.",
            "visual_elements": self._visual_elements(ocr_text, visual_summaries),
            "linked_transcript_segment_ids": unique_strings([segment.get("segment_id")]),
            "speaker_explanation_text": segment.get("transcript_text", ""),
            "validation_status": "needs_review",
        }

    def _extend_segment(
        self,
        current: dict[str, Any],
        segment: dict[str, Any],
        ocr_text: list[str],
        visual_summaries: list[str],
    ) -> None:
        current["timestamp_end"] = segment.get("timestamp_end") or current["timestamp_end"]
        current["visible_text"] = unique_strings(current["visible_text"] + ocr_text)
        current["ocr_text"] = unique_strings(current["ocr_text"] + ocr_text)
        current["visual_summary"] = text_blob(current["visual_summary"], visual_summaries)
        current["linked_transcript_segment_ids"] = unique_strings(current["linked_transcript_segment_ids"] + [segment.get("segment_id")])
        current["speaker_explanation_text"] = text_blob(current["speaker_explanation_text"], segment.get("transcript_text"))

    def _ocr_text(self, segment: dict[str, Any]) -> list[str]:
        return unique_strings(
            [
                record.get("extracted_text") or record.get("ocr_text") or record.get("text")
                for record in segment.get("ocr_records", [])
                if record.get("extracted_text") or record.get("ocr_text") or record.get("text")
            ]
        )

    def _has_large_gap(self, current: dict[str, Any], segment: dict[str, Any]) -> bool:
        current_end = timestamp_to_seconds(current.get("timestamp_end")) or 0.0
        next_start = timestamp_to_seconds(segment.get("timestamp_start")) or current_end
        if next_start - current_end > 12:
            return True
        if current.get("visible_text") or current.get("ocr_text"):
            return False
        current_start = timestamp_to_seconds(current.get("timestamp_start")) or current_end
        if current_end - current_start >= self.max_unknown_segment_seconds:
            return True
        return len(current.get("linked_transcript_segment_ids", [])) >= self.max_unknown_transcript_segments

    def _segment_type(self, text: str, visible_text: list[str]) -> str:
        lowered = text.lower()
        if "dashboard" in lowered:
            return "dashboard"
        if "diagram" in lowered or "architecture" in lowered:
            return "diagram"
        if "map" in lowered:
            return "system_map"
        if visible_text:
            return "ui_screen"
        return "unknown"

    def _slide_title(self, visible_text: list[str], segment_type: str, index: int) -> str:
        if visible_text:
            return visible_text[0][:80]
        return f"{segment_type.replace('_', ' ').title()} {index}"

    def _visual_elements(self, visible_text: list[str], visual_summaries: list[str]) -> list[dict[str, Any]]:
        if not visible_text and not visual_summaries:
            return []
        return [
            {
                "element_type": "screenshot",
                "description": text_blob(visual_summaries) or "Visible text captured from aligned frame.",
                "visible_labels": visible_text,
                "systems_or_components": [],
            }
        ]


class CandidateSegmentBuilder:
    def __init__(self, max_seconds: int = 90, max_cues: int = 12) -> None:
        self.max_seconds = max_seconds
        self.max_cues = max_cues

    def build(
        self,
        video_id: str,
        evidence_chunks: list[dict[str, Any]],
        slide_screen_segments: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if slide_screen_segments:
            return self._build_from_slides(video_id, evidence_chunks, slide_screen_segments)
        candidates = []
        current: list[dict[str, Any]] = []
        current_start: float | None = None
        for chunk in evidence_chunks:
            chunk_start = timestamp_to_seconds(chunk.get("timestamp_start")) or 0.0
            if current and self._starts_new_candidate(current, current_start or chunk_start, chunk):
                candidates.append(self._candidate_record(video_id, len(candidates) + 1, current, slide_screen_segments))
                current = []
                current_start = chunk_start
            if not current:
                current_start = chunk_start
            current.append(chunk)
        if current:
            candidates.append(self._candidate_record(video_id, len(candidates) + 1, current, slide_screen_segments))
        for index, candidate in enumerate(candidates):
            candidate["neighboring_context"] = {
                "previous_candidate_summary": self._candidate_summary(candidates[index - 1]) if index > 0 else "",
                "next_candidate_summary": self._candidate_summary(candidates[index + 1]) if index + 1 < len(candidates) else "",
            }
        return candidates

    def _build_from_slides(
        self,
        video_id: str,
        evidence_chunks: list[dict[str, Any]],
        slide_screen_segments: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        candidates = []
        for slide in slide_screen_segments:
            chunks = [chunk for chunk in evidence_chunks if self._chunk_matches_slide(chunk, slide)]
            if not chunks:
                chunks = [chunk for chunk in evidence_chunks if self._overlaps(chunk.get("timestamp_start"), chunk.get("timestamp_end"), slide)]
            if not chunks:
                continue
            candidates.append(self._slide_candidate_record(video_id, len(candidates) + 1, chunks, slide))
        for index, candidate in enumerate(candidates):
            candidate["neighboring_context"] = {
                "previous_candidate_summary": self._candidate_summary(candidates[index - 1]) if index > 0 else "",
                "next_candidate_summary": self._candidate_summary(candidates[index + 1]) if index + 1 < len(candidates) else "",
            }
        return candidates

    def _chunk_matches_slide(self, chunk: dict[str, Any], slide: dict[str, Any]) -> bool:
        linked_segments = set(slide.get("linked_transcript_segment_ids", []))
        chunk_segments = set(chunk.get("transcript_segment_ids", []))
        return bool(linked_segments.intersection(chunk_segments))

    def _slide_candidate_record(
        self,
        video_id: str,
        index: int,
        chunks: list[dict[str, Any]],
        slide: dict[str, Any],
    ) -> dict[str, Any]:
        timestamp_start = slide.get("timestamp_start") or chunks[0].get("timestamp_start")
        timestamp_end = slide.get("timestamp_end") or chunks[-1].get("timestamp_end")
        return {
            "candidate_segment_id": f"cand_{video_id}_{index:06d}",
            "video_id": video_id,
            "timestamp_start": timestamp_start,
            "timestamp_end": timestamp_end,
            "evidence_chunk_refs": [chunk["chunk_id"] for chunk in chunks],
            "transcript_cues": [
                {
                    "transcript_segment_id": first_value(chunk.get("transcript_segment_ids")),
                    "timestamp_start": chunk.get("timestamp_start"),
                    "timestamp_end": chunk.get("timestamp_end"),
                    "speaker": chunk.get("speaker") or first_value(chunk.get("speaker_candidates")) or "unknown",
                    "text": chunk.get("transcript_text", ""),
                }
                for chunk in chunks
            ],
            "slide_screen_segments": [self._compact_slide_segment(slide)],
            "ocr_highlights": unique_strings([text for chunk in chunks for text in chunk.get("ocr_text", [])])[:20],
            "speaker_candidates": unique_strings([speaker for chunk in chunks for speaker in chunk.get("speaker_candidates", [])]),
            "neighboring_context": {"previous_candidate_summary": "", "next_candidate_summary": ""},
        }

    def _starts_new_candidate(self, current: list[dict[str, Any]], current_start: float, chunk: dict[str, Any]) -> bool:
        last_end = timestamp_to_seconds(current[-1].get("timestamp_end")) or current_start
        chunk_start = timestamp_to_seconds(chunk.get("timestamp_start")) or last_end
        if chunk_start - last_end > 12:
            return True
        if chunk_start - current_start >= self.max_seconds:
            return True
        return len(current) >= self.max_cues

    def _candidate_record(
        self,
        video_id: str,
        index: int,
        chunks: list[dict[str, Any]],
        slide_screen_segments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        timestamp_start = chunks[0].get("timestamp_start")
        timestamp_end = chunks[-1].get("timestamp_end")
        slides = [segment for segment in slide_screen_segments if self._overlaps(timestamp_start, timestamp_end, segment)]
        return {
            "candidate_segment_id": f"cand_{video_id}_{index:06d}",
            "video_id": video_id,
            "timestamp_start": timestamp_start,
            "timestamp_end": timestamp_end,
            "evidence_chunk_refs": [chunk["chunk_id"] for chunk in chunks],
            "transcript_cues": [
                {
                    "transcript_segment_id": first_value(chunk.get("transcript_segment_ids")),
                    "timestamp_start": chunk.get("timestamp_start"),
                    "timestamp_end": chunk.get("timestamp_end"),
                    "speaker": chunk.get("speaker") or first_value(chunk.get("speaker_candidates")) or "unknown",
                    "text": chunk.get("transcript_text", ""),
                }
                for chunk in chunks
            ],
            "slide_screen_segments": [self._compact_slide_segment(segment) for segment in slides],
            "ocr_highlights": unique_strings([text for chunk in chunks for text in chunk.get("ocr_text", [])])[:20],
            "speaker_candidates": unique_strings([speaker for chunk in chunks for speaker in chunk.get("speaker_candidates", [])]),
            "neighboring_context": {"previous_candidate_summary": "", "next_candidate_summary": ""},
        }

    def _compact_slide_segment(self, segment: dict[str, Any]) -> dict[str, Any]:
        return {
            "slide_screen_segment_id": segment.get("slide_screen_segment_id"),
            "timestamp_start": segment.get("timestamp_start"),
            "timestamp_end": segment.get("timestamp_end"),
            "representative_frame_ref": segment.get("representative_frame_ref"),
            "slide_title": segment.get("slide_title", ""),
            "visible_text": segment.get("visible_text", []),
            "ocr_text": segment.get("ocr_text", []),
            "visual_summary": truncate_text(segment.get("visual_summary"), 600),
            "visual_elements": segment.get("visual_elements", []),
        }

    def _candidate_summary(self, candidate: dict[str, Any]) -> str:
        return truncate_text(text_blob([cue.get("text") for cue in candidate.get("transcript_cues", [])]), 300)

    def _overlaps(self, timestamp_start: Any, timestamp_end: Any, segment: dict[str, Any]) -> bool:
        start = timestamp_to_seconds(timestamp_start)
        end = timestamp_to_seconds(timestamp_end)
        segment_start = timestamp_to_seconds(segment.get("timestamp_start"))
        segment_end = timestamp_to_seconds(segment.get("timestamp_end"))
        if None in {start, end, segment_start, segment_end}:
            return False
        return bool(start <= segment_end and segment_start <= end)


class LLMOperationalScenePlanner:
    def __init__(
        self,
        config_path: Path | None,
        cache_dir: Path,
        allow_local_fallback: bool = False,
    ) -> None:
        self.config_path = config_path
        self.cache_dir = cache_dir
        self.allow_local_fallback = allow_local_fallback
        self.llm_status = "not_configured"
        self.llm_error: str | None = None

    def plan(
        self,
        video_id: str,
        evidence_chunks: list[dict[str, Any]],
        slide_screen_segments: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        config = self._config()
        if not config:
            if self.allow_local_fallback:
                self.llm_status = "local_fallback_scene_planning"
                return OperationalSceneBuilder().build(video_id, evidence_chunks)
            raise VideoStructuringError("LLM scene planning requires --llm-config unless --allow-local-fallback is explicitly passed.")
        planning_config = llm_stage_config(config, "scene_planner")
        candidate_builder = CandidateSegmentBuilder(
            max_seconds=int(planning_config.get("scene_planning_candidate_seconds", 75)),
            max_cues=int(planning_config.get("scene_planning_max_cues", 8)),
        )
        candidates = candidate_builder.build(video_id, evidence_chunks, slide_screen_segments)
        planned = []
        batch_size = max(1, int(planning_config.get("scene_planning_batch_size", 3)))
        candidate_batches = [candidates[index:index + batch_size] for index in range(0, len(candidates), batch_size)]
        try:
            for index, candidate_batch in enumerate(candidate_batches, start=1):
                batch_label = f"{candidate_batch[0]['candidate_segment_id']}..{candidate_batch[-1]['candidate_segment_id']}"
                print(f"LLM planning candidate batch {index}/{len(candidate_batches)}: {batch_label}", flush=True)
                payload = self._cached_or_plan_candidate_batch(planning_config, candidate_batch)
                planned.extend(as_list(payload.get("operational_scenes") or payload.get("scenes")))
                delay = float(planning_config.get("request_delay_seconds", 0))
                if delay > 0:
                    time.sleep(delay)
        except Exception as exc:
            self.llm_status = "failed"
            self.llm_error = str(exc)
            if self.allow_local_fallback:
                self.llm_status = "local_fallback_scene_planning"
                return OperationalSceneBuilder().build(video_id, evidence_chunks)
            raise
        self.llm_status = "openai" if str(planning_config.get("provider", "openai")).lower() == "openai" else "azure_openai"
        return self._normalize_scenes(video_id, planned, evidence_chunks, slide_screen_segments, candidates)

    def _config(self) -> dict[str, Any] | None:
        if not self.config_path or not self.config_path.exists():
            return None
        return read_json(self.config_path)

    def _cached_or_plan_candidate_batch(self, config: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
        cache_path = self._cache_path(config, candidates)
        if cache_path.exists():
            cached = read_json(cache_path)
            if self._valid_scene_plan_payload(cached):
                return cached
        payload = self._plan_candidate_batch(config, candidates)
        if not self._valid_scene_plan_payload(payload):
            raise VideoStructuringError(f"LLM scene planning returned an empty or invalid response for {cache_path.name}")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return payload

    def _cache_path(self, config: dict[str, Any], candidates: list[dict[str, Any]]) -> Path:
        model = clean_id(str(config.get("model") or config.get("deployment") or "unknown_model"))
        first_index = clean_id(str(candidates[0]["candidate_segment_id"])).split("_")[-1]
        last_index = clean_id(str(candidates[-1]["candidate_segment_id"])).split("_")[-1]
        batch_id = f"batch_{first_index}_{last_index}_{stable_hash(candidates)[:12]}"
        return self.cache_dir / "scene_planning" / model / PROMPT_VERSION / f"{batch_id}.json"

    def _valid_scene_plan_payload(self, payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False
        scenes = payload.get("operational_scenes") or payload.get("scenes")
        if not isinstance(scenes, list):
            return False
        return bool(scenes)

    def _plan_candidate_batch(self, config: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
        client, model, _provider = LLMRecordExtractor(self.config_path)._llm_client(config)
        packet = {
            "task": "llm_operational_scene_planning",
            "prompt_version": PROMPT_VERSION,
            "rules": [
                "Return only JSON.",
                "Return at most 6 operational scenes for each candidate segment.",
                "Return scene boundaries and intent only; do not create knowledge units or procedure candidates.",
                "Do not summarize, quote evidence, rewrite transcript text, or create procedure steps.",
                "Use full transcript cue text as primary evidence.",
                "Prefer fewer coherent scenes over many small scenes.",
                "Slide changes are strong but not automatic boundaries.",
                "Split when operational topic, intent, or action sequence changes.",
                "Merge across slides when one coherent operational process continues.",
                "Every scene must include source_candidate_segment_ids from candidate_segment_id.",
                "Do not copy or expand evidence_chunk_refs from candidate segments.",
                "Keep why_this_strategy under 16 words.",
                "Do not include transcript quotes, evidence excerpts, or scene summaries.",
                "All scenes must remain validation_status needs_review.",
            ],
            "required_output_key": "operational_scenes",
            "required_scene_fields": [
                "scene_title",
                "timestamp_start",
                "timestamp_end",
                "primary_intent",
                "operational_intents",
                "knowledge_extraction_strategy",
                "why_this_strategy",
                "source_candidate_segment_ids",
                "slide_screen_segment_refs",
            ],
            "candidate_segments": candidates,
        }
        response = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the Phase 0 LLM Operational Scene Planner. "
                        "Decide semantic operational scene boundaries from transcript, OCR, slide/screen text, visual summaries, speaker cues, and neighboring context. "
                        "Do not extract knowledge units. Do not create procedures."
                    ),
                },
                {"role": "user", "content": json.dumps(packet, ensure_ascii=False)},
            ],
            **openai_generation_args(config),
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)

    def _normalize_scenes(
        self,
        video_id: str,
        planned: list[dict[str, Any]],
        evidence_chunks: list[dict[str, Any]],
        slide_screen_segments: list[dict[str, Any]],
        candidates: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        chunks_by_id = {chunk["chunk_id"]: chunk for chunk in evidence_chunks}
        candidates_by_id = {candidate["candidate_segment_id"]: candidate for candidate in candidates or []}
        normalized = []
        for index, scene in enumerate(planned, start=1):
            chunk_refs = unique_strings(as_list(scene.get("evidence_chunk_refs")))
            candidate_refs = unique_strings(as_list(scene.get("source_candidate_segment_ids") or scene.get("candidate_segment_ids")))
            for candidate_ref in candidate_refs:
                candidate = candidates_by_id.get(candidate_ref)
                if candidate:
                    chunk_refs.extend(as_list(candidate.get("evidence_chunk_refs")))
            chunk_refs = unique_strings(chunk_refs)
            chunks = [chunks_by_id[chunk_id] for chunk_id in chunk_refs if chunk_id in chunks_by_id]
            if not chunks:
                continue
            timestamp_start = scene.get("timestamp_start") or chunks[0].get("timestamp_start")
            timestamp_end = scene.get("timestamp_end") or chunks[-1].get("timestamp_end")
            linked_slides = [segment for segment in slide_screen_segments if self._overlaps(timestamp_start, timestamp_end, segment)]
            primary_intent = str(scene.get("primary_intent") or "conceptual_only")
            strategy = scene.get("knowledge_extraction_strategy")
            if strategy not in ALLOWED_KNOWLEDGE_STRATEGIES:
                strategy = "procedure_candidate_allowed" if primary_intent in PROCEDURE_ELIGIBLE_INTENTS else "context_only"
            normalized.append(
                {
                    "scene_id": scene.get("scene_id") or f"scene_{video_id}_{index:06d}",
                    "video_id": video_id,
                    "timestamp_start": timestamp_start,
                    "timestamp_end": timestamp_end,
                    "scene_title": scene.get("scene_title") or f"Operational Scene {index}",
                    "primary_intent": primary_intent,
                    "operational_intents": unique_strings(as_list(scene.get("operational_intents")) or [primary_intent]),
                    "knowledge_extraction_strategy": strategy,
                    "why_this_strategy": scene.get("why_this_strategy") or "",
                    "evidence_chunk_refs": [chunk["chunk_id"] for chunk in chunks],
                    "transcript_segment_refs": unique_strings([segment_id for chunk in chunks for segment_id in chunk.get("transcript_segment_ids", [])]),
                    "slide_screen_segment_refs": unique_strings([segment["slide_screen_segment_id"] for segment in linked_slides]),
                    "representative_frame_refs": unique_strings([segment.get("representative_frame_ref") for segment in linked_slides if segment.get("representative_frame_ref")]),
                    "systems": unique_strings([system for chunk in chunks for system in chunk.get("systems", [])]),
                    "components": unique_strings([component for chunk in chunks for component in chunk.get("components", [])]),
                    "observed_signals": unique_strings([signal for chunk in chunks for signal in chunk.get("observed_signals", [])]),
                    "speaker_candidates": unique_strings([speaker for chunk in chunks for speaker in chunk.get("speaker_candidates", [])]),
                    "extraction_eligibility": {
                        "context_candidate_allowed": strategy in {"context_only", "procedure_candidate_allowed"},
                        "procedure_candidate_allowed": strategy == "procedure_candidate_allowed",
                        "knowledge_extraction_strategy": strategy,
                        "reason": scene.get("why_this_strategy") or "",
                    },
                    "validation_status": "needs_review",
                }
            )
        return normalized

    def _overlaps(self, timestamp_start: Any, timestamp_end: Any, segment: dict[str, Any]) -> bool:
        start = timestamp_to_seconds(timestamp_start)
        end = timestamp_to_seconds(timestamp_end)
        segment_start = timestamp_to_seconds(segment.get("timestamp_start"))
        segment_end = timestamp_to_seconds(segment.get("timestamp_end"))
        if None in {start, end, segment_start, segment_end}:
            return False
        return bool(start <= segment_end and segment_start <= end)


class ScenePlanValidator:
    def validate(self, scenes: list[dict[str, Any]], evidence_chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not scenes and evidence_chunks:
            raise VideoStructuringError("LLM scene plan produced no operational scenes.")
        chunk_ids = {chunk["chunk_id"] for chunk in evidence_chunks}
        valid_scenes = []
        for scene in scenes:
            failed = self._failed_rules(scene, chunk_ids)
            if failed:
                raise VideoStructuringError(f"LLM scene plan failed validation for {scene.get('scene_id')}: {', '.join(failed)}")
            valid_scenes.append(scene)
        return valid_scenes

    def _failed_rules(self, scene: dict[str, Any], chunk_ids: set[str]) -> list[str]:
        failed = []
        if not scene.get("scene_id"):
            failed.append("missing_scene_id")
        if not valid_timestamp(scene.get("timestamp_start")) or not valid_timestamp(scene.get("timestamp_end")):
            failed.append("invalid_scene_timestamps")
        start = timestamp_to_seconds(scene.get("timestamp_start"))
        end = timestamp_to_seconds(scene.get("timestamp_end"))
        if start is not None and end is not None and end < start:
            failed.append("scene_end_before_start")
        refs = set(scene.get("evidence_chunk_refs", []))
        if not refs:
            failed.append("missing_evidence_chunk_refs")
        if refs and not refs.issubset(chunk_ids):
            failed.append("references_unknown_evidence_chunks")
        if scene.get("knowledge_extraction_strategy") not in ALLOWED_KNOWLEDGE_STRATEGIES:
            failed.append("invalid_knowledge_extraction_strategy")
        if not scene.get("primary_intent"):
            failed.append("missing_primary_intent")
        if scene.get("validation_status") != "needs_review":
            failed.append("invalid_validation_status")
        return failed


class SourceArtifactBuilder:
    def build(self, video_id: str, aligned_segments: list[dict[str, Any]], evidence_chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        chunk_by_segment_id = {
            segment_id: chunk
            for chunk in evidence_chunks
            for segment_id in chunk.get("transcript_segment_ids", [])
        }
        artifacts: dict[str, dict[str, Any]] = {}
        for segment in aligned_segments:
            chunk = chunk_by_segment_id.get(segment.get("segment_id"))
            for frame in segment["frames"]:
                frame_id = frame.get("artifact_id")
                if not frame_id:
                    continue
                ocr_text = unique_strings(
                    [
                        record.get("extracted_text") or record.get("ocr_text") or record.get("text")
                        for record in segment["ocr_records"]
                        if (record.get("frame_artifact_id") or record.get("frame_id")) == frame_id
                        and (record.get("extracted_text") or record.get("ocr_text") or record.get("text"))
                    ]
                )
                visual_summary = self._frame_visual_summary(frame, segment)
                artifact = artifacts.setdefault(
                    frame_id,
                    {
                        "artifact_id": frame_id,
                        "video_id": video_id,
                        "timestamp": frame.get("timestamp", segment.get("timestamp_start")),
                        "artifact_type": self._artifact_type(text_blob(segment.get("transcript_text"), ocr_text, visual_summary)),
                        "frame_path": frame.get("image_path") or frame.get("frame_path") or "",
                        "visible_text": [],
                        "visual_summary": visual_summary,
                        "components_visible": [],
                        "observed_signals": [],
                        "linked_transcript_segment_ids": [],
                        "linked_evidence_chunk_ids": [],
                        "storage_uri": frame.get("storage_uri", ""),
                        "validation_status": "needs_review",
                        "retrieval_text": "",
                    },
                )
                artifact["visible_text"] = unique_strings(artifact["visible_text"] + ocr_text)
                artifact["components_visible"] = unique_strings(
                    artifact["components_visible"] + detect_terms(text_blob(segment.get("transcript_text"), ocr_text, visual_summary), COMPONENT_KEYWORDS)
                )
                artifact["observed_signals"] = unique_strings(
                    artifact["observed_signals"] + observed_signals(text_blob(segment.get("transcript_text"), ocr_text, visual_summary))
                )
                if segment.get("segment_id"):
                    artifact["linked_transcript_segment_ids"] = unique_strings(artifact["linked_transcript_segment_ids"] + [segment["segment_id"]])
                if chunk:
                    artifact["linked_evidence_chunk_ids"] = unique_strings(artifact["linked_evidence_chunk_ids"] + [chunk["chunk_id"]])
                artifact["retrieval_text"] = text_blob(
                    artifact["visual_summary"],
                    artifact["visible_text"],
                    artifact["components_visible"],
                    artifact["observed_signals"],
                )
        return list(artifacts.values())

    def _frame_visual_summary(self, frame: dict[str, Any], segment: dict[str, Any]) -> str:
        summaries = [
            record.get("visual_summary")
            for record in segment["visual_records"]
            if (record.get("frame_artifact_id") or record.get("frame_id")) == frame.get("artifact_id") and record.get("visual_summary")
        ]
        if summaries:
            return " ".join(unique_strings(summaries))
        return f"Frame aligned to transcript segment {segment.get('segment_id')} at {frame.get('timestamp', segment.get('timestamp_start'))}."

    def _artifact_type(self, text: str) -> str:
        lowered = text.lower()
        if "alarm" in lowered:
            return "alarm"
        if "diagram" in lowered or "map" in lowered:
            return "diagram"
        if "dashboard" in lowered:
            return "dashboard"
        if "menu" in lowered:
            return "menu"
        if "workflow" in lowered or "sequence" in lowered:
            return "workflow_visual"
        if any(term in lowered for term in ["screen", "ui", "hmi", "rms", "ignition"]):
            return "ui_screen"
        return "frame"


class LLMRecordExtractor:
    def __init__(self, config_path: Path | None = None, window_seconds: int = DEFAULT_WINDOW_SECONDS, cache_dir: Path | None = None) -> None:
        self.config_path = config_path
        self.window_seconds = min(90, max(30, window_seconds))
        self.cache_dir = cache_dir
        self.llm_status = "not_configured"
        self.llm_error: str | None = None
        self._last_scene_result_from_cache = False

    def extract(
        self,
        video_id: str,
        scenes: list[dict[str, Any]],
        evidence_chunks: list[dict[str, Any]],
        slide_artifacts: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        chunks_by_id = {chunk["chunk_id"]: chunk for chunk in evidence_chunks}
        slides_by_id = {artifact["slide_screen_segment_id"]: artifact for artifact in slide_artifacts if artifact.get("slide_screen_segment_id")}
        extracted = {"operational_knowledge_units": [], "procedure_candidate_attempts": []}
        for index, scene in enumerate(scenes, start=1):
            if self.config_path and self.config_path.exists():
                print(f"LLM extracting scene {index}/{len(scenes)}: {scene.get('scene_id')}", flush=True)
            scene_chunks = [chunks_by_id[chunk_id] for chunk_id in scene.get("evidence_chunk_refs", []) if chunk_id in chunks_by_id]
            scene_slides = [slides_by_id[slide_id] for slide_id in scene.get("slide_screen_segment_refs", []) if slide_id in slides_by_id]
            if not self._should_extract_scene(scene, scene_chunks, scene_slides):
                self._last_scene_result_from_cache = True
                scene_result = self._empty_extraction()
            else:
                scene_result = self._cached_or_extract_scene(video_id, scene, scene_chunks, scene_slides)
            scene_result = self._enrich_scene_result_from_sources(scene_result, scene, scene_chunks, scene_slides)
            for key in extracted:
                extracted[key].extend(scene_result.get(key, []))
            if self.config_path and self.config_path.exists() and not self._last_scene_result_from_cache:
                delay = float(read_json(self.config_path).get("request_delay_seconds", 0))
                if delay > 0:
                    time.sleep(delay)
        return {
            "operational_knowledge_units": self._dedupe(extracted["operational_knowledge_units"], "title"),
            "procedure_candidate_attempts": self._dedupe(extracted["procedure_candidate_attempts"], "title"),
        }

    def _cached_or_extract_scene(
        self,
        video_id: str,
        scene: dict[str, Any],
        chunks: list[dict[str, Any]],
        slide_artifacts: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        if self.config_path and self.config_path.exists() and self.cache_dir:
            config = llm_stage_config(read_json(self.config_path), "knowledge_extractor")
            cache_path = self._cache_path(config, scene)
            if cache_path.exists():
                cached = read_json(cache_path)
                if self._valid_extraction_payload(cached):
                    self.llm_status = "openai" if str(config.get("provider", "openai")).lower() == "openai" else "azure_openai"
                    self._last_scene_result_from_cache = True
                    return cached
            result = self._extract_scene(video_id, scene, chunks, slide_artifacts)
            if not self._valid_extraction_payload(result):
                raise VideoStructuringError(f"LLM knowledge extraction returned an invalid response for {scene.get('scene_id')}")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            self._last_scene_result_from_cache = False
            return result
        self._last_scene_result_from_cache = False
        return self._extract_scene(video_id, scene, chunks, slide_artifacts)

    def _cache_path(self, config: dict[str, Any], scene: dict[str, Any]) -> Path:
        model = clean_id(str(config.get("model") or config.get("deployment") or "unknown_model"))
        cache_id = f"{clean_id(str(scene['scene_id']))}_{stable_hash(scene)[:12]}"
        return (self.cache_dir or Path()) / "knowledge_extraction" / model / PROMPT_VERSION / f"{cache_id}.json"

    def _valid_extraction_payload(self, payload: Any) -> bool:
        return isinstance(payload, dict) and "operational_knowledge_units" in payload and "procedure_candidate_attempts" in payload

    def _extract_scene(
        self,
        video_id: str,
        scene: dict[str, Any],
        chunks: list[dict[str, Any]],
        slide_artifacts: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        if self.config_path and self.config_path.exists():
            try:
                return self._extract_scene_with_llm(video_id, scene, chunks, slide_artifacts)
            except Exception as exc:
                if not self._allow_local_fallback():
                    raise
                self.llm_status = "fallback_keyword_structuring"
                self.llm_error = str(exc)
        return self._fallback_scene(video_id, scene, chunks, slide_artifacts)

    def _allow_local_fallback(self) -> bool:
        if not self.config_path or not self.config_path.exists():
            return True
        try:
            config = read_json(self.config_path)
        except (OSError, json.JSONDecodeError):
            return False
        return bool(config.get("allow_local_fallback"))

    def _extract_scene_with_llm(
        self,
        video_id: str,
        scene: dict[str, Any],
        chunks: list[dict[str, Any]],
        slide_artifacts: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        config = llm_stage_config(read_json(self.config_path or Path()), "knowledge_extractor")
        client, model, provider = self._llm_client(config)
        packet = {
            "task": "scene_level_phase0_video_structuring",
            "video_id": video_id,
            "important_correction": (
                "The prior window-based extraction design is invalid. Do not infer broad topic records or procedures from keywords. "
                "The only valid flow is aligned chunks to operational scenes to operational knowledge units to strict validators."
            ),
            "scene": scene,
            "slide_screen_segments": [self._compact_slide_segment(artifact) for artifact in slide_artifacts],
            "rules": [
                "Return only JSON.",
                "Training videos must not produce workflow candidates.",
                "All records must remain validation_status needs_review.",
                "Return empty arrays when the scene lacks clear operational knowledge.",
                "Return at most 2 operational knowledge units per scene.",
                "Return at most 1 procedure candidate per scene.",
                "Keep summaries under 60 words and retrieval_text under 300 characters.",
                "Use at most 3 observed_evidence strings per knowledge unit.",
                "Use at most 3 relationships per knowledge unit.",
                f"unit_type must be exactly one of: {', '.join(sorted(ALLOWED_UNIT_TYPES))}.",
                "Do not infer support_safe unless explicit; use unknown otherwise.",
                "Create bounded operational knowledge units, not component buckets.",
                "Do not create broad records like AGV training video reference or RMS training video reference.",
                "Concept explanations may create operational knowledge units but not procedures.",
                "Architecture or process overview is not a procedure.",
                "Slide OCR alone is not enough to create a procedure.",
                "A vague action is not a step.",
                "Most scenes should output zero procedures.",
                "Preserve timestamps, source refs, artifact refs, and evidence chunk refs.",
            ],
            "scene_evidence_chunks": [self._compact_evidence_chunk(chunk) for chunk in chunks],
            "required_keys": ["operational_knowledge_units", "procedure_candidate_attempts"],
            "compact_output_contract": {
                "operational_knowledge_units": [
                    "knowledge_unit_id",
                    "source_scene_ids",
                    "source_artifact_ids",
                    "evidence_chunk_refs",
                    "artifact_refs",
                    "timestamp_start",
                    "timestamp_end",
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
                    "source_scene_id",
                    "title",
                    "procedure_type",
                    "systems",
                    "components",
                    "steps",
                    "validation_status",
                ],
            },
        }
        response = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the Phase 0 Video Evidence Structuring Agent. "
                        "Use LLM reasoning to synthesize bounded operational knowledge units from transcript, OCR, visual artifacts, and speaker explanation. "
                        "Draft procedure attempts only for explicit executable action sequences. "
                        "Never draft workflow candidates from training videos. Avoid keyword buckets and broad component records."
                    ),
                },
                {"role": "user", "content": json.dumps(packet, ensure_ascii=False)},
            ],
            **openai_generation_args(config),
        )
        self.llm_status = provider
        content = response.choices[0].message.content or "{}"
        payload = json.loads(content)
        return {
            "operational_knowledge_units": as_list(payload.get("operational_knowledge_units") or payload.get("knowledge_units")),
            "procedure_candidate_attempts": as_list(payload.get("procedure_candidate_attempts") or payload.get("procedure_candidates")),
        }

    def _should_extract_scene(
        self,
        scene: dict[str, Any],
        chunks: list[dict[str, Any]],
        slide_artifacts: list[dict[str, Any]],
    ) -> bool:
        if scene.get("knowledge_extraction_strategy") in {"ignore", "artifact_only"}:
            return False
        transcript_text = text_blob(*[chunk.get("transcript_text") for chunk in chunks])
        meaningful_transcript = self._has_meaningful_text(transcript_text)
        visual_text = text_blob(
            *[text for chunk in chunks for text in chunk.get("ocr_text", [])],
            *[text for artifact in slide_artifacts for text in artifact.get("visible_text", [])],
            *[text for artifact in slide_artifacts for text in artifact.get("ocr_text", [])],
        )
        operational_refs = any(
            chunk.get("systems") or chunk.get("components") or chunk.get("observed_signals")
            for chunk in chunks
        )
        return meaningful_transcript or self._has_meaningful_text(visual_text) or operational_refs

    def _has_meaningful_text(self, value: str) -> bool:
        normalized = re.sub(r"\W+", "", value or "").lower()
        return bool(normalized and normalized not in {"none", "na", "null", "empty"})

    def _empty_extraction(self) -> dict[str, list[dict[str, Any]]]:
        return {"operational_knowledge_units": [], "procedure_candidate_attempts": []}

    def _enrich_scene_result_from_sources(
        self,
        scene_result: dict[str, list[dict[str, Any]]],
        scene: dict[str, Any],
        chunks: list[dict[str, Any]],
        slide_artifacts: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        chunk_refs = unique_strings([chunk.get("chunk_id") for chunk in chunks])
        artifact_refs = unique_strings(
            [artifact_id for chunk in chunks for artifact_id in chunk.get("artifact_ids", [])]
            + [artifact.get("representative_frame_ref") for artifact in slide_artifacts if artifact.get("representative_frame_ref")]
        )
        source_refs = unique_values([ref for chunk in chunks for ref in chunk.get("source_refs", [])])
        for unit in scene_result.get("operational_knowledge_units", []):
            unit["source_scene_ids"] = unique_strings(as_list(unit.get("source_scene_ids")) or [scene.get("scene_id")])
            unit["evidence_chunk_refs"] = unique_strings(as_list(unit.get("evidence_chunk_refs")) or chunk_refs)
            unit["artifact_refs"] = unique_strings(as_list(unit.get("artifact_refs")) or artifact_refs)
            unit["source_refs"] = unique_values(as_list(unit.get("source_refs")) or source_refs)
            unit["timestamp_start"] = unit.get("timestamp_start") or scene.get("timestamp_start")
            unit["timestamp_end"] = unit.get("timestamp_end") or scene.get("timestamp_end")
            unit["validation_status"] = "needs_review"
        for attempt in scene_result.get("procedure_candidate_attempts", []):
            attempt["source_scene_id"] = attempt.get("source_scene_id") or scene.get("scene_id")
            attempt["validation_status"] = "needs_review"
        return scene_result

    def _compact_evidence_chunk(self, chunk: dict[str, Any]) -> dict[str, Any]:
        return {
            "chunk_id": chunk.get("chunk_id"),
            "timestamp_start": chunk.get("timestamp_start"),
            "timestamp_end": chunk.get("timestamp_end"),
            "transcript_segment_ids": chunk.get("transcript_segment_ids", []),
            "speaker": chunk.get("speaker") or first_value(chunk.get("speaker_candidates")) or "unknown",
            "transcript_text": chunk.get("transcript_text", ""),
            "ocr_text": unique_strings(chunk.get("ocr_text", []))[:12],
            "visual_summary": truncate_text(chunk.get("visual_summary"), 600),
            "artifact_ids": chunk.get("artifact_ids", []),
            "systems": chunk.get("systems", []),
            "components": chunk.get("components", []),
            "observed_signals": chunk.get("observed_signals", []),
        }

    def _compact_slide_segment(self, artifact: dict[str, Any]) -> dict[str, Any]:
        return {
            "slide_screen_segment_id": artifact.get("slide_screen_segment_id"),
            "timestamp_start": artifact.get("timestamp_start"),
            "timestamp_end": artifact.get("timestamp_end"),
            "representative_frame_ref": artifact.get("representative_frame_ref"),
            "slide_title": artifact.get("slide_title", ""),
            "visible_text": unique_strings(artifact.get("visible_text", []))[:20],
            "ocr_text": unique_strings(artifact.get("ocr_text", []))[:20],
            "visual_summary": truncate_text(artifact.get("visual_summary"), 600),
            "visual_elements": artifact.get("visual_elements", []),
            "linked_transcript_segment_ids": artifact.get("linked_transcript_segment_ids", []),
        }

    def _llm_client(self, config: dict[str, Any]) -> tuple[Any, str, str]:
        provider = str(config.get("provider") or ("azure_openai" if config.get("endpoint") else "openai")).lower()
        if provider == "openai":
            from openai import OpenAI

            required = ["api_key", "model"]
            missing = [field_name for field_name in required if not config.get(field_name)]
            if missing:
                raise VideoStructuringError(f"OpenAI config missing required fields for this LLM stage: {', '.join(missing)}")
            if str(config.get("api_key")).startswith("PASTE_"):
                raise VideoStructuringError("OpenAI config still contains the placeholder API key.")
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
                raise VideoStructuringError(f"Azure OpenAI config missing required fields: {', '.join(missing)}")
            client = AzureOpenAI(
                azure_endpoint=config["endpoint"],
                api_key=config["api_key"],
                api_version=config["api_version"],
                timeout=float(config.get("request_timeout_seconds", 180)),
                max_retries=int(config.get("max_retries", 2)),
            )
            return client, config["deployment"], "azure_openai"
        raise VideoStructuringError(f"Unsupported LLM provider: {provider}")

    def _fallback_scene(
        self,
        video_id: str,
        scene: dict[str, Any],
        chunks: list[dict[str, Any]],
        slide_artifacts: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        if self.llm_status == "not_configured":
            self.llm_status = "fallback_keyword_structuring"
        knowledge_units = self._fallback_knowledge_units(video_id, scene, chunks, slide_artifacts)
        procedure_candidates = self._fallback_procedures(video_id, scene, chunks)
        return {
            "operational_knowledge_units": knowledge_units,
            "procedure_candidate_attempts": procedure_candidates,
        }

    def _fallback_knowledge_units(
        self,
        video_id: str,
        scene: dict[str, Any],
        chunks: list[dict[str, Any]],
        slide_artifacts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not scene.get("extraction_eligibility", {}).get("context_candidate_allowed"):
            return []
        if scene.get("scene_type") in {"filler", "unknown"}:
            return []
        transcript_evidence = [chunk.get("transcript_text") for chunk in chunks if chunk.get("transcript_text")]
        if not transcript_evidence and not slide_artifacts:
            return []
        title_seed = scene.get("scene_summary") or scene.get("scene_title") or "Operational training evidence"
        title = self._bounded_title(title_seed)
        slide_text = unique_strings([text for artifact in slide_artifacts for text in artifact.get("visible_text", [])])
        return [
            {
                "knowledge_unit_id": f"ku_{video_id}_{clean_id(scene['scene_id'])}",
                "video_id": video_id,
                "source_scene_ids": [scene["scene_id"]],
                "source_artifact_ids": unique_strings([artifact["slide_screen_segment_id"] for artifact in slide_artifacts]),
                "timestamp_start": scene.get("timestamp_start"),
                "timestamp_end": scene.get("timestamp_end"),
                "unit_type": self._fallback_unit_type(scene),
                "title": title,
                "systems": scene.get("systems", []),
                "components": scene.get("components", []),
                "operational_problem_area": "",
                "summary": scene.get("scene_summary") or title,
                "observed_evidence": transcript_evidence[:5],
                "speaker_explanation": text_blob(*transcript_evidence[:5]),
                "slide_text_evidence": slide_text,
                "visual_evidence_summary": text_blob(*[artifact.get("visual_summary") for artifact in slide_artifacts]),
                "relationships": [],
                "evidence_chunk_refs": scene.get("evidence_chunk_refs", []),
                "artifact_refs": scene.get("artifact_refs", []),
                "source_refs": unique_values([ref for chunk in chunks for ref in chunk.get("source_refs", [])]),
                "retrieval_text": text_blob(title, transcript_evidence[:5], slide_text),
                "validation_status": "needs_review",
            }
        ]

    def _bounded_title(self, value: str) -> str:
        title = re.sub(r"\s+", " ", value).strip(" .")
        if len(title) > 90:
            title = title[:87].rstrip() + "..."
        if BROAD_TOPIC_TITLE_PATTERN.match(title):
            title = f"Operational concept from {title}"
        return title or "Operational knowledge unit"

    def _fallback_unit_type(self, scene: dict[str, Any]) -> str:
        intent = scene.get("primary_intent")
        if intent == "ui_walkthrough":
            return "ui_concept"
        if intent == "system_architecture":
            return "architecture_relationship"
        if intent == "operational_behavior":
            return "operational_process"
        if intent in PROCEDURE_ELIGIBLE_INTENTS:
            return "operational_process"
        return "system_behavior"

    def _fallback_procedures(self, video_id: str, scene: dict[str, Any], chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not scene.get("extraction_eligibility", {}).get("procedure_candidate_allowed"):
            return []
        action_chunks = [chunk for chunk in chunks if any(term in chunk.get("transcript_text", "").lower() for term in ACTION_TERMS)]
        scene_text = text_blob(*[chunk.get("transcript_text") for chunk in chunks]).lower()
        if len(action_chunks) < 1 or not any(term in scene_text for term in ACTION_TERMS):
            return []
        selected = action_chunks[:6] if action_chunks else chunks[:3]
        steps = [
            {
                "step_order": index,
                "instruction": chunk.get("transcript_text") or chunk.get("visual_summary") or "Review aligned video evidence.",
                "timestamp_start": chunk.get("timestamp_start", ""),
                "timestamp_end": chunk.get("timestamp_end", ""),
                "expected_outcome": "Expected UI or operational state is visible in the aligned evidence.",
                "validation_check": "Review the linked frame and transcript evidence for this action.",
                "artifact_refs": chunk.get("artifact_ids", []),
                "evidence_chunk_refs": [chunk["chunk_id"]],
            }
            for index, chunk in enumerate(selected, start=1)
        ]
        components = unique_strings([component for chunk in selected for component in chunk.get("components", [])])
        systems = unique_strings([system for chunk in selected for system in chunk.get("systems", [])])
        return [
            {
                "procedure_id": f"proc_{video_id}_{clean_id(scene['scene_id'])}",
                "source_scene_id": scene["scene_id"],
                "title": f"Candidate procedure from {scene.get('scene_title')}",
                "procedure_type": self._procedure_type(selected),
                "components": components,
                "systems": systems,
                "role_required": "unknown",
                "support_safe": "unknown",
                "steps": steps,
                "source_video": video_id,
                "source_refs": unique_values([ref for chunk in selected for ref in chunk.get("source_refs", [])]),
                "retrieval_text": text_blob([step["instruction"] for step in steps], components, systems),
            }
        ]

    def _procedure_type(self, chunks: list[dict[str, Any]]) -> str:
        text = text_blob(*[chunk.get("transcript_text") for chunk in chunks]).lower()
        if any(term in text for term in ["navigate", "go to", "open", "select", "click"]):
            return "navigation"
        if any(term in text for term in ["check", "verify", "look at"]):
            return "diagnostic_check"
        if any(term in text for term in ["restart", "start", "stop", "enable", "disable", "remove", "add"]):
            return "operational_action"
        return "unknown"

    def _dedupe(self, records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
        deduped: dict[str, dict[str, Any]] = {}
        for record in records:
            value = clean_id(str(record.get(key) or record.get("context_id") or record.get("procedure_id")))
            if value not in deduped:
                deduped[value] = record
                continue
            existing = deduped[value]
            for list_key in ["source_refs", "artifact_refs", "evidence_chunk_refs", "observed_evidence"]:
                existing[list_key] = unique_values(as_list(existing.get(list_key)) + as_list(record.get(list_key)))
        return list(deduped.values())


class OperationalKnowledgeExtractor(LLMRecordExtractor):
    pass


class OperationalKnowledgeUnitValidator:
    def validate(self, units: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        accepted = []
        discarded = []
        for unit in units:
            unit = self._with_normalized_unit_type(unit)
            failed_rules = self._failed_rules(unit)
            if failed_rules:
                discarded.append(
                    {
                        "candidate_id": unit.get("knowledge_unit_id"),
                        "candidate_type": "operational_knowledge_unit",
                        "source_scene_id": first_value(unit.get("source_scene_ids")),
                        "discard_reasons": [rule.replace("_", " ") for rule in failed_rules],
                        "failed_rules": failed_rules,
                        "original_candidate_summary": unit.get("title") or unit.get("summary") or "",
                        "timestamp_start": unit.get("timestamp_start", ""),
                        "timestamp_end": unit.get("timestamp_end", ""),
                    }
                )
            else:
                accepted.append(self._normalized(unit))
        return accepted, discarded

    def _failed_rules(self, unit: dict[str, Any]) -> list[str]:
        failed = []
        title = str(unit.get("title") or "").strip()
        if not title:
            failed.append("missing_title")
        if BROAD_TOPIC_TITLE_PATTERN.match(title):
            failed.append("broad_component_bucket_title")
        if len(title.split()) <= 1:
            failed.append("component_only_title")
        if unit.get("unit_type") not in ALLOWED_UNIT_TYPES:
            failed.append("invalid_unit_type")
        if not unit.get("summary"):
            failed.append("missing_summary")
        if not unit.get("observed_evidence") and not unit.get("slide_text_evidence"):
            failed.append("missing_observed_or_slide_evidence")
        if not unit.get("source_scene_ids"):
            failed.append("missing_source_scene")
        if not unit.get("evidence_chunk_refs") and not unit.get("source_artifact_ids"):
            failed.append("missing_traceable_evidence_refs")
        if not valid_timestamp(unit.get("timestamp_start")) or not valid_timestamp(unit.get("timestamp_end")):
            failed.append("missing_or_invalid_timestamps")
        if not unit.get("retrieval_text"):
            failed.append("missing_retrieval_text")
        return unique_strings(failed)

    def _normalized(self, unit: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(unit)
        normalized["validation_status"] = "needs_review"
        normalized["relationships"] = as_list(normalized.get("relationships"))
        normalized["observed_evidence"] = as_list(normalized.get("observed_evidence"))
        normalized["slide_text_evidence"] = as_list(normalized.get("slide_text_evidence"))
        normalized["source_scene_ids"] = unique_strings(as_list(normalized.get("source_scene_ids")))
        normalized["source_artifact_ids"] = unique_strings(as_list(normalized.get("source_artifact_ids")))
        normalized["evidence_chunk_refs"] = unique_strings(as_list(normalized.get("evidence_chunk_refs")))
        normalized["artifact_refs"] = unique_strings(as_list(normalized.get("artifact_refs")))
        return normalized

    def _with_normalized_unit_type(self, unit: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(unit)
        unit_type = str(normalized.get("unit_type") or "").strip()
        replacements = {
            "concept": "system_behavior",
            "concept_explanation": "system_behavior",
            "policy": "system_behavior",
            "operational_expectation": "system_behavior",
            "diagnostic_guideline": "diagnostic_concept",
        }
        if unit_type in replacements:
            normalized["unit_type"] = replacements[unit_type]
        return normalized


def first_value(values: Any) -> Any:
    values = as_list(values)
    return values[0] if values else ""


class ContextRecordBuilder:
    def build(self, video_id: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        built = []
        for index, record in enumerate(records, start=1):
            context_type = self._context_type(record)
            context_id = record.get("context_id") or f"ctx_{video_id}_{clean_id(record.get('knowledge_unit_id') or str(index))}"
            built.append(
                {
                    "context_id": context_id,
                    "container_id": "phase0_context_reference",
                    "source_video": video_id,
                    "context_type": context_type,
                    "title": record.get("title") or f"Video context candidate {index}",
                    "applies_to": unique_strings(as_list(record.get("systems")) + as_list(record.get("components"))),
                    "source_refs": as_list(record.get("source_refs")),
                    "artifact_refs": unique_strings(as_list(record.get("artifact_refs")) + as_list(record.get("source_artifact_ids"))),
                    "evidence_chunk_refs": unique_strings(as_list(record.get("evidence_chunk_refs"))),
                    "source_authority": "training_video",
                    "summary": record.get("summary") or "",
                    "observed_evidence": as_list(record.get("observed_evidence")),
                    "inferred_interpretations": as_list(record.get("inferred_interpretations")),
                    "validation_status": "needs_review",
                    "retrieval_text": record.get("retrieval_text") or text_blob(record.get("title"), record.get("summary"), record.get("observed_evidence")),
                }
            )
        return built

    def _context_type(self, unit: dict[str, Any]) -> str:
        unit_type = unit.get("unit_type")
        if unit_type == "glossary_definition":
            return "glossary"
        if unit_type in {"architecture_relationship", "system_behavior"}:
            return "product_behavior"
        if unit_type == "ui_concept":
            return "ui_reference"
        if unit_type in {"operational_process", "state_transition", "routing_rule", "queueing_rule", "diagnostic_concept"}:
            return "operational_concept"
        return "operational_concept"


class ProcedureCandidateBuilder:
    def build(self, video_id: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        built = []
        for index, record in enumerate(records, start=1):
            procedure_type = record.get("procedure_type") if record.get("procedure_type") in ALLOWED_PROCEDURE_TYPES else "unknown"
            role_required = record.get("role_required") if record.get("role_required") in ALLOWED_ROLES else "unknown"
            support_safe = record.get("support_safe") if record.get("support_safe") in {"yes", "no", "unknown"} else "unknown"
            steps = self._steps(record.get("steps"))
            built.append(
                {
                    "procedure_id": record.get("procedure_id") or f"proc_{video_id}_{index:06d}",
                    "source_scene_id": record.get("source_scene_id"),
                    "title": record.get("title") or f"Video procedure candidate {index}",
                    "procedure_type": procedure_type,
                    "components": unique_strings(as_list(record.get("components"))),
                    "systems": unique_strings(as_list(record.get("systems"))),
                    "role_required": role_required,
                    "support_safe": support_safe,
                    "steps": steps,
                    "source_video": record.get("source_video") or video_id,
                    "source_refs": as_list(record.get("source_refs")),
                    "validation_status": "needs_review",
                    "retrieval_text": record.get("retrieval_text") or text_blob(record.get("title"), [step.get("instruction") for step in steps]),
                }
            )
        return [record for record in built if record["steps"]]

    def _steps(self, raw_steps: Any) -> list[dict[str, Any]]:
        steps = []
        for index, step in enumerate(as_list(raw_steps), start=1):
            if not isinstance(step, dict):
                step = {"instruction": str(step)}
            steps.append(
                {
                    "step_order": int(step.get("step_order") or index),
                    "instruction": step.get("instruction") or "",
                    "timestamp_start": step.get("timestamp_start") or "",
                    "timestamp_end": step.get("timestamp_end") or "",
                    "expected_outcome": step.get("expected_outcome") or "",
                    "validation_check": step.get("validation_check") or "",
                    "artifact_refs": unique_strings(as_list(step.get("artifact_refs"))),
                    "evidence_chunk_refs": unique_strings(as_list(step.get("evidence_chunk_refs"))),
                }
            )
        return steps


class ProcedureQualityValidator:
    def validate(
        self,
        candidates: list[dict[str, Any]],
        scenes: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        scenes_by_id = {scene["scene_id"]: scene for scene in scenes}
        accepted = []
        discarded = []
        for candidate in candidates:
            scene = scenes_by_id.get(candidate.get("source_scene_id"), {})
            failed_rules = self._failed_rules(candidate, scene)
            if failed_rules:
                discarded.append(self._discard_record(candidate, scene, failed_rules))
            else:
                accepted.append(candidate)
        return accepted, discarded

    def _failed_rules(self, candidate: dict[str, Any], scene: dict[str, Any]) -> list[str]:
        failed = []
        scene_type = scene.get("scene_type")
        primary_intent = scene.get("primary_intent")
        steps = candidate.get("steps", [])
        if primary_intent not in PROCEDURE_ELIGIBLE_INTENTS and scene_type not in {"reusable_procedure", "ui_walkthrough"}:
            failed.append("scene_type_not_procedure_eligible")
        if primary_intent not in PROCEDURE_ELIGIBLE_INTENTS:
            failed.append("scene_intent_not_procedure_eligible")
        if self._title_is_component_only(candidate.get("title", "")):
            failed.append("title_is_component_only")
        if scene_type == "ui_walkthrough" and not self._has_explicit_action_sequence(candidate):
            failed.append("ui_walkthrough_missing_explicit_action_sequence")
        if not steps:
            failed.append("missing_steps")
            return failed
        concrete_steps = [step for step in steps if self._is_concrete_step(step)]
        if len(concrete_steps) < 2 and not self._has_atomic_ui_action(concrete_steps):
            failed.append("insufficient_concrete_ordered_actions")
        if any(not valid_timestamp(step.get("timestamp_start")) or not valid_timestamp(step.get("timestamp_end")) for step in steps):
            failed.append("missing_step_timestamps")
        if any(not step.get("artifact_refs") or not step.get("evidence_chunk_refs") for step in steps):
            failed.append("missing_step_evidence_refs")
        if not candidate.get("components") and not candidate.get("systems"):
            failed.append("missing_target_system_or_component")
        if all(not step.get("expected_outcome") and not step.get("validation_check") for step in steps):
            failed.append("missing_expected_outcome_or_validation_check")
        if any(self._is_vague_or_incomplete(step.get("instruction", "")) for step in steps):
            failed.append("vague_or_incomplete_step")
        if any(self._is_descriptive_narration(step.get("instruction", "")) for step in steps):
            failed.append("step_is_descriptive_narration")
        if not any(step.get("expected_outcome") for step in steps):
            failed.append("step_has_no_state_change")
        if not any(step.get("validation_check") for step in steps):
            failed.append("step_has_no_validation_result")
        return unique_strings(failed)

    def _has_explicit_action_sequence(self, candidate: dict[str, Any]) -> bool:
        text = text_blob(*[step.get("instruction") for step in candidate.get("steps", [])]).lower()
        return sum(1 for term in ACTION_TERMS if term in text) >= 2 or any(term in text for term in ORDER_TERMS)

    def _has_atomic_ui_action(self, steps: list[dict[str, Any]]) -> bool:
        if len(steps) != 1:
            return False
        step = steps[0]
        text = step.get("instruction", "").lower()
        return any(term in text for term in ACTION_TERMS) and bool(step.get("expected_outcome") or step.get("validation_check"))

    def _is_concrete_step(self, step: dict[str, Any]) -> bool:
        text = step.get("instruction", "").lower()
        return bool(text) and any(term in text for term in ACTION_TERMS)

    def _is_vague_or_incomplete(self, instruction: str) -> bool:
        text = instruction.strip().lower()
        if len(text.split()) < 3:
            return True
        if any(value in text for value in VAGUE_PROCEDURE_TEXT):
            return True
        return text.endswith((" and", " or", " to", " the", " a", " an"))

    def _is_descriptive_narration(self, instruction: str) -> bool:
        text = instruction.strip().lower()
        if not any(term in text for term in ACTION_TERMS):
            return True
        return text.startswith(("so we have", "this is", "these are", "all agvs", "the system", "it will"))

    def _title_is_component_only(self, title: str) -> bool:
        return bool(BROAD_TOPIC_TITLE_PATTERN.match(title.strip()))

    def _discard_record(self, candidate: dict[str, Any], scene: dict[str, Any], failed_rules: list[str]) -> dict[str, Any]:
        return {
            "candidate_id": candidate.get("procedure_id"),
            "candidate_type": "procedure",
            "source_scene_id": candidate.get("source_scene_id"),
            "discard_reasons": [rule.replace("_", " ") for rule in failed_rules],
            "failed_rules": failed_rules,
            "original_candidate_summary": candidate.get("title") or text_blob(*[step.get("instruction") for step in candidate.get("steps", [])])[:240],
            "timestamp_start": scene.get("timestamp_start") or self._first_step_timestamp(candidate, "timestamp_start"),
            "timestamp_end": scene.get("timestamp_end") or self._first_step_timestamp(candidate, "timestamp_end"),
        }

    def _first_step_timestamp(self, candidate: dict[str, Any], key: str) -> str:
        for step in candidate.get("steps", []):
            if step.get(key):
                return step[key]
        return ""


class LegacyOutputDetector:
    def detect(self, review_dir: Path) -> list[dict[str, Any]]:
        legacy_outputs = []
        for file_name, output_type in [
            ("procedure_dictionary_candidates.json", "procedure"),
            ("workflow_evidence_candidates.json", "workflow"),
        ]:
            path = review_dir / file_name
            if not path.exists():
                continue
            try:
                records = read_json(path)
            except (OSError, json.JSONDecodeError):
                records = []
            invalid_ids = []
            for record in as_list(records):
                record_id = str(record.get("procedure_id") or record.get("workflow_candidate_id") or "")
                if LEGACY_WINDOW_PATTERN.search(record_id):
                    invalid_ids.append(record_id)
            if invalid_ids or output_type == "workflow":
                legacy_outputs.append(
                    {
                        "path": str(path),
                        "output_type": output_type,
                        "legacy_status": "legacy_invalid",
                        "invalid_record_ids": invalid_ids,
                        "reason": "window_based_video_outputs_are_invalid_for_scene_first_structuring",
                    }
                )
        return legacy_outputs


class ValidationReporter:
    def build_report(
        self,
        bundle: EvidenceBundle,
        operational_scenes: list[dict[str, Any]],
        slide_artifacts: list[dict[str, Any]],
        operational_knowledge_units: list[dict[str, Any]],
        evidence_chunks: list[dict[str, Any]],
        source_artifacts: list[dict[str, Any]],
        context_candidates: list[dict[str, Any]],
        procedure_candidates: list[dict[str, Any]],
        discard_report: list[dict[str, Any]],
        legacy_invalid_outputs: list[dict[str, Any]],
        warnings: list[str],
    ) -> dict[str, Any]:
        artifact_ids = {artifact["artifact_id"] for artifact in source_artifacts}
        artifact_ids.update({artifact["slide_screen_segment_id"] for artifact in slide_artifacts if artifact.get("slide_screen_segment_id")})
        chunk_ids = {chunk["chunk_id"] for chunk in evidence_chunks}
        all_records = evidence_chunks + source_artifacts + slide_artifacts + operational_scenes + operational_knowledge_units + context_candidates + procedure_candidates
        missing_timestamps = self._records_with_missing_timestamps(all_records)
        weak_evidence = self._records_with_weak_evidence(context_candidates, procedure_candidates, artifact_ids, chunk_ids)
        inferred = [self._record_id(record) for record in all_records if record.get("inferred_interpretations")]
        approved = [self._record_id(record) for record in all_records if record.get("validation_status") == "approved"]
        validation_warnings = warnings + self._reference_warnings(context_candidates, procedure_candidates, artifact_ids, chunk_ids)
        if approved:
            validation_warnings.append("Approved records are not allowed in video structuring output.")
        return {
            "video_id": bundle.video_id,
            "structured_at": utc_now(),
            "total_transcript_segments_processed": len(bundle.transcript_segments),
            "total_frames_processed": len(bundle.frame_artifacts),
            "total_ocr_records_processed": len(bundle.ocr_records),
            "total_evidence_chunks_created": len(evidence_chunks),
            "total_source_artifacts_created": len(source_artifacts),
            "total_slide_screen_segments_created": len(slide_artifacts),
            "total_operational_scenes_created": len(operational_scenes),
            "total_operational_knowledge_units_created": len(operational_knowledge_units),
            "total_scenes_with_speaker_candidates": sum(1 for scene in operational_scenes if scene.get("speaker_candidates")),
            "total_context_candidates_created": len(context_candidates),
            "total_procedure_candidates_created": len(procedure_candidates),
            "total_procedure_candidates_discarded": len(discard_report),
            "legacy_invalid_outputs_detected": len(legacy_invalid_outputs),
            "legacy_invalid_outputs_marked": len(legacy_invalid_outputs),
            "legacy_review_mode_enabled": False,
            "warnings": validation_warnings,
            "records_needing_review": [self._record_id(record) for record in all_records if record.get("validation_status") == "needs_review"],
            "records_with_missing_timestamps": missing_timestamps,
            "records_with_weak_evidence": weak_evidence,
            "records_with_inferred_interpretations": inferred,
            "discarded_candidate_ids": [record["candidate_id"] for record in discard_report],
            "production_context_write_ran": False,
        }

    def _records_with_missing_timestamps(self, records: list[dict[str, Any]]) -> list[str]:
        missing = []
        for record in records:
            timestamp_values = []
            if record.get("timestamp"):
                timestamp_values.append(record.get("timestamp"))
            if record.get("timestamp_start"):
                timestamp_values.append(record.get("timestamp_start"))
            if record.get("timestamp_end"):
                timestamp_values.append(record.get("timestamp_end"))
            if record.get("timestamps"):
                timestamp_values.extend(record.get("timestamps"))
            if timestamp_values and not all(valid_timestamp(value) for value in timestamp_values if value):
                missing.append(self._record_id(record))
            if not timestamp_values and not record.get("source_refs"):
                missing.append(self._record_id(record))
        return missing

    def _records_with_weak_evidence(
        self,
        context_candidates: list[dict[str, Any]],
        procedure_candidates: list[dict[str, Any]],
        artifact_ids: set[str],
        chunk_ids: set[str],
    ) -> list[str]:
        weak = []
        for record in context_candidates:
            if not set(record.get("artifact_refs", [])).intersection(artifact_ids) and not set(record.get("evidence_chunk_refs", [])).intersection(chunk_ids):
                weak.append(self._record_id(record))
        for record in procedure_candidates:
            if not record.get("steps"):
                weak.append(self._record_id(record))
        return weak

    def _reference_warnings(
        self,
        context_candidates: list[dict[str, Any]],
        procedure_candidates: list[dict[str, Any]],
        artifact_ids: set[str],
        chunk_ids: set[str],
    ) -> list[str]:
        warnings = []
        records = context_candidates + procedure_candidates
        for record in records:
            if not (record.get("video_id") or record.get("source_video")):
                warnings.append(f"{self._record_id(record)} is missing video_id/source_video")
            if not record.get("source_refs"):
                warnings.append(f"{self._record_id(record)} is missing source_refs")
            for artifact_ref in record.get("artifact_refs", []):
                if artifact_ref not in artifact_ids:
                    warnings.append(f"{self._record_id(record)} references missing artifact {artifact_ref}")
            for chunk_ref in record.get("evidence_chunk_refs", []):
                if chunk_ref not in chunk_ids:
                    warnings.append(f"{self._record_id(record)} references missing evidence chunk {chunk_ref}")
            if "retrieval_text" in record and not record.get("retrieval_text"):
                warnings.append(f"{self._record_id(record)} has empty retrieval_text")
        return warnings

    def _record_id(self, record: dict[str, Any]) -> str:
        for key in ["chunk_id", "artifact_id", "scene_id", "context_id", "procedure_id"]:
            if record.get(key):
                return str(record[key])
        return "unknown_record"


class VideoEvidenceStructuringAgent:
    def __init__(
        self,
        video_id: str,
        input_dir: Path,
        output_dir: Path,
        review_dir: Path,
        mode: str = "full",
        llm_config: Path | None = None,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
        allow_local_fallback: bool = False,
        force: bool = False,
    ) -> None:
        self.video_id = clean_id(video_id)
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.review_dir = review_dir
        self.mode = mode
        self.llm_config = llm_config
        self.window_seconds = window_seconds
        self.allow_local_fallback = allow_local_fallback
        self.force = force

    def run(self) -> dict[str, Any]:
        self._guard_output_paths()
        legacy_invalid_outputs = LegacyOutputDetector().detect(self.review_dir)
        bundle = EvidenceBundleLoader(self.video_id, self.input_dir).load()
        bundle.video_id = self.video_id
        aligned_segments = TranscriptVisualAligner(bundle).aligned_segments()
        evidence_chunks = EvidenceChunkBuilder().build(self.video_id, aligned_segments)
        evidence_chunks = TeamsSpeakerAttributionExtractor().enrich(evidence_chunks, aligned_segments)
        slide_artifacts = SlideScreenSegmentBuilder().build(self.video_id, aligned_segments)
        scene_planner = LLMOperationalScenePlanner(self.llm_config, self.review_dir / "_cache", self.allow_local_fallback)
        try:
            operational_scenes = scene_planner.plan(self.video_id, evidence_chunks, slide_artifacts)
            operational_scenes = ScenePlanValidator().validate(operational_scenes, evidence_chunks)
        except Exception as exc:
            self._write_failed_scene_planning_report(bundle, evidence_chunks, slide_artifacts, exc)
            raise
        source_artifacts = SourceArtifactBuilder().build(self.video_id, aligned_segments, evidence_chunks)
        extractor = OperationalKnowledgeExtractor(self.llm_config, self.window_seconds, self.review_dir / "_cache")
        extracted = extractor.extract(self.video_id, operational_scenes, evidence_chunks, slide_artifacts)
        operational_knowledge_units, knowledge_unit_discards = OperationalKnowledgeUnitValidator().validate(extracted["operational_knowledge_units"])
        context_candidates = ContextRecordBuilder().build(self.video_id, operational_knowledge_units)
        procedure_attempts = ProcedureCandidateBuilder().build(self.video_id, extracted["procedure_candidate_attempts"])
        procedure_candidates, procedure_discards = ProcedureQualityValidator().validate(procedure_attempts, operational_scenes)
        discard_report = knowledge_unit_discards + procedure_discards
        report = ValidationReporter().build_report(
            bundle,
            operational_scenes,
            slide_artifacts,
            operational_knowledge_units,
            evidence_chunks,
            source_artifacts,
            context_candidates,
            procedure_candidates,
            discard_report,
            legacy_invalid_outputs,
            self._warnings(bundle, extractor, scene_planner, legacy_invalid_outputs),
        )
        master_bundle = self._master_bundle(
            bundle,
            operational_scenes,
            slide_artifacts,
            operational_knowledge_units,
            evidence_chunks,
            source_artifacts,
            context_candidates,
            procedure_candidates,
            discard_report,
            legacy_invalid_outputs,
            report,
            extractor,
        )
        manifest = self._promotion_manifest(operational_knowledge_units, context_candidates, procedure_candidates, legacy_invalid_outputs, report)
        self._write_outputs(master_bundle, operational_scenes, slide_artifacts, operational_knowledge_units, evidence_chunks, source_artifacts, context_candidates, procedure_candidates, discard_report, report, manifest)
        return {
            "video_id": self.video_id,
            "output_dir": str(self.output_dir),
            "review_dir": str(self.review_dir),
            "llm_status": extractor.llm_status,
            "scene_planning_status": scene_planner.llm_status,
            "extraction_report": report,
            "guardrails": {
                "dataset0_context_write_ran": False,
                "workflow_candidate_write_ran": False,
                "production_context_path": "data/context/context_reference.json",
            },
        }

    def _guard_output_paths(self) -> None:
        context_path = (ROOT / "data" / "context" / "context_reference.json").resolve()
        context_dir = context_path.parent
        for path in [self.output_dir.resolve(), self.review_dir.resolve()]:
            if path == context_path or path == context_dir or context_dir in path.parents:
                raise VideoStructuringError("Video structuring output cannot target data/context/context_reference.json or its directory")

    def _write_failed_scene_planning_report(
        self,
        bundle: EvidenceBundle,
        evidence_chunks: list[dict[str, Any]],
        slide_artifacts: list[dict[str, Any]],
        exc: Exception,
    ) -> None:
        report = {
            "video_id": self.video_id,
            "structured_at": utc_now(),
            "llm_status": "failed",
            "failed_stage": "llm_operational_scene_planning",
            "warnings": [f"LLM scene planning failed: {exc}"],
            "total_transcript_segments_processed": len(bundle.transcript_segments),
            "total_frames_processed": len(bundle.frame_artifacts),
            "total_ocr_records_processed": len(bundle.ocr_records),
            "total_evidence_chunks_created": len(evidence_chunks),
            "total_slide_screen_segments_created": len(slide_artifacts),
            "authoritative_operational_scenes_written": False,
            "local_fallback_allowed": self.allow_local_fallback,
        }
        write_json(self.output_dir / "extraction_report.json", report, self.force)

    def _warnings(
        self,
        bundle: EvidenceBundle,
        extractor: LLMRecordExtractor,
        scene_planner: LLMOperationalScenePlanner,
        legacy_invalid_outputs: list[dict[str, Any]],
    ) -> list[str]:
        warnings = []
        if not bundle.transcript_segments:
            warnings.append("No transcript segments found in input evidence.")
        if not bundle.frame_artifacts:
            warnings.append("No frame artifacts found in input evidence.")
        if not bundle.ocr_records:
            warnings.append("No OCR records found in input evidence.")
        if scene_planner.llm_status not in {"azure_openai", "openai"}:
            warnings.append(f"LLM scene planning used {scene_planner.llm_status}; authoritative scene planning requires review.")
        if extractor.llm_status not in {"azure_openai", "openai"}:
            warnings.append(f"LLM extraction used {extractor.llm_status}; records require review before promotion.")
        if extractor.llm_error:
            warnings.append(f"LLM fallback reason: {extractor.llm_error}")
        if legacy_invalid_outputs:
            warnings.append("Legacy invalid window-based video candidate outputs were detected and excluded from scene-first promotion.")
        return warnings

    def _master_bundle(
        self,
        bundle: EvidenceBundle,
        operational_scenes: list[dict[str, Any]],
        slide_artifacts: list[dict[str, Any]],
        operational_knowledge_units: list[dict[str, Any]],
        evidence_chunks: list[dict[str, Any]],
        source_artifacts: list[dict[str, Any]],
        context_candidates: list[dict[str, Any]],
        procedure_candidates: list[dict[str, Any]],
        discard_report: list[dict[str, Any]],
        legacy_invalid_outputs: list[dict[str, Any]],
        report: dict[str, Any],
        extractor: LLMRecordExtractor,
    ) -> dict[str, Any]:
        return {
            "video_metadata": bundle.video_metadata | {"video_id": self.video_id},
            "structuring_metadata": {
                "mode": self.mode,
                "structured_at": report["structured_at"],
                "input_dir": str(self.input_dir),
                "output_dir": str(self.output_dir),
                "review_dir": str(self.review_dir),
                "scene_first": True,
                "llm_status": extractor.llm_status,
            },
            "trust_boundary": {
                "raw_extraction_is_trusted_context": False,
                "dataset0_write_allowed": False,
                "validation_status": "needs_review",
            },
            "source_inputs": {
                "transcript_segment_count": len(bundle.transcript_segments),
                "frame_artifact_count": len(bundle.frame_artifacts),
                "ocr_record_count": len(bundle.ocr_records),
                "alignment_record_count": len(bundle.alignment_records),
            },
            "records": {
                "transcript_aligned_evidence_chunks": evidence_chunks,
                "operational_scenes": operational_scenes,
                "slide_screen_segments": slide_artifacts,
                "operational_knowledge_units": operational_knowledge_units,
                "source_artifacts": source_artifacts,
                "context_record_candidates": context_candidates,
                "procedure_dictionary_candidates": procedure_candidates,
                "discard_report": discard_report,
                "legacy_invalid_outputs": legacy_invalid_outputs,
            },
            "extraction_report": report,
        }

    def _promotion_manifest(
        self,
        operational_knowledge_units: list[dict[str, Any]],
        context_candidates: list[dict[str, Any]],
        procedure_candidates: list[dict[str, Any]],
        legacy_invalid_outputs: list[dict[str, Any]],
        report: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "created_at": report["structured_at"],
            "promotion_allowed": False,
            "promotion_rule": "Video structuring outputs require human review before becoming Dataset 0 context records or procedure dictionary records. Training videos do not generate workflow candidates.",
            "review_required_for": {
                "operational_knowledge_units": [record["knowledge_unit_id"] for record in operational_knowledge_units],
                "context_record_candidates": [record["context_id"] for record in context_candidates],
                "procedure_dictionary_candidates": [record["procedure_id"] for record in procedure_candidates],
            },
            "legacy_invalid_outputs": legacy_invalid_outputs,
            "target_production_context_file": "data/context/context_reference.json",
            "production_context_write_ran": False,
        }

    def _write_outputs(
        self,
        master_bundle: dict[str, Any],
        operational_scenes: list[dict[str, Any]],
        slide_artifacts: list[dict[str, Any]],
        operational_knowledge_units: list[dict[str, Any]],
        evidence_chunks: list[dict[str, Any]],
        source_artifacts: list[dict[str, Any]],
        context_candidates: list[dict[str, Any]],
        procedure_candidates: list[dict[str, Any]],
        discard_report: list[dict[str, Any]],
        report: dict[str, Any],
        manifest: dict[str, Any],
    ) -> None:
        write_json(self.output_dir / "video_evidence_bundle.json", master_bundle, self.force)
        write_json(self.output_dir / "transcript_aligned_evidence_chunks.json", evidence_chunks, self.force)
        write_json(self.output_dir / "operational_scenes.json", operational_scenes, self.force)
        write_json(self.output_dir / "slide_screen_segments.json", slide_artifacts, self.force)
        write_json(self.output_dir / "source_artifacts.json", source_artifacts, self.force)
        write_json(self.output_dir / "extraction_report.json", report, self.force)
        write_json(self.review_dir / "operational_knowledge_units.json", operational_knowledge_units, self.force)
        write_json(self.review_dir / "context_record_candidates.json", context_candidates, self.force)
        write_json(self.review_dir / "procedure_dictionary_candidates.json", procedure_candidates, self.force)
        write_json(self.review_dir / "discard_report.json", discard_report, self.force)
        write_json(self.review_dir / "promotion_review_manifest.json", manifest, self.force)


def run_video_evidence_structuring(
    video_id: str,
    input_dir: Path,
    output_dir: Path,
    review_dir: Path,
    mode: str = "full",
    llm_config: Path | None = None,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    allow_local_fallback: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    return VideoEvidenceStructuringAgent(
        video_id=video_id,
        input_dir=input_dir,
        output_dir=output_dir,
        review_dir=review_dir,
        mode=mode,
        llm_config=llm_config,
        window_seconds=window_seconds,
        allow_local_fallback=allow_local_fallback,
        force=force,
    ).run()


def default_llm_config() -> Path | None:
    configured = os.getenv("PHASE0_VIDEO_LLM_CONFIG")
    if configured:
        return Path(configured)
    path = ROOT / "config" / "openai.local.json"
    if path.exists():
        return path
    path = ROOT / "config" / "azure_openai.local.json"
    return path if path.exists() else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Structure aligned video evidence into Phase 0 review datasets.")
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--review-dir", required=True, type=Path)
    parser.add_argument("--mode", choices=["quick", "full"], default="full")
    parser.add_argument("--llm-config", type=Path, default=default_llm_config())
    parser.add_argument("--window-seconds", type=int, default=DEFAULT_WINDOW_SECONDS)
    parser.add_argument("--allow-local-fallback", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run_video_evidence_structuring(
        video_id=args.video_id,
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        review_dir=args.review_dir,
        mode=args.mode,
        llm_config=args.llm_config,
        window_seconds=args.window_seconds,
        allow_local_fallback=args.allow_local_fallback,
        force=args.force,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
