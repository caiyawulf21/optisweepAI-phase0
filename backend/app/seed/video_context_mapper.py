from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.models import ContextReference
from backend.app.models.base import model_to_dict
from backend.app.seed.local_dataset_mapper import (
    DATASET_PATHS,
    MERGE_KEYS,
    clean_id,
    ensure_local_dataset_files,
    load_json,
    merge_records,
    write_json,
)

OBSERVATION_TYPES = {"visual", "spoken", "inferred", "extracted_text"}
DEFAULT_CREATED_AT = "1970-01-01T00:00:00Z"


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def string_list(value: Any) -> list[str]:
    values = []
    for item in as_list(value):
        if item is None:
            continue
        values.append(str(item))
    return values


def bool_value(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def context_document_id(record: dict[str, Any], video_id: str, index: int) -> str:
    raw_id = record.get("context_id") or record.get("id") or f"{video_id}_context_{index:03d}"
    clean = clean_id(str(raw_id))
    return clean if clean.startswith("ctx_") else f"ctx_{clean}"


def context_records(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    records = bundle.get("records", {})
    for key in ["context_domain_records", "context_records", "context_reference", "dataset_c_context_records"]:
        value = records.get(key)
        if isinstance(value, list):
            return value
    value = bundle.get("context_domain_records")
    return value if isinstance(value, list) else []


def video_id_from_metadata(metadata: dict[str, Any]) -> str:
    return str(metadata.get("video_id") or metadata.get("source_video") or metadata.get("source_id") or "unknown_video")


def observation_type(record: dict[str, Any]) -> str:
    value = str(record.get("observation_type") or "spoken").strip().lower()
    return value if value in OBSERVATION_TYPES else "inferred"


def source_refs(record: dict[str, Any], video_id: str) -> list[str]:
    refs = [f"video:{record.get('source_video') or video_id}"]
    refs.extend(f"timestamp:{value}" for value in string_list(record.get("timestamps")))
    refs.extend(f"artifact:{value}" for value in string_list(record.get("artifact_refs")))
    return list(dict.fromkeys(refs))


def metadata_for_record(record: dict[str, Any], video_metadata: dict[str, Any], video_id: str) -> dict[str, Any]:
    frame_range = record.get("frame_range") if isinstance(record.get("frame_range"), dict) else {}
    return {
        "video_id": video_id,
        "video_title": video_metadata.get("title") or video_metadata.get("video_title"),
        "source_video": record.get("source_video") or video_id,
        "timestamps": string_list(record.get("timestamps")),
        "artifact_refs": string_list(record.get("artifact_refs")),
        "scene_id": record.get("scene_id"),
        "sequence_id": record.get("sequence_id"),
        "frame_range": {
            "start": frame_range.get("start") or record.get("frame_start"),
            "end": frame_range.get("end") or record.get("frame_end"),
        },
        "observation_type": observation_type(record),
        "description": record.get("description"),
        "workflow_candidate_hint": bool_value(record.get("workflow_candidate_hint")),
        "procedure_candidate_hint": bool_value(record.get("procedure_candidate_hint")),
        "operational_signal_tags": string_list(record.get("operational_signal_tags")),
    }


def map_video_context_record(record: dict[str, Any], video_metadata: dict[str, Any] | None = None, index: int = 1) -> dict[str, Any]:
    metadata = video_metadata or {}
    video_id = video_id_from_metadata(metadata)
    record_metadata = metadata_for_record(record, metadata, video_id)
    retrieval_text = record.get("retrieval_text") or record.get("description") or record.get("title")
    doc = ContextReference(
        id=context_document_id(record, video_id, index),
        context_type=record.get("context_type") or "operational_concept",
        title=record.get("title") or f"Video context {index}",
        applies_to=string_list(record.get("components") or record.get("applies_to")),
        created_at=record.get("created_at") or metadata.get("created_at") or metadata.get("extracted_at") or DEFAULT_CREATED_AT,
        updated_at=record.get("updated_at"),
        source_refs=source_refs(record, video_id),
        source_authority=record.get("source_authority") or "training_video",
        retrieval_text=retrieval_text,
        validation_status=record.get("validation_status") or "needs_review",
        requires_manual_review=bool_value(record.get("requires_manual_review"), True),
        metadata=record_metadata,
        observation_type=record_metadata["observation_type"],
        scene_id=record_metadata["scene_id"],
        sequence_id=record_metadata["sequence_id"],
        frame_range=record_metadata["frame_range"],
        workflow_candidate_hint=record_metadata["workflow_candidate_hint"],
        procedure_candidate_hint=record_metadata["procedure_candidate_hint"],
        operational_signal_tags=record_metadata["operational_signal_tags"],
    )
    return model_to_dict(doc)


def map_video_context_bundle(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = bundle.get("video_metadata", {})
    return [map_video_context_record(record, metadata, index) for index, record in enumerate(context_records(bundle), start=1)]


def export_video_context_bundle_to_local(bundle_path: Path, data_root: Path = Path("data")) -> dict[str, int]:
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    ensure_local_dataset_files(data_root)
    incoming = map_video_context_bundle(bundle)
    path = data_root / DATASET_PATHS["context_reference"]
    existing = load_json(path)
    records = merge_records(existing if isinstance(existing, list) else [], incoming, MERGE_KEYS["context_reference"])
    write_json(path, records)
    return {"context_reference": len(records)}
