from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXTRACTOR_VERSION = "0.1.0"
DEFAULT_OUTPUT_DIR = Path("output/phase0/video_training")
DEFAULT_DATA_ROOT = Path("data")
EVIDENCE_DATASET_PATHS = {
    "video_frame_artifacts": Path("evidence/video_frame_artifacts.json"),
    "video_transcript_segments": Path("evidence/video_transcript_segments.json"),
    "video_ocr_artifacts": Path("evidence/video_ocr_artifacts.json"),
    "video_visual_summary_artifacts": Path("evidence/video_visual_summary_artifacts.json"),
    "video_alignment_records": Path("evidence/video_alignment_records.json"),
}


class MP4ExtractionError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()


def seconds_to_timestamp(seconds: float) -> str:
    millis = int(round((seconds - int(seconds)) * 1000))
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def timestamp_token(seconds: float) -> str:
    return seconds_to_timestamp(seconds).replace(":", "").replace(".", "_")


def timestamp_to_seconds(value: str) -> float:
    parsed = parse_timestamp(value)
    return parsed if parsed is not None else 0.0


def parse_timestamp(value: Any) -> float | None:
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


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def require_cv2():
    try:
        import cv2  # type: ignore
    except ImportError as exc:
        raise MP4ExtractionError("OpenCV is required for MP4 extraction. Install opencv-contrib-python or requirements-ocr.txt.") from exc
    return cv2


def video_id_for_path(source: Path, video_id: str | None = None) -> str:
    return clean_id(video_id or source.stem)


def video_metadata(cv2: Any, capture: Any, source: Path, video_id: str, mode: str) -> dict[str, Any]:
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    duration = frame_count / fps if fps else 0
    return {
        "video_id": video_id,
        "source_video_path": str(source),
        "duration_seconds": duration,
        "fps": fps,
        "width": width,
        "height": height,
        "extraction_mode": mode,
        "extraction_started_at": utc_now(),
        "extractor_version": EXTRACTOR_VERSION,
    }


def frame_times(duration_seconds: float, interval_seconds: float, max_duration_seconds: float | None = None) -> list[float]:
    covered_duration = min(duration_seconds, max_duration_seconds) if max_duration_seconds else duration_seconds
    if covered_duration <= 0:
        return []
    count = max(1, int(math.floor((covered_duration - 0.001) / interval_seconds)) + 1)
    times = [round(index * interval_seconds, 3) for index in range(count)]
    return [value for value in times if value <= covered_duration]


def frame_artifact_record(
    video_id: str,
    timestamp: float,
    frame_index: int,
    sequence_id: str,
    scene_id: str,
    image_path: Path,
    artifact_id: str | None = None,
    frame_capture_reasons: list[str] | None = None,
    vtt_cue_ids: list[str] | None = None,
    vtt_cue_indices: list[int] | None = None,
) -> dict[str, Any]:
    reasons = frame_capture_reasons or ["baseline_interval"]
    cue_ids = vtt_cue_ids or []
    cue_indices = vtt_cue_indices or []
    return {
        "artifact_id": artifact_id or f"vf_{video_id}_{frame_index:06d}",
        "video_id": video_id,
        "source_video_id": video_id,
        "timestamp": seconds_to_timestamp(timestamp),
        "timestamp_seconds": timestamp,
        "frame_index": frame_index,
        "sequence_id": sequence_id,
        "scene_id": scene_id,
        "frame_range": {"start": frame_index, "end": frame_index},
        "image_path": str(image_path),
        "artifact_type": "video_frame",
        "frame_capture_reason": reasons[0],
        "frame_capture_reasons": reasons,
        "vtt_cue_ids": cue_ids,
        "vtt_cue_indices": cue_indices,
        "extraction_status": "completed",
        "validation_status": "needs_review",
        "ocr_status": "pending",
        "visual_summary_status": "pending",
        "source_refs": [f"video:{video_id}", f"timestamp:{seconds_to_timestamp(timestamp)}", f"frame:{frame_index}"],
    }


def vtt_cue_midpoint(cue: dict[str, Any]) -> float:
    return round((float(cue["timestamp_start_seconds"]) + float(cue["timestamp_end_seconds"])) / 2, 3)


def frame_capture_requests(
    duration_seconds: float,
    interval_seconds: float,
    max_duration_seconds: float | None,
    vtt_cues: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    covered_duration = min(duration_seconds, max_duration_seconds) if max_duration_seconds else duration_seconds
    requests = [
        {"timestamp": timestamp, "frame_capture_reason": "baseline_interval"}
        for timestamp in frame_times(duration_seconds, interval_seconds, max_duration_seconds)
    ]
    for cue in vtt_cues or []:
        midpoint = vtt_cue_midpoint(cue)
        if midpoint <= covered_duration:
            requests.append(
                {
                    "timestamp": midpoint,
                    "frame_capture_reason": "vtt_cue_midpoint",
                    "cue_id": cue["cue_id"],
                    "cue_index": cue["cue_index"],
                }
            )
    return requests


def merged_frame_requests(requests: list[dict[str, Any]], fps: float) -> list[dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for request in requests:
        timestamp = float(request["timestamp"])
        frame_number = int(round(timestamp * fps)) if fps else len(merged)
        existing = merged.get(frame_number)
        if not existing:
            merged[frame_number] = {
                "timestamp": frame_number / fps if fps else timestamp,
                "frame_index": frame_number,
                "frame_capture_reasons": [request["frame_capture_reason"]],
                "vtt_cue_ids": [],
                "vtt_cue_indices": [],
                "preferred_cue_index": None,
            }
            existing = merged[frame_number]
        reason = request["frame_capture_reason"]
        if reason not in existing["frame_capture_reasons"]:
            existing["frame_capture_reasons"].append(reason)
        if request.get("cue_id"):
            existing["vtt_cue_ids"].append(str(request["cue_id"]))
        if request.get("cue_index"):
            cue_index = int(request["cue_index"])
            existing["vtt_cue_indices"].append(cue_index)
            if existing["preferred_cue_index"] is None:
                existing["preferred_cue_index"] = cue_index
    return sorted(merged.values(), key=lambda value: value["timestamp"])


def frame_artifact_id(video_id: str, request: dict[str, Any]) -> str:
    if "baseline_interval" in request["frame_capture_reasons"]:
        return f"vf_{video_id}_{int(request['frame_index']):06d}"
    cue_index = request.get("preferred_cue_index")
    if cue_index is not None:
        return f"vf_{video_id}_cue_{int(cue_index):06d}_midpoint"
    return f"vf_{video_id}_{int(request['frame_index']):06d}"


def extract_frames(
    cv2: Any,
    capture: Any,
    video_id: str,
    output_root: Path,
    duration_seconds: float,
    fps: float,
    interval_seconds: float,
    max_duration_seconds: float | None,
    vtt_cues: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    frames_dir = output_root / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    artifacts = []
    failures = []
    requests = merged_frame_requests(frame_capture_requests(duration_seconds, interval_seconds, max_duration_seconds, vtt_cues), fps)
    for index, request in enumerate(requests, start=1):
        timestamp = float(request["timestamp"])
        frame_number = int(request["frame_index"])
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ok, frame = capture.read()
        if not ok:
            failures.append({"timestamp": seconds_to_timestamp(timestamp), "frame_index": frame_number})
            continue
        sequence_id = f"seq_{index:06d}"
        scene_id = f"scene_{index:06d}"
        image_path = frames_dir / f"{video_id}_{index:06d}_{timestamp_token(timestamp)}.jpg"
        if not cv2.imwrite(str(image_path), frame):
            failures.append({"timestamp": seconds_to_timestamp(timestamp), "frame_index": frame_number})
            continue
        artifacts.append(
            frame_artifact_record(
                video_id,
                timestamp,
                frame_number,
                sequence_id,
                scene_id,
                image_path,
                artifact_id=frame_artifact_id(video_id, request),
                frame_capture_reasons=request["frame_capture_reasons"],
                vtt_cue_ids=request["vtt_cue_ids"],
                vtt_cue_indices=request["vtt_cue_indices"],
            )
        )
    return artifacts, failures, []


def transcript_text_from_record(record: dict[str, Any]) -> str:
    return str(record.get("transcript_text") or record.get("text") or record.get("content") or "")


def transcript_source_refs(record: dict[str, Any], video_id: str, start: float, end: float) -> list[Any]:
    refs = record.get("source_refs")
    if isinstance(refs, list) and refs:
        return refs
    return [f"video:{video_id}", f"timestamp:{seconds_to_timestamp(start)}-{seconds_to_timestamp(end)}"]


def alignment_quality(distance: float) -> str:
    if distance == 0:
        return "exact"
    if distance <= 1.0:
        return "near"
    return "weak"


def frame_distance_to_range(record: dict[str, Any], start: float, end: float) -> float:
    timestamp = float(record.get("timestamp_seconds", 0))
    if start <= timestamp <= end:
        return 0.0
    return round(min(abs(timestamp - start), abs(timestamp - end)), 3)


def frame_distance_to_midpoint(record: dict[str, Any], start: float, end: float) -> float:
    timestamp = float(record.get("timestamp_seconds", 0))
    midpoint = (start + end) / 2
    return round(abs(timestamp - midpoint), 3)


def alignment_for_range(frame_artifacts: list[dict[str, Any]], start: float, end: float, cue_index: int | None = None) -> dict[str, Any]:
    if not frame_artifacts:
        return {
            "aligned_frame_ids": [],
            "alignment_method": "no_frame_available",
            "alignment_distance_seconds": None,
            "alignment_quality": "weak",
        }
    cue_matches = [
        record
        for record in frame_artifacts
        if cue_index is not None and cue_index in record.get("vtt_cue_indices", [])
    ]
    if cue_matches:
        distance = min(frame_distance_to_midpoint(record, start, end) for record in cue_matches)
        return {
            "aligned_frame_ids": [record["artifact_id"] for record in cue_matches],
            "alignment_method": "cue_midpoint_frame",
            "alignment_distance_seconds": distance,
            "alignment_quality": alignment_quality(distance),
        }
    overlap_matches = [
        record
        for record in frame_artifacts
        if start <= float(record.get("timestamp_seconds", 0)) <= end
    ]
    if overlap_matches:
        return {
            "aligned_frame_ids": [record["artifact_id"] for record in overlap_matches],
            "alignment_method": "timestamp_overlap",
            "alignment_distance_seconds": 0.0,
            "alignment_quality": "exact",
        }
    nearest = min(frame_artifacts, key=lambda record: frame_distance_to_range(record, start, end))
    distance = frame_distance_to_range(nearest, start, end)
    return {
        "aligned_frame_ids": [nearest["artifact_id"]],
        "alignment_method": "nearest_frame",
        "alignment_distance_seconds": distance,
        "alignment_quality": alignment_quality(distance),
    }


def apply_alignment(record: dict[str, Any], alignment: dict[str, Any]) -> dict[str, Any]:
    record["aligned_frame_ids"] = alignment["aligned_frame_ids"]
    record["alignment_method"] = alignment["alignment_method"]
    record["alignment_distance_seconds"] = alignment["alignment_distance_seconds"]
    record["alignment_quality"] = alignment["alignment_quality"]
    return record


def normalize_transcript_records(
    raw: Any,
    video_id: str,
    duration_seconds: float,
    frame_artifacts: list[dict[str, Any]],
    transcript_path: Path | None = None,
) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        raw_records = raw.get("segments") or raw.get("transcript_segments") or [raw]
    elif isinstance(raw, list):
        raw_records = raw
    else:
        raw_records = [{"transcript_text": str(raw), "timestamp_start": 0, "timestamp_end": duration_seconds}]
    segments = []
    for index, record in enumerate(raw_records, start=1):
        if not isinstance(record, dict):
            record = {"transcript_text": str(record)}
        start = parse_timestamp(record.get("timestamp_start") or record.get("start")) or 0.0
        end = parse_timestamp(record.get("timestamp_end") or record.get("end")) or duration_seconds
        segment_id = str(record.get("segment_id") or f"vts_{video_id}_{index:06d}")
        segments.append(
            apply_alignment(
                {
                "segment_id": segment_id,
                "video_id": video_id,
                "source_video_id": video_id,
                "timestamp_start": seconds_to_timestamp(start),
                "timestamp_end": seconds_to_timestamp(end),
                "timestamp_start_seconds": start,
                "timestamp_end_seconds": end,
                "speaker": record.get("speaker") or "unknown",
                "transcript_text": transcript_text_from_record(record),
                "transcript_status": "provided",
                "validation_status": "needs_review",
                "source_refs": transcript_source_refs(record, video_id, start, end),
                },
                alignment_for_range(frame_artifacts, start, end),
            )
        )
    return segments


def read_vtt_cues(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    cues = []
    index = 0
    cue_index = 1
    while index < len(lines):
        line = lines[index].strip()
        if not line or line == "WEBVTT" or line.startswith(("NOTE", "STYLE", "REGION")):
            index += 1
            continue
        cue_id = line
        index += 1
        if index >= len(lines):
            break
        timing = lines[index].strip()
        if "-->" not in timing:
            cue_id = f"cue_{cue_index:06d}"
            timing = line
        else:
            index += 1
        if "-->" not in timing:
            continue
        start_text, end_text = [part.strip().split()[0] for part in timing.split("-->", 1)]
        text_lines = []
        while index < len(lines) and lines[index].strip():
            text_lines.append(lines[index].strip())
            index += 1
        start = timestamp_to_seconds(start_text)
        end = timestamp_to_seconds(end_text)
        transcript_text = " ".join(text_lines).strip()
        cues.append(
            {
                "cue_index": cue_index,
                "cue_id": cue_id,
                "timestamp_start_seconds": start,
                "timestamp_end_seconds": end,
                "transcript_text": transcript_text,
            }
        )
        cue_index += 1
        index += 1
    return cues


def parse_vtt_transcript(path: Path, video_id: str, frame_artifacts: list[dict[str, Any]], cues: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    segments = []
    for cue in cues if cues is not None else read_vtt_cues(path):
        start = float(cue["timestamp_start_seconds"])
        end = float(cue["timestamp_end_seconds"])
        segment_id = f"vts_{video_id}_{int(cue['cue_index']):06d}"
        segments.append(
            apply_alignment(
                {
                    "segment_id": segment_id,
                    "video_id": video_id,
                    "source_video_id": video_id,
                    "timestamp_start": seconds_to_timestamp(start),
                    "timestamp_end": seconds_to_timestamp(end),
                    "timestamp_start_seconds": start,
                    "timestamp_end_seconds": end,
                    "speaker": "unknown",
                    "transcript_text": cue["transcript_text"],
                    "transcript_status": "provided",
                    "validation_status": "needs_review",
                    "source_refs": [
                        {
                            "source_type": "vtt",
                            "source_path": str(path),
                            "cue_id": cue["cue_id"],
                            "timestamp_start": seconds_to_timestamp(start),
                            "timestamp_end": seconds_to_timestamp(end),
                        }
                    ],
                },
                alignment_for_range(frame_artifacts, start, end, int(cue["cue_index"])),
            )
        )
    return segments


def load_transcript_segments(
    transcript: Path | None,
    video_id: str,
    duration_seconds: float,
    frame_artifacts: list[dict[str, Any]],
    vtt_cues: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if transcript is None:
        return []
    if transcript.suffix.lower() == ".json":
        raw = load_json_file(transcript)
    elif transcript.suffix.lower() == ".vtt":
        return parse_vtt_transcript(transcript, video_id, frame_artifacts, vtt_cues)
    else:
        raw = transcript.read_text(encoding="utf-8")
    return normalize_transcript_records(raw, video_id, duration_seconds, frame_artifacts, transcript)


def aligned_frames(frame_artifacts: list[dict[str, Any]], start: float, end: float) -> list[str]:
    return alignment_for_range(frame_artifacts, start, end)["aligned_frame_ids"]


def placeholder_transcript_segments(video_id: str, duration_seconds: float, covered_duration: float, frame_artifacts: list[dict[str, Any]], interval_seconds: float) -> list[dict[str, Any]]:
    segment_seconds = max(interval_seconds, 60.0)
    segment_count = max(1, int(math.ceil(covered_duration / segment_seconds))) if covered_duration > 0 else 1
    segments = []
    for index in range(segment_count):
        start = round(index * segment_seconds, 3)
        end = round(min((index + 1) * segment_seconds, covered_duration), 3)
        if end <= start:
            end = min(duration_seconds, start + segment_seconds)
        segments.append(
            apply_alignment(
                {
                    "segment_id": f"vts_{video_id}_{index + 1:06d}",
                    "video_id": video_id,
                    "source_video_id": video_id,
                    "timestamp_start": seconds_to_timestamp(start),
                    "timestamp_end": seconds_to_timestamp(end),
                    "timestamp_start_seconds": start,
                    "timestamp_end_seconds": end,
                    "speaker": "unknown",
                    "transcript_text": "[transcript not provided]",
                    "transcript_status": "missing_transcript",
                    "validation_status": "needs_review",
                    "source_refs": [f"video:{video_id}", f"timestamp:{seconds_to_timestamp(start)}-{seconds_to_timestamp(end)}"],
                },
                alignment_for_range(frame_artifacts, start, end),
            )
        )
    return segments


def ocr_artifacts(video_id: str, frame_artifacts: list[dict[str, Any]], run_ocr: bool) -> tuple[list[dict[str, Any]], list[str]]:
    status = "failed" if run_ocr else "pending"
    failed = []
    records = []
    for frame in frame_artifacts:
        if run_ocr:
            failed.append(frame["artifact_id"])
        records.append(
            {
                "ocr_artifact_id": f"ocr_{frame['artifact_id']}",
                "video_id": video_id,
                "source_video_id": video_id,
                "frame_artifact_id": frame["artifact_id"],
                "timestamp": frame["timestamp"],
                "extracted_text": "",
                "confidence": None,
                "ocr_engine": None,
                "ocr_status": status,
                "validation_status": "needs_review",
                "source_refs": frame["source_refs"],
            }
        )
    return records, failed


def visual_summary_artifacts(video_id: str, frame_artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "visual_summary_id": f"vs_{frame['artifact_id']}",
            "video_id": video_id,
            "source_video_id": video_id,
            "frame_artifact_id": frame["artifact_id"],
            "scene_id": frame["scene_id"],
            "timestamp": frame["timestamp"],
            "visual_summary": "",
            "visible_components": [],
            "observed_signals": [],
            "visual_summary_status": "pending",
            "validation_status": "needs_review",
            "source_refs": frame["source_refs"],
        }
        for frame in frame_artifacts
    ]


def alignment_frame_details(frame_artifacts: list[dict[str, Any]], frame_ids: list[str]) -> list[dict[str, Any]]:
    frame_artifacts_by_id = {frame["artifact_id"]: frame for frame in frame_artifacts}
    details = []
    for frame_id in frame_ids:
        frame = frame_artifacts_by_id.get(frame_id)
        if not frame:
            details.append({"artifact_id": frame_id, "frame_lookup_status": "missing"})
            continue
        details.append(
            {
                "artifact_id": frame["artifact_id"],
                "timestamp": frame["timestamp"],
                "timestamp_seconds": frame.get("timestamp_seconds"),
                "frame_index": frame["frame_index"],
                "sequence_id": frame["sequence_id"],
                "scene_id": frame["scene_id"],
                "frame_range": frame["frame_range"],
                "image_path": frame["image_path"],
                "frame_capture_reason": frame.get("frame_capture_reason"),
                "frame_capture_reasons": frame.get("frame_capture_reasons", []),
                "vtt_cue_ids": frame.get("vtt_cue_ids", []),
                "vtt_cue_indices": frame.get("vtt_cue_indices", []),
                "source_refs": frame["source_refs"],
                "frame_lookup_status": "matched",
            }
        )
    return details


def alignment_records(video_id: str, transcript_segments: list[dict[str, Any]], frame_artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for segment in transcript_segments:
        records.append(
            {
                "alignment_id": f"align_{segment['segment_id']}",
                "video_id": video_id,
                "source_video_id": video_id,
                "segment_id": segment["segment_id"],
                "frame_artifact_ids": segment["aligned_frame_ids"],
                "aligned_frames": alignment_frame_details(frame_artifacts, segment["aligned_frame_ids"]),
                "timestamp_start": segment["timestamp_start"],
                "timestamp_end": segment["timestamp_end"],
                "transcript_text": segment.get("transcript_text"),
                "transcript_status": segment.get("transcript_status"),
                "speaker": segment.get("speaker"),
                "transcript_source_refs": segment.get("source_refs", []),
                "alignment_method": segment.get("alignment_method"),
                "alignment_distance_seconds": segment.get("alignment_distance_seconds"),
                "alignment_quality": segment.get("alignment_quality"),
                "validation_status": "needs_review",
                "source_refs": segment["source_refs"],
            }
        )
    return records


def coverage_percent(actual: int, expected: int) -> float:
    if expected <= 0:
        return 0.0
    return round(min(100.0, (actual / expected) * 100), 2)


def merged_ranges(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    normalized = sorted((max(0.0, start), max(0.0, end)) for start, end in ranges if end > start)
    if not normalized:
        return []
    merged = [normalized[0]]
    for start, end in normalized[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def transcript_coverage(transcript_segments: list[dict[str, Any]], duration_seconds: float) -> tuple[float, list[dict[str, str]]]:
    provided_ranges = [
        (
            float(segment.get("timestamp_start_seconds") or timestamp_to_seconds(segment.get("timestamp_start", "0"))),
            min(duration_seconds, float(segment.get("timestamp_end_seconds") or timestamp_to_seconds(segment.get("timestamp_end", "0")))),
        )
        for segment in transcript_segments
        if segment.get("transcript_status") == "provided"
    ]
    ranges = merged_ranges(provided_ranges)
    covered_seconds = sum(end - start for start, end in ranges)
    missing = []
    cursor = 0.0
    for start, end in ranges:
        if start > cursor:
            missing.append({"start": seconds_to_timestamp(cursor), "end": seconds_to_timestamp(start)})
        cursor = max(cursor, end)
    if cursor < duration_seconds:
        missing.append({"start": seconds_to_timestamp(cursor), "end": seconds_to_timestamp(duration_seconds)})
    return coverage_percent(int(round(covered_seconds * 1000)), int(round(duration_seconds * 1000))), missing


def extraction_report(
    video_id: str,
    duration_seconds: float,
    mode: str,
    interval_seconds: float,
    expected_frame_count: int,
    frame_artifacts: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
    ocr_records: list[dict[str, Any]],
    failed_frame_extractions: list[dict[str, Any]],
    failed_ocr_frames: list[str],
    output_bundle_path: Path,
    counts: dict[str, int],
    baseline_frame_count: int,
    cue_anchor_frame_count: int,
    requested_frame_count: int,
) -> dict[str, Any]:
    transcript_coverage_percent, missing_transcript_ranges = transcript_coverage(transcript_segments, duration_seconds)
    completed_ocr = sum(1 for record in ocr_records if record["ocr_status"] == "completed")
    weak_alignment_count = sum(1 for record in transcript_segments if record.get("alignment_quality") == "weak")
    return {
        "video_id": video_id,
        "video_duration_seconds": duration_seconds,
        "extraction_mode": mode,
        "frame_interval_seconds": interval_seconds,
        "expected_frame_count": expected_frame_count,
        "actual_frame_count": len(frame_artifacts),
        "baseline_frame_count": baseline_frame_count,
        "cue_anchor_frame_count": cue_anchor_frame_count,
        "requested_frame_count": requested_frame_count,
        "deduplicated_frame_count": max(0, requested_frame_count - len(frame_artifacts)),
        "weak_alignment_count": weak_alignment_count,
        "visual_coverage_percent": coverage_percent(len(frame_artifacts), expected_frame_count),
        "transcript_coverage_percent": transcript_coverage_percent,
        "ocr_coverage_percent": coverage_percent(completed_ocr, len(frame_artifacts)),
        "missing_transcript_ranges": missing_transcript_ranges,
        "missing_frame_ranges": [],
        "failed_frame_extractions": failed_frame_extractions,
        "failed_ocr_frames": failed_ocr_frames,
        "output_bundle_path": str(output_bundle_path),
        "evidence_record_counts": counts,
    }


def write_local_evidence_datasets(data_root: Path, datasets: dict[str, list[dict[str, Any]]]) -> list[str]:
    updated = []
    for dataset_name, records in datasets.items():
        path = data_root / EVIDENCE_DATASET_PATHS[dataset_name]
        write_json(path, records)
        updated.append(str(path))
    return updated


def run_video_mp4_extraction(
    source: Path,
    video_id: str | None = None,
    mode: str = "quick_sample",
    frame_interval_seconds: float = 10.0,
    max_duration_seconds: float | None = None,
    transcript: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    data_root: Path = DEFAULT_DATA_ROOT,
    run_ocr: bool = False,
    generate_placeholders: bool = True,
) -> dict[str, Any]:
    if mode not in {"quick_sample", "full_coverage"}:
        raise MP4ExtractionError("mode must be quick_sample or full_coverage")
    if frame_interval_seconds <= 0:
        raise MP4ExtractionError("frame_interval_seconds must be greater than zero")
    if mode == "full_coverage":
        max_duration_seconds = None
    if not source.exists():
        raise MP4ExtractionError(f"Source video not found: {source}")
    cv2 = require_cv2()
    resolved_video_id = video_id_for_path(source, video_id)
    vtt_cues = read_vtt_cues(transcript) if transcript and transcript.suffix.lower() == ".vtt" else []
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise MP4ExtractionError(f"Could not open video: {source}")
    try:
        metadata = video_metadata(cv2, capture, source, resolved_video_id, mode)
        output_root = output_dir / resolved_video_id
        covered_duration = min(metadata["duration_seconds"], max_duration_seconds) if max_duration_seconds else metadata["duration_seconds"]
        frame_artifacts, failed_frames, _ = extract_frames(
            cv2,
            capture,
            resolved_video_id,
            output_root,
            metadata["duration_seconds"],
            metadata["fps"],
            frame_interval_seconds,
            max_duration_seconds,
            vtt_cues,
        )
    finally:
        capture.release()

    transcript_segments = load_transcript_segments(transcript, resolved_video_id, covered_duration, frame_artifacts, vtt_cues)
    if not transcript_segments and generate_placeholders:
        transcript_segments = placeholder_transcript_segments(resolved_video_id, metadata["duration_seconds"], covered_duration, frame_artifacts, frame_interval_seconds)
    ocr_records, failed_ocr_frames = ocr_artifacts(resolved_video_id, frame_artifacts, run_ocr)
    visual_records = visual_summary_artifacts(resolved_video_id, frame_artifacts)
    alignments = alignment_records(resolved_video_id, transcript_segments, frame_artifacts)
    counts = {
        "video_frame_artifacts": len(frame_artifacts),
        "video_transcript_segments": len(transcript_segments),
        "video_ocr_artifacts": len(ocr_records),
        "video_visual_summary_artifacts": len(visual_records),
        "video_alignment_records": len(alignments),
    }
    expected_baseline_frame_count = len(frame_times(metadata["duration_seconds"], frame_interval_seconds, max_duration_seconds))
    requested_frame_count = len(frame_capture_requests(metadata["duration_seconds"], frame_interval_seconds, max_duration_seconds, vtt_cues))
    baseline_frame_count = sum(1 for record in frame_artifacts if "baseline_interval" in record.get("frame_capture_reasons", []))
    cue_anchor_frame_count = sum(1 for record in frame_artifacts if "vtt_cue_midpoint" in record.get("frame_capture_reasons", []))
    bundle_path = output_root / "video_evidence_bundle.json"
    report = extraction_report(
        resolved_video_id,
        metadata["duration_seconds"],
        mode,
        frame_interval_seconds,
        expected_baseline_frame_count,
        frame_artifacts,
        transcript_segments,
        ocr_records,
        failed_frames,
        failed_ocr_frames,
        bundle_path,
        counts,
        baseline_frame_count,
        cue_anchor_frame_count,
        requested_frame_count,
    )
    bundle = {
        "video_metadata": metadata,
        "trust_boundary": {
            "raw_extraction_is_trusted_context": False,
            "dataset0_write_allowed": False,
            "validation_status": "needs_review",
        },
        "records": {
            "video_frame_artifacts": frame_artifacts,
            "video_transcript_segments": transcript_segments,
            "video_ocr_artifacts": ocr_records,
            "video_visual_summary_artifacts": visual_records,
            "video_alignment_records": alignments,
            "context_domain_records": [],
        },
        "extraction_report": report,
    }
    write_json(output_root / "transcript_segments.json", transcript_segments)
    write_json(output_root / "ocr_artifacts.json", ocr_records)
    write_json(output_root / "frame_transcript_alignment.json", alignments)
    write_json(output_root / "visual_summary_artifacts.json", visual_records)
    write_json(output_root / "extraction_report.json", report)
    write_json(bundle_path, bundle)
    local_files = write_local_evidence_datasets(
        data_root,
        {
            "video_frame_artifacts": frame_artifacts,
            "video_transcript_segments": transcript_segments,
            "video_ocr_artifacts": ocr_records,
            "video_visual_summary_artifacts": visual_records,
            "video_alignment_records": alignments,
        },
    )
    return {
        "video_id": resolved_video_id,
        "output_bundle_path": str(bundle_path),
        "output_dir": str(output_root),
        "local_evidence_files_updated": local_files,
        "evidence_record_counts": counts,
        "extraction_report": report,
        "guardrails": {
            "dataset0_context_write_ran": False,
            "asr_ran": False,
            "workflow_mining_ran": False,
            "procedure_mining_ran": False,
            "azure_cosmos_sync_ran": False,
            "azure_search_sync_ran": False,
            "blob_upload_ran": False,
            "runtime_retrieval_promotion_ran": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract source evidence artifacts from Optisweep training MP4 files.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--video-id")
    parser.add_argument("--mode", choices=["quick_sample", "full_coverage"], default="quick_sample")
    parser.add_argument("--frame-interval-seconds", type=float, default=10.0)
    parser.add_argument("--max-duration-seconds", type=float)
    parser.add_argument("--transcript", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--run-ocr", action="store_true")
    parser.add_argument("--generate-placeholders", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    try:
        result = run_video_mp4_extraction(
            args.source,
            video_id=args.video_id,
            mode=args.mode,
            frame_interval_seconds=args.frame_interval_seconds,
            max_duration_seconds=args.max_duration_seconds,
            transcript=args.transcript,
            output_dir=args.output_dir,
            data_root=args.data_root,
            run_ocr=args.run_ocr,
            generate_placeholders=args.generate_placeholders,
        )
    except MP4ExtractionError as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
