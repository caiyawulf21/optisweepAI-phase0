import json
from pathlib import Path

import cv2
import numpy as np

from ingestion.video_mp4_extractor import run_video_mp4_extraction


def create_synthetic_video(path: Path, seconds: int = 4, fps: int = 5) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (64, 48))
    for index in range(seconds * fps):
        frame = np.full((48, 64, 3), index * 5 % 255, dtype=np.uint8)
        writer.write(frame)
    writer.release()


def test_quick_sample_extraction_creates_evidence_bundle_and_no_context_writes(tmp_path):
    source = tmp_path / "training.mp4"
    output_dir = tmp_path / "output"
    data_root = tmp_path / "data"
    create_synthetic_video(source, seconds=5, fps=5)

    result = run_video_mp4_extraction(
        source,
        video_id="training_day_1",
        mode="quick_sample",
        frame_interval_seconds=2,
        max_duration_seconds=3,
        output_dir=output_dir,
        data_root=data_root,
    )

    bundle_path = Path(result["output_bundle_path"])
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    frames = bundle["records"]["video_frame_artifacts"]
    transcripts = bundle["records"]["video_transcript_segments"]
    ocr = bundle["records"]["video_ocr_artifacts"]
    visual = bundle["records"]["video_visual_summary_artifacts"]
    alignments = bundle["records"]["video_alignment_records"]

    assert bundle_path.exists()
    assert len(frames) == 2
    assert len(ocr) == len(frames)
    assert len(visual) == len(frames)
    assert len(alignments) == len(transcripts)
    assert all(Path(frame["image_path"]).exists() for frame in frames)
    assert {frame["validation_status"] for frame in frames} == {"needs_review"}
    assert {record["ocr_status"] for record in ocr} == {"pending"}
    assert {record["validation_status"] for record in ocr} == {"needs_review"}
    assert transcripts[0]["transcript_status"] == "missing_transcript"
    assert transcripts[0]["transcript_text"] == "[transcript not provided]"
    assert alignments[0]["frame_artifact_ids"] == [frame["artifact_id"] for frame in frames]
    assert bundle["trust_boundary"]["dataset0_write_allowed"] is False
    assert not (data_root / "context" / "context_reference.json").exists()
    assert (data_root / "evidence" / "video_frame_artifacts.json").exists()
    assert result["guardrails"]["dataset0_context_write_ran"] is False


def test_full_coverage_extraction_reports_complete_visual_coverage(tmp_path):
    source = tmp_path / "training.mp4"
    create_synthetic_video(source, seconds=3, fps=5)

    result = run_video_mp4_extraction(
        source,
        video_id="full_coverage_video",
        mode="full_coverage",
        frame_interval_seconds=1,
        max_duration_seconds=1,
        output_dir=tmp_path / "output",
        data_root=tmp_path / "data",
    )

    report = result["extraction_report"]
    assert report["extraction_mode"] == "full_coverage"
    assert report["expected_frame_count"] == report["actual_frame_count"]
    assert report["visual_coverage_percent"] == 100.0
    assert report["transcript_coverage_percent"] == 0.0
    assert report["ocr_coverage_percent"] == 0.0


def test_transcript_file_is_ingested_and_aligned_to_frames(tmp_path):
    source = tmp_path / "training.mp4"
    transcript = tmp_path / "transcript.json"
    create_synthetic_video(source, seconds=4, fps=5)
    transcript.write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "segment_id": "seg_intro",
                        "timestamp_start": "00:00:00.000",
                        "timestamp_end": "00:00:02.000",
                        "speaker": "trainer",
                        "transcript_text": "RMS map is shown.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = run_video_mp4_extraction(
        source,
        video_id="transcript_video",
        mode="quick_sample",
        frame_interval_seconds=1,
        max_duration_seconds=3,
        transcript=transcript,
        output_dir=tmp_path / "output",
        data_root=tmp_path / "data",
    )
    bundle = json.loads(Path(result["output_bundle_path"]).read_text(encoding="utf-8"))
    segment = bundle["records"]["video_transcript_segments"][0]

    assert segment["segment_id"] == "seg_intro"
    assert segment["transcript_status"] == "provided"
    assert segment["speaker"] == "trainer"
    assert segment["transcript_text"] == "RMS map is shown."
    assert segment["aligned_frame_ids"]
    assert result["extraction_report"]["transcript_coverage_percent"] == 100.0


def test_run_ocr_flag_creates_failed_ocr_evidence_without_context_promotion(tmp_path):
    source = tmp_path / "training.mp4"
    create_synthetic_video(source, seconds=2, fps=5)

    result = run_video_mp4_extraction(
        source,
        video_id="ocr_pending_video",
        mode="quick_sample",
        frame_interval_seconds=1,
        max_duration_seconds=1,
        output_dir=tmp_path / "output",
        data_root=tmp_path / "data",
        run_ocr=True,
    )
    bundle = json.loads(Path(result["output_bundle_path"]).read_text(encoding="utf-8"))

    assert {record["ocr_status"] for record in bundle["records"]["video_ocr_artifacts"]} == {"failed"}
    assert result["extraction_report"]["failed_ocr_frames"]
    assert result["guardrails"]["dataset0_context_write_ran"] is False
