from __future__ import annotations

from typing import Any, Literal


OutcomeLevel = Literal["success", "warning", "info", "error"]


def review_effective_id(row: dict[str, Any] | None) -> str:
    data = row if isinstance(row, dict) else {}
    for key in ("review_id", "id", "brain_review_id"):
        value = data.get(key)
        if value:
            return str(value)
    return ""


def review_queue_label(row: dict[str, Any] | None) -> str:
    data = row if isinstance(row, dict) else {}
    rid = review_effective_id(data) or "unknown"
    kind = str(data.get("kind") or "").strip() or "review"
    title = (
        str(data.get("title") or data.get("summary") or "").strip()
        or str(data.get("proposed_change") or "")[:80].strip()
        or rid
    )
    status = str(data.get("status") or "open").strip()
    priority = str(data.get("priority") or "").strip()
    bits = [kind, status]
    if priority:
        bits.append(priority)
    return f"{' · '.join(bits)} — {title}"


def _coerce_applied(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "applied"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def format_resolve_outcome(response: dict[str, Any] | None) -> tuple[OutcomeLevel, str]:
    """Map Brain resolve response to UI level + message.

    ``applied`` is the source of truth for whether the corpus changed
    (MERGE → true; RETYPE/RECLASSIFY → false with explanation).
    """
    data = response if isinstance(response, dict) else {}
    if not data:
        return "error", "Empty resolve response from Brain."

    message = str(data.get("message") or data.get("detail") or "").strip()
    status = str(data.get("status") or "").strip().lower()
    resolution = str(data.get("resolution") or "").strip().lower()
    applied = _coerce_applied(data.get("applied"))
    apply_status = str(
        data.get("apply_status")
        or data.get("execution_status")
        or data.get("apply_result")
        or ""
    ).strip().lower()
    mutated = [str(item) for item in (data.get("mutated_record_ids") or []) if item]

    if status in {"error", "failed"} or data.get("errors"):
        errs = data.get("errors") or []
        detail = "; ".join(str(item) for item in errs) if errs else message
        return "error", detail or "Resolve failed."

    if resolution == "reject":
        return "info", message or "Review rejected; trusted cite set unchanged."

    # Brain contract: applied is authoritative for corpus mutation.
    if applied is False:
        text = message or (
            "Approval recorded, but applied=false — corpus was not changed "
            "(e.g. RETYPE/RECLASSIFY pending ID cascade)."
        )
        return "warning", text

    if applied is True:
        text = message or "Corpus mutation applied."
        if mutated:
            return "success", f"{text} Mutated: {', '.join(mutated)}"
        return "success", text

    not_executed_markers = {
        "needs_human",
        "accepted_not_executed",
        "accepted_not_yet_executed",
        "not_auto_applied",
        "pending_tooling",
        "not_executed",
    }
    if (
        status in not_executed_markers
        or apply_status in not_executed_markers
        or "not auto-applied" in message.lower()
        or "not yet executed" in message.lower()
        or "pending tooling" in message.lower()
    ):
        text = message or (
            "Approval recorded, but the change was not executed yet "
            "(e.g. RETYPE/RECLASSIFY). Corpus IDs were not rewritten."
        )
        return "warning", text

    if mutated:
        text = message or "Corpus mutation applied."
        return "success", f"{text} Mutated: {', '.join(mutated)}"

    if status in {"rejected", "resolved"}:
        text = message or "Review resolved."
        if status == "resolved" and not mutated:
            return "info", (
                text
                + " No applied=true / mutated_record_ids — do not assume corpus changed."
            )
        return "info", text

    return "info", message or "Resolve completed."


__all__ = [
    "format_resolve_outcome",
    "review_effective_id",
    "review_queue_label",
]
