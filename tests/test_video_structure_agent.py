import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from scripts import video_structure_agent
from scripts.video_structure_agent import (
    CandidateSegmentBuilder,
    EvidenceBundleLoader,
    EvidenceChunkBuilder,
    LLMOperationalScenePlanner,
    OperationalKnowledgeUnitValidator,
    SlideScreenSegmentBuilder,
    TranscriptVisualAligner,
    VideoStructuringError,
    llm_stage_config,
    run_video_evidence_structuring,
)


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_frame(path: Path, purple_marker: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = np.zeros((80, 120, 3), dtype=np.uint8)
    if purple_marker:
        frame[58:76, 4:44] = (180, 60, 180)
    cv2.imwrite(str(path), frame)


def create_video_evidence(input_dir: Path, video_id: str, segments: list[dict], purple_marker: bool = False) -> None:
    records = {
        "video_transcript_segments": [],
        "video_frame_artifacts": [],
        "video_ocr_artifacts": [],
        "video_visual_summary_artifacts": [],
        "video_alignment_records": [],
    }
    for index, segment in enumerate(segments, start=1):
        segment_id = f"vts_{video_id}_{index:06d}"
        frame_id = f"vf_{video_id}_{index:06d}"
        frame_path = input_dir / "frames" / f"{frame_id}.jpg"
        write_frame(frame_path, purple_marker=purple_marker and index == 1)
        transcript = {
            "segment_id": segment_id,
            "video_id": video_id,
            "timestamp_start": segment["start"],
            "timestamp_end": segment["end"],
            "speaker": segment.get("speaker", "unknown"),
            "transcript_text": segment["text"],
            "transcript_status": "provided",
            "validation_status": "needs_review",
            "source_refs": [
                {
                    "source_type": "vtt",
                    "source_path": "data/raw_videos/training.vtt",
                    "timestamp_start": segment["start"],
                    "timestamp_end": segment["end"],
                }
            ],
        }
        frame = {
            "artifact_id": frame_id,
            "video_id": video_id,
            "timestamp": segment["midpoint"],
            "timestamp_seconds": segment.get("midpoint_seconds", 15.0 + index),
            "frame_index": 450 + index,
            "sequence_id": f"seq_{index:06d}",
            "scene_id": f"source_scene_{index:06d}",
            "frame_range": {"start": 450 + index, "end": 450 + index},
            "image_path": str(frame_path),
            "artifact_type": "video_frame",
            "frame_capture_reason": "vtt_cue_midpoint",
            "frame_capture_reasons": ["vtt_cue_midpoint"],
            "source_refs": [f"video:{video_id}", f"timestamp:{segment['midpoint']}", f"frame:{450 + index}"],
            "validation_status": "needs_review",
        }
        records["video_transcript_segments"].append(transcript)
        records["video_frame_artifacts"].append(frame)
        records["video_ocr_artifacts"].append(
            {
                "ocr_artifact_id": f"ocr_{frame_id}",
                "video_id": video_id,
                "frame_artifact_id": frame_id,
                "timestamp": segment["midpoint"],
                "extracted_text": segment.get("ocr", ""),
                "ocr_status": "completed" if segment.get("ocr") else "pending",
                "validation_status": "needs_review",
                "source_refs": [f"frame_artifact:{frame_id}"],
            }
        )
        records["video_visual_summary_artifacts"].append(
            {
                "visual_summary_id": f"vs_{frame_id}",
                "video_id": video_id,
                "frame_artifact_id": frame_id,
                "timestamp": segment["midpoint"],
                "visual_summary": segment.get("visual_summary", "Aligned training frame."),
                "visible_components": segment.get("components", []),
                "observed_signals": segment.get("signals", []),
                "validation_status": "needs_review",
            }
        )
        records["video_alignment_records"].append(
            {
                "alignment_id": f"align_{segment_id}",
                "video_id": video_id,
                "source_video_id": video_id,
                "segment_id": segment_id,
                "frame_artifact_ids": [frame_id],
                "aligned_frames": [frame],
                "timestamp_start": segment["start"],
                "timestamp_end": segment["end"],
                "transcript_text": segment["text"],
                "transcript_status": "provided",
                "speaker": segment.get("speaker", "unknown"),
                "source_refs": [f"transcript_segment:{segment_id}", f"frame_artifact:{frame_id}"],
                "validation_status": "needs_review",
            }
        )
    write_json(
        input_dir / "video_evidence_bundle.json",
        {
            "video_metadata": {"video_id": video_id, "duration_seconds": 120},
            "records": records,
            "extraction_report": {"actual_frame_count": len(segments)},
        },
    )


def run_agent(tmp_path, video_id: str = "training_video", segments: list[dict] | None = None, purple_marker: bool = False):
    input_dir = tmp_path / "data" / "video_evidence" / video_id
    output_dir = tmp_path / "data" / "evidence" / "video" / video_id
    review_dir = tmp_path / "data" / "review" / "video" / video_id
    create_video_evidence(input_dir, video_id, segments or conceptual_segments(), purple_marker)
    result = run_video_evidence_structuring(
        video_id=video_id,
        input_dir=input_dir,
        output_dir=output_dir,
        review_dir=review_dir,
        force=True,
        llm_config=None,
        allow_local_fallback=True,
    )
    return result, output_dir, review_dir


def conceptual_segments() -> list[dict]:
    return [
        {
            "start": "00:00:10.000",
            "end": "00:00:20.000",
            "midpoint": "00:00:15.000",
            "text": "The RMS map shows where AGVs are located in Optisweep.",
            "ocr": "RMS Map",
            "visual_summary": "RMS map UI is visible.",
        }
    ]


def procedure_segments() -> list[dict]:
    return [
        {
            "start": "00:00:10.000",
            "end": "00:00:20.000",
            "midpoint": "00:00:15.000",
            "text": "First open the RMS map and check the AGV heartbeat alarm.",
            "ocr": "RMS Map Heartbeat Alarm",
            "visual_summary": "RMS map UI with heartbeat alarm text visible.",
        },
        {
            "start": "00:00:21.000",
            "end": "00:00:30.000",
            "midpoint": "00:00:25.000",
            "text": "Then select the AGV and validate the heartbeat state in the dashboard.",
            "ocr": "AGV Heartbeat State",
            "visual_summary": "AGV dashboard state is visible.",
        },
    ]


def test_conceptual_scene_creates_context_without_procedure_or_workflow(tmp_path):
    result, output_dir, review_dir = run_agent(tmp_path)

    scenes = json.loads((output_dir / "operational_scenes.json").read_text(encoding="utf-8"))
    slides = json.loads((output_dir / "slide_screen_segments.json").read_text(encoding="utf-8"))
    knowledge_units = json.loads((review_dir / "operational_knowledge_units.json").read_text(encoding="utf-8"))
    context_candidates = json.loads((review_dir / "context_record_candidates.json").read_text(encoding="utf-8"))
    procedure_candidates = json.loads((review_dir / "procedure_dictionary_candidates.json").read_text(encoding="utf-8"))
    discard_report = json.loads((review_dir / "discard_report.json").read_text(encoding="utf-8"))
    manifest = json.loads((review_dir / "promotion_review_manifest.json").read_text(encoding="utf-8"))

    assert result["guardrails"]["dataset0_context_write_ran"] is False
    assert scenes[0]["scene_type"] in {"conceptual_explanation", "system_overview"}
    assert scenes[0]["extraction_eligibility"]["context_candidate_allowed"] is True
    assert scenes[0]["extraction_eligibility"]["procedure_candidate_allowed"] is False
    assert scenes[0]["operational_intents"]
    assert slides
    assert knowledge_units
    assert all(not record["title"].lower().endswith("training video reference") for record in context_candidates)
    assert context_candidates
    assert procedure_candidates == []
    assert discard_report == []
    assert not (review_dir / "workflow_evidence_candidates.json").exists()
    assert "workflow_evidence_candidates" not in manifest["review_required_for"]
    assert not (tmp_path / "data" / "context" / "context_reference.json").exists()


def test_scene_planning_requires_llm_or_explicit_local_fallback(tmp_path):
    video_id = "training_video"
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "out"
    review_dir = tmp_path / "review"
    create_video_evidence(input_dir, video_id, conceptual_segments())

    with pytest.raises(VideoStructuringError, match="LLM scene planning requires"):
        run_video_evidence_structuring(video_id, input_dir, output_dir, review_dir, force=True, llm_config=None)

    report = json.loads((output_dir / "extraction_report.json").read_text(encoding="utf-8"))
    assert report["llm_status"] == "failed"
    assert report["authoritative_operational_scenes_written"] is False
    assert not (output_dir / "operational_scenes.json").exists()


def test_scene_planning_packet_preserves_full_transcript_without_frame_objects(tmp_path):
    video_id = "training_video"
    input_dir = tmp_path / "input"
    full_text = "When you remove an AGV that has a tote, you have to remove the tote at the hospital before reintroducing the state."
    create_video_evidence(
        input_dir,
        video_id,
        [
            {
                "start": "00:00:10.000",
                "end": "00:00:20.000",
                "midpoint": "00:00:15.000",
                "text": full_text,
                "ocr": "AGV Tote Hospital",
                "visual_summary": "Training slide shows AGV and tote handling state.",
            }
        ],
    )

    bundle = EvidenceBundleLoader(video_id, input_dir).load()
    aligned = TranscriptVisualAligner(bundle).aligned_segments()
    chunks = EvidenceChunkBuilder().build(video_id, aligned)
    slides = SlideScreenSegmentBuilder().build(video_id, aligned)
    candidates = CandidateSegmentBuilder().build(video_id, chunks, slides)
    packet = candidates[0]

    assert packet["transcript_cues"][0]["text"] == full_text
    assert packet["transcript_cues"][0]["timestamp_start"] == "00:00:10.000"
    assert packet["slide_screen_segments"][0]["representative_frame_ref"] == f"vf_{video_id}_000001"
    assert "frames" not in packet["slide_screen_segments"][0]
    assert "aligned_frames" not in json.dumps(packet)


def test_stage_model_config_uses_cheaper_scene_planner_and_gpt5_extractor():
    config = {
        "provider": "openai",
        "api_key": "test-key",
        "model": "gpt-5",
        "scene_planner_model": "gpt-4.1-mini",
        "knowledge_extractor_model": "gpt-5",
        "scene_planner_max_tokens": 700,
        "knowledge_extractor_max_tokens": 1200,
    }

    scene_config = llm_stage_config(config, "scene_planner")
    knowledge_config = llm_stage_config(config, "knowledge_extractor")

    assert scene_config["model"] == "gpt-4.1-mini"
    assert scene_config["max_tokens"] == 700
    assert knowledge_config["model"] == "gpt-5"
    assert knowledge_config["max_tokens"] == 1200


def test_slide_first_candidate_planning_reduces_request_count(tmp_path):
    video_id = "training_video"
    input_dir = tmp_path / "input"
    segments = [
        {
            "start": f"00:00:{10 + index:02d}.000",
            "end": f"00:00:{11 + index:02d}.000",
            "midpoint": f"00:00:{10 + index:02d}.500",
            "text": f"Speaker explains RMS map behavior cue {index}.",
            "ocr": "RMS Map",
            "visual_summary": "Same RMS map screen is visible.",
        }
        for index in range(8)
    ]
    create_video_evidence(input_dir, video_id, segments)
    bundle = EvidenceBundleLoader(video_id, input_dir).load()
    aligned = TranscriptVisualAligner(bundle).aligned_segments()
    chunks = EvidenceChunkBuilder().build(video_id, aligned)
    slides = SlideScreenSegmentBuilder().build(video_id, aligned)

    slide_candidates = CandidateSegmentBuilder(max_cues=1).build(video_id, chunks, slides)
    window_candidates = CandidateSegmentBuilder(max_cues=1).build(video_id, chunks, [])

    assert len(slides) == 1
    assert len(slide_candidates) == 1
    assert len(window_candidates) == len(chunks)
    assert len(slide_candidates[0]["transcript_cues"]) == len(chunks)


def test_scene_planner_rejects_empty_cache_payload(tmp_path):
    planner = LLMOperationalScenePlanner(config_path=None, cache_dir=tmp_path)

    assert planner._valid_scene_plan_payload({}) is False
    assert planner._valid_scene_plan_payload({"operational_scenes": []}) is False
    assert planner._valid_scene_plan_payload({"operational_scenes": [{"scene_title": "RMS map overview"}]}) is True


def test_knowledge_unit_validator_normalizes_llm_near_miss_unit_types():
    units, discarded = OperationalKnowledgeUnitValidator().validate(
        [
            {
                "knowledge_unit_id": "ku_1",
                "source_scene_ids": ["scene_1"],
                "source_artifact_ids": [],
                "evidence_chunk_refs": ["chunk_1"],
                "timestamp_start": "00:00:01.000",
                "timestamp_end": "00:00:02.000",
                "unit_type": "diagnostic_guideline",
                "title": "RMS faults should be checked first",
                "summary": "The training indicates RMS system faults are a first diagnostic check.",
                "observed_evidence": ["Check RMS system faults first."],
                "retrieval_text": "RMS system faults first diagnostic check",
            }
        ]
    )

    assert discarded == []
    assert units[0]["unit_type"] == "diagnostic_concept"


def test_explicit_reusable_procedure_survives_validation(tmp_path):
    _, output_dir, review_dir = run_agent(tmp_path, segments=procedure_segments(), purple_marker=True)

    chunks = json.loads((output_dir / "transcript_aligned_evidence_chunks.json").read_text(encoding="utf-8"))
    scenes = json.loads((output_dir / "operational_scenes.json").read_text(encoding="utf-8"))
    procedure_candidates = json.loads((review_dir / "procedure_dictionary_candidates.json").read_text(encoding="utf-8"))

    assert any(chunk["speaker_attribution_method"] == "teams_purple_indicator" for chunk in chunks)
    assert any(scene["speaker_attribution_method"] == "teams_purple_indicator" for scene in scenes)
    assert len(procedure_candidates) == 1
    assert procedure_candidates[0]["source_scene_id"] == scenes[0]["scene_id"]
    assert len(procedure_candidates[0]["steps"]) == 2
    assert all(step["timestamp_start"] and step["artifact_refs"] and step["evidence_chunk_refs"] for step in procedure_candidates[0]["steps"])


def test_weak_action_attempt_is_discarded_before_output(tmp_path, monkeypatch):
    weak_segments = [
        {
            "start": "00:00:10.000",
            "end": "00:00:14.000",
            "midpoint": "00:00:12.000",
            "text": "Then open",
            "ocr": "RMS Map",
            "visual_summary": "Generic Teams training frame.",
        }
    ]

    def fake_extract(self, video_id, scenes, evidence_chunks, slide_artifacts):
        scene = scenes[0]
        chunk = evidence_chunks[0]
        return {
            "operational_knowledge_units": [],
            "procedure_candidate_attempts": [
                {
                    "procedure_id": "proc_weak",
                    "source_scene_id": scene["scene_id"],
                    "title": "RMS",
                    "procedure_type": "operational_action",
                    "components": [],
                    "systems": [],
                    "steps": [
                        {
                            "step_order": 1,
                            "instruction": "Then open",
                            "timestamp_start": chunk["timestamp_start"],
                            "timestamp_end": chunk["timestamp_end"],
                            "expected_outcome": "",
                            "validation_check": "",
                            "artifact_refs": chunk["artifact_ids"],
                            "evidence_chunk_refs": [chunk["chunk_id"]],
                        }
                    ],
                    "source_video": video_id,
                    "source_refs": chunk["source_refs"],
                    "retrieval_text": "Then open",
                }
            ],
        }

    monkeypatch.setattr(video_structure_agent.LLMRecordExtractor, "extract", fake_extract)

    _, _, review_dir = run_agent(tmp_path, segments=weak_segments)

    procedure_candidates = json.loads((review_dir / "procedure_dictionary_candidates.json").read_text(encoding="utf-8"))
    discard_report = json.loads((review_dir / "discard_report.json").read_text(encoding="utf-8"))

    assert procedure_candidates == []
    assert discard_report
    assert discard_report[0]["candidate_type"] == "procedure"
    assert "vague_or_incomplete_step" in discard_report[0]["failed_rules"]
    assert "title_is_component_only" in discard_report[0]["failed_rules"]


def test_legacy_window_outputs_are_marked_invalid_and_excluded(tmp_path):
    video_id = "training_video"
    input_dir = tmp_path / "data" / "video_evidence" / video_id
    output_dir = tmp_path / "data" / "evidence" / "video" / video_id
    review_dir = tmp_path / "data" / "review" / "video" / video_id
    create_video_evidence(input_dir, video_id, conceptual_segments())
    write_json(review_dir / "procedure_dictionary_candidates.json", [{"procedure_id": f"proc_{video_id}_window_001"}])
    write_json(review_dir / "workflow_evidence_candidates.json", [{"workflow_candidate_id": f"wf_{video_id}_window_001"}])

    run_video_evidence_structuring(video_id, input_dir, output_dir, review_dir, force=True, llm_config=None, allow_local_fallback=True)
    manifest = json.loads((review_dir / "promotion_review_manifest.json").read_text(encoding="utf-8"))

    assert manifest["legacy_invalid_outputs"]
    assert all(item["legacy_status"] == "legacy_invalid" for item in manifest["legacy_invalid_outputs"])
    assert "workflow_evidence_candidates" not in manifest["review_required_for"]


def test_valid_agent_knowledge_unit_creates_context_and_procedure(tmp_path, monkeypatch):
    def fake_extract(self, video_id, scenes, evidence_chunks, slide_artifacts):
        scene = scenes[0]
        return {
            "operational_knowledge_units": [
                {
                    "knowledge_unit_id": "ku_agv_tote_removal",
                    "video_id": video_id,
                    "source_scene_ids": [scene["scene_id"]],
                    "source_artifact_ids": [slide_artifacts[0]["slide_screen_segment_id"]],
                    "timestamp_start": scene["timestamp_start"],
                    "timestamp_end": scene["timestamp_end"],
                    "unit_type": "operational_process",
                    "title": "AGV removal with tote requires hospital tote removal",
                    "systems": ["AGV", "RMS", "Hospital"],
                    "components": ["tote"],
                    "operational_problem_area": "AGV tote state recovery",
                    "summary": "When an AGV with a tote is removed, the tote must be removed at the hospital before the AGV/tote state is reintroduced.",
                    "observed_evidence": ["Remove the AGV, then remove the tote at the hospital."],
                    "speaker_explanation": "Trainer explains AGV and tote removal ordering.",
                    "slide_text_evidence": ["AGV", "Tote", "Hospital"],
                    "visual_evidence_summary": "Training screen references AGV/tote state.",
                    "relationships": [
                        {
                            "subject": "AGV removal",
                            "relationship": "requires",
                            "object": "tote removal at hospital",
                            "evidence_refs": [scene["scene_id"]],
                        }
                    ],
                    "evidence_chunk_refs": scene["evidence_chunk_refs"],
                    "artifact_refs": scene["artifact_refs"],
                    "source_refs": evidence_chunks[0]["source_refs"],
                    "retrieval_text": "AGV removal tote removal hospital RMS reintroduced state",
                    "validation_status": "needs_review",
                }
            ],
            "procedure_candidate_attempts": [
                {
                    "procedure_id": "proc_agv_tote_removal",
                    "source_scene_id": scene["scene_id"],
                    "title": "Remove AGV with tote",
                    "procedure_type": "operational_action",
                    "components": ["tote"],
                    "systems": ["AGV", "RMS", "Hospital"],
                    "steps": [
                        {
                            "step_order": 1,
                            "instruction": "Remove the AGV from RMS.",
                            "timestamp_start": evidence_chunks[0]["timestamp_start"],
                            "timestamp_end": evidence_chunks[0]["timestamp_end"],
                            "expected_outcome": "AGV is removed from active RMS handling.",
                            "validation_check": "Confirm AGV is no longer active in RMS.",
                            "artifact_refs": evidence_chunks[0]["artifact_ids"],
                            "evidence_chunk_refs": [evidence_chunks[0]["chunk_id"]],
                        },
                        {
                            "step_order": 2,
                            "instruction": "Remove the tote at the hospital.",
                            "timestamp_start": evidence_chunks[1]["timestamp_start"],
                            "timestamp_end": evidence_chunks[1]["timestamp_end"],
                            "expected_outcome": "Tote is cleared from the removed AGV state.",
                            "validation_check": "Confirm tote state is cleared before reintroducing AGV/tote state.",
                            "artifact_refs": evidence_chunks[1]["artifact_ids"],
                            "evidence_chunk_refs": [evidence_chunks[1]["chunk_id"]],
                        },
                    ],
                    "source_video": video_id,
                    "source_refs": evidence_chunks[0]["source_refs"] + evidence_chunks[1]["source_refs"],
                    "retrieval_text": "Remove AGV with tote remove tote at hospital validate RMS state",
                }
            ],
        }

    monkeypatch.setattr(video_structure_agent.LLMRecordExtractor, "extract", fake_extract)

    _, _, review_dir = run_agent(tmp_path, segments=procedure_segments())

    knowledge_units = json.loads((review_dir / "operational_knowledge_units.json").read_text(encoding="utf-8"))
    context_candidates = json.loads((review_dir / "context_record_candidates.json").read_text(encoding="utf-8"))
    procedure_candidates = json.loads((review_dir / "procedure_dictionary_candidates.json").read_text(encoding="utf-8"))

    assert knowledge_units[0]["title"] == "AGV removal with tote requires hospital tote removal"
    assert context_candidates[0]["title"] == knowledge_units[0]["title"]
    assert procedure_candidates[0]["title"] == "Remove AGV with tote"
    assert all(record["validation_status"] == "needs_review" for record in knowledge_units + context_candidates + procedure_candidates)


def test_video_structure_agent_refuses_to_overwrite_without_force(tmp_path):
    video_id = "training_video"
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "out"
    review_dir = tmp_path / "review"
    create_video_evidence(input_dir, video_id, conceptual_segments())

    run_video_evidence_structuring(video_id, input_dir, output_dir, review_dir, force=True, llm_config=None, allow_local_fallback=True)

    with pytest.raises(VideoStructuringError, match="Refusing to overwrite"):
        run_video_evidence_structuring(video_id, input_dir, output_dir, review_dir, llm_config=None, allow_local_fallback=True)


def test_video_structure_agent_rejects_context_reference_output_target(tmp_path):
    video_id = "training_video"
    input_dir = tmp_path / "input"
    create_video_evidence(input_dir, video_id, conceptual_segments())

    with pytest.raises(VideoStructuringError, match="context_reference"):
        run_video_evidence_structuring(
            video_id=video_id,
            input_dir=input_dir,
            output_dir=Path("data/context"),
            review_dir=tmp_path / "review",
            force=True,
            llm_config=None,
        )
