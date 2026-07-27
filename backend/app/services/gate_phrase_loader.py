"""Load first-turn gate phrase tables from Cosmos publish docs.

Symptom keys are whatever ingestion published — not a CAT taxonomy.
Root-cause labeling is out of scope for the first-turn gate.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Mapping

from backend.app.services.keyword_signal_extractor import (
    KeywordSignalExtractor,
    _normalize_operator_text,
    set_default_extractor,
)

logger = logging.getLogger(__name__)

GATE_PHRASE_DOC_ID = "gate_phrases"
GATE_PHRASE_DOC_TYPE = "gate_phrase_table"
_WS_RE = re.compile(r"\s+")


def _normalize_phrase(text: str) -> str:
    return _WS_RE.sub(" ", _normalize_operator_text(str(text or "")).strip())


def _as_phrase_map(raw: Any) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, list[str]] = {}
    for key, phrases in raw.items():
        key_s = str(key or "").strip()
        if not key_s:
            continue
        if phrases is None:
            cleaned[key_s] = []
            continue
        if not isinstance(phrases, list):
            continue
        out: list[str] = []
        seen: set[str] = set()
        for item in phrases:
            phrase = _normalize_phrase(str(item or ""))
            if not phrase or phrase in seen:
                continue
            seen.add(phrase)
            out.append(phrase)
        cleaned[key_s] = out
    return cleaned


def normalize_gate_phrase_doc(doc: Mapping[str, Any] | None) -> dict[str, dict[str, list[str]]]:
    """Accept top-level or payload-nested phrase maps from the published doc.

    Ingest currently emits ``legacy_signal_phrases``; ``symptom_phrases`` is
    accepted as an alias for the same first-turn symptom vocabulary.
    """
    empty = {
        "symptom_phrases": {},
        "canonical_signal_phrases": {},
        "component_phrases": {},
    }
    if not isinstance(doc, dict):
        return empty
    payload = doc.get("payload") if isinstance(doc.get("payload"), dict) else {}
    merged = {**payload, **doc}
    symptom_raw = merged.get("symptom_phrases")
    if not isinstance(symptom_raw, dict) or not symptom_raw:
        symptom_raw = merged.get("legacy_signal_phrases")
    return {
        "symptom_phrases": _as_phrase_map(symptom_raw),
        "canonical_signal_phrases": _as_phrase_map(merged.get("canonical_signal_phrases")),
        "component_phrases": _as_phrase_map(merged.get("component_phrases")),
    }


def gate_phrase_table_usable(table: Mapping[str, Any] | None) -> bool:
    maps = normalize_gate_phrase_doc(table if isinstance(table, dict) else None)
    return bool(maps["symptom_phrases"] or maps["canonical_signal_phrases"])


def install_extractor_from_gate_phrase_table(
    table: Mapping[str, Any] | None,
) -> str:
    """Install process extractor from Cosmos table, else local YAML fallback.

    Returns ``\"cosmos\"`` or ``\"yaml_fallback\"``.
    """
    if gate_phrase_table_usable(table):
        maps = normalize_gate_phrase_doc(table)
        set_default_extractor(
            KeywordSignalExtractor.from_phrases(
                signal_phrases=maps["symptom_phrases"],
                component_phrases=maps["component_phrases"],
                canonical_signal_phrases=maps["canonical_signal_phrases"],
            )
        )
        logger.info(
            "Gate phrases installed from Cosmos table "
            "(symptom_keys=%s canonical_keys=%s component_keys=%s)",
            len(maps["symptom_phrases"]),
            len(maps["canonical_signal_phrases"]),
            len(maps["component_phrases"]),
        )
        return "cosmos"
    set_default_extractor(KeywordSignalExtractor.from_files())
    logger.info("Gate phrases installed from local YAML fallback")
    return "yaml_fallback"


__all__ = [
    "GATE_PHRASE_DOC_ID",
    "GATE_PHRASE_DOC_TYPE",
    "gate_phrase_table_usable",
    "install_extractor_from_gate_phrase_table",
    "normalize_gate_phrase_doc",
]
