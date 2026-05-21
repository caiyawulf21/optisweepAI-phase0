import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.seed.issue_category_context import category_for_case, issue_category_context

SOURCE_OCR_PATH = ROOT / "output" / "phase0" / "case_229716_docx" / "extracted" / "case_229716_docx_ocr.json"
SOURCE_ARTIFACT_DIR = ROOT / "output" / "phase0" / "case_229716_docx" / "artifacts" / "docx_media"
REFERENCE_EXTRACTION_PATH = ROOT / "output" / "phase0" / "case_229716_docx" / "extracted" / "reference_docx_extraction.json"
PHASE0_PROMPT_PATH = ROOT / "prompts" / "phase0_system_prompt.txt"
ISSUE_CATEGORY_DOC_PATH = ROOT / "docs" / "Optisweep Issue Categories.docx"
OUTPUT_DIR = ROOT / "output" / "phase0" / "case_229716_docx_v2"
EXTRACTED_DIR = OUTPUT_DIR / "extracted"
ARTIFACT_DIR = OUTPUT_DIR / "artifacts" / "docx_media"
EMBEDDED_ARTIFACT_DIR = OUTPUT_DIR / "artifacts" / "embedded_regions"
ACTIVE_SOURCE_FILE = "data/Case 229716 Data.docx"


def clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def bbox_from_poly(poly):
    xs = [point[0] for point in poly or []]
    ys = [point[1] for point in poly or []]
    if not xs or not ys:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def merge_bbox(boxes):
    boxes = [box for box in boxes if box]
    if not boxes:
        return None
    return [min(box[0] for box in boxes), min(box[1] for box in boxes), max(box[2] for box in boxes), max(box[3] for box in boxes)]


def line_center(line):
    box = bbox_from_poly(line.get("polygon"))
    if not box:
        return 0, 0
    return (box[1] + box[3]) / 2, (box[0] + box[2]) / 2


def noise_score(text, confidence):
    text = clean_text(text)
    if not text:
        return 1.0
    chars = len(text)
    non_ascii = sum(1 for char in text if ord(char) > 127)
    alpha = [char.lower() for char in text if char.isalpha()]
    vowels = sum(1 for char in alpha if char in "aeiou")
    vowel_ratio = vowels / max(1, len(alpha))
    tokens = text.split()
    short_ratio = sum(1 for token in tokens if len(token) <= 2) / max(1, len(tokens))
    confidence_penalty = 1 - (confidence or 0)
    non_ascii_penalty = min(0.35, non_ascii / max(1, chars))
    vowel_penalty = 0.25 if alpha and vowel_ratio < 0.18 else 0
    short_penalty = 0.25 if len(tokens) >= 5 and short_ratio > 0.65 else 0
    return round(min(1.0, confidence_penalty + non_ascii_penalty + vowel_penalty + short_penalty), 4)


def reconstruct_layout_blocks(ocr_data):
    pages = []
    for page in ocr_data["pages"]:
        rows = []
        sorted_lines = sorted(enumerate(page["ocr_lines"], start=1), key=lambda item: (line_center(item[1])[0], line_center(item[1])[1]))
        for line_index, line in sorted_lines:
            y_center, _ = line_center(line)
            box = bbox_from_poly(line.get("polygon"))
            placed = False
            for row in rows:
                if abs(row["y_center"] - y_center) <= 12:
                    row["items"].append((line_index, line, box))
                    centers = [line_center(item[1])[0] for item in row["items"]]
                    row["y_center"] = sum(centers) / len(centers)
                    placed = True
                    break
            if not placed:
                rows.append({"y_center": y_center, "items": [(line_index, line, box)]})
        blocks = []
        for row_index, row in enumerate(rows, start=1):
            items = sorted(row["items"], key=lambda item: line_center(item[1])[1])
            text = clean_text(" ".join(item[1]["text"] for item in items))
            confidences = [item[1].get("confidence") or 0 for item in items]
            block_id = f"layout_{page['page']:02d}_{row_index:03d}"
            blocks.append(
                {
                    "block_id": block_id,
                    "artifact_id": f"case_229716_docx_artifact_{page['page']:02d}",
                    "artifact_path": page["artifact_path"],
                    "source_section": page["source_section"],
                    "source_page": page["page"],
                    "bbox": merge_bbox([item[2] for item in items]),
                    "text": text,
                    "ocr_line_refs": [f"ocr_line={item[0]}" for item in items],
                    "confidence": round(sum(confidences) / max(1, len(confidences)), 4),
                    "noise_score": noise_score(text, sum(confidences) / max(1, len(confidences))),
                }
            )
        pages.append(
            {
                "source_page": page["page"],
                "source_section": page["source_section"],
                "artifact_id": f"case_229716_docx_artifact_{page['page']:02d}",
                "artifact_path": page["artifact_path"],
                "blocks": blocks,
            }
        )
    return {"source_file": ACTIVE_SOURCE_FILE, "pages": pages}


def line_text(page, start, end):
    return clean_text(" ".join(line["text"] for line in page["ocr_lines"][start - 1 : end]))


def line_refs(start, end):
    return [f"ocr_line={index}" for index in range(start, end + 1)]


def region(page, region_id, region_type, title, start, end, summary, role="primary_evidence", visual=False):
    lines = page["ocr_lines"][start - 1 : end]
    confidences = [line.get("confidence") or 0 for line in lines]
    boxes = [bbox_from_poly(line.get("polygon")) for line in lines]
    return {
        "region_id": region_id,
        "region_type": region_type,
        "title": title,
        "role": role,
        "source_file": ACTIVE_SOURCE_FILE,
        "source_section": page["source_section"],
        "source_page": page["page"],
        "source_ref": f"Case 229716 Data.docx#media=image{page['page']}.png:lines={start}-{end}",
        "artifact_id": f"case_229716_docx_artifact_{page['page']:02d}",
        "artifact_path": page["artifact_path"],
        "bbox": merge_bbox(boxes),
        "text": line_text(page, start, end),
        "ocr_line_refs": line_refs(start, end),
        "confidence": round(sum(confidences) / max(1, len(confidences)), 4),
        "noise_score": noise_score(line_text(page, start, end), sum(confidences) / max(1, len(confidences))),
        "visual_evidence": visual,
        "visual_evidence_summary": summary,
    }


def classify_regions(ocr_data):
    by_page = {page["page"]: page for page in ocr_data["pages"]}
    regions = [
        region(by_page[1], "region_sf_case_created", "salesforce_case_update", "Case created and initial metadata", 2, 12, "Salesforce shows case 00229716 created by Gianny D Perez Rocha with subject Problems with the ACD system, UPS Fort Worth Haslet, New status, and medium priority."),
        region(by_page[1], "region_sf_status_updates", "salesforce_status_update", "Initial status transitions and escalation request", 13, 43, "Salesforce updates show New to In Progress, escalation request to internal recipients, and opened date 4/15/2026 7:40 PM."),
        region(by_page[2], "region_sf_escalation_questions", "salesforce_case_fields", "Escalation question block", 1, 14, "Escalation questions identify ACD System as the location and report that nothing is coming to the tippers."),
        region(by_page[2], "region_sf_l2_engaged", "salesforce_case_update", "L2 engaged and site contact", 19, 24, "Gianny notes Justin McCalmont L2 is engaged and will connect to site; Antonio Rodrigo is listed as point of contact."),
        region(by_page[3], "region_sf_symptom_narrative", "salesforce_case_update", "Detailed symptom narrative", 1, 7, "Justin reports sort had just started, AGVs lined up to go to tippers, all three lines stopped, hospital tote removal failed, tippers show heartbeat timeout active, tippers enabled, and no RMS faults."),
        region(by_page[3], "region_visual_rms_map", "embedded_operational_screenshot", "RMS map monitor screenshot", 8, 60, "Embedded RMS/remote desktop visual evidence is present but OCR is noisy; retain as visual support for the symptom narrative.", role="visual_support", visual=True),
        region(by_page[4], "region_visual_tipper_alarms", "embedded_operational_screenshot", "Tipper alarms and heartbeat screenshots", 1, 88, "Ignition/RMS screenshots show tipper alarms, heartbeat/status details, and webvisu pages; OCR is partially noisy but visually relevant.", role="visual_support", visual=True),
        region(by_page[4], "region_sf_resolution_update", "salesforce_case_update", "Resolution and case status updates", 89, 109, "Justin reports that per Mitchell Flynn the system was E-stopped and Optisweep service restarted; Antonio confirmed AVG operation and hospital function; server event and Ignition logs were downloaded; status moved to resolved and closed."),
        region(by_page[5], "region_sf_closure_summary", "salesforce_closure_summary", "Closed case summary", 1, 31, "Salesforce closure summary includes account, contact, affected asset, opened/resolved dates, priority, symptoms, and resolution details."),
        region(by_page[6], "region_visual_opc_noise", "embedded_operational_screenshot", "OPC/connection diagnostic screenshot", 1, 96, "Large operational screenshot with OPC/connection data; OCR is low-confidence and should be retained as visual evidence rather than promoted into procedure text.", role="visual_support", visual=True),
        region(by_page[7], "region_teams_restart_decision", "teams_message_thread", "Restart decision and instructions", 1, 26, "Teams thread asks if services are being reset; Mitchel asks for heartbeat statistics, instructs E-stop AGVs, restart service, remove E-stop, collect event or DB logs, and confirms Optisweep restart."),
        region(by_page[7], "region_visual_hb_statistics", "embedded_operational_screenshot", "Heartbeat statistics screenshot", 6, 19, "Embedded RMS/Ignition screenshot showing heartbeat/statistics context inside the Teams thread.", role="visual_support", visual=True),
        region(by_page[8], "region_teams_services_window", "teams_message_thread", "Services window and performance monitor request", 1, 97, "Teams thread confirms restart Optisweep versus Ignition OPC, includes a Windows services screenshot, and asks for performance monitor screenshot for logs."),
        region(by_page[8], "region_visual_windows_services", "embedded_operational_screenshot", "Windows services screenshot", 6, 94, "Embedded Windows Services screenshot used as visual evidence around the Optisweep restart discussion.", role="visual_support", visual=True),
        region(by_page[9], "region_teams_prior_fix", "teams_message_thread", "Prior fix and remote-in coordination", 1, 20, "Teams thread states prior fix was resetting services, plans to reset all services before preload/daysort, and Justin says he will remote in and connect to site."),
        region(by_page[10], "region_teams_initial_report", "teams_message_thread", "Initial Haslet outage report", 1, 17, "Teams thread reports Haslet down, ACD system problems, CBRE number, everything waiting, no path, and nothing coming to tippers; Justin says he will remote in."),
        region(by_page[11], "region_visual_performance_monitor", "embedded_operational_screenshot", "Performance monitor visual evidence", 1, 33, "Performance monitor/system overview screenshot is present; retain as visual evidence and do not promote noisy numeric OCR into procedural text.", role="visual_support", visual=True),
        region(by_page[11], "region_teams_recovery_confirmation", "teams_message_thread", "Recovery confirmation and log request", 34, 42, "Teams thread says AVGs are moving, hospital tote removal works after logout/login, system is operational, and Mitchel asks to add DB/event logs and switch-log follow-up."),
        region(by_page[12], "region_teams_log_collection", "teams_message_thread", "Log collection handoff", 1, 9, "Justin reports Ignition and Windows event logs saved to RDP desktop and notes DB log transfer uncertainty; Kevin thanks the team."),
        region(by_page[12], "region_visual_saved_logs", "embedded_operational_screenshot", "Saved log files screenshot", 2, 5, "Embedded RDP desktop screenshot shows saved Ignition/event log files associated with the log collection handoff.", role="visual_support", visual=True),
    ]
    return {"source_file": ACTIVE_SOURCE_FILE, "regions": regions}


def base_record(record_type, source_section, source_page, source_ref, confidence, missing_fields, notes):
    return {
        "record_type": record_type,
        "incident_id": "229716",
        "source_file": ACTIVE_SOURCE_FILE,
        "source_section": source_section,
        "source_page": source_page,
        "source_ref": source_ref,
        "confidence": confidence,
        "validation_status": "candidate_extracted",
        "requires_manual_review": True,
        "missing_fields": missing_fields,
        "extraction_notes": notes,
    }


def clamp_bbox(bbox, width, height, padding=8):
    if not bbox:
        return None
    left = max(0, int(bbox[0]) - padding)
    top = max(0, int(bbox[1]) - padding)
    right = min(width, int(bbox[2]) + padding)
    bottom = min(height, int(bbox[3]) + padding)
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def create_embedded_region_artifacts(regions):
    EMBEDDED_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for region_data in regions["regions"]:
        if not region_data.get("visual_evidence"):
            continue
        source_path = ROOT / region_data["artifact_path"]
        if not source_path.exists():
            continue
        with Image.open(source_path) as image:
            crop_box = clamp_bbox(region_data.get("bbox"), image.width, image.height)
            if not crop_box:
                continue
            cropped = image.crop(crop_box)
            embedded_id = f"case_229716_embedded_{region_data['region_id'].replace('region_', '')}"
            target_path = EMBEDDED_ARTIFACT_DIR / f"{embedded_id}.png"
            cropped.save(target_path)
        region_data["embedded_artifact_id"] = embedded_id
        region_data["embedded_artifact_type"] = "embedded_screenshot_region"
        region_data["embedded_artifact_path"] = str(target_path.relative_to(ROOT)).replace("\\", "/")
        region_data["embedded_parent_artifact_id"] = region_data["artifact_id"]
        region_data["embedded_parent_artifact_path"] = region_data["artifact_path"]
    return regions


def refs_for(regions, ids):
    selected = [region for region in regions if region["region_id"] in ids]
    artifact_ids = sorted({region["artifact_id"] for region in selected})
    artifact_paths = sorted({region["artifact_path"] for region in selected})
    embedded_ids = sorted({region["embedded_artifact_id"] for region in selected if region.get("embedded_artifact_id")})
    embedded_paths = sorted({region["embedded_artifact_path"] for region in selected if region.get("embedded_artifact_path")})
    artifact_ids = sorted(set(artifact_ids + embedded_ids))
    artifact_paths = sorted(set(artifact_paths + embedded_paths))
    region_refs = [region["region_id"] for region in selected]
    source_pages = sorted({region["source_page"] for region in selected})
    return selected, artifact_ids, artifact_paths, embedded_ids, embedded_paths, region_refs, source_pages


SIGNAL_BUCKETS = ["observed_failure_signals", "diagnostic_signals", "action_signals", "recovery_validation_signals", "escalation_signals"]
ALLOWED_RAW_SOURCE_TYPES = {"salesforce_case", "teams_chat", "rca_doc", "confluence_kba", "visual_artifact", "spreadsheet", "log_file", "sop"}
ALLOWED_EVIDENCE_TYPES = {"symptom", "diagnostic", "action", "validation", "escalation", "resolution", "log_collection", "status_change", "context"}
ALLOWED_PROCEDURE_CATEGORIES = {"diagnostic_check", "service_restart", "log_collection", "recovery_validation", "status_update", "site_coordination", "visual_evidence_review"}


def signal_buckets(failure=None, diagnostic=None, action=None, recovery=None, escalation=None):
    return {
        "observed_failure_signals": failure or [],
        "diagnostic_signals": diagnostic or [],
        "action_signals": action or [],
        "recovery_validation_signals": recovery or [],
        "escalation_signals": escalation or [],
    }


def review_fields(role_constraints=None, required_permissions=None):
    return {
        "role_constraints": role_constraints or [],
        "required_permissions": required_permissions or [],
        "requires_role_review": True,
    }


def dataset_context_packet(reference):
    paragraphs = reference.get("paragraphs", [])
    wanted = ["Dataset 0", "Dataset 1", "Dataset 1.5", "Dataset 2", "Dataset 5", "Source Artifact Strategy", "Initial Taxonomy", "Design Principles"]
    snippets = [text for text in paragraphs if any(marker in text for marker in wanted)][:24]
    category_context = issue_category_context(ISSUE_CATEGORY_DOC_PATH)
    return {
        "source": "docs/Phase0 Cat1 Dataset Seed Records V1.docx",
        "category_context_source": "docs/Optisweep Issue Categories.docx",
        "active_scope": category_for_case("229716", category_context),
        "issue_category_context": category_context,
        "deterministic_issue_category": category_for_case("229716", category_context),
        "dataset_layers": [
            "Dataset 0 - Context / Domain Reference",
            "Dataset 1 - Canonical Incident Records",
            "Dataset 1.5 - Incident Timeline Events",
            "Dataset 2A - Workflow Definitions",
            "Dataset 2B - Reusable Procedure Dictionary",
            "Dataset 5 - Escalation Summaries",
            "Source Artifact Strategy",
        ],
        "support_tier_context": {
            "L1_technical_support": ["ticket intake", "triage", "evidence gathering", "severity validation", "routing"],
            "L2_L3_software_support": ["advanced troubleshooting", "production issue recovery", "customer escalation handling"],
            "L2_L3_infrastructure_controls_dba_devops": ["servers", "databases", "networking", "OT infrastructure", "controls"],
            "L4_engineering_project_team": ["software fixes", "patches", "permanent corrective actions"],
        },
        "taxonomy_constraints": [
            "Use source-provided issue categories only.",
            "CAT-1 through CAT-4 are authoritative category context, not keyword matching rules.",
            "Validated workflows, procedures, escalation thresholds, ownership rules, support-safe boundaries, and root-cause relationships must not be inferred in Phase 0.",
        ],
        "design_principles": [
            "Operational signatures are more important than case IDs.",
            "Keep evidence separate from conclusions.",
            "Workflows should be built from timelines and procedures.",
            "Raw evidence must remain traceable.",
            "Do not overbuild Phase 0.",
        ],
        "reference_snippets_used": snippets,
    }


def interpretation_payload(prompt_text, reference):
    dataset_context = dataset_context_packet(reference)
    return {
        "interpreter": "cursor_llm_cached_v2",
        "prompt_source": "prompts/phase0_system_prompt.txt",
        "reference_source": "docs/Phase0 Cat1 Dataset Seed Records V1.docx",
        "category_reference_source": "docs/Optisweep Issue Categories.docx",
        "dataset_context_used": dataset_context,
        "prompt_rules_used": [
            "do_not_invent_missing_facts",
            "separate_failure_diagnostic_recovery_and_escalation_signals",
            "validated_root_cause_false_unless_explicit",
            "candidate_extracted_manual_review",
            "source_traceability_required",
            "teams_chat_implies_escalation",
            "event_occurred_at_separate_from_event_documented_at",
            "raw_and_normalized_terms_required_for_ocr_sensitive_terms",
            "step_based_procedure_candidates_required",
            "candidate_inferred_causes_required",
            "action_signals_separate_from_recovery_validation",
            "workflows_orchestrate_procedures_operationalize",
            "explicit_relationship_ids_required",
            "procedure_step_evidence_quality_required",
            "visual_artifacts_are_first_class_evidence",
            "dataset_0_context_is_not_incident_evidence",
            "dataset_2a_workflows_are_symptom_driven",
            "dataset_2b_procedures_are_reusable_building_blocks",
            "dataset_5_escalation_handoff_questions_required",
        ],
        "llm_output_contract": {
            "canonical_incident": ["retrieval_text", "candidate_inferred_causes", *SIGNAL_BUCKETS, "raw_terms", "normalized_terms", "normalization_confidence"],
            "raw_evidence_chunks": ["raw_source_type", "evidence_type", *SIGNAL_BUCKETS],
            "timeline_events": ["event_occurred_at", "event_documented_at", *SIGNAL_BUCKETS],
            "procedure_candidates": ["procedure_name", "procedure_category", "procedure_category_status", "procedure_steps", "candidate_maturity", "promotion_blockers"],
            "workflow_candidate_steps": ["candidate_workflow_name", "step_type", "entry_conditions", "required_signals", "negative_signals", "procedure_refs", "status"],
            "escalation_summary_template": ["trigger_reason", "known_facts", "actions_taken", "evidence_available", "open_questions", "follow_up_owners", "handoff_summary"],
        },
        "prompt_excerpt": clean_text(prompt_text)[:1200],
    }


def build_interpretations(regions, prompt_text, reference):
    context = interpretation_payload(prompt_text, reference)
    return {
        "metadata": {
            **context,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_file": ACTIVE_SOURCE_FILE,
            "notes": "Cached LLM interpretation layer for v2 seed assembly. Inputs are deterministic OCR/layout regions; outputs are source-linked candidate facts for human review.",
        },
        "dataset_context_used": context["dataset_context_used"],
        "canonical_incident": {
            "container_id": "phase0_candidate_incident",
            "dataset_record_type": "incident_summary",
            "case_id": "229716",
            "source_case_id": "00229716",
            "title": "Case 229716 - ACD/AVG system waiting with no path to tippers at UPS Fort Worth Haslet",
            "incident_date": "2026-04-15",
            "opened_at": "2026-04-15 19:40",
            "resolved_at": "2026-04-17",
            "priority": "3 - Medium: Minor impact to production",
            "case_status": "Closed",
            "site": "UPS Fort Worth, TX (Haslet)",
            "customer": "UPS",
            "contact_name": "Antonio Rodrigo",
            "affected_asset": "Z-UPS Fort Worth, TX (Haslet)",
            "issue_category": context["dataset_context_used"].get("deterministic_issue_category"),
            "failure_signature": ["no_path_to_tippers_reported", "all_lines_stopped", "tipper_heartbeat_timeout_active", "hospital_tote_removal_failed", "no_active_rms_faults_reported"],
            "operational_signature": ["agv_startup_to_tipper_flow_blocked", "tipper_flow_blocked", "candidate_service_restart_recovery_pattern"],
            "symptom_summary": "After sort startup, AGVs lined up to go to tippers and all three lines stopped. The site reported no path showing and nothing coming to tippers. Hospital tote removal failed, tippers showed heartbeat timeout active, tippers were enabled, and no RMS faults were reported.",
            "component": ["AGV", "ACD", "Optisweep service", "RMS", "Ignition", "tippers", "hospital station"],
            "retrieval_text": "UPS Fort Worth Haslet reported ACD/AGV startup problems with everything waiting, no path showing, and nothing coming to tippers. After AGVs lined up to tippers, all three lines stopped, hospital tote removal failed, tippers showed heartbeat timeout active, tippers were enabled, and no RMS faults were reported. Teams escalation engaged L2/L3 support; heartbeat statistics and Windows services were reviewed. Qualified support directed E-stop, Optisweep service restart, E-stop removal, operational validation, and event/Ignition/DB/switch log collection. Recovery was documented with AGV operation and hospital function confirmed.",
            **signal_buckets(
                failure=["acd_agv_startup_problem", "system_waiting_state", "no_path_to_tippers_reported", "tipper_flow_blocked", "all_lines_stopped", "hospital_tote_removal_failed", "tipper_heartbeat_timeout_active", "tippers_enabled", "no_active_rms_faults_reported"],
                diagnostic=["heartbeat_statistics_requested", "windows_services_checked", "server_event_logs_collected", "ignition_logs_collected", "db_logs_requested", "switch_logs_requested"],
                action=["system_estop_performed", "optisweep_service_restart_documented", "estop_removed", "case_status_moved_to_resolved", "case_closed"],
                recovery=["agv_operation_confirmed", "agvs_moving", "hospital_tote_removal_restored", "system_operational"],
                escalation=["teams_escalation", "l2_engaged", "service_restart_required", "logs_requested", "switch_logs_requested"],
            ),
            "raw_terms": ["AVG", "AVGs", "ACD", "everything waiting", "nothing coming to tippers", "heartbeat timeout", "no RMS faults"],
            "normalized_terms": ["AGV", "AGVs", "ACD", "system_waiting_state", "tipper_flow_blocked", "tipper_heartbeat_timeout_active", "no_active_rms_faults_reported"],
            "normalization_confidence": 0.94,
            "candidate_inferred_causes": [
                {
                    "cause_summary": "Possible Optisweep service state issue inferred from recovery after service restart.",
                    "basis": ["optisweep_service_restart_documented", "agv_operation_confirmed_after_restart", "hospital_function_confirmed_after_restart"],
                    "confidence": 0.55,
                    "validation_status": "candidate_extracted",
                    "requires_manual_review": True,
                }
            ],
            "validated_root_cause": False,
            "resolution_summary": "Per Mitchell Flynn, the system was E-stopped and the Optisweep service was restarted. Antonio confirmed proper AVG operation and hospital function. Server event and Ignition logs were downloaded, with switch logs assigned for follow-up.",
            "resolution_steps": [
                "E-stop AGVs/system.",
                "Restart Optisweep service.",
                "Remove E-stop.",
                "Validate AVG operation.",
                "Validate hospital function and tote removal.",
                "Collect server event logs, Ignition logs, DB logs if available, and switch logs.",
            ],
            "roles_involved": ["Gianny D Perez Rocha", "Justin McCalmont", "Kevin Buczek", "Mitchel Flynn", "Harvey Dhillon", "Antonio Rodrigo", "Christopher Corbett"],
            "support_tiers_involved": ["L1_technical_support", "L2_L3_software_support"],
            "logs_collected": ["Server event logs", "Ignition logs", "Windows event logs"],
            "escalated": True,
            "escalation_source": "teams_chat",
            "region_ids": [region["region_id"] for region in regions],
        },
        "semantic_chunks": [
            {
                "chunk_id": "case_229716_chunk_case_metadata",
                "title": "Salesforce case metadata and initial status",
                "raw_source_type": "salesforce_case",
                "evidence_type": "context",
                "region_ids": ["region_sf_case_created", "region_sf_status_updates"],
                "summary": "Case 00229716 was created for UPS Fort Worth Haslet with subject Problems with the ACD system, malfunction type, New status, and medium priority. Status updates moved from New to In Progress and then escalated.",
                **signal_buckets(escalation=["case_created", "case_status_escalated"]),
            },
            {
                "chunk_id": "case_229716_chunk_escalation_questions",
                "title": "Escalation questions and L2 engagement",
                "raw_source_type": "salesforce_case",
                "evidence_type": "escalation",
                "region_ids": ["region_sf_escalation_questions", "region_sf_l2_engaged"],
                "summary": "Escalation questions identify ACD System as the issue location and state nothing is coming to the tippers. Justin McCalmont L2 was engaged and would connect to site; Antonio Rodrigo was the site point of contact.",
                **signal_buckets(failure=["tipper_flow_blocked"], escalation=["l2_engaged", "site_contact_identified"]),
            },
            {
                "chunk_id": "case_229716_chunk_symptom_visuals",
                "title": "Symptom narrative with RMS/Ignition visual evidence",
                "raw_source_type": "visual_artifact",
                "evidence_type": "symptom",
                "region_ids": ["region_sf_symptom_narrative", "region_visual_rms_map", "region_visual_tipper_alarms", "region_visual_opc_noise", "region_visual_hb_statistics", "region_visual_windows_services", "region_visual_performance_monitor"],
                "summary": "Salesforce and embedded screenshots describe AGVs lining up to tippers, all three lines stopping, hospital tote removal failure, heartbeat timeout active on tippers, and operational screenshots from RMS/Ignition/performance monitor.",
                **signal_buckets(failure=["all_lines_stopped", "hospital_tote_removal_failed", "tipper_heartbeat_timeout_active", "tippers_enabled", "no_active_rms_faults_reported"], diagnostic=["operational_screenshots_captured", "heartbeat_statistics_available"]),
            },
            {
                "chunk_id": "case_229716_chunk_teams_initial",
                "title": "Teams initial report and remote-in coordination",
                "raw_source_type": "teams_chat",
                "evidence_type": "symptom",
                "region_ids": ["region_teams_initial_report", "region_teams_prior_fix"],
                "summary": "Teams chat reports Haslet down, ACD system problems, everything waiting, no path, nothing coming to tippers, and prior recovery by resetting services. Justin planned to remote in and connect to site.",
                **signal_buckets(failure=["site_reported_down", "acd_system_problem", "system_waiting_state", "no_path_to_tippers_reported", "tipper_flow_blocked"], diagnostic=["remote_support_initiated"], escalation=["teams_escalation", "prior_service_reset_pattern_reported"]),
            },
            {
                "chunk_id": "case_229716_chunk_restart_decision",
                "title": "Service restart decision and execution",
                "raw_source_type": "teams_chat",
                "evidence_type": "action",
                "region_ids": ["region_teams_restart_decision", "region_visual_hb_statistics", "region_teams_services_window", "region_visual_windows_services", "region_sf_resolution_update"],
                "summary": "Teams and Salesforce evidence show discussion of resetting services, heartbeat statistics, E-stopping AGVs, restarting Optisweep, removing E-stop, collecting logs, and confirming the resolution in Salesforce.",
                **signal_buckets(diagnostic=["heartbeat_statistics_requested", "windows_services_checked"], action=["system_estop_performed", "optisweep_service_restart_documented", "estop_removed"], escalation=["teams_escalation", "service_restart_required", "logs_requested"]),
            },
            {
                "chunk_id": "case_229716_chunk_recovery_logs",
                "title": "Recovery confirmation and log handoff",
                "raw_source_type": "teams_chat",
                "evidence_type": "log_collection",
                "region_ids": ["region_teams_recovery_confirmation", "region_teams_log_collection", "region_visual_saved_logs", "region_sf_closure_summary"],
                "summary": "Teams confirms AVGs moving, hospital tote removal works after logout/login, system operational, and event/DB/switch logs requested. Salesforce closure summary documents the issue and resolution.",
                **signal_buckets(diagnostic=["event_logs_collected", "ignition_logs_collected", "db_log_transfer_unclear"], recovery=["agvs_moving", "hospital_tote_removal_restored", "system_operational"], escalation=["switch_logs_requested"]),
            },
        ],
        "timeline_events": [
            {"event_id": "case_229716_event_001", "container_id": "phase0_timeline_events", "timestamp_raw": "2026-04-15 19:40", "event_occurred_at": "2026-04-15T19:40", "event_documented_at": "2026-04-15T19:40", "timestamp_basis": "direct_salesforce_case_created_time", "actor": "Gianny D Perez Rocha", "actor_role": "L1_technical_support", "event_type": "initial_report", "event_summary": "Salesforce case 00229716 created for Problems with the ACD system at UPS Fort Worth Haslet.", **signal_buckets(failure=["acd_system_problem_reported"], action=["case_created"]), "action_taken": "Case created.", "outcome": "Case opened with New status.", "region_ids": ["region_sf_case_created"]},
            {"event_id": "case_229716_event_002", "container_id": "phase0_timeline_events", "timestamp_raw": "2026-04-15 19:41", "event_occurred_at": "2026-04-15T19:41", "event_documented_at": "2026-04-15T19:41", "timestamp_basis": "direct_teams_message_time", "actor": "Gianny D Perez Rocha", "actor_role": "L1_technical_support", "event_type": "symptom_observed", "event_summary": "Teams report says ACD system has problems, everything is waiting, no path is showing, and nothing is coming up to the tippers.", **signal_buckets(failure=["acd_system_problem", "system_waiting_state", "no_path_to_tippers_reported", "tipper_flow_blocked"], escalation=["teams_escalation"]), "action_taken": "", "outcome": "Support discussion begins.", "region_ids": ["region_teams_initial_report"]},
            {"event_id": "case_229716_event_003", "container_id": "phase0_timeline_events", "timestamp_raw": "2026-04-15 19:52", "event_occurred_at": "2026-04-15T19:52", "event_documented_at": "2026-04-15T19:52", "actor": "Justin McCalmont", "actor_role": "L2_L3_software_support", "event_type": "diagnostic_check", "event_summary": "Justin says he will remote in and see what he can find.", **signal_buckets(diagnostic=["remote_support_initiated"], escalation=["teams_escalation"]), "action_taken": "Remote investigation initiated.", "outcome": "Connecting to site followed at 8:00 PM.", "region_ids": ["region_teams_initial_report", "region_teams_prior_fix"]},
            {"event_id": "case_229716_event_004", "container_id": "phase0_timeline_events", "timestamp_raw": "2026-04-15 19:53", "event_occurred_at": "2026-04-15T19:53", "event_documented_at": "2026-04-15T19:53", "actor": "Kevin Buczek / Harvey Dhillon", "actor_role": "unknown", "event_type": "action_proposed", "event_summary": "Team notes the previous fix was resetting services and agrees to reset services if needed.", **signal_buckets(diagnostic=["prior_service_reset_pattern_reported"], action=["service_reset_proposed"], escalation=["teams_escalation"]), "action_taken": "Service reset proposed.", "outcome": "Justin continues investigation.", "region_ids": ["region_teams_prior_fix"]},
            {"event_id": "case_229716_event_005", "container_id": "phase0_timeline_events", "timestamp_raw": "2026-04-15 20:15", "event_occurred_at": "2026-04-15T20:15", "event_documented_at": "2026-04-15T20:15", "actor": "Gianny D Perez Rocha", "actor_role": "L1_technical_support", "event_type": "escalation", "event_summary": "Salesforce update states Justin McCalmont L2 is engaged and will connect to site; Antonio Rodrigo is listed as site contact.", **signal_buckets(action=["case_escalated_to_l2"], escalation=["l2_engaged", "site_contact_identified"]), "action_taken": "Escalated to L2.", "outcome": "Justin connects to investigate.", "region_ids": ["region_sf_l2_engaged"]},
            {"event_id": "case_229716_event_006", "container_id": "phase0_timeline_events", "timestamp_raw": "2026-04-15 20:16", "event_occurred_at": "2026-04-15T20:16", "event_documented_at": "2026-04-15T20:16", "actor": "Kevin Buczek / Mitchel Flynn", "actor_role": "L2_L3_software_support", "event_type": "diagnostic_check", "event_summary": "Kevin asks if services are being reset; Mitchel asks for heartbeat statistics and whether they came back.", **signal_buckets(diagnostic=["heartbeat_statistics_requested"], escalation=["teams_escalation"]), "action_taken": "Requested heartbeat statistics.", "outcome": "Restart path discussed.", "region_ids": ["region_teams_restart_decision"]},
            {"event_id": "case_229716_event_007", "container_id": "phase0_timeline_events", "timestamp_raw": "2026-04-15 20:17", "event_occurred_at": "2026-04-15T20:17", "event_documented_at": "2026-04-15T20:17", "actor": "Mitchel Flynn", "actor_role": "L2_L3_software_support", "event_type": "action_taken", "event_summary": "Mitchel instructs to E-stop AGVs, restart the service, remove E-stop, and collect event or DB logs.", **signal_buckets(diagnostic=["event_or_db_logs_requested"], action=["system_estop_requested", "service_restart_requested", "estop_removal_requested"], escalation=["teams_escalation", "service_restart_required", "logs_requested"]), "action_taken": "E-stop AGVs, restart service, remove E-stop, collect logs.", "outcome": "Justin clarifies whether to restart Optisweep, Ignition OPC, or both.", "region_ids": ["region_teams_restart_decision", "region_visual_hb_statistics"]},
            {"event_id": "case_229716_event_008", "container_id": "phase0_timeline_events", "timestamp_raw": "2026-04-15 20:18", "event_occurred_at": "2026-04-15T20:18", "event_documented_at": "2026-04-15T20:18", "actor": "Mitchel Flynn / Justin McCalmont", "actor_role": "L2_L3_software_support", "event_type": "action_taken", "event_summary": "Justin asks whether to restart Optisweep, Ignition OPC, or both. Mitchel answers Optisweep.", **signal_buckets(diagnostic=["windows_services_checked"], action=["optisweep_service_restart_selected"], escalation=["teams_escalation"]), "action_taken": "Restart Optisweep service.", "outcome": "Service restart proceeds.", "region_ids": ["region_teams_restart_decision", "region_teams_services_window", "region_visual_windows_services"]},
            {"event_id": "case_229716_event_009", "container_id": "phase0_timeline_events", "timestamp_raw": "2026-04-15 20:24", "event_occurred_at": "2026-04-15T20:24", "event_documented_at": "2026-04-15T20:24", "actor": "Mitchel Flynn", "actor_role": "L2_L3_software_support", "event_type": "log_collection", "event_summary": "Mitchel requests DB logs and event logs be added to the ticket and asks Christopher Corbett to follow up with UPS on switch logs.", **signal_buckets(diagnostic=["db_logs_requested", "event_logs_requested"], escalation=["teams_escalation", "switch_logs_requested"]), "action_taken": "Requested DB/event/switch logs.", "outcome": "Log handoff initiated.", "region_ids": ["region_teams_recovery_confirmation"]},
            {"event_id": "case_229716_event_010", "container_id": "phase0_timeline_events", "timestamp_raw": "2026-04-15 20:36", "event_occurred_at": "2026-04-15T20:36", "event_documented_at": "2026-04-15T20:36", "actor": "Justin McCalmont", "actor_role": "L2_L3_software_support", "event_type": "log_collection", "event_summary": "Justin reports Ignition and Windows event logs saved to RDP desktop and notes uncertainty about DB log transfer.", **signal_buckets(diagnostic=["ignition_logs_collected", "windows_event_logs_collected", "db_log_transfer_unclear"], escalation=["teams_escalation"]), "action_taken": "Saved Ignition and Windows event logs.", "outcome": "Logs available on RDP desktop; DB log transfer unresolved.", "region_ids": ["region_teams_log_collection", "region_visual_saved_logs"]},
            {"event_id": "case_229716_event_011", "container_id": "phase0_timeline_events", "timestamp_raw": "2026-04-15 20:48", "event_occurred_at": "2026-04-15T19:41", "event_documented_at": "2026-04-15T20:48", "timestamp_basis": "inferred_from_prior_teams_report", "actor": "Justin McCalmont", "actor_role": "L2_L3_software_support", "event_type": "symptom_observed", "event_summary": "Salesforce symptom narrative reports sort started, AGVs lined up to tippers, all three lines stopped, hospital tote removal failed, tippers heartbeat timeout active, tippers enabled, and no RMS faults.", **signal_buckets(failure=["all_lines_stopped", "hospital_tote_removal_failed", "tipper_heartbeat_timeout_active", "tippers_enabled", "no_active_rms_faults_reported"], diagnostic=["operational_screenshots_captured"]), "action_taken": "Documented operational symptoms.", "outcome": "Symptoms and visuals captured.", "region_ids": ["region_sf_symptom_narrative", "region_visual_rms_map", "region_visual_tipper_alarms", "region_visual_hb_statistics", "region_visual_windows_services"]},
            {"event_id": "case_229716_event_012", "container_id": "phase0_timeline_events", "timestamp_raw": "2026-04-15 20:53", "event_occurred_at": None, "event_documented_at": "2026-04-15T20:53", "timestamp_basis": "salesforce_resolution_update_documents_actions_after_the_fact", "actor": "Justin McCalmont", "actor_role": "L2_L3_software_support", "event_type": "validation", "event_summary": "Salesforce resolution update says the system was E-stopped and Optisweep restarted; Antonio confirmed AVG operation and hospital function; server event and Ignition logs downloaded.", **signal_buckets(diagnostic=["server_event_logs_collected", "ignition_logs_collected"], action=["system_estop_performed", "optisweep_service_restart_documented"], recovery=["agv_operation_confirmed", "hospital_function_confirmed"], escalation=["switch_logs_followup_assigned"]), "action_taken": "E-stopped system and restarted Optisweep service.", "outcome": "Proper AVG operation and hospital function confirmed.", "region_ids": ["region_sf_resolution_update"]},
            {"event_id": "case_229716_event_013", "container_id": "phase0_timeline_events", "timestamp_raw": "2026-04-15 20:54", "event_occurred_at": "2026-04-15T20:54", "event_documented_at": "2026-04-15T20:54", "actor": "Justin McCalmont", "actor_role": "L2_L3_software_support", "event_type": "status_change", "event_summary": "Case status updated from Escalated Waiting on Another Department to Resolved.", **signal_buckets(action=["case_status_moved_to_resolved"]), "action_taken": "Status changed to Resolved.", "outcome": "Case moved to Resolved.", "region_ids": ["region_sf_resolution_update"]},
            {"event_id": "case_229716_event_014", "container_id": "phase0_timeline_events", "timestamp_raw": "2026-04-17 12:56", "event_occurred_at": "2026-04-17T12:56", "event_documented_at": "2026-04-17T12:56", "actor": "Gianny D Perez Rocha", "actor_role": "L1_technical_support", "event_type": "closure", "event_summary": "Salesforce case closed with closure summary including symptoms and resolution details.", **signal_buckets(action=["case_closed"]), "action_taken": "Case closed.", "outcome": "Case status Resolved to Closed.", "region_ids": ["region_sf_closure_summary"]},
        ],
        "procedure_candidates": [
            {
                "procedure_candidate_id": "inspect_heartbeat_and_tipper_status_candidate",
                "procedure_name": "Inspect Heartbeat And Tipper Status",
                "procedure_category": "diagnostic_check",
                "candidate_maturity": "single_case_candidate",
                "related_cases": ["229716"],
                "related_components": ["AGV", "tippers", "RMS", "Ignition", "heartbeat"],
                "related_workflows": ["heartbeat_timeout_no_rms_alarm_v1", "agvs_stopped_hospital_remove_hangs_v1"],
                "related_escalation_patterns": ["teams_escalation", "l2_engaged"],
                "known_failure_modes": ["tipper_heartbeat_timeout_active", "all_lines_stopped", "no_active_rms_faults_reported"],
                "procedure_summary": "Candidate diagnostic procedure for reviewing heartbeat and tipper status when AGVs stop before tippers and no RMS faults are present.",
                "procedure_goal": "Capture heartbeat/tipper evidence before recovery actions are selected.",
                "required_tools_or_systems": ["RMS", "Ignition", "HMI or webvisu screenshot access"],
                "role_requirements": ["L2_L3_software_support"],
                "required_permissions": ["remote_visual_access"],
                "preconditions": ["No-path-to-tippers or heartbeat timeout symptoms are reported."],
                "validation_checks": ["heartbeat_status_reviewed", "tipper_status_reviewed"],
                "validation_evidence": ["case_229716_embedded_visual_hb_statistics", "case_229716_embedded_visual_tipper_alarms"],
                "recovery_outcomes": [],
                "known_risks": ["Noisy OCR from HMI/RMS screenshots must not be promoted into procedural truth without review."],
                "escalation_conditions": ["Heartbeat timeout active or unclear RMS/Ignition state requires L2/L3 review."],
                "supporting_evidence_chunks": ["case_229716_chunk_symptom_visuals", "case_229716_chunk_restart_decision"],
                "supporting_timeline_events": ["case_229716_event_006", "case_229716_event_011"],
                "supporting_artifacts": ["case_229716_embedded_visual_hb_statistics", "case_229716_embedded_visual_tipper_alarms"],
                "refinement_opportunities": ["Confirm exact heartbeat thresholds and approved interpretation criteria with SME review."],
                "procedure_steps": [
                    {"step_order": 1, "instruction": "Review the failure report for no path, stopped lines, and heartbeat timeout symptoms.", "expected_result": "Failure presentation is documented before action selection.", "required_tools_or_systems": ["Salesforce", "Teams"], "related_artifacts": [], "source_region_refs": ["region_sf_symptom_narrative", "region_teams_initial_report"], "supporting_evidence_chunks": ["case_229716_chunk_symptom_visuals", "case_229716_chunk_teams_initial"], "supporting_timeline_events": ["case_229716_event_002", "case_229716_event_011"], "validation_signal_refs": ["no_path_to_tippers_reported", "tipper_heartbeat_timeout_active"], "risk_notes": [], "escalation_boundary": "Escalate to L2/L3 if heartbeat status cannot be interpreted by L1.", "requires_role_review": True},
                    {"step_order": 2, "instruction": "Review heartbeat or tipper status screenshots if available.", "expected_result": "Heartbeat and tipper status evidence is captured for review.", "required_tools_or_systems": ["RMS", "Ignition", "HMI or webvisu"], "related_artifacts": ["case_229716_embedded_visual_hb_statistics", "case_229716_embedded_visual_tipper_alarms"], "source_region_refs": ["region_visual_hb_statistics", "region_visual_tipper_alarms"], "supporting_evidence_chunks": ["case_229716_chunk_symptom_visuals"], "supporting_timeline_events": ["case_229716_event_006", "case_229716_event_011"], "validation_signal_refs": ["heartbeat_statistics_requested"], "risk_notes": ["OCR may misread HMI labels."], "escalation_boundary": "Do not infer root cause from screenshot labels alone.", "requires_role_review": True},
                ],
                "region_ids": ["region_teams_restart_decision", "region_visual_hb_statistics", "region_sf_symptom_narrative", "region_visual_tipper_alarms"],
                "validation_status": "candidate_extracted",
            },
            {
                "procedure_candidate_id": "restart_optisweep_service_candidate",
                "procedure_name": "Restart Optisweep Service",
                "procedure_category": "service_restart",
                "candidate_maturity": "single_case_candidate",
                "related_cases": ["229716"],
                "related_components": ["Optisweep service", "AGV", "tippers", "hospital station", "Windows Services"],
                "related_workflows": ["service_restart_recovery_flow_v1", "heartbeat_timeout_no_rms_alarm_v1"],
                "related_escalation_patterns": ["teams_escalation", "service_restart_required", "logs_requested"],
                "known_failure_modes": ["no_path_to_tippers_reported", "all_lines_stopped", "tipper_heartbeat_timeout_active", "hospital_tote_removal_failed"],
                "procedure_summary": "Candidate recovery procedure preserving the observed E-stop, Optisweep service restart, E-stop removal, validation, and log-collection sequence.",
                "procedure_goal": "Restore AGV movement and operational flow after no-path-to-tippers symptoms when qualified support determines Optisweep service restart is appropriate.",
                "required_tools_or_systems": ["Windows Services", "Optisweep service", "RMS", "Ignition", "site operational coordination"],
                "role_requirements": ["L2_L3_software_support"],
                "required_permissions": ["remote_service_access", "service_restart_access", "site_coordination"],
                "preconditions": ["Qualified support directs service restart.", "Operational pause or E-stop sequence is coordinated."],
                "validation_checks": ["agv_operation_confirmed", "hospital_function_confirmed", "system_operational"],
                "validation_evidence": ["case_229716_event_012", "case_229716_chunk_recovery_logs"],
                "recovery_outcomes": ["agv_operation_confirmed", "hospital_function_confirmed"],
                "known_risks": ["Service restart and E-stop actions require role and permission review.", "Exact operational safety boundary is not approved by Phase 0 extraction."],
                "escalation_conditions": ["Service restart should remain escalated to qualified support until SME-reviewed."],
                "supporting_evidence_chunks": ["case_229716_chunk_restart_decision", "case_229716_chunk_recovery_logs"],
                "supporting_timeline_events": ["case_229716_event_007", "case_229716_event_008", "case_229716_event_012"],
                "supporting_artifacts": ["case_229716_embedded_visual_windows_services", "case_229716_embedded_visual_rms_map", "case_229716_embedded_visual_tipper_alarms"],
                "refinement_opportunities": ["Confirm exact Windows service name/status, site pause prerequisites, and SME-approved risk boundaries."],
                "procedure_steps": [
                    {"step_order": 1, "instruction": "Verify the site is ready for operational pause and confirm support escalation context.", "expected_result": "Operational pause is understood and support context is documented.", "required_tools_or_systems": ["Teams", "site contact"], "related_artifacts": [], "source_region_refs": ["region_teams_restart_decision"], "supporting_evidence_chunks": ["case_229716_chunk_restart_decision"], "supporting_timeline_events": ["case_229716_event_007"], "validation_signal_refs": ["teams_escalation"], "risk_notes": ["Phase 0 does not approve operational pause authority."], "escalation_boundary": "Requires role and access review before execution.", "requires_role_review": True},
                    {"step_order": 2, "instruction": "Review heartbeat or tipper status evidence before restart decision.", "expected_result": "Heartbeat/tipper status is captured for review.", "required_tools_or_systems": ["RMS", "Ignition"], "related_artifacts": ["case_229716_embedded_visual_hb_statistics"], "source_region_refs": ["region_visual_hb_statistics"], "supporting_evidence_chunks": ["case_229716_chunk_symptom_visuals"], "supporting_timeline_events": ["case_229716_event_006"], "validation_signal_refs": ["heartbeat_statistics_requested"], "risk_notes": ["Visual evidence is support context, not final root-cause proof."], "escalation_boundary": "Escalate if heartbeat/tipper state is unclear.", "requires_role_review": True},
                    {"step_order": 3, "instruction": "If directed by qualified support, place AGVs/system into E-stop state.", "expected_result": "System is stopped before service restart.", "required_tools_or_systems": ["site operational controls"], "related_artifacts": [], "source_region_refs": ["region_teams_restart_decision"], "supporting_evidence_chunks": ["case_229716_chunk_restart_decision"], "supporting_timeline_events": ["case_229716_event_007"], "validation_signal_refs": [], "risk_notes": ["E-stop authority and safety constraints require SME review."], "escalation_boundary": "Do not execute without qualified support direction.", "requires_role_review": True},
                    {"step_order": 4, "instruction": "If directed by qualified support, restart the Optisweep Windows service.", "expected_result": "Optisweep service restart is completed.", "required_tools_or_systems": ["Windows Services", "remote service access"], "related_artifacts": ["case_229716_embedded_visual_windows_services"], "source_region_refs": ["region_teams_services_window", "region_visual_windows_services"], "supporting_evidence_chunks": ["case_229716_chunk_restart_decision"], "supporting_timeline_events": ["case_229716_event_008"], "validation_signal_refs": ["optisweep_restart_selected"], "risk_notes": ["Service access permissions are not validated by ingestion."], "escalation_boundary": "Requires role and permission review.", "requires_role_review": True},
                    {"step_order": 5, "instruction": "Remove E-stop and monitor operational recovery.", "expected_result": "AGVs resume movement and hospital/tipper function is validated.", "required_tools_or_systems": ["RMS", "Ignition", "site confirmation"], "related_artifacts": ["case_229716_embedded_visual_rms_map", "case_229716_embedded_visual_tipper_alarms"], "source_region_refs": ["region_visual_rms_map", "region_visual_tipper_alarms", "region_sf_resolution_update"], "supporting_evidence_chunks": ["case_229716_chunk_recovery_logs"], "supporting_timeline_events": ["case_229716_event_012"], "validation_signal_refs": ["agv_operation_confirmed", "hospital_function_confirmed"], "risk_notes": [], "escalation_boundary": "Escalate if AGV movement or hospital function is not restored.", "requires_role_review": True},
                    {"step_order": 6, "instruction": "Collect event, Ignition, DB, or switch logs requested during escalation.", "expected_result": "Logs are attached or follow-up ownership is documented.", "required_tools_or_systems": ["RDP desktop", "Ignition logs", "Windows event logs", "database logs", "switch logs"], "related_artifacts": ["case_229716_embedded_visual_saved_logs"], "source_region_refs": ["region_teams_log_collection", "region_visual_saved_logs"], "supporting_evidence_chunks": ["case_229716_chunk_recovery_logs"], "supporting_timeline_events": ["case_229716_event_009", "case_229716_event_010"], "validation_signal_refs": ["ignition_logs_collected", "windows_event_logs_collected"], "risk_notes": ["DB log transfer method was unclear."], "escalation_boundary": "Assign follow-up owner for missing logs.", "requires_role_review": True},
                ],
                "region_ids": ["region_teams_restart_decision", "region_visual_hb_statistics", "region_teams_services_window", "region_visual_windows_services", "region_sf_resolution_update"],
                "validation_status": "candidate_extracted",
            },
            {
                "procedure_candidate_id": "collect_incident_logs_for_engineering_review_candidate",
                "procedure_name": "Collect Incident Logs For Engineering Review",
                "procedure_category": "log_collection",
                "candidate_maturity": "single_case_candidate",
                "related_cases": ["229716"],
                "related_components": ["Ignition", "Windows event logs", "database logs", "switch logs"],
                "related_workflows": ["service_restart_recovery_flow_v1"],
                "related_escalation_patterns": ["logs_requested", "switch_logs_followup"],
                "known_failure_modes": ["service_restart_required"],
                "procedure_summary": "Candidate procedure for collecting logs after recovery actions and preserving open follow-up on unavailable logs.",
                "procedure_goal": "Attach enough evidence for engineering review after operational recovery.",
                "required_tools_or_systems": ["RDP desktop", "Ignition logs", "Windows Event Viewer", "database log access", "switch log owner"],
                "role_requirements": ["L2_L3_software_support", "L2_L3_infrastructure_controls_dba_devops"],
                "required_permissions": ["log_access", "remote_desktop_access", "database_log_access"],
                "preconditions": ["Engineering or L2/L3 requests logs."],
                "validation_checks": ["logs_saved_or_followup_documented"],
                "validation_evidence": ["case_229716_embedded_visual_saved_logs"],
                "recovery_outcomes": [],
                "known_risks": ["DB and switch logs may require separate owner or permissions."],
                "escalation_conditions": ["Missing DB or switch logs require follow-up owner."],
                "supporting_evidence_chunks": ["case_229716_chunk_recovery_logs"],
                "supporting_timeline_events": ["case_229716_event_009", "case_229716_event_010", "case_229716_event_012"],
                "supporting_artifacts": ["case_229716_embedded_visual_saved_logs"],
                "refinement_opportunities": ["Define exact DB log transfer method and switch-log ownership."],
                "procedure_steps": [
                    {"step_order": 1, "instruction": "Record which logs were requested during escalation.", "expected_result": "Event, DB, Ignition, and switch log requests are listed.", "required_tools_or_systems": ["Teams", "Salesforce"], "related_artifacts": [], "source_region_refs": ["region_teams_recovery_confirmation"], "supporting_evidence_chunks": ["case_229716_chunk_recovery_logs"], "supporting_timeline_events": ["case_229716_event_009"], "validation_signal_refs": ["db_logs_requested", "event_logs_requested", "switch_logs_requested"], "risk_notes": [], "escalation_boundary": "Assign owner for logs outside support access.", "requires_role_review": True},
                    {"step_order": 2, "instruction": "Save Ignition and Windows event logs to the available handoff location.", "expected_result": "Ignition and Windows event logs are saved or attached.", "required_tools_or_systems": ["RDP desktop", "Ignition logs", "Windows Event Viewer"], "related_artifacts": ["case_229716_embedded_visual_saved_logs"], "source_region_refs": ["region_teams_log_collection", "region_visual_saved_logs"], "supporting_evidence_chunks": ["case_229716_chunk_recovery_logs"], "supporting_timeline_events": ["case_229716_event_010"], "validation_signal_refs": ["ignition_logs_collected", "windows_event_logs_collected"], "risk_notes": [], "escalation_boundary": "Escalate if logs cannot be accessed.", "requires_role_review": True},
                    {"step_order": 3, "instruction": "Document unresolved DB or switch log follow-up.", "expected_result": "Missing log ownership or transfer uncertainty is captured.", "required_tools_or_systems": ["database logs", "switch log owner"], "related_artifacts": [], "source_region_refs": ["region_teams_log_collection", "region_sf_resolution_update"], "supporting_evidence_chunks": ["case_229716_chunk_recovery_logs"], "supporting_timeline_events": ["case_229716_event_009", "case_229716_event_010", "case_229716_event_012"], "validation_signal_refs": ["db_log_transfer_unclear", "switch_logs_followup_assigned"], "risk_notes": ["Incomplete logs can weaken post-incident review."], "escalation_boundary": "Assign follow-up owner for unavailable logs.", "requires_role_review": True},
                ],
                "region_ids": ["region_teams_recovery_confirmation", "region_teams_log_collection", "region_visual_saved_logs", "region_sf_resolution_update"],
                "validation_status": "candidate_extracted",
            },
            {
                "procedure_candidate_id": "validate_agv_and_hospital_recovery_candidate",
                "procedure_name": "Validate AGV And Hospital Recovery",
                "procedure_category": "recovery_validation",
                "candidate_maturity": "single_case_candidate",
                "related_cases": ["229716"],
                "related_components": ["AGV", "hospital station", "tippers", "RMS"],
                "related_workflows": ["service_restart_recovery_flow_v1", "agvs_stopped_hospital_remove_hangs_v1"],
                "related_escalation_patterns": ["teams_escalation", "resolution_validation"],
                "known_failure_modes": ["hospital_tote_removal_failed", "all_lines_stopped"],
                "procedure_summary": "Candidate validation procedure for confirming AGV movement, hospital function, and operational status after recovery actions.",
                "procedure_goal": "Confirm the operational failure is resolved before disengaging or closing the case.",
                "required_tools_or_systems": ["RMS", "site confirmation", "Salesforce"],
                "role_requirements": ["L1_technical_support", "L2_L3_software_support"],
                "required_permissions": ["case_update_access"],
                "preconditions": ["Recovery action has been attempted."],
                "validation_checks": ["agvs_moving", "hospital_tote_removal_restored", "system_operational"],
                "validation_evidence": ["case_229716_chunk_recovery_logs", "case_229716_event_012"],
                "recovery_outcomes": ["agvs_moving", "hospital_tote_removal_restored", "system_operational"],
                "known_risks": ["Recovery confirmation may depend on site observation."],
                "escalation_conditions": ["Escalate if movement or hospital function remains impaired."],
                "supporting_evidence_chunks": ["case_229716_chunk_recovery_logs"],
                "supporting_timeline_events": ["case_229716_event_012", "case_229716_event_013"],
                "supporting_artifacts": ["case_229716_embedded_visual_rms_map", "case_229716_embedded_visual_tipper_alarms"],
                "refinement_opportunities": ["Define minimum validation duration and required site confirmation language."],
                "procedure_steps": [
                    {"step_order": 1, "instruction": "Confirm AGVs are moving after recovery action.", "expected_result": "AGV movement is confirmed.", "required_tools_or_systems": ["RMS", "site confirmation"], "related_artifacts": ["case_229716_embedded_visual_rms_map"], "source_region_refs": ["region_visual_rms_map", "region_teams_recovery_confirmation"], "supporting_evidence_chunks": ["case_229716_chunk_recovery_logs"], "supporting_timeline_events": ["case_229716_event_012"], "validation_signal_refs": ["agvs_moving", "agv_operation_confirmed"], "risk_notes": [], "escalation_boundary": "Escalate if AGVs remain stopped.", "requires_role_review": True},
                    {"step_order": 2, "instruction": "Confirm hospital tote removal or hospital function is restored.", "expected_result": "Hospital function is confirmed operational.", "required_tools_or_systems": ["site confirmation", "RMS"], "related_artifacts": ["case_229716_embedded_visual_tipper_alarms"], "source_region_refs": ["region_teams_recovery_confirmation", "region_sf_resolution_update"], "supporting_evidence_chunks": ["case_229716_chunk_recovery_logs"], "supporting_timeline_events": ["case_229716_event_012"], "validation_signal_refs": ["hospital_tote_removal_restored", "hospital_function_confirmed"], "risk_notes": [], "escalation_boundary": "Escalate if tote removal is still failing.", "requires_role_review": True},
                    {"step_order": 3, "instruction": "Document system operational state and case status transition.", "expected_result": "Operational status and case resolution are documented.", "required_tools_or_systems": ["Salesforce", "Teams"], "related_artifacts": [], "source_region_refs": ["region_sf_resolution_update", "region_teams_recovery_confirmation"], "supporting_evidence_chunks": ["case_229716_chunk_recovery_logs"], "supporting_timeline_events": ["case_229716_event_013"], "validation_signal_refs": ["system_operational", "case_moved_to_resolved"], "risk_notes": [], "escalation_boundary": "Do not close if open recovery validation questions remain.", "requires_role_review": True},
                ],
                "region_ids": ["region_teams_recovery_confirmation", "region_sf_resolution_update", "region_visual_rms_map", "region_visual_tipper_alarms"],
                "validation_status": "candidate_extracted",
            },
        ],
        "workflow_candidate_steps": [
            {"workflow_step_id": "heartbeat_timeout_no_rms_alarm_step_001", "container_id": "phase0_workflow_candidates", "candidate_workflow_name": "heartbeat_timeout_no_rms_alarm_v1", "step_type": "question", "question": "Are tippers showing heartbeat timeout while RMS shows no active faults?", "why_asked": "This case links tipper heartbeat timeout, enabled tippers, and no active RMS faults to the no-path-to-tippers presentation.", "candidate_step": "If ACD/AGV startup shows no path and tipper flow is blocked, gather case metadata, site contact, current status, and prior occurrence details.", "entry_conditions": ["no_path_to_tippers_reported", "tipper_flow_blocked"], "required_signals": ["tipper_heartbeat_timeout_active", "no_active_rms_faults_reported"], "negative_signals": [], "procedure_refs": ["inspect_heartbeat_and_tipper_status_candidate"], "evidence_refs": ["case_229716_chunk_escalation_questions", "case_229716_chunk_symptom_visuals"], "image_refs": ["case_229716_embedded_visual_hb_statistics", "case_229716_embedded_visual_tipper_alarms"], "status": "draft", "region_ids": ["region_sf_escalation_questions", "region_teams_initial_report", "region_visual_tipper_alarms"], **review_fields(["L1_technical_support", "L2_L3_software_support"], [])},
            {"workflow_step_id": "heartbeat_timeout_no_rms_alarm_step_002", "container_id": "phase0_workflow_candidates", "candidate_workflow_name": "heartbeat_timeout_no_rms_alarm_v1", "step_type": "diagnostic_check", "question": "", "why_asked": "Heartbeat and tipper visual evidence helps preserve the diagnostic context before recovery action.", "candidate_step": "If tippers show heartbeat timeout or all lines stop, route to L2/L3 review and inspect heartbeat statistics plus RMS/Ignition visual evidence.", "entry_conditions": ["tipper_heartbeat_timeout_active", "all_lines_stopped"], "required_signals": ["heartbeat_statistics_requested"], "negative_signals": [], "procedure_refs": ["inspect_heartbeat_and_tipper_status_candidate"], "evidence_refs": ["case_229716_chunk_symptom_visuals", "case_229716_chunk_restart_decision"], "image_refs": ["case_229716_embedded_visual_hb_statistics", "case_229716_embedded_visual_rms_map"], "status": "draft", "region_ids": ["region_sf_l2_engaged", "region_sf_symptom_narrative", "region_visual_tipper_alarms", "region_teams_restart_decision"], **review_fields(["L2_L3_software_support"], ["remote_visual_access"])},
            {"workflow_step_id": "service_restart_recovery_flow_step_001", "container_id": "phase0_workflow_candidates", "candidate_workflow_name": "service_restart_recovery_flow_v1", "step_type": "action_reference", "question": "", "why_asked": "Teams evidence shows qualified support selected Optisweep restart after heartbeat/service discussion.", "candidate_step": "If restart criteria are met and qualified support approves, invoke the restart Optisweep service procedure candidate.", "entry_conditions": ["service_restart_required"], "required_signals": ["optisweep_service_restart_selected"], "negative_signals": [], "procedure_refs": ["restart_optisweep_service_candidate"], "evidence_refs": ["case_229716_chunk_restart_decision"], "image_refs": ["case_229716_embedded_visual_windows_services"], "status": "draft", "region_ids": ["region_teams_restart_decision", "region_teams_services_window", "region_visual_windows_services", "region_sf_resolution_update"], **review_fields(["L2_L3_software_support"], ["remote_service_access", "service_restart_access"])},
            {"workflow_step_id": "service_restart_recovery_flow_step_002", "container_id": "phase0_workflow_candidates", "candidate_workflow_name": "service_restart_recovery_flow_v1", "step_type": "validation", "question": "", "why_asked": "Recovery validation separates post-action confirmations from failure symptoms.", "candidate_step": "After the referenced recovery procedure is completed, invoke the AGV and hospital recovery validation procedure candidate.", "entry_conditions": ["recovery_action_attempted"], "required_signals": ["agv_operation_confirmed", "hospital_function_confirmed"], "negative_signals": ["agvs_remain_stopped", "hospital_tote_removal_still_failed"], "procedure_refs": ["validate_agv_and_hospital_recovery_candidate"], "evidence_refs": ["case_229716_chunk_recovery_logs"], "image_refs": ["case_229716_embedded_visual_rms_map", "case_229716_embedded_visual_tipper_alarms"], "status": "draft", "region_ids": ["region_teams_recovery_confirmation", "region_sf_resolution_update"], **review_fields(["L1_technical_support", "L2_L3_software_support"], [])},
            {"workflow_step_id": "service_restart_recovery_flow_step_003", "container_id": "phase0_workflow_candidates", "candidate_workflow_name": "service_restart_recovery_flow_v1", "step_type": "escalation", "question": "", "why_asked": "Log collection and switch follow-up preserve engineer handoff context.", "candidate_step": "If logs or follow-up evidence are needed, invoke the incident log collection procedure candidate and assign open follow-up owners.", "entry_conditions": ["logs_requested"], "required_signals": ["event_logs_requested", "db_logs_requested", "switch_logs_requested"], "negative_signals": [], "procedure_refs": ["collect_incident_logs_for_engineering_review_candidate"], "evidence_refs": ["case_229716_chunk_recovery_logs"], "image_refs": ["case_229716_embedded_visual_saved_logs"], "status": "draft", "region_ids": ["region_teams_recovery_confirmation", "region_teams_log_collection", "region_visual_saved_logs"], **review_fields(["L2_L3_software_support", "L2_L3_infrastructure_controls_dba_devops"], ["log_access"])},
        ],
        "escalation_summary_template": {
            "container_id": "phase0_escalation_summaries",
            "trigger_reason": "ACD/AGV startup issue with no path, nothing coming to tippers, all three lines stopped, hospital tote removal failure, and heartbeat timeout active on tippers.",
            "symptoms": ["no_path_to_tippers_reported", "tipper_flow_blocked", "all_lines_stopped", "hospital_tote_removal_failed", "tipper_heartbeat_timeout_active", "no_active_rms_faults_reported"],
            "steps_attempted": ["Remote support initiated.", "Heartbeat statistics requested.", "E-stop AGVs/system.", "Restart Optisweep service.", "Remove E-stop.", "Validate AGV and hospital function.", "Collect event and Ignition logs."],
            "steps_not_attempted": ["DB log transfer was unclear in source evidence.", "Switch logs were assigned for follow-up with UPS."],
            "evidence_refs": ["case_229716_chunk_symptom_visuals", "case_229716_chunk_restart_decision", "case_229716_chunk_recovery_logs"],
            "logs_collected": ["Server event logs", "Ignition logs", "Windows event logs"],
            "source_artifacts": ["case_229716_embedded_visual_hb_statistics", "case_229716_embedded_visual_windows_services", "case_229716_embedded_visual_saved_logs"],
            "known_facts": [
                "AGVs stopped before tippers.",
                "Tipper heartbeat timeout was active.",
                "No active RMS faults were reported.",
                "Hospital tote removal failed.",
                "L2/L3 support was engaged through Teams.",
            ],
            "actions_taken": [
                "Remote support initiated.",
                "Heartbeat statistics requested.",
                "System was E-stopped.",
                "Optisweep service restart was performed.",
                "E-stop was removed.",
                "Event and Ignition logs were collected.",
            ],
            "evidence_available": [
                "Heartbeat statistics screenshot",
                "Windows Services screenshot",
                "RMS/tipper visual evidence",
                "Saved logs screenshot",
                "Salesforce resolution update",
                "Teams escalation thread",
            ],
            "open_questions": ["DB log transfer method was unclear in the source evidence.", "Switch logs required follow-up with UPS."],
            "follow_up_owners": [
                {"item": "db_logs", "owner": "L2/L3 Software Support or database owner", "status": "needs_follow_up"},
                {"item": "switch_logs", "owner": "UPS or assigned infrastructure contact", "status": "needs_follow_up"},
            ],
            "recommended_owner": "L2/L3 Software Support with possible infrastructure, database, or switch-log follow-up owner.",
            "handoff_summary": "UPS Fort Worth Haslet reported no path to tippers, all lines stopped, hospital tote removal failure, and heartbeat timeout active. Teams escalation engaged L2/L3 support, who requested heartbeat details and directed E-stop, Optisweep service restart, E-stop removal, and log collection. Recovery was documented with AGV operation and hospital function confirmed; DB log transfer and switch logs remained follow-up items.",
            **signal_buckets(
                failure=["no_path_to_tippers_reported", "tipper_flow_blocked", "all_lines_stopped", "hospital_tote_removal_failed", "tipper_heartbeat_timeout_active", "no_active_rms_faults_reported"],
                diagnostic=["heartbeat_statistics_requested", "server_event_logs_collected", "ignition_logs_collected", "db_logs_requested"],
                action=["system_estop_performed", "optisweep_service_restart_documented", "case_status_moved_to_resolved"],
                recovery=["agv_operation_confirmed", "hospital_function_confirmed"],
                escalation=["teams_escalation", "l2_engaged", "service_restart_required", "switch_logs_requested"],
            ),
        },
    }


def enrich_with_refs(item, regions):
    selected, artifact_ids, artifact_paths, embedded_ids, embedded_paths, region_refs, source_pages = refs_for(regions, item.get("region_ids", []))
    confidence = round(sum(region["confidence"] for region in selected) / max(1, len(selected)), 4)
    enriched = {
        **item,
        "source_artifact_ids": artifact_ids,
        "source_artifact_paths": artifact_paths,
        "embedded_artifact_ids": embedded_ids,
        "embedded_artifact_paths": embedded_paths,
        "source_region_refs": region_refs,
        "source_pages": source_pages,
        "confidence": confidence,
    }
    if any(region.get("region_type") == "teams_message_thread" or "Teams" in region.get("source_section", "") for region in selected):
        enriched.update(
            {
                "escalated": True,
                "escalation_source": "teams_chat",
                "support_tiers_involved": ["L1_technical_support", "L2_L3_software_support"],
            }
        )
    return enriched


def relationship_fields(linked_incident_ids=None, linked_event_ids=None, linked_chunk_ids=None, linked_artifact_ids=None, linked_procedure_ids=None, linked_workflow_ids=None):
    return {
        "linked_incident_ids": linked_incident_ids or [],
        "linked_event_ids": linked_event_ids or [],
        "linked_chunk_ids": linked_chunk_ids or [],
        "linked_artifact_ids": linked_artifact_ids or [],
        "linked_procedure_ids": linked_procedure_ids or [],
        "linked_workflow_ids": linked_workflow_ids or [],
    }


def ensure_procedure_contract(proc):
    proc["procedure_category_status"] = "candidate"
    proc.setdefault("promotion_blockers", [])
    if not proc["promotion_blockers"]:
        proc["promotion_blockers"] = [
            "Requires SME review before promotion.",
            "Requires access and role validation.",
            "Requires repeated incident evidence before multi-case maturity.",
        ]
    proc.setdefault("refinement_opportunities", [])
    for step in proc.get("procedure_steps", []):
        related_artifacts = step.get("related_artifacts", [])
        step.setdefault("evidence_quality", "medium" if related_artifacts else "low")
        if related_artifacts:
            step.setdefault("evidence_quality_notes", "Step is supported by source text and linked visual evidence, but screenshot interpretation remains candidate-level pending SME review.")
        else:
            step.setdefault("evidence_quality_notes", "Step is supported by source text only; no direct screenshot was linked for this step.")
    return proc


def add_relationship_ids(records):
    timeline = records["timeline_events"]
    chunks = records["raw_evidence_chunks"]
    procedures = records["procedure_candidates"]
    workflows = records["workflow_candidate_steps"]
    artifacts = records["source_artifact_references"]
    all_event_ids = [event["event_id"] for event in timeline]
    all_chunk_ids = [chunk["chunk_id"] for chunk in chunks]
    all_procedure_ids = [procedure["procedure_id"] for procedure in procedures]
    all_workflow_ids = sorted({workflow["candidate_workflow_name"] for workflow in workflows})
    all_artifact_ids = [artifact["artifact_id"] for artifact in artifacts]

    records["canonical_incident"].update(
        relationship_fields(
            linked_incident_ids=["229716"],
            linked_event_ids=all_event_ids,
            linked_chunk_ids=all_chunk_ids,
            linked_artifact_ids=records["canonical_incident"].get("source_artifact_ids", []),
            linked_procedure_ids=all_procedure_ids,
            linked_workflow_ids=all_workflow_ids,
        )
    )

    for chunk in chunks:
        chunk_regions = set(chunk.get("source_region_refs", []))
        linked_events = [event["event_id"] for event in timeline if chunk_regions.intersection(event.get("source_region_refs", []))]
        linked_procedures = [
            procedure["procedure_id"]
            for procedure in procedures
            if chunk["chunk_id"] in procedure.get("supporting_evidence_chunks", []) or chunk_regions.intersection(procedure.get("source_region_refs", []))
        ]
        linked_workflows = [workflow["candidate_workflow_name"] for workflow in workflows if chunk["chunk_id"] in workflow.get("evidence_refs", [])]
        chunk.update(
            relationship_fields(
                linked_incident_ids=["229716"],
                linked_event_ids=linked_events,
                linked_chunk_ids=[chunk["chunk_id"]],
                linked_artifact_ids=chunk.get("source_artifact_ids", []),
                linked_procedure_ids=linked_procedures,
                linked_workflow_ids=sorted(set(linked_workflows)),
            )
        )

    for event in timeline:
        event_regions = set(event.get("source_region_refs", []))
        linked_chunks = [chunk["chunk_id"] for chunk in chunks if event_regions.intersection(chunk.get("source_region_refs", []))]
        linked_procedures = [
            procedure["procedure_id"]
            for procedure in procedures
            if event["event_id"] in procedure.get("supporting_timeline_events", []) or event_regions.intersection(procedure.get("source_region_refs", []))
        ]
        linked_workflows = [
            workflow["candidate_workflow_name"]
            for workflow in workflows
            if set(workflow.get("evidence_refs", [])).intersection(linked_chunks) or set(workflow.get("procedure_refs", [])).intersection(linked_procedures)
        ]
        event.update(
            relationship_fields(
                linked_incident_ids=["229716"],
                linked_event_ids=[event["event_id"]],
                linked_chunk_ids=linked_chunks,
                linked_artifact_ids=event.get("source_artifact_ids", []),
                linked_procedure_ids=linked_procedures,
                linked_workflow_ids=sorted(set(linked_workflows)),
            )
        )

    for procedure in procedures:
        procedure.update(
            relationship_fields(
                linked_incident_ids=["229716"],
                linked_event_ids=procedure.get("supporting_timeline_events", []),
                linked_chunk_ids=procedure.get("supporting_evidence_chunks", []),
                linked_artifact_ids=sorted(set(procedure.get("supporting_artifacts", []) + procedure.get("source_artifact_ids", []))),
                linked_procedure_ids=[procedure["procedure_id"]],
                linked_workflow_ids=procedure.get("related_workflows", []),
            )
        )

    for workflow in workflows:
        workflow.update(
            relationship_fields(
                linked_incident_ids=["229716"],
                linked_event_ids=[],
                linked_chunk_ids=workflow.get("evidence_refs", []),
                linked_artifact_ids=sorted(set(workflow.get("image_refs", []) + workflow.get("source_artifact_ids", []))),
                linked_procedure_ids=workflow.get("procedure_refs", []),
                linked_workflow_ids=[workflow["candidate_workflow_name"]],
            )
        )

    records["escalation_summary_template"].update(
        relationship_fields(
            linked_incident_ids=["229716"],
            linked_event_ids=all_event_ids,
            linked_chunk_ids=records["escalation_summary_template"].get("evidence_refs", []),
            linked_artifact_ids=sorted(set(records["escalation_summary_template"].get("source_artifacts", []) + records["escalation_summary_template"].get("source_artifact_ids", []))),
            linked_procedure_ids=all_procedure_ids,
            linked_workflow_ids=all_workflow_ids,
        )
    )

    for artifact in artifacts:
        artifact.update(
            relationship_fields(
                linked_incident_ids=["229716"],
                linked_artifact_ids=[artifact["artifact_id"]],
            )
        )
    return records


def build_artifact_records(regions):
    seen = {}
    for region in regions:
        seen[region["artifact_id"]] = region
    records = []
    for artifact_id, region_data in sorted(seen.items()):
        records.append(
            {
                **base_record("source_artifact_reference", region_data["source_section"], region_data["source_page"], f"Case 229716 Data.docx#artifact={artifact_id}", 1.0, [], ["DOCX embedded screenshot retained for region-level traceability."]),
                "artifact_id": artifact_id,
                "artifact_type": "docx_embedded_image",
                "artifact_path": region_data["artifact_path"],
                "regions": [region["region_id"] for region in regions if region["artifact_id"] == artifact_id],
            }
        )
    for region_data in sorted((region for region in regions if region.get("embedded_artifact_id")), key=lambda item: item["embedded_artifact_id"]):
        records.append(
            {
                **base_record("source_artifact_reference", region_data["source_section"], region_data["source_page"], f"Case 229716 Data.docx#embedded-region={region_data['region_id']}", region_data["confidence"], [], ["Cropped embedded screenshot region retained as its own visual source artifact."]),
                "artifact_id": region_data["embedded_artifact_id"],
                "artifact_type": region_data["embedded_artifact_type"],
                "artifact_path": region_data["embedded_artifact_path"],
                "parent_artifact_id": region_data["embedded_parent_artifact_id"],
                "parent_artifact_path": region_data["embedded_parent_artifact_path"],
                "source_region_ref": region_data["region_id"],
                "bbox": region_data["bbox"],
                "visual_evidence_summary": region_data["visual_evidence_summary"],
            }
        )
    return records


def build_records(regions, interpretations):
    region_list = regions["regions"]
    canonical_regions = [region["region_id"] for region in region_list if region["role"] in ["primary_evidence", "visual_support"]]
    canonical_refs = enrich_with_refs({"region_ids": canonical_regions}, region_list)
    canonical_data = interpretations["canonical_incident"]
    canonical = {
        **base_record("canonical_incident", "All Source Sections", None, "Case 229716 Data.docx#mixed-screenshot-regions", 0.82, ["validated_root_cause"], ["LLM-assisted candidate summary from region-level screenshot interpretation."]),
        **canonical_data,
        "source_artifact_ids": canonical_refs["source_artifact_ids"],
        "source_artifact_paths": canonical_refs["source_artifact_paths"],
        "embedded_artifact_ids": canonical_refs["embedded_artifact_ids"],
        "embedded_artifact_paths": canonical_refs["embedded_artifact_paths"],
        "source_region_refs": canonical_refs["source_region_refs"],
        **review_fields(["L2_L3_software_support"], ["remote_service_access", "service_restart_access", "log_access"]),
        "workflow_candidate": True,
    }
    chunks = []
    for chunk in interpretations["semantic_chunks"]:
        refs = enrich_with_refs(chunk, region_list)
        chunks.append(
            {
                **base_record("raw_evidence_chunk", "Mixed Screenshot Evidence", refs["source_pages"], ",".join(refs["source_region_refs"]), refs["confidence"], [], ["Semantic chunk created from LLM-assisted interpretation of OCR/layout regions."]),
                "chunk_id": chunk["chunk_id"],
                "title": chunk["title"],
                "content": chunk["summary"],
                "raw_source_type": chunk["raw_source_type"],
                "evidence_type": chunk["evidence_type"],
                **{bucket: chunk.get(bucket, []) for bucket in SIGNAL_BUCKETS},
                **({key: refs[key] for key in ["escalated", "escalation_source", "support_tiers_involved"] if key in refs}),
                "source_artifact_ids": refs["source_artifact_ids"],
                "source_artifact_paths": refs["source_artifact_paths"],
                "embedded_artifact_ids": refs["embedded_artifact_ids"],
                "embedded_artifact_paths": refs["embedded_artifact_paths"],
                "source_region_refs": refs["source_region_refs"],
                "visual_evidence_summary": "Includes full screenshots and cropped embedded operational screenshot regions when referenced regions are visual evidence.",
            }
        )
    timeline = []
    for index, event in enumerate(interpretations["timeline_events"], start=1):
        refs = enrich_with_refs(event, region_list)
        timeline.append(
            {
                **base_record("timeline_event", "Mixed Screenshot Evidence", refs["source_pages"], ",".join(refs["source_region_refs"]), refs["confidence"], ["normalized_timestamp"] if not event.get("timestamp_raw") else [], ["Timeline event created from grouped content block, not timestamp-only OCR line."]),
                "event_id": event["event_id"],
                "container_id": event["container_id"],
                "event_order": index,
                "timestamp_raw": event["timestamp_raw"],
                "event_occurred_at": event["event_occurred_at"],
                "event_documented_at": event["event_documented_at"],
                "actor": event["actor"],
                "actor_role": event["actor_role"],
                "event_type": event["event_type"],
                "event_summary": event["event_summary"],
                **{bucket: event.get(bucket, []) for bucket in SIGNAL_BUCKETS},
                "action_taken": event["action_taken"],
                "outcome": event["outcome"],
                **({key: refs[key] for key in ["escalated", "escalation_source", "support_tiers_involved"] if key in refs}),
                "source_artifact_ids": refs["source_artifact_ids"],
                "source_artifact_paths": refs["source_artifact_paths"],
                "embedded_artifact_ids": refs["embedded_artifact_ids"],
                "embedded_artifact_paths": refs["embedded_artifact_paths"],
                "source_region_refs": refs["source_region_refs"],
            }
        )
    procedures = []
    for proc in interpretations["procedure_candidates"]:
        proc = ensure_procedure_contract(proc)
        refs = enrich_with_refs(proc, region_list)
        procedures.append(
            {
                **base_record("procedure_candidate", "Mixed Screenshot Evidence", refs["source_pages"], ",".join(refs["source_region_refs"]), refs["confidence"], ["approval_status", "preconditions"], ["Procedure candidate filtered to require operational action context and source regions."]),
                **proc,
                "procedure_id": proc["procedure_candidate_id"],
                "container_id": "phase0_procedure_candidates",
                **review_fields(proc.get("role_requirements", []), proc.get("required_permissions", [])),
                **({key: refs[key] for key in ["escalated", "escalation_source", "support_tiers_involved"] if key in refs}),
                "source_artifact_ids": refs["source_artifact_ids"],
                "source_artifact_paths": refs["source_artifact_paths"],
                "embedded_artifact_ids": refs["embedded_artifact_ids"],
                "embedded_artifact_paths": refs["embedded_artifact_paths"],
                "source_region_refs": refs["source_region_refs"],
            }
        )
    workflows = []
    for workflow in interpretations["workflow_candidate_steps"]:
        refs = enrich_with_refs(workflow, region_list)
        workflows.append(
            {
                **base_record("workflow_candidate_step", "Mixed Screenshot Evidence", refs["source_pages"], ",".join(refs["source_region_refs"]), refs["confidence"], ["approved_owner"], ["Workflow candidate filtered to require event context and source regions."]),
                "workflow_step_id": workflow["workflow_step_id"],
                "container_id": workflow["container_id"],
                "candidate_workflow_name": workflow["candidate_workflow_name"],
                "step_type": workflow["step_type"],
                "question": workflow["question"],
                "why_asked": workflow["why_asked"],
                "candidate_step": workflow["candidate_step"],
                "entry_conditions": workflow["entry_conditions"],
                "required_signals": workflow["required_signals"],
                "negative_signals": workflow["negative_signals"],
                "procedure_refs": workflow["procedure_refs"],
                "evidence_refs": workflow["evidence_refs"],
                "image_refs": workflow["image_refs"],
                "status": workflow["status"],
                "workflow_candidate": True,
                "role_constraints": workflow.get("role_constraints", []),
                "required_permissions": workflow.get("required_permissions", []),
                "requires_role_review": workflow.get("requires_role_review", True),
                **({key: refs[key] for key in ["escalated", "escalation_source", "support_tiers_involved"] if key in refs}),
                "source_artifact_ids": refs["source_artifact_ids"],
                "source_artifact_paths": refs["source_artifact_paths"],
                "embedded_artifact_ids": refs["embedded_artifact_ids"],
                "embedded_artifact_paths": refs["embedded_artifact_paths"],
                "source_region_refs": refs["source_region_refs"],
            }
        )
    escalation_data = interpretations["escalation_summary_template"]
    escalation = {
        **base_record("escalation_summary_template", "Mixed Screenshot Evidence", None, "Case 229716 Data.docx#mixed-screenshot-regions", 0.82, ["open_questions"], ["Escalation template assembled from LLM-assisted semantic regions."]),
        **escalation_data,
        "case_id": "229716",
        "escalation_trigger": escalation_data["trigger_reason"],
        "current_state": "System operational was reported after recovery.",
        "actions_taken": escalation_data["steps_attempted"],
        **review_fields(["L2_L3_software_support", "L2_L3_infrastructure_controls_dba_devops"], ["remote_service_access", "log_access"]),
        "escalated": True,
        "escalation_source": "teams_chat",
        "support_tiers_involved": ["L1_technical_support", "L2_L3_software_support"],
        "source_artifact_ids": canonical_refs["source_artifact_ids"],
        "source_artifact_paths": canonical_refs["source_artifact_paths"],
        "embedded_artifact_ids": canonical_refs["embedded_artifact_ids"],
        "embedded_artifact_paths": canonical_refs["embedded_artifact_paths"],
        "source_region_refs": canonical_refs["source_region_refs"],
    }
    records = {
        "canonical_incident": canonical,
        "timeline_events": timeline,
        "raw_evidence_chunks": chunks,
        "source_artifact_references": build_artifact_records(region_list),
        "procedure_candidates": procedures,
        "workflow_candidate_steps": workflows,
        "escalation_summary_template": escalation,
    }
    return add_relationship_ids(records)


def contains_key(value, key):
    if isinstance(value, dict):
        return key in value or any(contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(contains_key(item, key) for item in value)
    return False


def has_signal_buckets(record):
    return all(bucket in record and isinstance(record[bucket], list) for bucket in SIGNAL_BUCKETS)


def validate_records(records, interpretations):
    required = ["record_type", "incident_id", "source_file", "source_section", "source_page", "source_ref", "confidence", "validation_status", "requires_manual_review", "missing_fields", "extraction_notes"]
    flat = [records["canonical_incident"], *records["timeline_events"], *records["raw_evidence_chunks"], *records["source_artifact_references"], *records["procedure_candidates"], *records["workflow_candidate_steps"], records["escalation_summary_template"]]
    issues = []
    for index, record in enumerate(flat, start=1):
        for field in required:
            if field not in record:
                issues.append({"record_index": index, "record_type": record.get("record_type"), "issue": f"missing {field}"})
        if record.get("validation_status") != "candidate_extracted":
            issues.append({"record_index": index, "record_type": record.get("record_type"), "issue": "invalid validation_status"})
        if record.get("requires_manual_review") is not True:
            issues.append({"record_index": index, "record_type": record.get("record_type"), "issue": "requires_manual_review must be true"})
        for path in record.get("source_artifact_paths", []):
            if not (ROOT / path).exists():
                issues.append({"record_index": index, "record_type": record.get("record_type"), "issue": f"missing artifact path {path}"})
        for path in record.get("embedded_artifact_paths", []):
            if not (ROOT / path).exists():
                issues.append({"record_index": index, "record_type": record.get("record_type"), "issue": f"missing embedded artifact path {path}"})
        if contains_key(record, "observed_signals"):
            issues.append({"record_index": index, "record_type": record.get("record_type"), "issue": "observed_signals is deprecated"})
        if contains_key(record, "inferred_causes"):
            issues.append({"record_index": index, "record_type": record.get("record_type"), "issue": "inferred_causes must be candidate_inferred_causes objects"})
        if record.get("record_type") in {"canonical_incident", "procedure_candidate", "workflow_candidate_step", "escalation_summary_template"}:
            if contains_key(record, "support_safe") or contains_key(record, "engineer_required"):
                issues.append({"record_index": index, "record_type": record.get("record_type"), "issue": "premature safety classification field present"})
            if "role_constraints" not in record or "required_permissions" not in record or record.get("requires_role_review") is not True:
                issues.append({"record_index": index, "record_type": record.get("record_type"), "issue": "missing role review fields"})
        if record.get("record_type") in {"canonical_incident", "timeline_event", "raw_evidence_chunk", "escalation_summary_template"} and not has_signal_buckets(record):
            issues.append({"record_index": index, "record_type": record.get("record_type"), "issue": "missing separated signal buckets"})
        if record.get("record_type") in {"canonical_incident", "timeline_event", "raw_evidence_chunk", "procedure_candidate", "workflow_candidate_step", "escalation_summary_template"}:
            for field in ["linked_incident_ids", "linked_event_ids", "linked_chunk_ids", "linked_artifact_ids", "linked_procedure_ids", "linked_workflow_ids"]:
                if field not in record:
                    issues.append({"record_index": index, "record_type": record.get("record_type"), "issue": f"missing relationship field {field}"})
        if record.get("record_type") == "raw_evidence_chunk":
            if record.get("raw_source_type") not in ALLOWED_RAW_SOURCE_TYPES:
                issues.append({"record_index": index, "record_type": record.get("record_type"), "issue": "invalid raw_source_type"})
            if record.get("evidence_type") not in ALLOWED_EVIDENCE_TYPES:
                issues.append({"record_index": index, "record_type": record.get("record_type"), "issue": "invalid evidence_type"})
        if record.get("record_type") == "timeline_event":
            if "event_occurred_at" not in record or "event_documented_at" not in record or not record.get("event_documented_at"):
                issues.append({"record_index": index, "record_type": record.get("record_type"), "issue": "missing occurred/documented timestamp fields"})
        if record.get("record_type") in {"timeline_event", "raw_evidence_chunk", "procedure_candidate", "workflow_candidate_step"}:
            refs = record.get("source_region_refs", [])
            teams_like = any(ref.startswith("region_teams") or ref in {"region_visual_hb_statistics", "region_visual_windows_services", "region_visual_saved_logs", "region_visual_performance_monitor"} for ref in refs)
            if teams_like and (record.get("escalated") is not True or record.get("escalation_source") != "teams_chat" or not record.get("support_tiers_involved")):
                issues.append({"record_index": index, "record_type": record.get("record_type"), "issue": "Teams-derived record missing escalation metadata"})
    visual_artifacts = [record for record in records["source_artifact_references"] if record.get("artifact_type") == "embedded_screenshot_region"]
    visual_chunks = [chunk for chunk in records["raw_evidence_chunks"] if any(ref.startswith("region_visual_") for ref in chunk.get("source_region_refs", []))]
    canonical = records["canonical_incident"]
    procedures = records["procedure_candidates"]
    workflows = records["workflow_candidate_steps"]
    escalation = records["escalation_summary_template"]
    procedure_required = {"procedure_candidate_id", "procedure_name", "procedure_category", "candidate_maturity", "related_cases", "related_components", "related_workflows", "related_escalation_patterns", "known_failure_modes", "procedure_summary", "procedure_goal", "required_tools_or_systems", "role_requirements", "required_permissions", "preconditions", "validation_checks", "validation_evidence", "recovery_outcomes", "known_risks", "escalation_conditions", "refinement_opportunities", "procedure_steps", "validation_status"}
    workflow_names_are_symptom_driven = all(not workflow.get("candidate_workflow_name", "").startswith("case_") and workflow.get("status") == "draft" for workflow in workflows)
    workflows_orchestrate = all(workflow.get("step_type") != "action" and "negative_signals" in workflow for workflow in workflows)
    escalation_fields = ["trigger_reason", "symptoms", "steps_attempted", "steps_not_attempted", "evidence_refs", "logs_collected", "source_artifacts", "known_facts", "actions_taken", "evidence_available", "open_questions", "follow_up_owners", "recommended_owner", "handoff_summary"]
    procedure_categories_candidate = all(proc.get("procedure_category") in ALLOWED_PROCEDURE_CATEGORIES and proc.get("procedure_category_status") == "candidate" for proc in procedures)
    procedure_steps_have_evidence_quality = all(
        all(step.get("evidence_quality") in {"high", "medium", "low"} and "evidence_quality_notes" in step for step in proc.get("procedure_steps", []))
        for proc in procedures
    )
    relationship_ids_present = all(
        all(field in record for field in ["linked_incident_ids", "linked_event_ids", "linked_chunk_ids", "linked_artifact_ids", "linked_procedure_ids", "linked_workflow_ids"])
        for record in [records["canonical_incident"], *records["timeline_events"], *records["raw_evidence_chunks"], *records["procedure_candidates"], *records["workflow_candidate_steps"], records["escalation_summary_template"]]
    )
    no_deprecated_cause_field = not contains_key(canonical, "inferred_causes") and isinstance(canonical.get("candidate_inferred_causes"), list)
    return {
        "validation_status": "passed" if not issues else "failed",
        "record_count": len(flat),
        "issues": issues,
        "quality_checks": {
            "timeline_events_have_actors": all(event.get("actor") for event in records["timeline_events"]),
            "timeline_events_have_event_types": all(event.get("event_type") and event.get("event_type") != "unknown" for event in records["timeline_events"]),
            "chunks_are_semantic_not_page_sized": all("chunk_" in chunk["chunk_id"] and not re.search(r"docx_\\d+$", chunk["chunk_id"]) for chunk in records["raw_evidence_chunks"]),
            "records_link_images_directly": all(record.get("source_artifact_paths") for record in [*records["timeline_events"], *records["raw_evidence_chunks"]]),
            "embedded_visual_artifacts_created": len(visual_artifacts) >= 1,
            "visual_chunks_link_embedded_images": all(chunk.get("embedded_artifact_paths") for chunk in visual_chunks),
            "role_review_fields_replace_safety_fields": not any(contains_key(record, "support_safe") or contains_key(record, "engineer_required") for record in flat),
            "signal_buckets_replace_observed_signals": not any(contains_key(record, "observed_signals") for record in flat),
            "candidate_inferred_causes_used": no_deprecated_cause_field,
            "action_signals_present": all("action_signals" in record for record in [canonical, *records["timeline_events"], *records["raw_evidence_chunks"], escalation]),
            "canonical_has_retrieval_text": bool(canonical.get("retrieval_text")),
            "raw_chunks_have_source_and_evidence_types": all(chunk.get("raw_source_type") in ALLOWED_RAW_SOURCE_TYPES and chunk.get("evidence_type") in ALLOWED_EVIDENCE_TYPES for chunk in records["raw_evidence_chunks"]),
            "teams_records_have_escalation_metadata": not any(issue["issue"] == "Teams-derived record missing escalation metadata" for issue in issues),
            "timeline_has_occurred_and_documented_timestamps": all("event_occurred_at" in event and event.get("event_documented_at") for event in records["timeline_events"]),
            "normalization_metadata_present": all(field in canonical for field in ["raw_terms", "normalized_terms", "normalization_confidence"]),
            "procedure_candidates_step_based": all(procedure_required.issubset(set(proc.keys())) and proc.get("procedure_steps") and not contains_key(proc, "candidate_action") for proc in procedures),
            "procedure_categories_remain_candidate": procedure_categories_candidate,
            "procedure_candidates_have_promotion_blockers": all(proc.get("promotion_blockers") for proc in procedures),
            "procedure_steps_have_evidence_quality": procedure_steps_have_evidence_quality,
            "procedure_steps_link_artifacts": any(any(step.get("related_artifacts") for step in proc.get("procedure_steps", [])) for proc in procedures),
            "relationship_ids_present": relationship_ids_present,
            "seed_doc_context_alignment_present": bool(interpretations.get("dataset_context_used", {}).get("dataset_layers")),
            "llm_interpretation_contract_present": bool(interpretations.get("metadata", {}).get("llm_output_contract")),
            "workflow_candidates_are_symptom_driven_drafts": workflow_names_are_symptom_driven,
            "workflow_steps_orchestrate_procedures": workflows_orchestrate,
            "escalation_template_answers_handoff_questions": all(escalation.get(field) is not None for field in escalation_fields),
            "escalation_template_preserves_follow_up": bool(escalation.get("open_questions")) and bool(escalation.get("follow_up_owners")),
            "procedure_candidates_filtered": not any(proc.get("procedure_name") in ["G RMS - Map Monitor", "RMS - Map Monitor"] for proc in procedures),
        },
    }


def copy_artifacts(ocr_data):
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for page in ocr_data["pages"]:
        source_path = ROOT / page["artifact_path"]
        target_path = ARTIFACT_DIR / source_path.name
        if source_path.exists() and not target_path.exists():
            shutil.copyfile(source_path, target_path)
        page["artifact_path"] = str(target_path.relative_to(ROOT)).replace("\\", "/")
    return ocr_data


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    ocr_data = json.loads(SOURCE_OCR_PATH.read_text(encoding="utf-8"))
    ocr_data = copy_artifacts(ocr_data)
    prompt_text = PHASE0_PROMPT_PATH.read_text(encoding="utf-8")
    reference = json.loads(REFERENCE_EXTRACTION_PATH.read_text(encoding="utf-8"))
    layout_blocks = reconstruct_layout_blocks(ocr_data)
    regions = classify_regions(ocr_data)
    regions = create_embedded_region_artifacts(regions)
    interpretations = build_interpretations(regions["regions"], prompt_text, reference)
    records = build_records(regions, interpretations)
    bundle = {
        "bundle_metadata": {
            "incident_id": "229716",
            "phase": "0",
            "category": interpretations["dataset_context_used"].get("deterministic_issue_category"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_files": ["prompts/phase0_system_prompt.txt", "docs/Phase0 Cat1 Dataset Seed Records V1.docx", "docs/Optisweep Issue Categories.docx", ACTIVE_SOURCE_FILE],
            "ocr_engine": "PaddleOCR 3.5.0 / PaddlePaddle 3.2.2 / PP-OCRv5 server det+rec",
            "interpretation_engine": "cursor_llm_cached_v2",
            "validation_status": "candidate_extracted",
            "requires_manual_review": True,
        },
        "records": records,
    }
    report = validate_records(records, interpretations)
    write_json(EXTRACTED_DIR / "case_229716_docx_ocr.json", ocr_data)
    write_json(EXTRACTED_DIR / "case_229716_layout_blocks.json", layout_blocks)
    write_json(EXTRACTED_DIR / "case_229716_semantic_regions.json", regions)
    write_json(EXTRACTED_DIR / "case_229716_llm_interpretations.json", interpretations)
    write_json(OUTPUT_DIR / "seed_records.json", bundle)
    write_json(OUTPUT_DIR / "validation_report.json", report)
    print(json.dumps({"output_dir": str(OUTPUT_DIR), **report}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
