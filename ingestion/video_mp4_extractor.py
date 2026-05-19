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
) -> dict[str, Any]:
    artifact_id = f"vf_{video_id}_{frame_index:06d}"
    return {
        "artifact_id": artifact_id,
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
        "extraction_status": "completed",
        "validation_status": "needs_review",
        "ocr_status": "pending",
        "visual_summary_status": "pending",
        "source_refs": [f"video:{video_id}", f"timestamp:{seconds_to_timestamp(timestamp)}", f"frame:{frame_index}"],
    }


def extract_frames(
    cv2: Any,
    capture: Any,
    video_id: str,
    output_root: Path,
    duration_seconds: float,
    fps: float,
    interval_seconds: float,
    max_duration_seconds: float | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    frames_dir = output_root / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    artifacts = []
    failures = []
    times = frame_times(duration_seconds, interval_seconds, max_duration_seconds)
    for index, timestamp in enumerate(times, start=1):
        frame_number = int(round(timestamp * fps)) if fps else index - 1
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
        artifacts.append(frame_artifact_record(video_id, timestamp, frame_number, sequence_id, scene_id, image_path))
    return artifacts, failures, [{"start": seconds_to_timestamp(value), "end": seconds_to_timestamp(value)} for value in times if value < 0]


def transcript_text_from_record(record: dict[str, Any]) -> str:
    return str(record.get("transcript_text") or record.get("text") or record.get("content") or "")


def normalize_transcript_records(raw: Any, video_id: str, duration_seconds: float, frame_artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
        aligned_frame_ids = aligned_frames(frame_artifacts, start, end)
        segments.append(
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
                "aligned_frame_ids": aligned_frame_ids,
                "validation_status": "needs_review",
                "source_refs": [f"video:{video_id}", f"timestamp:{seconds_to_timestamp(start)}-{seconds_to_timestamp(end)}"],
            }
        )
    return segments


def load_transcript_segments(transcript: Path | None, video_id: str, duration_seconds: float, frame_artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if transcript is None:
        return []
    if transcript.suffix.lower() == ".json":
        raw = load_json_file(transcript)
    else:
        raw = transcript.read_text(encoding="utf-8")
    return normalize_transcript_records(raw, video_id, duration_seconds, frame_artifacts)


def aligned_frames(frame_artifacts: list[dict[str, Any]], start: float, end: float) -> list[str]:
    return [
        record["artifact_id"]
        for record in frame_artifacts
        if start <= float(record.get("timestamp_seconds", 0)) <= end
    ]


def placeholder_transcript_segments(video_id: str, duration_seconds: float, covered_duration: float, frame_artifacts: list[dict[str, Any]], interval_seconds: float) -> list[dict[str, Any]]:
    segment_seconds = max(interval_seconds, 60.0)
    segment_count = max(1, int(math.ceil(covered_duration / segment_seconds))) if covered_duration > 0 else 1
    segments = []
    for index in range(segment_count):
        start = round(index * segment_seconds, 3)
        end = round(min((index + 1) * segment_seconds, covered_duration), 3)
        if end <= start:
            end = min(duration_seconds, start + segment_seconds)
        aligned_frame_ids = aligned_frames(frame_artifacts, start, end)
        segments.append(
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
                "aligned_frame_ids": aligned_frame_ids,
                "validation_status": "needs_review",
                "source_refs": [f"video:{video_id}", f"timestamp:{seconds_to_timestamp(start)}-{seconds_to_timestamp(end)}"],
            }
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


def alignment_records(video_id: str, transcript_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for segment in transcript_segments:
        records.append(
            {
                "alignment_id": f"align_{segment['segment_id']}",
                "video_id": video_id,
                "source_video_id": video_id,
                "segment_id": segment["segment_id"],
                "frame_artifact_ids": segment["aligned_frame_ids"],
                "timestamp_start": segment["timestamp_start"],
                "timestamp_end": segment["timestamp_end"],
                "alignment_method": "timestamp_overlap",
                "validation_status": "needs_review",
                "source_refs": segment["source_refs"],
            }
        )
    return records


def coverage_percent(actual: int, expected: int) -> float:
    if expected <= 0:
        return 0.0
    return round(min(100.0, (actual / expected) * 100), 2)


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
) -> dict[str, Any]:
    provided_transcript = any(segment["transcript_status"] == "provided" for segment in transcript_segments)
    completed_ocr = sum(1 for record in ocr_records if record["ocr_status"] == "completed")
    return {
        "video_id": video_id,
        "video_duration_seconds": duration_seconds,
        "extraction_mode": mode,
        "frame_interval_seconds": interval_seconds,
        "expected_frame_count": expected_frame_count,
        "actual_frame_count": len(frame_artifacts),
        "visual_coverage_percent": coverage_percent(len(frame_artifacts), expected_frame_count),
        "transcript_coverage_percent": 100.0 if provided_transcript else 0.0,
        "ocr_coverage_percent": coverage_percent(completed_ocr, len(frame_artifacts)),
        "missing_transcript_ranges": [] if provided_transcript else [{"start": seconds_to_timestamp(0), "end": seconds_to_timestamp(duration_seconds)}],
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
        )
    finally:
        capture.release()

    transcript_segments = load_transcript_segments(transcript, resolved_video_id, covered_duration, frame_artifacts)
    if not transcript_segments and generate_placeholders:
        transcript_segments = placeholder_transcript_segments(resolved_video_id, metadata["duration_seconds"], covered_duration, frame_artifacts, frame_interval_seconds)
    ocr_records, failed_ocr_frames = ocr_artifacts(resolved_video_id, frame_artifacts, run_ocr)
    visual_records = visual_summary_artifacts(resolved_video_id, frame_artifacts)
    alignments = alignment_records(resolved_video_id, transcript_segments)
    counts = {
        "video_frame_artifacts": len(frame_artifacts),
        "video_transcript_segments": len(transcript_segments),
        "video_ocr_artifacts": len(ocr_records),
        "video_visual_summary_artifacts": len(visual_records),
        "video_alignment_records": len(alignments),
    }
    bundle_path = output_root / "video_evidence_bundle.json"
    report = extraction_report(
        resolved_video_id,
        metadata["duration_seconds"],
        mode,
        frame_interval_seconds,
        len(frame_times(metadata["duration_seconds"], frame_interval_seconds, max_duration_seconds)),
        frame_artifacts,
        transcript_segments,
        ocr_records,
        failed_frames,
        failed_ocr_frames,
        bundle_path,
        counts,
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
