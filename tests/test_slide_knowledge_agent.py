import json
from pathlib import Path

import pytest

from scripts import slide_knowledge_agent
from scripts.slide_knowledge_agent import (
    ContextCandidateBuilder,
    LLMSlideKnowledgeExtractor,
    LoadedSlide,
    ProcedureCandidateBuilder,
    SlideKnowledgeError,
    SlideKnowledgeValidator,
    run_slide_knowledge_extraction,
)


class FakeSlideDeckLoader:
    def __init__(
        self,
        source_pdf: Path,
        image_dir: Path,
        limit_slides: int | None = None,
        start_slide: int | None = None,
        end_slide: int | None = None,
        enable_ocr: bool = False,
    ) -> None:
        self.limit_slides = limit_slides
        self.start_slide = start_slide
        self.end_slide = end_slide

    def load(self) -> list[LoadedSlide]:
        slides = [
            LoadedSlide(1, ["Robot Selection - Add and Remove", "Enter the corresponding robot ID.", "Click Add.", "System shows operation was successful."], "slide_0001.png", {}),
            LoadedSlide(2, ["Robot Selection - Restart Robot", "Enter robot ID.", "Click Restart.", "Check robot returns to service."], "slide_0002.png", {}),
            LoadedSlide(3, ["Go-to function", "Select target AGV.", "Enter destination.", "Click Go-to."], "slide_0003.png", {}),
            LoadedSlide(4, ["Services - Unplanned restart", "RDP into primary.", "Check SSMS connectivity.", "Check tipper heartbeat.", "Check Stunnel connections.", "Confirm RMS loads.", "Check SQL Server Agent on backup server."], "slide_0004.png", {}),
            LoadedSlide(5, ["AGVs", "Geek+ AGVs operate over QR codes and are directly controlled by Geek+ RMS."], "slide_0005.png", {}),
            LoadedSlide(6, ["Tipping", "Assignment is round-robin across available enabled tippers serviced by the queue."], "slide_0006.png", {}),
            LoadedSlide(7, ["APIs - AGVs", "ExecutedAgvCommand requires robotId and helps during unplanned restarts when OptiSweep missed callbacks from Geek+."], "slide_0007.png", {}),
        ]
        if self.limit_slides:
            return slides[: self.limit_slides]
        return slides


class ScriptedLLMExtractor:
    def __init__(self, config_path: Path | None, cache_dir: Path, allow_local_fallback: bool = False, mode: str = "full") -> None:
        self.llm_status = "scripted_llm"
        self.llm_error = ""

    def extract(self, deck_id: str, artifacts: list[dict]) -> dict[str, list[dict]]:
        units: list[dict] = []
        procedures: list[dict] = []
        for artifact in artifacts:
            title = artifact["slide_title"]
            slide = artifact["slide_number"]
            artifact_refs = [artifact["artifact_id"]]
            if "Add and Remove" in title:
                procedures.append(
                    procedure(
                        deck_id,
                        "Add robot in Geek+ RMS",
                        "operational_action",
                        slide,
                        artifact_refs,
                        ["Geek+ RMS", "AGV"],
                        ["robot"],
                        [
                            step(1, "Enter the corresponding robot ID.", "Robot ID is populated in the robot control field.", "Confirm the entered robot ID matches the target AGV.", "robot ID field"),
                            step(2, "Click Add.", "The system submits the add robot request.", "Check that the system shows the adding operation was successful.", "Add button"),
                        ],
                    )
                )
            elif "Restart Robot" in title:
                procedures.append(
                    procedure(
                        deck_id,
                        "Restart robot in Geek+ RMS",
                        "recovery_action",
                        slide,
                        artifact_refs,
                        ["Geek+ RMS", "AGV"],
                        ["robot"],
                        [
                            step(1, "Enter the corresponding robot ID.", "Robot ID is populated for restart.", "Confirm the robot ID matches the target AGV.", "robot ID field"),
                            step(2, "Click Restart.", "The restart request is submitted.", "Check the robot returns to service.", "Restart button"),
                        ],
                    )
                )
            elif "Go-to function" in title:
                procedures.append(
                    procedure(
                        deck_id,
                        "Send robot to a destination with Go-to",
                        "navigation",
                        slide,
                        artifact_refs,
                        ["Geek+ RMS", "AGV"],
                        ["Go-to function"],
                        [
                            step(1, "Select the target AGV.", "The target AGV is selected.", "Confirm the selected AGV is the intended robot.", "AGV selector"),
                            step(2, "Enter the destination.", "Destination is populated.", "Confirm the destination is correct.", "destination field"),
                            step(3, "Click Go-to.", "The system submits the movement command.", "Check the robot begins routing to the target destination.", "Go-to button"),
                        ],
                    )
                )
            elif "Unplanned restart" in title:
                procedures.append(
                    procedure(
                        deck_id,
                        "Validate OptiSweep services after unplanned restart",
                        "service_restart",
                        slide,
                        artifact_refs,
                        ["OptiSweep", "Ignition", "Stunnel", "RMS", "SQL Server"],
                        ["primary server", "backup server", "tipper heartbeat"],
                        [
                            step(1, "RDP into fortna-wcs-primary.txrth.otnet.ups.com.", "Primary WCS server session is available.", "Confirm login succeeds.", "primary server RDP target"),
                            step(2, "Open SQL Server Management Studio and verify database connectivity.", "SQL Server connection succeeds.", "Confirm SSMS can connect.", "SSMS connection window"),
                            step(3, "Check that tippers are receiving heartbeat by opening the tipper web interface.", "Tipper heartbeat is active.", "If heartbeat is flatlined, restart the OptiSweep service.", "tipper heartbeat screen"),
                            step(4, "Open Stunnel and check Connections under the File menu.", "AI01, AI02, and SortationChat connections are present.", "Confirm all three expected connections are listed.", "Stunnel File menu"),
                            step(5, "Log into RMS and confirm the screen loads before UPS removes the master E-stop.", "RMS monitor loads successfully.", "Confirm RMS screen is visible before master E-stop removal.", "RMS monitor screen"),
                            step(6, "RDP into fortna-wcs-backup.txrth.otnet.ups.com and confirm SQL Server Agent is running.", "Backup server SQL Server Agent is running.", "Check SQL Server Configuration Manager.", "SQL Server Configuration Manager"),
                        ],
                    )
                )
            elif title.startswith("AGVs"):
                units.append(
                    knowledge_unit(
                        deck_id,
                        "Geek+ RMS directly controls AGV movement",
                        "architecture_relationship",
                        slide,
                        artifact_refs,
                        ["Geek+ RMS", "AGV"],
                        ["QR codes", "collision sensors"],
                        "Geek+ AGVs operate over QR codes and are directly controlled by Geek+ RMS.",
                        [{"subject": "Geek+ RMS", "relationship": "directly_controls", "object": "AGV movement", "evidence_refs": [f"slide:{slide}"]}],
                    )
                )
            elif title.startswith("Tipping"):
                units.append(
                    knowledge_unit(
                        deck_id,
                        "Tipper assignment uses round-robin across available enabled tippers",
                        "routing_rule",
                        slide,
                        artifact_refs,
                        ["OptiSweep", "Tipper", "AGV"],
                        ["sorter exit queue", "tipper entrance queue"],
                        "A full tote on an AGV is assigned round-robin across available enabled tippers serviced by the queue.",
                        [{"subject": "full tote AGV", "relationship": "assigned_to", "object": "available enabled tipper", "evidence_refs": [f"slide:{slide}"]}],
                    )
                )
            elif "APIs" in title:
                units.append(
                    knowledge_unit(
                        deck_id,
                        "ExecutedAgvCommand recovers missed Geek+ callbacks after unplanned restart",
                        "api_capability",
                        slide,
                        artifact_refs,
                        ["OptiSweep API", "Geek+ RMS", "AGV"],
                        ["ExecutedAgvCommand"],
                        "ExecutedAgvCommand requires a robot ID and executes the active command the AGV has after missed Geek+ callbacks.",
                        [{"subject": "ExecutedAgvCommand", "relationship": "requires", "object": "robotId", "evidence_refs": [f"slide:{slide}"]}],
                    )
                )
        return {"operational_knowledge_units": units, "procedure_candidate_attempts": procedures, "discarded_candidates": []}

    def extract_slide(self, deck_id: str, artifact: dict) -> dict[str, list[dict]]:
        return self.extract(deck_id, [artifact])


class FailingAfterFirstSlideExtractor(ScriptedLLMExtractor):
    def __init__(self, config_path: Path | None, cache_dir: Path, allow_local_fallback: bool = False, mode: str = "full") -> None:
        super().__init__(config_path, cache_dir, allow_local_fallback, mode)
        self.calls = 0

    def extract_slide(self, deck_id: str, artifact: dict) -> dict[str, list[dict]]:
        self.calls += 1
        if self.calls == 2:
            raise SlideKnowledgeError("simulated slide failure")
        return super().extract_slide(deck_id, artifact)


def step(order: int, instruction: str, expected: str, validation: str, visual_region_hint: str = "") -> dict:
    return {
        "step_order": order,
        "instruction": instruction,
        "expected_outcome": expected,
        "validation_check": validation,
        "visual_region_hint": visual_region_hint,
    }


def procedure(deck_id: str, title: str, procedure_type: str, slide: int, artifact_refs: list[str], systems: list[str], components: list[str], steps: list[dict]) -> dict:
    return {
        "title": title,
        "procedure_type": procedure_type,
        "source_deck": deck_id,
        "source_slide_numbers": [slide],
        "artifact_refs": artifact_refs,
        "systems": systems,
        "components": components,
        "role_required": "unknown",
        "support_safe": "unknown",
        "preconditions": [],
        "steps": steps,
        "warnings": [],
        "related_context_refs": [],
        "retrieval_text": f"{title} " + " ".join(item["instruction"] for item in steps),
    }


def knowledge_unit(deck_id: str, title: str, unit_type: str, slide: int, artifact_refs: list[str], systems: list[str], components: list[str], summary: str, relationships: list[dict]) -> dict:
    return {
        "knowledge_unit_id": f"ku_{slide}",
        "deck_id": deck_id,
        "source_slide_numbers": [slide],
        "artifact_refs": artifact_refs,
        "unit_type": unit_type,
        "title": title,
        "systems": systems,
        "components": components,
        "summary": summary,
        "observed_evidence": [summary],
        "relationships": relationships,
        "retrieval_text": f"{title} {summary}",
        "validation_status": "needs_review",
    }


@pytest.fixture()
def scripted_run(monkeypatch, tmp_path):
    monkeypatch.setattr(slide_knowledge_agent, "SlideDeckLoader", FakeSlideDeckLoader)
    monkeypatch.setattr(slide_knowledge_agent, "LLMSlideKnowledgeExtractor", ScriptedLLMExtractor)
    source_pdf = tmp_path / "OptiSweep Training Slides [INTERNAL ONLY].pdf"
    source_pdf.write_bytes(b"fake")
    review_dir = tmp_path / "data" / "review" / "slides" / "optisweep_training_internal"
    result = run_slide_knowledge_extraction(
        source_pdf=source_pdf,
        deck_id="optisweep_training_internal",
        review_dir=review_dir,
        llm_config=tmp_path / "config.json",
        force=True,
    )
    return result, review_dir, tmp_path


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_procedure_extraction_from_add_robot_slide(scripted_run):
    _, review_dir, _ = scripted_run
    procedures = read_json(review_dir / "procedure_dictionary_candidates.json")

    add_robot = next(record for record in procedures if record["title"] == "Add robot in Geek+ RMS")

    assert add_robot["procedure_type"] == "operational_action"
    assert add_robot["systems"] == ["Geek+ RMS", "AGV"]
    assert [step["instruction"] for step in add_robot["steps"]] == ["Enter the corresponding robot ID.", "Click Add."]
    assert add_robot["procedure_screenshot_refs"] == ["slide_artifact_optisweep_training_internal_0001"]
    assert add_robot["procedure_visual_summary"]
    assert add_robot["steps"][1]["screenshot_refs"] == ["slide_artifact_optisweep_training_internal_0001"]
    assert add_robot["steps"][1]["visual_region_hint"] == "Add button"
    assert add_robot["validation_status"] == "needs_review"


def test_procedure_extraction_from_restart_robot_slide(scripted_run):
    _, review_dir, _ = scripted_run
    procedures = read_json(review_dir / "procedure_dictionary_candidates.json")

    restart = next(record for record in procedures if record["title"] == "Restart robot in Geek+ RMS")

    assert restart["procedure_type"] == "recovery_action"
    assert restart["source_slide_numbers"] == [2]
    assert restart["procedure_screenshot_refs"] == ["slide_artifact_optisweep_training_internal_0002"]
    assert restart["steps"][1]["validation_check"] == "Check the robot returns to service."
    assert restart["steps"][1]["visual_region_hint"] == "Restart button"


def test_procedure_extraction_from_go_to_function_slide(scripted_run):
    _, review_dir, _ = scripted_run
    procedures = read_json(review_dir / "procedure_dictionary_candidates.json")

    go_to = next(record for record in procedures if record["title"] == "Send robot to a destination with Go-to")

    assert go_to["procedure_type"] == "navigation"
    assert len(go_to["steps"]) == 3
    assert go_to["steps"][2]["instruction"] == "Click Go-to."
    assert go_to["steps"][2]["screenshot_refs"] == ["slide_artifact_optisweep_training_internal_0003"]
    assert go_to["steps"][2]["visual_region_hint"] == "Go-to button"


def test_procedure_extraction_from_unplanned_restart_slides(scripted_run):
    _, review_dir, _ = scripted_run
    procedures = read_json(review_dir / "procedure_dictionary_candidates.json")

    restart = next(record for record in procedures if record["title"] == "Validate OptiSweep services after unplanned restart")

    assert restart["procedure_type"] == "service_restart"
    assert "Stunnel" in restart["systems"]
    assert restart["procedure_screenshot_refs"] == ["slide_artifact_optisweep_training_internal_0004"]
    assert len(restart["steps"]) == 6
    assert restart["steps"][5]["validation_check"] == "Check SQL Server Configuration Manager."
    assert restart["steps"][3]["visual_region_hint"] == "Stunnel File menu"


def test_context_extraction_from_agv_architecture_slide(scripted_run):
    _, review_dir, _ = scripted_run
    units = read_json(review_dir / "operational_knowledge_unit_candidates.json")
    contexts = read_json(review_dir / "context_record_candidates.json")

    unit = next(record for record in units if record["title"] == "Geek+ RMS directly controls AGV movement")
    context = next(record for record in contexts if record["knowledge_unit_refs"] == [unit["knowledge_unit_id"]])

    assert unit["unit_type"] == "architecture_relationship"
    assert context["context_type"] == "architecture_reference"
    assert unit["relationships"][0]["relationship"] == "directly_controls"


def test_context_extraction_from_tipping_round_robin_slide(scripted_run):
    _, review_dir, _ = scripted_run
    units = read_json(review_dir / "operational_knowledge_unit_candidates.json")

    tipping = next(record for record in units if record["title"] == "Tipper assignment uses round-robin across available enabled tippers")

    assert tipping["unit_type"] == "routing_rule"
    assert "round-robin" in tipping["summary"]
    assert tipping["validation_status"] == "needs_review"


def test_api_capability_context_from_executed_agv_command_slide(scripted_run):
    _, review_dir, _ = scripted_run
    units = read_json(review_dir / "operational_knowledge_unit_candidates.json")
    contexts = read_json(review_dir / "context_record_candidates.json")

    api_unit = next(record for record in units if "ExecutedAgvCommand" in record["title"])
    api_context = next(record for record in contexts if record["knowledge_unit_refs"] == [api_unit["knowledge_unit_id"]])

    assert api_unit["unit_type"] == "api_capability"
    assert api_context["context_type"] == "api_reference"
    assert read_json(review_dir / "procedure_dictionary_candidates.json")
    assert not any(record["procedure_type"] == "api_action" for record in read_json(review_dir / "procedure_dictionary_candidates.json"))


def test_rejects_broad_titles_like_agv_training_slide_reference():
    validator = SlideKnowledgeValidator()
    units, contexts, procedures, discards = validator.validate_all(
        Path("review"),
        [
            {
                "knowledge_unit_id": "ku_bad",
                "source_slide_numbers": [1],
                "unit_type": "system_behavior",
                "title": "AGV training slide reference",
                "summary": "Too broad.",
                "retrieval_text": "Too broad.",
                "validation_status": "needs_review",
            }
        ],
        [
            {
                "context_id": "ctx_bad",
                "context_type": "operational_concept",
                "title": "AGV training slide reference",
                "source_refs": ["slide:1"],
                "retrieval_text": "Too broad.",
                "validation_status": "needs_review",
            }
        ],
        [],
    )

    assert units == []
    assert contexts == []
    assert procedures == []
    assert {discard["candidate_type"] for discard in discards} == {"knowledge_unit", "context"}
    assert all("broad_topic_title" in discard["failed_rules"] for discard in discards)


def test_rejects_empty_and_vague_procedure():
    validator = SlideKnowledgeValidator()
    procedures = ProcedureCandidateBuilder().build(
        "deck",
        [
            {
                "title": "Robot Selection",
                "procedure_type": "operational_action",
                "source_slide_numbers": [1],
                "systems": ["Geek+ RMS"],
                "steps": [],
            },
            {
                "title": "Restart robot vaguely",
                "procedure_type": "recovery_action",
                "source_slide_numbers": [2],
                "artifact_refs": ["slide_artifact_deck_0002"],
                "systems": ["Geek+ RMS"],
                "steps": [{"instruction": "Use APIs."}],
            },
        ],
    )

    _, _, accepted, discards = validator.validate_all(Path("review"), [], [], procedures)

    assert accepted == []
    assert len(discards) == 2
    assert any("missing_steps" in discard["failed_rules"] for discard in discards)
    assert any("vague_steps" in discard["failed_rules"] for discard in discards)


def test_no_direct_dataset0_writes_all_outputs_need_review_and_promotion_false(scripted_run):
    result, review_dir, tmp_path = scripted_run

    assert result["dataset0_write_ran"] is False
    assert not (tmp_path / "data" / "context" / "context_reference.json").exists()
    assert not (tmp_path / "data" / "procedures" / "procedure_dictionary.json").exists()

    for file_name in [
        "slide_artifact_records.json",
        "operational_knowledge_unit_candidates.json",
        "context_record_candidates.json",
        "procedure_dictionary_candidates.json",
    ]:
        records = read_json(review_dir / file_name)
        assert records
        assert all(record["validation_status"] == "needs_review" for record in records)

    procedures = read_json(review_dir / "procedure_dictionary_candidates.json")
    assert all(record["procedure_screenshot_refs"] for record in procedures)
    assert all(step["screenshot_refs"] for record in procedures for step in record["steps"])

    report = read_json(review_dir / "extraction_report.json")
    manifest = read_json(review_dir / "promotion_review_manifest.json")
    assert report["validation_status"] == "needs_review"
    assert manifest["promotion_allowed"] is False
    assert manifest["dataset0_write_ran"] is False


def test_llm_required_without_explicit_local_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(slide_knowledge_agent, "SlideDeckLoader", FakeSlideDeckLoader)
    source_pdf = tmp_path / "slides.pdf"
    source_pdf.write_bytes(b"fake")
    review_dir = tmp_path / "review"

    with pytest.raises(SlideKnowledgeError, match="LLM slide extraction requires"):
        run_slide_knowledge_extraction(source_pdf, "deck", review_dir, force=True)

    report = read_json(review_dir / "extraction_report.json")
    assert report["llm_status"] == "failed"
    assert report["failed_slide_number"] == 1
    assert read_json(review_dir / "procedure_dictionary_candidates.json") == []


def test_partial_outputs_are_written_when_later_slide_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(slide_knowledge_agent, "SlideDeckLoader", FakeSlideDeckLoader)
    monkeypatch.setattr(slide_knowledge_agent, "LLMSlideKnowledgeExtractor", FailingAfterFirstSlideExtractor)
    source_pdf = tmp_path / "slides.pdf"
    source_pdf.write_bytes(b"fake")
    review_dir = tmp_path / "review"

    with pytest.raises(SlideKnowledgeError, match="simulated slide failure"):
        run_slide_knowledge_extraction(
            source_pdf=source_pdf,
            deck_id="optisweep_training_internal",
            review_dir=review_dir,
            llm_config=tmp_path / "config.json",
            force=True,
        )

    report = read_json(review_dir / "extraction_report.json")
    artifacts = read_json(review_dir / "slide_artifact_records.json")
    procedures = read_json(review_dir / "procedure_dictionary_candidates.json")
    manifest = read_json(review_dir / "promotion_review_manifest.json")

    assert report["llm_status"] == "failed"
    assert report["last_completed_slide"] == 1
    assert report["failed_slide_number"] == 2
    assert artifacts
    assert [record["title"] for record in procedures] == ["Add robot in Geek+ RMS"]
    assert manifest["promotion_allowed"] is False
