"""Symptom extraction node.

Two extractors compose here, gated by the ``ENABLE_LLM_SYMPTOM_EXTRACTION``
flag and Azure credential availability:

1. ``KeywordSignalExtractor`` (always runs) — deterministic, negation-aware
   substring matcher with a YAML phrase table. Produces the legacy 13-key
   ``INITIAL_CAT1_SIGNALS`` dict plus a ``components`` set the dynamic
   procedure selector consumes.
2. ``LLMSignalExtractor`` (optional) — JSON-mode Azure OpenAI call that maps
   free-text operator messages to the canonical signal vocabulary AND
   reports ``fresh_issue``. When enabled and credentials resolve, its
   output is MERGED on top of the keyword extractor's so we keep
   deterministic baseline behaviour even when the LLM is silent or fails.

Outputs written to state:

* ``extracted_signals`` — the legacy bool dict, still the contract every
  downstream node consumes today.
* ``extracted_observed_signals`` — legacy-keyed signal observations from this
  turn only, excluding default False values.
* ``extracted_canonical_signals`` — the canonical-vocabulary signals the
  LLM extractor emits directly (not derived through the legacy alias map).
  Empty when the LLM extractor is disabled or returns no canonical
  signals. The canonical_routing_node merges this with the legacy
  alias-translated signals so the LLM extractor's main value (direct
  canonical vocabulary, including signals with no legacy alias) reaches
  the router instead of dying in metadata.
* ``extracted_components`` — sorted list of canonical components detected
  in the user's message (consumed by the dynamic procedure selector via
  ``component_overlap``).
* ``extracted_signal_metadata`` — diagnostic dict with negated signals,
  matched phrases, LLM rationale, and ``fresh_issue`` so downstream nodes
  and operators can see how the extractor decided. Never required for
  routing; purely observability.
* ``issue_category`` — ``"CAT-1"`` when at least one CAT-1-defining signal
  is True. Unchanged contract.
"""
from __future__ import annotations

from backend.app.config import get_app_settings
from backend.app.graph.state import AssistantState
from backend.app.services.keyword_signal_extractor import (
    ExtractionResult,
    KeywordSignalExtractor,
    get_default_extractor,
)


_CAT1_DEFINING_SIGNALS = frozenset(
    {
        "agvs_stopped",
        "tipper_heartbeat_timeout",
        "hospital_tote_removal_hangs",
        "system_active_but_frozen",
        "ignition_or_wcs_down",
    }
)


def symptom_extraction_node(
    state: AssistantState,
    *,
    keyword_extractor: KeywordSignalExtractor | None = None,
    llm_extractor=None,
) -> AssistantState:
    cfg = get_app_settings()
    extractor = keyword_extractor or get_default_extractor()
    user_message = state.get("user_message") or ""
    keyword_result = extractor.extract(user_message)

    signals: dict[str, bool] = dict(keyword_result.signals)
    observed_signals: dict[str, bool] = dict(
        getattr(keyword_result, "observed_signals", {}) or {}
    )
    canonical_signals: dict[str, bool] = dict(
        getattr(keyword_result, "canonical_signals", {}) or {}
    )
    components: set[str] = set(keyword_result.components)
    metadata: dict[str, object] = {
        "extractor": "keyword",
        "negated_signals": sorted(keyword_result.negated_signals),
        "matched_phrases": dict(keyword_result.matched_phrases),
        "components": sorted(components),
    }

    followup_signal = _resolve_followup_signal(state, user_message)
    if followup_signal is not None:
        signal, value = followup_signal
        signals[str(signal)] = bool(value)
        observed_signals[str(signal)] = bool(value)
        canonical_signals.setdefault(str(signal), bool(value))

    llm_payload = _maybe_run_llm_extractor(
        state=state,
        cfg=cfg,
        injected_extractor=llm_extractor,
        keyword_result=keyword_result,
    )
    _ABSENCE_AFFIRMATIVE_KEYS = frozenset({"no_rms_alarm"})
    if llm_payload is not None:
        for key, value in (llm_payload.get("signals") or {}).items():
            key_s = str(key)
            if key_s in _ABSENCE_AFFIRMATIVE_KEYS:
                if value:
                    signals[key_s] = True
                    observed_signals[key_s] = True
                continue
            signals[key_s] = bool(value)
            if value:
                observed_signals[key_s] = True
            elif key_s in observed_signals and value is False:
                observed_signals.pop(key_s, None)
                signals[key_s] = False
        for key, value in (llm_payload.get("canonical_signals") or {}).items():
            canonical_signals[key] = bool(value)
        for key in _ABSENCE_AFFIRMATIVE_KEYS:
            if dict(getattr(keyword_result, "observed_signals", {}) or {}).get(key):
                signals[key] = True
                observed_signals[key] = True
                canonical_signals.setdefault("rms_screen_no_faults_visible", True)
        for component in llm_payload.get("components") or ():
            components.add(component)
        metadata["extractor"] = "keyword+llm"
        metadata["llm"] = {
            "rationale": llm_payload.get("rationale"),
            "confidences": llm_payload.get("confidences", {}),
            "fresh_issue": llm_payload.get("fresh_issue", False),
            "extracted_canonical_signals": llm_payload.get(
                "canonical_signals", {}
            ),
            "model": llm_payload.get("model"),
        }
        if llm_payload.get("fresh_issue"):
            metadata["fresh_issue"] = True

    state["extracted_signals"] = signals
    state["extracted_observed_signals"] = observed_signals
    state["extracted_canonical_signals"] = canonical_signals
    state["extracted_components"] = sorted(components)
    state["extracted_signal_metadata"] = metadata
    state["issue_category"] = (
        "CAT-1"
        if any(signals.get(name) for name in _CAT1_DEFINING_SIGNALS)
        else None
    )
    return state


def _maybe_run_llm_extractor(
    *,
    state: AssistantState,
    cfg,
    injected_extractor,
    keyword_result: ExtractionResult,
) -> dict | None:
    """Run the LLM extractor when the flag is on and credentials resolve.

    Returns ``None`` when the flag is off, the extractor fails to load
    config, or the call raises. Failures are intentionally swallowed: the
    keyword extractor's output is always written to state, so a degraded
    LLM never blocks the runtime.
    """
    if not getattr(cfg, "enable_llm_symptom_extraction", False):
        return None
    extractor = injected_extractor
    if extractor is None:
        try:
            from backend.app.tools.llm_signal_extractor import (
                LLMSignalExtractor,
            )

            extractor = LLMSignalExtractor()
        except Exception:
            return None
    try:
        return extractor.extract(
            user_message=state.get("user_message") or "",
            keyword_result=keyword_result,
        )
    except Exception:
        return None


def _resolve_followup_signal(
    state: AssistantState, user_message: str
) -> tuple[str, bool] | None:
    return None
