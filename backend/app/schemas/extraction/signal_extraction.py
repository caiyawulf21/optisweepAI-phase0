"""Pydantic schemas for the LLM signal extractor.

The LLM returns JSON shaped as :class:`LLMSignalExtractionResult`. The
extractor module then validates the response against the supplied
canonical signal vocabulary AND the legacy CAT-1 vocabulary; signals not
in either list are dropped (with a warning) so the LLM can never inject
a hallucinated key into the runtime.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LLMSignalExtractionResultPayload(BaseModel):
    """The raw shape we expect Azure OpenAI to return (JSON mode).

    The two outer fields (``signals`` / ``confidences``) are keyed by
    LEGACY signal keys (members of
    :data:`backend.app.schemas.assistant.INITIAL_CAT1_SIGNALS`).
    ``canonical_signals`` is keyed by canonical signal vocabulary keys
    (members of the procedure dictionary's
    ``relationship_tracking.{requires,produces,confirms,rules_out}_signals``
    lists). The two layers exist because today's runtime contract is
    legacy keys; the canonical-signal layer lets us start moving over
    without breaking the existing graph.
    """

    signals: dict[str, bool] = Field(default_factory=dict)
    canonical_signals: dict[str, bool] = Field(default_factory=dict)
    confidences: dict[str, Any] = Field(default_factory=dict)
    components: list[str] = Field(default_factory=list)
    fresh_issue: bool = False
    rationale: str = ""


class LLMSignalExtractionResult(BaseModel):
    """The post-validated, runtime-safe extraction result.

    The :class:`backend.app.tools.llm_signal_extractor.LLMSignalExtractor`
    builds one of these after dropping unknown keys, clipping confidences
    into ``[0, 1]``, and stamping the model name. The symptom extraction
    node consumes this view (NOT the raw payload) so a malformed or
    over-eager LLM cannot corrupt downstream state.
    """

    signals: dict[str, bool] = Field(default_factory=dict)
    canonical_signals: dict[str, bool] = Field(default_factory=dict)
    confidences: dict[str, float] = Field(default_factory=dict)
    components: list[str] = Field(default_factory=list)
    fresh_issue: bool = False
    rationale: str = ""
    model: str | None = None
    dropped_unknown_keys: list[str] = Field(default_factory=list)

    def to_node_dict(self) -> dict[str, Any]:
        """Serialise into the dict shape the symptom extraction node merges."""
        return {
            "signals": dict(self.signals),
            "canonical_signals": dict(self.canonical_signals),
            "confidences": dict(self.confidences),
            "components": list(self.components),
            "fresh_issue": self.fresh_issue,
            "rationale": self.rationale,
            "model": self.model,
            "dropped_unknown_keys": list(self.dropped_unknown_keys),
        }


__all__ = [
    "LLMSignalExtractionResult",
    "LLMSignalExtractionResultPayload",
]
