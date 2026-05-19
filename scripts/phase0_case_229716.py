import argparse
import json
import re
import shutil
import statistics
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import fitz
import numpy as np
from PIL import Image
from paddleocr import PaddleOCR


ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATH = ROOT / "prompts" / "phase0_system_prompt.txt"
REFERENCE_DOCX_PATH = ROOT / "docs" / "Phase0 Cat1 Dataset Seed Records V1.docx"
SOURCE_PDF_PATH = ROOT / "data" / "Case 229716 Data.pdf"
SOURCE_DOCX_PATH = ROOT / "data" / "Case 229716 Data.docx"
OUTPUT_DIR = ROOT / "output" / "phase0" / "case_229716"
EXTRACTED_DIR = OUTPUT_DIR / "extracted"
ARTIFACTS_DIR = OUTPUT_DIR / "artifacts"
REFERENCE_MEDIA_DIR = ARTIFACTS_DIR / "reference_docx_media"
PAGE_IMAGE_DIR = ARTIFACTS_DIR / "pdf_pages"
REFERENCE_EXTRACTION_PATH = EXTRACTED_DIR / "reference_docx_extraction.json"
PDF_OCR_PATH = EXTRACTED_DIR / "case_229716_pdf_ocr.json"
SOURCE_OCR_PATH = PDF_OCR_PATH
ACTIVE_SOURCE_FILE = "data/Case 229716 Data.pdf"
ACTIVE_SOURCE_REF_PREFIX = "Case 229716 Data.pdf"
ACTIVE_SOURCE_RANGE_REF = "Case 229716 Data.pdf#pages=1-13"
ACTIVE_SOURCE_KIND = "pdf"


def configure_paths(source_kind):
    global OUTPUT_DIR
    global EXTRACTED_DIR
    global ARTIFACTS_DIR
    global REFERENCE_MEDIA_DIR
    global PAGE_IMAGE_DIR
    global REFERENCE_EXTRACTION_PATH
    global SOURCE_OCR_PATH
    global ACTIVE_SOURCE_FILE
    global ACTIVE_SOURCE_REF_PREFIX
    global ACTIVE_SOURCE_RANGE_REF
    global ACTIVE_SOURCE_KIND
    ACTIVE_SOURCE_KIND = source_kind
    if source_kind == "docx":
        OUTPUT_DIR = ROOT / "output" / "phase0" / "case_229716_docx"
        ACTIVE_SOURCE_FILE = "data/Case 229716 Data.docx"
        ACTIVE_SOURCE_REF_PREFIX = "Case 229716 Data.docx"
        ACTIVE_SOURCE_RANGE_REF = "Case 229716 Data.docx#embedded-media=1-12"
        source_ocr_name = "case_229716_docx_ocr.json"
        artifact_dir_name = "docx_media"
    else:
        OUTPUT_DIR = ROOT / "output" / "phase0" / "case_229716"
        ACTIVE_SOURCE_FILE = "data/Case 229716 Data.pdf"
        ACTIVE_SOURCE_REF_PREFIX = "Case 229716 Data.pdf"
        ACTIVE_SOURCE_RANGE_REF = "Case 229716 Data.pdf#pages=1-13"
        source_ocr_name = "case_229716_pdf_ocr.json"
        artifact_dir_name = "pdf_pages"
    EXTRACTED_DIR = OUTPUT_DIR / "extracted"
    ARTIFACTS_DIR = OUTPUT_DIR / "artifacts"
    REFERENCE_MEDIA_DIR = ARTIFACTS_DIR / "reference_docx_media"
    PAGE_IMAGE_DIR = ARTIFACTS_DIR / artifact_dir_name
    REFERENCE_EXTRACTION_PATH = EXTRACTED_DIR / "reference_docx_extraction.json"
    SOURCE_OCR_PATH = EXTRACTED_DIR / source_ocr_name


def ensure_dirs():
    for path in [OUTPUT_DIR, EXTRACTED_DIR, ARTIFACTS_DIR, REFERENCE_MEDIA_DIR, PAGE_IMAGE_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def qn(local_name):
    return "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}" + local_name


def extract_docx_text(path):
    paragraphs = []
    media = []
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if "word/document.xml" in names:
            root = ET.fromstring(archive.read("word/document.xml"))
            for para in root.iter(qn("p")):
                parts = []
                for node in para.iter():
                    if node.tag == qn("t") and node.text:
                        parts.append(node.text)
                    elif node.tag == qn("tab"):
                        parts.append("\t")
                    elif node.tag == qn("br"):
                        parts.append("\n")
                text = clean_text("".join(parts))
                if text:
                    paragraphs.append(text)
        for name in names:
            if name.startswith("word/media/"):
                target = REFERENCE_MEDIA_DIR / Path(name).name
                target.write_bytes(archive.read(name))
                media.append(str(target.relative_to(ROOT)).replace("\\", "/"))
    return paragraphs, media


def make_ocr():
    return PaddleOCR(
        text_detection_model_name="PP-OCRv5_server_det",
        text_recognition_model_name="PP-OCRv5_server_rec",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=True,
        text_det_limit_side_len=2400,
        text_det_limit_type="max",
    )


def normalize_poly(poly):
    if poly is None:
        return None
    try:
        return [[float(point[0]), float(point[1])] for point in poly]
    except Exception:
        return None


def run_ocr(ocr, image):
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


def image_to_array(path):
    with Image.open(path) as image:
        return np.array(image.convert("RGB"))


def ocr_reference_media(ocr, media_paths):
    outputs = []
    for media_path in media_paths:
        print(f"OCR reference media {len(outputs) + 1}/{len(media_paths)}: {media_path}", flush=True)
        full_path = ROOT / media_path
        suffix = full_path.suffix.lower()
        item = {
            "artifact_path": media_path,
            "ocr_supported": suffix in [".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"],
            "ocr_lines": [],
            "extraction_notes": [],
        }
        if item["ocr_supported"]:
            try:
                item["ocr_lines"] = run_ocr(ocr, image_to_array(full_path))
            except Exception as exc:
                item["extraction_notes"].append(str(exc))
        outputs.append(item)
    return outputs


def section_for_page(page_number):
    if 1 <= page_number <= 6:
        return "Salesforce Case Data"
    if 7 <= page_number <= 13:
        return "Teams Chat Data / Haslet Support Chat"
    return "Unknown Evidence"


def section_from_heading(text, current_section):
    normalized = clean_text(text).lower()
    if "salesforce" in normalized and "case" in normalized:
        return "Salesforce Case Data"
    if "teams" in normalized or "haslet support chat" in normalized:
        return "Teams Chat Data / Haslet Support Chat"
    return current_section


def render_and_ocr_pdf(ocr, path):
    doc = fitz.open(path)
    pages = []
    for page_index in range(doc.page_count):
        page_number = page_index + 1
        print(f"OCR PDF page {page_number}/{doc.page_count}", flush=True)
        page = doc.load_page(page_index)
        native_text = page.get_text("text").strip()
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        image_path = PAGE_IMAGE_DIR / f"case_229716_page_{page_number:02d}.png"
        pix.save(image_path)
        image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        ocr_lines = run_ocr(ocr, image)
        pages.append(
            {
                "page": page_number,
                "source_section": section_for_page(page_number),
                "native_text": native_text,
                "ocr_lines": ocr_lines,
                "artifact_path": str(image_path.relative_to(ROOT)).replace("\\", "/"),
                "source_ref": f"{ACTIVE_SOURCE_REF_PREFIX}#page={page_number}",
                "artifact_type": "pdf_page_render",
                "width": pix.width,
                "height": pix.height,
            }
        )
    doc.close()
    return pages


def relationship_targets(archive):
    rels = {}
    rels_path = "word/_rels/document.xml.rels"
    if rels_path not in archive.namelist():
        return rels
    root = ET.fromstring(archive.read(rels_path))
    for rel in root:
        rel_id = rel.attrib.get("Id")
        target = rel.attrib.get("Target")
        if rel_id and target:
            rels[rel_id] = "word/" + target.lstrip("/")
    return rels


def paragraph_text(para):
    parts = []
    for node in para.iter():
        if node.tag == qn("t") and node.text:
            parts.append(node.text)
        elif node.tag == qn("tab"):
            parts.append("\t")
        elif node.tag == qn("br"):
            parts.append("\n")
    return clean_text("".join(parts))


def embedded_relationship_ids(para):
    ids = []
    for node in para.iter():
        if node.tag.endswith("}blip"):
            rel_id = node.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
            if rel_id:
                ids.append(rel_id)
    return ids


def extract_and_ocr_docx_media(ocr, path):
    pages = []
    current_section = "Unknown Evidence"
    with zipfile.ZipFile(path) as archive:
        rels = relationship_targets(archive)
        root = ET.fromstring(archive.read("word/document.xml"))
        body = root.find(qn("body"))
        if body is None:
            return pages
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
                image_path = PAGE_IMAGE_DIR / f"case_229716_docx_image_{media_index:02d}{suffix}"
                image_path.write_bytes(archive.read(target))
                with Image.open(image_path) as image:
                    width, height = image.size
                    image_array = np.array(image.convert("RGB"))
                print(f"OCR DOCX media {media_index}: {Path(target).name}", flush=True)
                ocr_lines = run_ocr(ocr, image_array)
                pages.append(
                    {
                        "page": media_index,
                        "source_section": current_section,
                        "native_text": text,
                        "ocr_lines": ocr_lines,
                        "artifact_path": str(image_path.relative_to(ROOT)).replace("\\", "/"),
                        "source_ref": f"{ACTIVE_SOURCE_REF_PREFIX}#media={Path(target).name}",
                        "artifact_type": "docx_embedded_image",
                        "width": width,
                        "height": height,
                    }
                )
    return pages


def average_confidence(lines):
    scores = [line["confidence"] for line in lines if line.get("confidence") is not None]
    return round(statistics.mean(scores), 4) if scores else 0.0


def record_base(record_type, section, page, source_ref, confidence, missing_fields, extraction_notes):
    return {
        "record_type": record_type,
        "incident_id": "229716",
        "source_file": ACTIVE_SOURCE_FILE,
        "source_section": section,
        "source_page": page,
        "source_ref": source_ref,
        "confidence": confidence,
        "validation_status": "candidate_extracted",
        "requires_manual_review": True,
        "missing_fields": missing_fields,
        "extraction_notes": extraction_notes,
    }


def page_text(page):
    ocr_text = "\n".join(line["text"] for line in page["ocr_lines"])
    return clean_text("\n".join([page["native_text"], ocr_text]))


def all_page_text(pages):
    return clean_text(" ".join(page_text(page) for page in pages))


def has_text(text, *needles):
    lower = text.lower()
    return any(needle.lower() in lower for needle in needles)


def case_fields(pages):
    text = all_page_text(pages)
    lower = text.lower()
    subject_variants = []
    if "problems with the acd system" in lower:
        subject_variants.append("Problems with the ACD system")
    if "problems with the avg system" in lower:
        subject_variants.append("Problems with the AVG system")
    observed = []
    if has_text(text, "nothing is coming up to the tippers", "nothing is comming to the tippers"):
        observed.append("Nothing was coming up to the tippers.")
    if has_text(text, "everything is waiting") and has_text(text, "path"):
        observed.append("Everything was waiting and no path was showing.")
    if has_text(text, "all 3 lines stopped"):
        observed.append("All 3 lines stopped after AGVs lined up to go to tippers.")
    if has_text(text, "unable to remove the tote", "weren't able to remove the tote"):
        observed.append("The site was unable to remove a tote at the hospital station.")
    if has_text(text, "heartbeat timeout"):
        observed.append("Tippers showed heartbeat timeout status.")
    if has_text(text, "all tippers are enabled"):
        observed.append("All tippers were enabled.")
    if has_text(text, "avgs are moving"):
        observed.append("AVGs were moving after recovery.")
    if has_text(text, "able to remove totes"):
        observed.append("The site was able to remove totes after recovery.")
    if has_text(text, "system operational"):
        observed.append("System operational was reported before the call disengaged.")
    status_transitions = []
    for transition in [
        "New to In Progress",
        "In Progress to Escalated (Waiting on Another Department)",
        "Escalated (Waiting on Another Department) to Resolved",
        "Resolved to Closed",
    ]:
        if has_text(text, transition):
            status_transitions.append(transition)
    roles = []
    for name in [
        "Gianny D Perez Rocha",
        "Justin McCalmont",
        "Kevin Buczek",
        "Mitchel Flynn",
        "Harvey Dhillon",
        "Antonio Rodrigo",
    ]:
        compact = name.replace(" ", "")
        if has_text(text, name) or has_text(text, compact):
            roles.append(name)
    resolution_steps = []
    if has_text(text, "E-stopped system"):
        resolution_steps.append("E-stopped system.")
    if has_text(text, "Restarted Optisweep service", "Restart optisweep"):
        resolution_steps.append("Restarted Optisweep service.")
    if has_text(text, "Antonio confirmed proper AVG operation"):
        resolution_steps.append("Antonio confirmed proper AVG operation.")
    if has_text(text, "Hospital function"):
        resolution_steps.append("Confirmed hospital function.")
    if has_text(text, "Ignition and Windows event logs"):
        resolution_steps.append("Saved Ignition and Windows event logs to the RDP desktop.")
    return {
        "source_case_id": "00229716" if has_text(text, "00229716", "Case:00229716") else None,
        "opened_at": "4/15/2026 7:40 PM" if has_text(text, "4/15/2026") and has_text(text, "7:40 PM") else None,
        "resolved_at": "4/17/2026" if has_text(text, "4/17/2026") else None,
        "site": "UPS Fort Worth, TX (Haslet)" if has_text(text, "UPS Fort Worth", "Haslet") else None,
        "customer": "UPS" if has_text(text, "UPS") else None,
        "contact_name": "Antonio Rodrigo" if has_text(text, "Antonio Rodrigo") else None,
        "installation_group": "IG0011744 / UPS TXRTH - HASLET TX" if has_text(text, "IG0011744", "UPS TXRTH") else None,
        "affected_asset": "Z - UPS Fort Worth, TX (Haslet)" if has_text(text, "AffectedAsset", "Affected Asset") else None,
        "priority": "Medium: Minor impact to production" if has_text(text, "Medium: Minor impact") else None,
        "case_status": "Closed" if has_text(text, "Resolved to Closed", "has been Closed") else None,
        "status_transitions": status_transitions,
        "subject_variants": subject_variants,
        "symptom_summary": "Problems with the ACD/AVG system; everything was waiting, no path was showing, and nothing was coming up to the tippers." if observed else None,
        "failure_signature": [
            item for item in [
                "ACD/AVG system not starting normally" if subject_variants else None,
                "No path showing" if has_text(text, "path") else None,
                "Nothing coming to tippers" if has_text(text, "tippers") else None,
                "Heartbeat timeout on tippers" if has_text(text, "heartbeat timeout") else None,
                "Hospital tote removal issue" if has_text(text, "remove the tote", "remove totes") else None,
            ] if item
        ],
        "observed_signals": observed,
        "resolution_summary": "Per Mitchel Flynn, the system was E-stopped and the Optisweep service was restarted. Antonio confirmed proper AVG operation and hospital function." if resolution_steps else None,
        "resolution_steps": resolution_steps,
        "roles_involved": roles,
        "escalated": bool(status_transitions) or has_text(text, "L2", "engaged", "Escalated"),
        "logs_collected": ["Ignition logs", "Windows event logs"] if has_text(text, "Ignition and Windows event logs") else [],
        "inferred_causes": ["Possible Optisweep service state issue inferred from service restart and recovery confirmation."] if has_text(text, "Restarted Optisweep service") else [],
    }


def evidence_chunks(pages):
    records = []
    for page in pages:
        content = page_text(page)
        source_ref = page.get("source_ref", f"{ACTIVE_SOURCE_REF_PREFIX}#page={page['page']}")
        notes = []
        if not content:
            notes.append("No native text or OCR text was extracted from this page.")
        elif len(content) < 80:
            notes.append("Only limited OCR/native text was extracted from this page.")
        records.append(
            {
                **record_base(
                    "raw_evidence_chunk",
                    page["source_section"],
                    page["page"],
                    source_ref,
                    average_confidence(page["ocr_lines"]),
                    ["substantive_case_details"] if len(content) < 80 else [],
                    notes,
                ),
                "chunk_id": f"case_229716_{ACTIVE_SOURCE_KIND}_{page['page']:02d}",
                "content": content,
                "native_text": page["native_text"],
                "ocr_text_lines": page["ocr_lines"],
            }
        )
    return records


def artifact_records(pages, reference_media):
    records = []
    for page in pages:
        source_ref = page.get("source_ref", f"{ACTIVE_SOURCE_REF_PREFIX}#page={page['page']}")
        records.append(
            {
                **record_base(
                    "source_artifact_reference",
                    page["source_section"],
                    page["page"],
                    source_ref,
                    1.0,
                    [],
                    ["Source artifact image retained for traceability and review."],
                ),
                "artifact_id": f"case_229716_{ACTIVE_SOURCE_KIND}_artifact_{page['page']:02d}",
                "artifact_type": page.get("artifact_type", "source_image"),
                "artifact_path": page["artifact_path"],
                "dimensions": {"width": page["width"], "height": page["height"]},
            }
        )
    for index, item in enumerate(reference_media, start=1):
        records.append(
            {
                **record_base(
                    "source_artifact_reference",
                    "Reference Format",
                    None,
                    item["artifact_path"],
                    average_confidence(item["ocr_lines"]),
                    [],
                    item["extraction_notes"] or ["Reference DOCX embedded media retained for format traceability."],
                ),
                "artifact_id": f"reference_docx_media_{index:02d}",
                "artifact_type": "docx_embedded_media",
                "artifact_path": item["artifact_path"],
            }
        )
    return records


def canonical_record(pages):
    all_text = all_page_text(pages)
    fields = case_fields(pages)
    observed = []
    if "Salesforce Case Data" in all_text:
        observed.append("The source package includes a Salesforce Case Data section.")
    if "Teams Chat Data" in all_text or "Haslet Support Chat" in all_text:
        observed.append("The source package includes Teams Chat Data / Haslet Support Chat content.")
    if ACTIVE_SOURCE_KIND == "docx":
        observed.append(f"The source DOCX contains {len(pages)} embedded image artifacts.")
    else:
        observed.append("The source PDF contains 13 pages.")
    observed.extend(fields["observed_signals"])
    missing_fields = []
    for field_name in [
        "customer",
        "site",
        "opened_at",
        "resolved_at",
        "affected_asset",
        "resolution_summary",
    ]:
        if not fields.get(field_name):
            missing_fields.append(field_name)
    if not fields["observed_signals"]:
        missing_fields.append("observed_signals")
    return {
        **record_base(
            "canonical_incident",
            "All Source Sections",
            None,
            ACTIVE_SOURCE_RANGE_REF,
            0.72 if fields["observed_signals"] and fields["resolution_summary"] else 0.55,
            missing_fields + ["validated_root_cause"],
            ["Canonical fields are OCR-derived candidates and require manual review against rendered source pages."],
        ),
        "case_id": "229716",
        "source_case_id": fields["source_case_id"],
        "category": "CAT-1: WCS / Service Failure",
        "title": "Case 229716 - Problems with the ACD/AVG system at UPS Fort Worth Haslet",
        "incident_date": "4/15/2026" if fields["opened_at"] else None,
        "opened_at": fields["opened_at"],
        "resolved_at": fields["resolved_at"],
        "priority": fields["priority"],
        "case_status": fields["case_status"],
        "status_transitions": fields["status_transitions"],
        "site": fields["site"],
        "customer": fields["customer"],
        "contact_name": fields["contact_name"],
        "installation_group": fields["installation_group"],
        "affected_asset": fields["affected_asset"],
        "subject_variants": fields["subject_variants"],
        "symptom_summary": fields["symptom_summary"],
        "failure_signature": fields["failure_signature"],
        "observed_signals": observed,
        "inferred_causes": fields["inferred_causes"],
        "validated_root_cause": False,
        "root_cause_summary": None,
        "resolution_summary": fields["resolution_summary"],
        "resolution_steps": fields["resolution_steps"],
        "escalated": fields["escalated"],
        "logs_collected": fields["logs_collected"],
        "roles_involved": fields["roles_involved"],
        "support_safe": False,
        "engineer_required": True,
        "workflow_candidate": True,
    }


def timeline_records(pages):
    records = []
    pattern = re.compile(r"(\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?(?:\s+\d{1,2}:\d{2}\s?(?:AM|PM|am|pm))?\b|\b(?:1[0-2]|0?[1-9]):[0-5]\d\s?(?:AM|PM|am|pm)\b)")
    for page in pages:
        for index, line in enumerate(page["ocr_lines"], start=1):
            text = line["text"]
            match = pattern.search(text)
            if not match:
                continue
            source_ref = page.get("source_ref", f"{ACTIVE_SOURCE_REF_PREFIX}#page={page['page']}")
            records.append(
                {
                    **record_base(
                        "timeline_event",
                        page["source_section"],
                        page["page"],
                        f"{source_ref}:ocr_line={index}",
                        line.get("confidence") or 0.0,
                        ["normalized_timestamp", "actor", "event_type"],
                        ["Timeline event is sourced from OCR text and needs manual timestamp/actor validation."],
                    ),
                    "event_id": f"case_229716_timeline_{len(records) + 1:03d}",
                    "timestamp_raw": match.group(0),
                    "event_text": text,
                    "actor": None,
                    "event_type": "unknown",
                }
            )
    return records


def procedure_records(pages):
    verbs = re.compile(r"\b(check|verify|restart|reset|clear|review|collect|confirm|open|close|enable|disable|escalate|monitor|validate)\b", re.I)
    engineering = re.compile(r"\b(restart|server|service|database|db|log|logs|remote|vpn|plc|hmi|ignition|rms|network|control|controls)\b", re.I)
    records = []
    seen = set()
    for page in pages:
        for index, line in enumerate(page["ocr_lines"], start=1):
            text = line["text"]
            key = text.lower()
            if key in seen or not verbs.search(text) or len(text) < 12:
                continue
            seen.add(key)
            source_ref = page.get("source_ref", f"{ACTIVE_SOURCE_REF_PREFIX}#page={page['page']}")
            records.append(
                {
                    **record_base(
                        "procedure_candidate",
                        page["source_section"],
                        page["page"],
                        f"{source_ref}:ocr_line={index}",
                        line.get("confidence") or 0.0,
                        ["approval_status", "preconditions", "expected_result"],
                        ["Candidate action is OCR-derived and not SME-approved."],
                    ),
                    "procedure_id": f"case_229716_procedure_{len(records) + 1:03d}",
                    "candidate_action": text,
                    "support_safe": "unknown",
                    "engineer_required": bool(engineering.search(text)),
                }
            )
    return records


def workflow_records(pages):
    pattern = re.compile(r"\b(if|when|after|before|once|then|otherwise)\b", re.I)
    records = []
    seen = set()
    for page in pages:
        for index, line in enumerate(page["ocr_lines"], start=1):
            text = line["text"]
            key = text.lower()
            if key in seen or not pattern.search(text) or len(text) < 16:
                continue
            seen.add(key)
            source_ref = page.get("source_ref", f"{ACTIVE_SOURCE_REF_PREFIX}#page={page['page']}")
            records.append(
                {
                    **record_base(
                        "workflow_candidate_step",
                        page["source_section"],
                        page["page"],
                        f"{source_ref}:ocr_line={index}",
                        line.get("confidence") or 0.0,
                        ["decision_condition", "approved_owner", "next_step"],
                        ["Workflow candidate is source-backed but not approved workflow."],
                    ),
                    "workflow_step_id": f"case_229716_workflow_{len(records) + 1:03d}",
                    "candidate_step": text,
                    "workflow_candidate": True,
                    "support_safe": "unknown",
                    "engineer_required": True,
                }
            )
    return records


def escalation_summary_record(pages):
    all_text = all_page_text(pages)
    fields = case_fields(pages)
    missing = []
    if not fields["resolution_steps"]:
        missing.append("actions_taken")
    if not fields["logs_collected"]:
        missing.append("logs_collected")
    missing.extend(["open_questions"])
    return {
        **record_base(
            "escalation_summary_template",
            "All Source Sections",
            None,
            ACTIVE_SOURCE_RANGE_REF,
            0.68 if fields["resolution_steps"] else 0.45,
            missing,
            ["Escalation summary is OCR-derived and should be checked against the rendered Salesforce and Teams pages."],
        ),
        "case_id": "229716",
        "available_source_sections": sorted({page["source_section"] for page in pages}),
        "escalation_trigger": fields["symptom_summary"],
        "current_state": "System operational was reported after recovery." if has_text(all_text, "System operational") else None,
        "actions_taken": fields["resolution_steps"],
        "logs_collected": fields["logs_collected"],
        "recommended_owner": "L2/L3 Software Support or engineer with service/server access" if fields["resolution_steps"] else None,
        "open_questions": [],
        "handoff_notes": [
            "Service restart and log collection require engineer review before becoming a support-safe workflow.",
            "Validated root cause was not explicitly confirmed in the source evidence.",
        ],
    }


def validate_record(record):
    required = [
        "record_type",
        "incident_id",
        "source_file",
        "source_section",
        "source_page",
        "source_ref",
        "confidence",
        "validation_status",
        "requires_manual_review",
        "missing_fields",
        "extraction_notes",
    ]
    errors = []
    for field in required:
        if field not in record:
            errors.append(f"missing {field}")
    if record.get("validation_status") != "candidate_extracted":
        errors.append("validation_status must be candidate_extracted")
    if record.get("requires_manual_review") is not True:
        errors.append("requires_manual_review must be true")
    return errors


def validation_report(bundle):
    flat_records = []
    flat_records.append(bundle["records"]["canonical_incident"])
    flat_records.extend(bundle["records"]["timeline_events"])
    flat_records.extend(bundle["records"]["raw_evidence_chunks"])
    flat_records.extend(bundle["records"]["source_artifact_references"])
    flat_records.extend(bundle["records"]["procedure_candidates"])
    flat_records.extend(bundle["records"]["workflow_candidate_steps"])
    flat_records.append(bundle["records"]["escalation_summary_template"])
    issues = []
    for index, record in enumerate(flat_records, start=1):
        for error in validate_record(record):
            issues.append({"record_index": index, "record_type": record.get("record_type"), "issue": error})
    return {
        "validation_status": "passed" if not issues else "failed",
        "record_count": len(flat_records),
        "issues": issues,
        "empty_candidate_sets": {
            "timeline_events": len(bundle["records"]["timeline_events"]) == 0,
            "procedure_candidates": len(bundle["records"]["procedure_candidates"]) == 0,
            "workflow_candidate_steps": len(bundle["records"]["workflow_candidate_steps"]) == 0,
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["pdf", "docx"], default="pdf")
    args = parser.parse_args()
    configure_paths(args.source)
    ensure_dirs()
    if REFERENCE_EXTRACTION_PATH.exists():
        reference = json.loads(REFERENCE_EXTRACTION_PATH.read_text(encoding="utf-8"))
        reference_paragraphs = reference["paragraphs"]
        reference_media = reference["embedded_media"]
        media_paths = [item["artifact_path"] for item in reference_media]
        print(f"Loaded cached reference extraction from {REFERENCE_EXTRACTION_PATH}", flush=True)
    else:
        reference_paragraphs, media_paths = extract_docx_text(REFERENCE_DOCX_PATH)
        ocr = make_ocr() if media_paths else None
        reference_media = ocr_reference_media(ocr, media_paths) if ocr else []
        if ocr:
            ocr.close()
        reference = {
            "source_file": "docs/Phase0 Cat1 Dataset Seed Records V1.docx",
            "paragraph_count": len(reference_paragraphs),
            "paragraphs": reference_paragraphs,
            "embedded_media_count": len(media_paths),
            "embedded_media": reference_media,
        }
    if SOURCE_OCR_PATH.exists():
        raw_source = json.loads(SOURCE_OCR_PATH.read_text(encoding="utf-8"))
        pages = raw_source["pages"]
        print(f"Loaded cached source OCR from {SOURCE_OCR_PATH}", flush=True)
    else:
        ocr = make_ocr()
        if args.source == "docx":
            pages = extract_and_ocr_docx_media(ocr, SOURCE_DOCX_PATH)
        else:
            pages = render_and_ocr_pdf(ocr, SOURCE_PDF_PATH)
        ocr.close()
        raw_source = {
            "source_file": ACTIVE_SOURCE_FILE,
            "source_kind": ACTIVE_SOURCE_KIND,
            "artifact_count": len(pages),
            "pages": pages,
        }
    records = {
        "canonical_incident": canonical_record(pages),
        "timeline_events": timeline_records(pages),
        "raw_evidence_chunks": evidence_chunks(pages),
        "source_artifact_references": artifact_records(pages, reference_media),
        "procedure_candidates": procedure_records(pages),
        "workflow_candidate_steps": workflow_records(pages),
        "escalation_summary_template": escalation_summary_record(pages),
    }
    bundle = {
        "bundle_metadata": {
            "incident_id": "229716",
            "phase": "0",
            "category": "CAT-1: WCS / Service Failure",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_files": [
                "prompts/phase0_system_prompt.txt",
                "docs/Phase0 Cat1 Dataset Seed Records V1.docx",
                ACTIVE_SOURCE_FILE,
            ],
            "ocr_engine": "PaddleOCR 3.5.0 / PaddlePaddle 3.2.2 / PP-OCRv5 server det+rec",
            "validation_status": "candidate_extracted",
            "requires_manual_review": True,
        },
        "reference_format": {
            "paragraph_count": len(reference_paragraphs),
            "embedded_media_count": len(media_paths),
            "notes": "Reference DOCX text and embedded media OCR were extracted to support seed-record shape review.",
        },
        "records": records,
    }
    report = validation_report(bundle)
    write_json(EXTRACTED_DIR / "reference_docx_extraction.json", reference)
    write_json(SOURCE_OCR_PATH, raw_source)
    write_json(OUTPUT_DIR / "seed_records.json", bundle)
    write_json(OUTPUT_DIR / "validation_report.json", report)
    shutil.copyfile(PROMPT_PATH, OUTPUT_DIR / "phase0_system_prompt_used.txt")
    print(json.dumps({"output_dir": str(OUTPUT_DIR), **report}, indent=2))


if __name__ == "__main__":
    main()
