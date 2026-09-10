from __future__ import annotations

from typing import Any, Literal


PlaybookResolution = Literal["pinned", "awaiting_candidate", "unpinned"]


def classify_playbook_resolution(
    state: dict[str, Any] | None,
    *,
    response_type: str | None = None,
) -> PlaybookResolution:
    """How far Guided Troubleshoot got toward a chosen playbook/case."""
    data = state if isinstance(state, dict) else {}
    if data.get("active_playbook_id") or data.get("selected_workflow_id"):
        return "pinned"
    branch = data.get("branch_state") if isinstance(data.get("branch_state"), dict) else {}
    rt = str(response_type or data.get("response_type") or "").strip().lower()
    if branch.get("awaiting_candidate") or rt == "playbook_candidates":
        return "awaiting_candidate"
    return "unpinned"


def candidate_playbook_ids(state: dict[str, Any] | None) -> list[str]:
    data = state if isinstance(state, dict) else {}
    rows = list(data.get("playbook_candidates") or [])
    ids: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in ("playbook_id", "workflow_id", "id", "case_id"):
            value = str(row.get(key) or "").strip()
            if value and value not in seen:
                seen.add(value)
                ids.append(value)
                break
    return ids


def needs_brain_routing_learning(resolution: PlaybookResolution) -> bool:
    return resolution in {"unpinned", "awaiting_candidate"}


__all__ = [
    "PlaybookResolution",
    "candidate_playbook_ids",
    "classify_playbook_resolution",
    "needs_brain_routing_learning",
]
