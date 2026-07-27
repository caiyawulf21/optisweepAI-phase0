"""Optional Azure OpenAI symptom extractor overlay.

Keyword extraction remains the deterministic baseline. When
``ENABLE_LLM_SYMPTOM_EXTRACTION`` is on and Azure credentials resolve, this
module maps free-text paraphrases onto the legacy + canonical signal
vocabularies and merges on top of keyword results.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

from backend.app.schemas.extraction.signal_extraction import (
    LLMSignalExtractionResult,
    LLMSignalExtractionResultPayload,
)
from backend.app.services.keyword_signal_extractor import (
    DEFAULT_CANONICAL_SIGNAL_PHRASES_PATH,
    DEFAULT_COMPONENT_PHRASES_PATH,
    DEFAULT_SIGNAL_PHRASES_PATH,
    ExtractionResult,
    get_default_extractor,
)


_PROMPTS_ROOT = Path(__file__).resolve().parents[1] / "prompts"
_CAT_CODE_RE = re.compile(r"\bCAT[-\s]?\d+\b", re.IGNORECASE)
_MIN_CONFIDENCE = 0.3


def _humanize(key: str) -> str:
    return str(key or "").replace("_", " ").strip()


def _default_symptom_vocabulary() -> dict[str, str]:
    try:
        keys = get_default_extractor().symptom_keys
        if keys:
            return {key: _humanize(key) for key in keys}
    except Exception:
        pass
    return _load_yaml_keys(DEFAULT_SIGNAL_PHRASES_PATH)


def _load_yaml_keys(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): _humanize(str(key))
        for key in raw.keys()
        if isinstance(key, str) and key.strip()
    }


def _strip_prompt_frontmatter(text: str) -> str:
    body = text.strip()
    if not body.startswith("---"):
        return body
    parts = body.split("---", 2)
    if len(parts) < 3:
        return body
    return parts[2].strip()


class LLMSignalExtractor:
    """JSON-mode Azure OpenAI extractor with vocabulary post-validation."""

    def __init__(
        self,
        *,
        system_prompt: str | None = None,
        legacy_vocabulary: dict[str, str] | None = None,
        canonical_vocabulary: dict[str, str] | None = None,
        component_vocabulary: list[str] | None = None,
    ) -> None:
        prompt_path = _PROMPTS_ROOT / "symptom_extraction_prompt.md"
        loaded = ""
        if prompt_path.exists():
            loaded = _strip_prompt_frontmatter(prompt_path.read_text(encoding="utf-8"))
        self._system_prompt = system_prompt or loaded or (
            "Extract structured Optisweep support signals as JSON only."
        )
        self._legacy_vocabulary = legacy_vocabulary or _default_symptom_vocabulary()
        self._canonical_vocabulary = canonical_vocabulary or _load_yaml_keys(
            DEFAULT_CANONICAL_SIGNAL_PHRASES_PATH
        )
        components = component_vocabulary
        if components is None:
            components = sorted(_load_yaml_keys(DEFAULT_COMPONENT_PHRASES_PATH).keys())
        self._component_vocabulary = list(components)

    def extract(
        self,
        *,
        user_message: str,
        keyword_result: ExtractionResult | None = None,
        already_observed_signals: dict[str, bool] | None = None,
        prior_operator_turns: list[dict[str, Any]] | None = None,
        last_extraction_rationale: str | None = None,
    ) -> dict[str, Any]:
        keyword_result = keyword_result or ExtractionResult()
        packet = self._build_packet(
            user_message=user_message,
            keyword_result=keyword_result,
            already_observed_signals=already_observed_signals or {},
            prior_operator_turns=prior_operator_turns or [],
            last_extraction_rationale=last_extraction_rationale,
        )
        raw = self._complete_json(packet)
        if not raw:
            raise RuntimeError("LLM symptom extraction returned no content")
        self._last_model = os.getenv("AZURE_OPENAI_DEPLOYMENT") or os.getenv(
            "AZURE_EMBEDDINGS_DEPLOYMENT"
        )
        payload = LLMSignalExtractionResultPayload.model_validate(self._parse_json(raw))
        validated = self._validate(payload)
        return validated.to_node_dict()

    def _build_packet(
        self,
        *,
        user_message: str,
        keyword_result: ExtractionResult,
        already_observed_signals: dict[str, bool],
        prior_operator_turns: list[dict[str, Any]] | None = None,
        last_extraction_rationale: str | None = None,
    ) -> dict[str, Any]:
        packet: dict[str, Any] = {
            "operator_message": user_message,
            "legacy_vocabulary": [
                {"key": key, "description": desc}
                for key, desc in self._legacy_vocabulary.items()
            ],
            "canonical_vocabulary": [
                {"key": key, "description": desc}
                for key, desc in self._canonical_vocabulary.items()
            ],
            "component_vocabulary": list(self._component_vocabulary),
            "keyword_extractor_signals": {
                key: bool(value)
                for key, value in dict(keyword_result.signals or {}).items()
                if key in self._legacy_vocabulary
            },
            "already_observed_signals": {
                key: bool(value)
                for key, value in dict(already_observed_signals or {}).items()
                if value
            },
        }
        turns = [
            {
                "role": str(item.get("role") or "user"),
                "content": str(item.get("content") or "").strip(),
            }
            for item in list(prior_operator_turns or [])
            if isinstance(item, dict) and str(item.get("content") or "").strip()
        ]
        if turns:
            packet["prior_operator_turns"] = turns[-8:]
        rationale = str(last_extraction_rationale or "").strip()
        if rationale:
            packet["last_extraction_rationale"] = rationale[:400]
        prior = self._semantic_prior(user_message)
        if prior:
            packet["semantically_related_signals"] = prior
        return packet

    def _semantic_prior(self, user_message: str) -> list[dict[str, Any]]:
        from backend.app.config import get_app_settings

        cfg = get_app_settings()
        if not getattr(cfg, "enable_semantic_signal_prior", False):
            return []
        if not self._canonical_vocabulary:
            return []
        from backend.app.services.semantic_signal_scorer import SemanticSignalScorer

        scored = SemanticSignalScorer().score_signals(
            user_message,
            self._canonical_vocabulary,
            top_k=8,
        )
        return [
            {"key": item.key, "description": item.description, "score": round(item.score, 4)}
            for item in scored
        ]

    def _complete_json(self, packet: dict[str, Any]) -> str | None:
        from backend.app.services.llm_playbook_client import complete_json, llm_available

        if not llm_available():
            return None
        return complete_json(
            system_prompt=self._system_prompt,
            user_prompt=json.dumps(packet, indent=2, default=str),
            max_tokens=700,
        )

    def _parse_json(self, raw: str) -> dict[str, Any]:
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("LLM symptom extraction did not return a JSON object")
        return payload

    def _validate(self, payload: LLMSignalExtractionResultPayload) -> LLMSignalExtractionResult:
        dropped: list[str] = []
        confidences_raw = {
            str(key): value for key, value in dict(payload.confidences or {}).items()
        }

        def keep_signal(key: str, value: bool, *, allowed: set[str]) -> bool | None:
            if key not in allowed:
                dropped.append(key)
                return None
            conf = confidences_raw.get(key)
            try:
                score = float(conf) if conf is not None else 0.7
            except (TypeError, ValueError):
                score = 0.7
            if score < _MIN_CONFIDENCE:
                return None
            return bool(value)

        legacy_allowed = set(self._legacy_vocabulary)
        canonical_allowed = set(self._canonical_vocabulary)
        components_allowed = set(self._component_vocabulary)

        signals: dict[str, bool] = {}
        for key, value in dict(payload.signals or {}).items():
            kept = keep_signal(str(key), bool(value), allowed=legacy_allowed)
            if kept is not None:
                signals[str(key)] = kept

        canonical_signals: dict[str, bool] = {}
        for key, value in dict(payload.canonical_signals or {}).items():
            kept = keep_signal(str(key), bool(value), allowed=canonical_allowed)
            if kept is not None:
                canonical_signals[str(key)] = kept

        confidences: dict[str, float] = {}
        for key, value in confidences_raw.items():
            if key not in signals and key not in canonical_signals:
                if key not in legacy_allowed and key not in canonical_allowed:
                    dropped.append(key)
                continue
            try:
                score = float(value)
            except (TypeError, ValueError):
                continue
            confidences[key] = max(0.0, min(1.0, score))

        components: list[str] = []
        for item in list(payload.components or []):
            text = str(item or "").strip()
            if not text:
                continue
            if text not in components_allowed:
                dropped.append(text)
                continue
            if text not in components:
                components.append(text)

        rationale = str(payload.rationale or "").strip()
        if _CAT_CODE_RE.search(rationale):
            rationale = _CAT_CODE_RE.sub("[signal group]", rationale)

        return LLMSignalExtractionResult(
            signals=signals,
            canonical_signals=canonical_signals,
            confidences=confidences,
            components=components,
            fresh_issue=bool(payload.fresh_issue),
            rationale=rationale,
            model=getattr(self, "_last_model", None)
            or os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            dropped_unknown_keys=sorted(set(dropped)),
        )


__all__ = ["LLMSignalExtractor"]
