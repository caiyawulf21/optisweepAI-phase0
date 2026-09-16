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


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def proposed_change_action(proposed: Any) -> str:
    if isinstance(proposed, dict):
        for key in ("action", "resolution_type", "type", "kind"):
            text = str(proposed.get(key) or "").strip()
            if text:
                return text.upper()
    return ""


def format_proposed_change_card(proposed: Any) -> dict[str, Any]:
    """Normalize Brain proposed_change into a friendly card payload."""
    action = proposed_change_action(proposed)
    if isinstance(proposed, dict):
        winner = str(
            proposed.get("winner_record_id")
            or proposed.get("keep_record_id")
            or proposed.get("target_record_id")
            or ""
        ).strip()
        losers = [
            str(item).strip()
            for item in _as_list(
                proposed.get("loser_record_ids")
                or proposed.get("merge_away_record_ids")
                or proposed.get("source_record_ids")
            )
            if str(item).strip()
        ]
        target = str(
            proposed.get("record_id")
            or proposed.get("target_record_id")
            or proposed.get("entity_id")
            or ""
        ).strip()
        new_type = str(
            proposed.get("new_record_type")
            or proposed.get("to_type")
            or proposed.get("record_type")
            or ""
        ).strip()
        new_id = str(
            proposed.get("new_record_id")
            or proposed.get("to_record_id")
            or proposed.get("renamed_record_id")
            or ""
        ).strip()
        reason = str(
            proposed.get("reason")
            or proposed.get("rationale")
            or proposed.get("summary")
            or proposed.get("description")
            or ""
        ).strip()

        if action == "MERGE" or (winner and losers):
            headline = "Merge duplicate records"
            if winner:
                headline = f"Keep `{winner}` as the surviving record"
            details = []
            if winner:
                details.append(("Keep", winner))
            if losers:
                details.append(("Merge away", ", ".join(f"`{item}`" for item in losers)))
            if reason:
                details.append(("Why", reason))
            return {
                "action": action or "MERGE",
                "headline": headline,
                "details": details,
                "raw": proposed,
            }

        if action in {"RETYPE", "RECLASSIFY"} or new_type or new_id:
            label = action or ("RETYPE" if new_id else "RECLASSIFY")
            headline = f"{label.title()} record"
            if target:
                headline = f"{label.title()} `{target}`"
            details = []
            if target:
                details.append(("Record", target))
            if new_type:
                details.append(("New type", new_type))
            if new_id:
                details.append(("New id", new_id))
            if reason:
                details.append(("Why", reason))
            return {
                "action": label,
                "headline": headline,
                "details": details,
                "raw": proposed,
            }

        details = [
            (str(key).replace("_", " ").title(), str(value))
            for key, value in proposed.items()
            if value not in (None, "", [], {})
            and key
            not in {
                "action",
                "resolution_type",
                "type",
                "kind",
                "reason",
                "rationale",
                "summary",
                "description",
            }
        ]
        if reason:
            details.insert(0, ("Why", reason))
        return {
            "action": action or "CHANGE",
            "headline": reason or (f"{action} proposed" if action else "Proposed change"),
            "details": details[:12],
            "raw": proposed,
        }

    text = str(proposed or "").strip()
    return {
        "action": action or "CHANGE",
        "headline": text or "No proposed change provided",
        "details": [],
        "raw": proposed,
    }


def format_affected_records(
    *,
    affected_records: Any = None,
    affected_record_ids: Any = None,
    proposed: Any = None,
) -> list[dict[str, str]]:
    """Build friendly rows for affected corpus records."""
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    role_by_id: dict[str, str] = {}
    change = _as_dict(proposed)
    winner = str(
        change.get("winner_record_id")
        or change.get("keep_record_id")
        or ""
    ).strip()
    if winner:
        role_by_id[winner] = "Keep"
    for item in _as_list(
        change.get("loser_record_ids") or change.get("merge_away_record_ids")
    ):
        text = str(item).strip()
        if text:
            role_by_id[text] = "Merge away"
    target = str(
        change.get("record_id")
        or change.get("target_record_id")
        or change.get("entity_id")
        or ""
    ).strip()
    if target and target not in role_by_id:
        role_by_id[target] = "Target"

    for item in _as_list(affected_records):
        if not isinstance(item, dict):
            continue
        rid = str(
            item.get("record_id") or item.get("id") or item.get("entity_id") or ""
        ).strip()
        if not rid or rid in seen:
            continue
        seen.add(rid)
        rows.append(
            {
                "record_id": rid,
                "record_type": str(item.get("record_type") or item.get("type") or "—"),
                "validation_status": str(
                    item.get("validation_status") or item.get("status") or "—"
                ),
                "role": role_by_id.get(rid, "Affected"),
            }
        )

    for item in _as_list(affected_record_ids):
        rid = str(item).strip()
        if not rid or rid in seen:
            continue
        seen.add(rid)
        rows.append(
            {
                "record_id": rid,
                "record_type": "—",
                "validation_status": "—",
                "role": role_by_id.get(rid, "Affected"),
            }
        )
    return rows


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
    "format_affected_records",
    "format_proposed_change_card",
    "format_resolve_outcome",
    "proposed_change_action",
    "review_effective_id",
    "review_queue_label",
]
