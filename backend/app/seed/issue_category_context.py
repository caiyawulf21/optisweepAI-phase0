from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
DEFAULT_ISSUE_CATEGORY_DOC = Path("docs/Optisweep Issue Categories.docx")


def _text_from_cell(cell: ET.Element) -> str:
    parts = [node.text or "" for node in cell.iter(f"{WORD_NS}t")]
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _document_xml(docx_path: Path) -> ET.Element | None:
    if not docx_path.exists():
        return None
    with zipfile.ZipFile(docx_path) as archive:
        with archive.open("word/document.xml") as document:
            return ET.fromstring(document.read())


def docx_tables(docx_path: Path) -> list[list[list[str]]]:
    root = _document_xml(docx_path)
    if root is None:
        return []
    tables = []
    for table in root.iter(f"{WORD_NS}tbl"):
        rows = []
        for row in table.iter(f"{WORD_NS}tr"):
            cells = [_text_from_cell(cell) for cell in row.iter(f"{WORD_NS}tc")]
            if any(cells):
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables


def docx_paragraphs(docx_path: Path) -> list[str]:
    root = _document_xml(docx_path)
    if root is None:
        return []
    paragraphs = []
    for paragraph in root.iter(f"{WORD_NS}p"):
        text = re.sub(r"\s+", " ", "".join(node.text or "" for node in paragraph.iter(f"{WORD_NS}t"))).strip()
        if text:
            paragraphs.append(text)
    return paragraphs


def _row_record(headers: list[str], row: list[str]) -> dict[str, str]:
    record = {}
    for index, value in enumerate(row):
        key = headers[index] if index < len(headers) else f"column_{index + 1}"
        normalized_key = re.sub(r"[^a-zA-Z0-9]+", "_", key).strip("_").lower()
        if normalized_key and value:
            record[normalized_key] = value
    return record


def issue_category_context(docx_path: Path = DEFAULT_ISSUE_CATEGORY_DOC) -> dict[str, Any]:
    tables = docx_tables(docx_path)
    records = []
    for table in tables:
        if not table:
            continue
        headers = table[0]
        records.extend(_row_record(headers, row) for row in table[1:] if any(row))
    paragraphs = docx_paragraphs(docx_path)
    return {
        "source": str(docx_path).replace("\\", "/"),
        "usage": [
            "deterministic_case_category_lookup_when_case_id_is_explicitly_listed",
            "llm_enrichment_context",
            "category_reference_display",
        ],
        "non_usage": [
            "keyword_or_symptom_based_category_inference",
            "source_language_normalization",
        ],
        "records": records,
        "paragraphs": paragraphs,
    }


def category_for_case(case_id: str, context: dict[str, Any]) -> str | None:
    case_text = str(case_id).strip()
    if not case_text:
        return None
    for record in context.get("records", []):
        values = {str(value) for value in record.values()}
        if not any(case_text in value for value in values):
            continue
        for key in ("category", "issue_category", "cat", "issue_type"):
            value = record.get(key)
            if value:
                return str(value)
    return None
