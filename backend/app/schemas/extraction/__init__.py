"""Pydantic models for the optional LLM signal extractor.

The shapes here are internal to :mod:`backend.app.tools.llm_signal_extractor`
and to :mod:`backend.app.graph.nodes.symptom_extraction`. They never appear
on the wire — the symptom extraction node merges their output into the
existing ``state["extracted_signals"]`` legacy bool dict.
"""
from __future__ import annotations

from backend.app.schemas.extraction.signal_extraction import (
    LLMSignalExtractionResult,
    LLMSignalExtractionResultPayload,
)


__all__ = [
    "LLMSignalExtractionResult",
    "LLMSignalExtractionResultPayload",
]
