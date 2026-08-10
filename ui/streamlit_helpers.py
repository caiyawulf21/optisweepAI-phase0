"""Phase 1 Step 12 — pure helpers for the Streamlit guided UI.

Extracted out of :mod:`ui.streamlit_app` so the rendering logic stays
unit-testable without Streamlit's runtime. None of the helpers import
Streamlit, return Streamlit widgets, or rely on session state. They only
transform JSON-shaped response payloads (the contract emitted by
:func:`backend.app.api.troubleshoot._build_troubleshoot_response` in Step
11) into small primitive structures the renderer functions consume.
"""
from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
from typing import Any, Callable, Mapping


SignalBadge = dict[str, Any]
"""Badge primitive: ``{"signal": str, "value": bool, "label": str}``."""


RendererName = str
"""Renderer identifier matching a ``response_type`` value."""

UNKNOWN_ANSWER = "unknown"
UNKNOWN_ANSWER_LABEL = "I don't know / not sure"
HOW_TO_CHECK_MESSAGE = "How do I check?"


def is_latest_assistant_turn(
    history: list[Mapping[str, Any]] | None,
    current_index: int,
) -> bool:
    if not history or current_index < 0 or current_index >= len(history):
        return False
    if history[current_index].get("role") != "assistant":
        return False
    for entry in history[current_index + 1 :]:
        if entry.get("role") == "assistant":
            return False
    return True


def answer_button_key(
    prefix: str,
    message_index: int,
    node_id: str | None,
    answer_index: int,
    answer: Any,
) -> str:
    node = str(node_id or "unknown")
    return f"{prefix}-{message_index}-{node}-{answer_index}-{answer}"


def widget_key(
    prefix: str,
    message_index: int,
    node_id: str | None,
    suffix: str,
) -> str:
    node = str(node_id or "unknown")
    return f"{prefix}-{message_index}-{node}-{suffix}"


def allowed_answers_with_unknown(allowed_answers: list[Any] | None) -> list[str]:
    answers: list[str] = []
    seen: set[str] = set()
    for answer in allowed_answers or []:
        label = str(answer).strip()
        if not label:
            continue
        normalized = label.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        answers.append(label)
    if UNKNOWN_ANSWER not in seen:
        answers.append(UNKNOWN_ANSWER)
    return answers


def display_answer_label(answer: Any, *, next_node_title: Any = None) -> str:
    if str(answer).strip().lower() == UNKNOWN_ANSWER:
        return UNKNOWN_ANSWER_LABEL
    label = str(answer)
    destination = str(next_node_title or "").strip()
    if destination:
        return f"{label} → {destination}"
    return label


def next_node_title_for_answer(
    answer: Any,
    branch_options: list[Any] | None = None,
    metrics: dict[str, Any] | None = None,
) -> str | None:
    key = str(answer or "").strip().lower()
    if not key or key == UNKNOWN_ANSWER:
        return None
    for item in branch_options or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("label") or "").strip().lower() != key:
            continue
        title = str(item.get("next_node_title") or item.get("next_node_id") or "").strip()
        return title or None
    if isinstance(metrics, dict):
        payload = metrics.get(key)
        if isinstance(payload, dict):
            title = str(
                payload.get("next_node_title") or payload.get("next_node_id") or ""
            ).strip()
            return title or None
    return None


def format_role_label(role: Any) -> str | None:
    if role is None:
        return None
    raw = str(role).strip()
    if not raw:
        return None
    normalized = raw.lower()
    mapping = {
        "support": "L1 Support",
        "l1_technical_support": "L1 Support",
        "l1_support": "L1 Support",
        "site_operations": "Site Operations",
        "engineer": "L2/L3 Engineer",
        "l2_l3_software_support": "L2/L3 Support",
        "l2_l3_software_support_with_site_operator": "L2/L3 Support + Site Ops",
        "l2_support": "L2 Support",
        "l3_support": "L3 Support",
    }
    if normalized in mapping:
        return mapping[normalized]
    if normalized.startswith("l1"):
        return "L1 Support"
    if normalized.startswith("l2"):
        return "L2 Support"
    if normalized.startswith("l3"):
        return "L3 Support"
    return raw


def build_guided_submission(
    answer: str | None = None,
    custom_text: str | None = None,
) -> str:
    custom = (custom_text or "").strip()
    if answer and custom:
        return f"Answer: {answer}. Additional context: {custom}"
    if answer:
        return str(answer)
    return custom


# ---------------------------------------------------------------------------
# Renderer dispatch
# ---------------------------------------------------------------------------


_RENDERER_NAMES: dict[str, RendererName] = {
    "answer": "answer",
    "case_match": "case_match",
    "guided_question": "guided_question",
    "workflow_step": "workflow_step",
    "playbook_candidates": "guided_question",
    "escalation": "escalation",
    "terminal": "terminal",
}

# Kept for import compatibility; playbook runtime never shows this banner.
PROCEDURE_GUIDANCE_BANNER = ""

SOURCE_ARTIFACTS_PATH = Path("data/evidence/source_artifacts.json")
CANONICAL_PROCEDURES_PATH = Path("data/normalized/canonical_procedure_dictionary.json")
DISCOVERED_PROCEDURES_PATH = Path("data/normalized/discovered_canonical_procedures.json")
COSMOS_PROCEDURES_PATH = Path("data/archives/20260610/cosmos/canonical_procedure_dictionary.json")
ACCEPT_RECOMMENDATION_CONFIDENCE_THRESHOLD = 0.75


def select_renderer(
    response_type: str | None,
    *,
    renderers: Mapping[str, Callable[..., Any]] | None = None,
    default: str = "answer",
) -> Callable[..., Any] | RendererName:
    """Pick the renderer to handle ``response_type``.

    When ``renderers`` is supplied (mapping renderer name -> callable) the
    callable is returned. Otherwise the renderer name itself is returned so
    callers (and the unit tests) can assert on the name without needing a
    real callable.

    Unknown / missing values fall back to ``default`` ("answer"), matching
    the legacy single-turn behavior — the operator still sees a free-text
    response even if the contract emits an unrecognised type in the
    future.
    """
    name = _RENDERER_NAMES.get(response_type or "", default)
    if renderers is None:
        return name
    chosen = renderers.get(name) or renderers.get(default)
    if chosen is None:
        raise KeyError(
            f"No renderer registered for response_type={response_type!r} "
            f"and no default {default!r} renderer either."
        )
    return chosen


# ---------------------------------------------------------------------------
# Signal badges
# ---------------------------------------------------------------------------


def format_signal_badges(
    signals: Mapping[str, Any] | None,
) -> list[SignalBadge]:
    """Render a signal dict as a sorted list of badge dicts.

    Output order is alphabetical by signal name so the sidebar stays
    stable across re-renders. Non-bool values are coerced to bool so the
    UI never has to reason about None / int values bleeding in from
    upstream payloads.
    """
    if not signals:
        return []
    badges: list[SignalBadge] = []
    for name in sorted(signals.keys()):
        raw = signals[name]
        value = bool(raw) if raw is not None else False
        badges.append(
            {
                "signal": name,
                "value": value,
                "label": "true" if value else "false",
            }
        )
    return badges


def merge_observed_signals(
    prior: Mapping[str, bool] | None,
    latest: Mapping[str, bool] | None,
) -> dict[str, bool]:
    """Accumulate observed signals across turns.

    ``latest`` overwrites ``prior`` on shared keys so the most recent
    turn always wins; entries unique to ``prior`` are preserved. This is
    the only correct behavior for the UI sidebar: once a signal has been
    asserted in a prior turn it should remain visible (and continue to
    drive workflow advancement) even if the latest turn's payload only
    reports the deltas. Non-bool values are coerced to bool — the
    canonical workflow runtime only ever emits bool signals, but defence
    in depth keeps the sidebar contract stable when an upstream change
    leaks a different primitive.
    """
    merged: dict[str, bool] = {}
    if prior:
        for key, value in prior.items():
            merged[str(key)] = bool(value)
    if latest:
        for key, value in latest.items():
            merged[str(key)] = bool(value)
    return merged


def latest_observed_signals_from_response(
    response: Mapping[str, Any] | None,
) -> dict[str, bool]:
    if not response:
        return {}
    latest: dict[str, bool] = {}
    workflow_state = response.get("workflow_state") or {}
    if isinstance(workflow_state, Mapping):
        runtime_step = workflow_state.get("workflow_step") or {}
        if isinstance(runtime_step, Mapping):
            latest.update(runtime_step.get("observed_signals") or {})
        observed_signals = workflow_state.get("observed_signals") or {}
        if isinstance(observed_signals, Mapping):
            latest.update(observed_signals)
    if latest:
        return {str(key): bool(value) for key, value in latest.items()}
    observed = response.get("extracted_observed_signals") or {}
    if isinstance(observed, Mapping):
        return {str(key): bool(value) for key, value in observed.items()}
    return {}


# ---------------------------------------------------------------------------
# Progress label
# ---------------------------------------------------------------------------


def derive_progress_label(
    workflow_summary: Mapping[str, Any] | None,
) -> str | None:
    """Return the workflow's ``progress_label`` field as-is.

    The Step 11 response contract is already responsible for picking
    between ``"Step N of M"`` and ``"Step N"`` based on whether the
    canonical loader can resolve a total node count. The UI should not
    second-guess that decision; this helper exists so the sidebar
    renderer can stay dumb and unit-tests can pin the pass-through
    behavior.
    """
    if not workflow_summary:
        return None
    label = workflow_summary.get("progress_label")
    if isinstance(label, str) and label.strip():
        return label.strip()
    return None


def should_show_procedure_guidance_banner(
    mode: str | None,
) -> bool:
    """Legacy DPG banner removed — always False for playbook runtime."""
    del mode
    return False


def derive_dynamic_path_progress(
    payload: Mapping[str, Any] | None,
) -> str | None:
    """Legacy DPG progress helper — unused by playbook runtime."""
    del payload
    return None


def derive_recommended_next_step(
    payload: Mapping[str, Any] | None,
) -> str | None:
    if not payload:
        return None
    step = _primary_step_payload(payload)
    if not step:
        return None
    guidance = step.get("procedure_guidance")
    if isinstance(guidance, Mapping):
        procedures = guidance.get("rendered_procedures") or guidance.get("procedures")
        if isinstance(procedures, list) and procedures:
            first = procedures[0]
            if isinstance(first, Mapping):
                title = first.get("title") or first.get("procedure_id")
                if isinstance(title, str) and title.strip():
                    return title.strip()
    for key in ("instruction", "question"):
        value = step.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    procedure_refs = step.get("procedure_refs")
    if isinstance(procedure_refs, list) and procedure_refs:
        first_ref = procedure_refs[0]
        if isinstance(first_ref, str) and first_ref.strip():
            return first_ref.replace("_", " ").strip().title()
    return None


def select_confidence_value(
    payload: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not payload:
        return None
    candidates: list[tuple[str, Any]] = []
    candidates.append(("retrieval confidence", payload.get("retrieval_confidence")))
    runtime_trace = payload.get("runtime_trace")
    if isinstance(runtime_trace, Mapping):
        retrieval = runtime_trace.get("retrieval")
        if isinstance(retrieval, Mapping):
            candidates.append(("retrieval confidence", retrieval.get("top_confidence")))
    for source, value in candidates:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            continue
        if 0.0 < confidence <= 1.0:
            return {"source": source, "confidence": confidence}
    return None


def accept_recommendation_value(
    payload: Mapping[str, Any] | None,
    *,
    threshold: float = ACCEPT_RECOMMENDATION_CONFIDENCE_THRESHOLD,
) -> str | None:
    confidence = select_confidence_value(payload)
    if not confidence or confidence["confidence"] < threshold:
        return None
    step = _primary_step_payload(payload)
    if not step or step.get("support_safe") is False:
        return None
    options = step.get("answer_options")
    if isinstance(options, list):
        for option in options:
            if not isinstance(option, Mapping):
                continue
            value = str(option.get("value") or "").strip()
            label = str(option.get("label") or "").strip().lower()
            if value and (value.lower() == "yes" or label in {"yes", "accept"}):
                return value
    allowed = step.get("allowed_answers")
    if isinstance(allowed, list):
        for answer in allowed:
            value = str(answer).strip()
            if value.lower() == "yes":
                return value
    return None


def _primary_step_payload(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for key in ("workflow_step", "guided_question"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            return value
    return None


def extract_visual_artifact_refs(
    visual_evidence: Mapping[str, Any] | None,
) -> list[str]:
    if not visual_evidence:
        return []
    refs: list[str] = []
    for key in ("primary_screenshot_refs", "supporting_screenshot_refs", "source_artifacts"):
        values = visual_evidence.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, str) or not value.strip():
                continue
            if value not in refs:
                refs.append(value)
    for ev in visual_evidence.get("evidence_refs") or []:
        if not isinstance(ev, Mapping):
            continue
        source_artifact_id = ev.get("source_artifact_id")
        if isinstance(source_artifact_id, str) and source_artifact_id and source_artifact_id not in refs:
            refs.append(source_artifact_id)
    return refs


def visual_evidence_from_refs(refs: list[str] | tuple[str, ...]) -> dict[str, Any]:
    return {
        "primary_screenshot_refs": [
            ref for ref in refs if isinstance(ref, str) and ref.strip()
        ]
    }


def resolve_visual_artifacts(
    visual_evidence: Mapping[str, Any] | None,
    *,
    artifact_records: list[Mapping[str, Any]] | None = None,
    artifact_root: Path | str = ".",
) -> list[dict[str, Any]]:
    refs = extract_visual_artifact_refs(visual_evidence)
    if not refs:
        return []
    records = artifact_records
    if records is None:
        records = _load_source_artifact_records()
    by_id = {
        str(record.get("artifact_id")): record
        for record in records
        if isinstance(record, Mapping) and record.get("artifact_id")
    }
    root = Path(artifact_root)
    out: list[dict[str, Any]] = []
    for ref in refs:
        record = by_id.get(ref)
        artifact_path = record.get("artifact_path") if record else None
        if _is_remote_uri(artifact_path):
            path = str(artifact_path)
            exists = True
        else:
            path = root / artifact_path if isinstance(artifact_path, str) else None
            exists = bool(path and path.exists())
        suppress_missing_warning = _is_runtime_ref(ref) and not exists
        out.append(
            {
                "artifact_id": ref,
                "artifact_path": str(path) if path is not None else None,
                "exists": exists,
                "source_ref": record.get("source_ref") if record else None,
                "artifact_type": record.get("artifact_type") if record else None,
                "incident_id": record.get("incident_id") if record else None,
                "visible_text": record.get("visible_text") if record else None,
                "visual_summary": record.get("visual_summary") if record else None,
                "server_or_ip": record.get("server_or_ip") if record else None,
                "required": ref in (visual_evidence.get("primary_screenshot_refs") or []),
                "suppress_missing_warning": suppress_missing_warning,
            }
        )
    return out


def resolve_canonical_image_records(
    images: list[Mapping[str, Any]] | None,
    *,
    artifact_records: list[Mapping[str, Any]] | None = None,
    artifact_root: Path | str = ".",
) -> list[dict[str, Any]]:
    if not images:
        return []
    records = artifact_records if artifact_records is not None else _load_source_artifact_records()
    by_artifact_id = {
        str(record.get("artifact_id")): record
        for record in records
        if isinstance(record, Mapping) and record.get("artifact_id")
    }
    root = Path(artifact_root)
    resolved: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for image in images:
        if not isinstance(image, Mapping):
            continue
        source_ids = _string_list(image.get("source_artifact_ids"))
        image_id = str(image.get("image_id") or image.get("id") or "").strip()
        key = image_id or (source_ids[0] if source_ids else "")
        if not key:
            continue
        candidates: list[tuple[str, Path | str | None]] = []
        storage_uri = image.get("storage_uri")
        if _is_remote_uri(storage_uri):
            candidates.append(("storage_uri", str(storage_uri)))
        else:
            storage_path = _resolve_path_candidate(storage_uri, root)
            candidates.append(("storage_uri", storage_path))
        for source_id in source_ids:
            artifact_record = by_artifact_id.get(source_id)
            if artifact_record is None:
                continue
            for field in ("artifact_path", "original_path"):
                candidate_value = artifact_record.get(field)
                if _is_remote_uri(candidate_value):
                    candidate = str(candidate_value)
                else:
                    candidate = _resolve_path_candidate(candidate_value, root)
                candidates.append((source_id, candidate))
        if not any(path for _, path in candidates):
            candidates.append(("runtime_fallback", _resolve_runtime_image_path(image, root)))
        for source_ref, path in candidates:
            dedupe_key = (key, str(path or ""))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            if isinstance(path, str) and _is_remote_uri(path):
                exists = True
            else:
                exists = bool(path and isinstance(path, Path) and path.exists())
            suppress_missing_warning = _is_runtime_ref(image_id or source_ref) and not exists
            resolved.append(
                {
                    "image_id": image_id or key,
                    "title": image.get("title") or image_id or key,
                    "description": image.get("description"),
                    "category": image.get("category"),
                    "use_case": image.get("use_case"),
                    "source_artifact_ids": source_ids,
                    "storage_uri": image.get("storage_uri"),
                    "source_artifact_id": source_ref,
                    "artifact_path": str(path) if path is not None else None,
                    "exists": exists,
                    "suppress_missing_warning": suppress_missing_warning,
                }
            )
    return resolved


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _is_runtime_ref(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return value.startswith("runtime_")


def _resolve_path_candidate(value: Any, root: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    if _is_remote_uri(value):
        return None
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    return path


def _is_remote_uri(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return value.startswith("http://") or value.startswith("https://")


def _resolve_canonical_image_path(
    image: Mapping[str, Any],
    *,
    source_ids: list[str],
    artifact_records_by_id: Mapping[str, Mapping[str, Any]],
    root: Path,
) -> Path | None:
    for candidate in (
        _resolve_path_candidate(image.get("storage_uri"), root),
        *[
            _resolve_path_candidate(record.get("original_path"), root)
            for record in image.get("source_artifact_records") or []
            if isinstance(record, Mapping)
        ],
    ):
        if candidate is not None and candidate.exists():
            return candidate
    for source_id in source_ids:
        artifact_record = artifact_records_by_id.get(source_id)
        if artifact_record is None:
            continue
        for field in ("artifact_path", "original_path"):
            candidate = _resolve_path_candidate(artifact_record.get(field), root)
            if candidate is not None and candidate.exists():
                return candidate
    runtime_candidate = _resolve_runtime_image_path(image, root)
    if runtime_candidate is not None and runtime_candidate.exists():
        return runtime_candidate
    return None


def _resolve_runtime_image_path(
    image: Mapping[str, Any],
    root: Path,
) -> Path | None:
    image_id = str(image.get("image_id") or image.get("id") or "").strip()
    if not image_id.startswith("runtime_"):
        return None
    candidates: list[Path] = []
    for base in (
        root / "runtime_images",
        root / "runtime_screens",
        root / "assets",
        root / "output" / "runtime_images",
        root / "output" / "phase0" / "runtime_images",
    ):
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            candidates.append(base / f"{image_id}{ext}")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _load_source_artifact_records() -> list[Mapping[str, Any]]:
    import json

    try:
        raw = json.loads(SOURCE_ARTIFACTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


@lru_cache(maxsize=1)
def _load_canonical_image_records() -> list[Mapping[str, Any]]:
    import json

    path = Path(__file__).resolve().parents[1] / "data" / "normalized" / "canonical_images.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def lookup_canonical_images(image_ids: list[str]) -> list[dict[str, Any]]:
    if not image_ids:
        return []
    records = _load_canonical_image_records()
    by_id = {
        str(record.get("image_id") or record.get("id") or ""): record
        for record in records
        if isinstance(record, Mapping)
    }
    resolved: list[dict[str, Any]] = []
    seen: set[str] = set()
    for image_id in image_ids:
        key = str(image_id).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        record = by_id.get(key)
        if record:
            resolved.append(dict(record))
    return resolved


@lru_cache(maxsize=1)
def _load_procedure_records() -> dict[str, dict[str, Any]]:
    import json

    records: dict[str, dict[str, Any]] = {}
    for path in (COSMOS_PROCEDURES_PATH, CANONICAL_PROCEDURES_PATH, DISCOVERED_PROCEDURES_PATH):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            procedure_id = str(item.get("procedure_id") or "").strip()
            if not procedure_id:
                continue
            if procedure_id not in records:
                records[procedure_id] = dict(item)
    return records


def resolve_procedures(procedure_ids: list[str]) -> list[dict[str, Any]]:
    if not procedure_ids:
        return []
    records = _load_procedure_records()
    resolved: list[dict[str, Any]] = []
    seen: set[str] = set()
    for proc_id in procedure_ids:
        key = str(proc_id).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        record = records.get(key)
        if record:
            resolved.append(dict(record))
    return resolved


__all__ = [
    "HOW_TO_CHECK_MESSAGE",
    "PROCEDURE_GUIDANCE_BANNER",
    "ACCEPT_RECOMMENDATION_CONFIDENCE_THRESHOLD",
    "accept_recommendation_value",
    "RendererName",
    "SignalBadge",
    "UNKNOWN_ANSWER",
    "UNKNOWN_ANSWER_LABEL",
    "answer_button_key",
    "allowed_answers_with_unknown",
    "build_guided_submission",
    "derive_dynamic_path_progress",
    "derive_progress_label",
    "derive_recommended_next_step",
    "display_answer_label",
    "format_role_label",
    "extract_visual_artifact_refs",
    "format_signal_badges",
    "is_latest_assistant_turn",
    "latest_observed_signals_from_response",
    "merge_observed_signals",
    "lookup_canonical_images",
    "next_node_title_for_answer",
    "resolve_procedures",
    "resolve_visual_artifacts",
    "resolve_canonical_image_records",
    "select_renderer",
    "select_confidence_value",
    "should_show_procedure_guidance_banner",
    "widget_key",
    "visual_evidence_from_refs",
]
