"""Compact troubleshooting context for contextual Search Chat retrieval.

Search Chat may read playbook/session context to improve retrieval precision.
It must never mutate workflow/playbook state — that remains on /troubleshoot.
"""

from __future__ import annotations

import re
from typing import Any


def compact_search_context(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Keep only retrieval-useful fields; drop bulky session dumps."""
    raw = raw if isinstance(raw, dict) else {}
    symptoms = _string_list(raw.get("symptoms") or raw.get("observed_entry_symptoms"))
    signals = _signal_list(raw.get("observed_signals") or raw.get("symptoms_signals"))
    components = _string_list(raw.get("components"))
    systems = _string_list(raw.get("systems"))
    completed = _string_list(raw.get("completed_nodes") or raw.get("completed_node_ids"))
    context: dict[str, Any] = {}
    for key in (
        "session_id",
        "active_playbook_id",
        "active_playbook_version",
        "playbook_title",
        "current_node_id",
        "current_node_title",
        "current_node_type",
        "current_runbook_id",
        "current_procedure_title",
    ):
        value = str(raw.get(key) or "").strip()
        if value:
            context[key] = value
    if symptoms:
        context["symptoms"] = symptoms[:8]
    if signals:
        context["observed_signals"] = signals[:12]
    if components:
        context["components"] = components[:8]
    if systems:
        context["systems"] = systems[:8]
    if completed:
        context["completed_nodes"] = completed[:12]
    allowed = _string_list(raw.get("allowed_answers"))
    if allowed:
        context["allowed_answers"] = allowed[:12]
    return context


def build_contextual_retrieval_query(user_query: str, context: dict[str, Any] | None) -> str:
    """Rewrite the operator question with compact playbook context for retrieval."""
    query = str(user_query or "").strip()
    ctx = compact_search_context(context)
    if not query or not ctx:
        return query
    bits: list[str] = []
    node_title = str(ctx.get("current_node_title") or "").strip()
    node_id = str(ctx.get("current_node_id") or "").strip()
    playbook = str(ctx.get("playbook_title") or ctx.get("active_playbook_id") or "").strip()
    runbook = str(ctx.get("current_procedure_title") or ctx.get("current_runbook_id") or "").strip()
    if node_title:
        bits.append(f"current troubleshooting step: {node_title}")
    elif node_id:
        bits.append(f"current troubleshooting step: {node_id}")
    if playbook:
        bits.append(f"active playbook: {playbook}")
    if runbook:
        bits.append(f"linked procedure: {runbook}")
    for label, key in (
        ("symptoms", "symptoms"),
        ("observed signals", "observed_signals"),
        ("components", "components"),
        ("systems", "systems"),
    ):
        values = list(ctx.get(key) or [])
        if values:
            bits.append(f"{label}: {', '.join(str(v) for v in values[:6])}")
    if not bits:
        return query
    return f"{query} — for OptiSweep troubleshooting involving {'; '.join(bits)}"


def infer_workflow_relevance(
    *,
    answer: str,
    hits: list[dict[str, Any]] | None = None,
    search_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Suggest an optional, user-confirmed bridge back into the active node.

    Never applies state. Only proposes a structured update when the active node
    exposes allowed answers and the answer/hits clearly map to one of them.
    """
    ctx = compact_search_context(search_context)
    node_id = str(ctx.get("current_node_id") or "").strip()
    node_title = str(ctx.get("current_node_title") or "").strip()
    hit_rows = [hit for hit in list(hits or []) if isinstance(hit, dict)]
    related = bool((node_id or node_title) and (hit_rows or str(answer or "").strip()))
    allowed = _string_list(ctx.get("allowed_answers"))
    possible = None
    if allowed:
        matched = _match_allowed_answer(answer, allowed, hit_rows)
        if matched:
            possible = {
                "field": "branch_answer",
                "value": matched,
                "node_id": node_id or None,
                "requires_user_confirmation": True,
            }
    return {
        "related_to_current_node": related,
        "possible_state_update": possible,
    }


def search_context_trace_fields(context: dict[str, Any] | None) -> dict[str, Any]:
    ctx = compact_search_context(context)
    return {
        "search_context_present": bool(ctx),
        "active_playbook_id": ctx.get("active_playbook_id"),
        "current_node_id": ctx.get("current_node_id"),
        "current_runbook_id": ctx.get("current_runbook_id"),
        "symptom_count": len(list(ctx.get("symptoms") or [])),
        "signal_count": len(list(ctx.get("observed_signals") or [])),
    }


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        return [
            str(key).replace("_", " ")
            for key, flag in value.items()
            if flag and str(key).strip()
        ]
    if not isinstance(value, (list, tuple, set)):
        text = str(value).strip()
        return [text] if text else []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, dict):
            text = str(
                item.get("title")
                or item.get("signal")
                or item.get("name")
                or item.get("id")
                or ""
            ).strip()
        else:
            text = str(item or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _signal_list(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [
            str(key).replace("_", " ")
            for key, flag in value.items()
            if flag and str(key).strip()
        ]
    return _string_list(value)


def _match_allowed_answer(
    answer: str,
    allowed: list[str],
    hits: list[dict[str, Any]],
) -> str | None:
    blob = " ".join(
        [
            str(answer or ""),
            " ".join(str(hit.get("snippet") or "") for hit in hits[:3] if isinstance(hit, dict)),
            " ".join(str(hit.get("title") or "") for hit in hits[:3] if isinstance(hit, dict)),
        ]
    ).lower()
    ranked: list[tuple[int, str]] = []
    for label in allowed:
        text = str(label or "").strip()
        if not text:
            continue
        lowered = text.lower()
        if re.search(rf"\b{re.escape(lowered)}\b", blob):
            ranked.append((len(lowered), text))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]
