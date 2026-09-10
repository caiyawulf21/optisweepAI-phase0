from __future__ import annotations

from typing import Any

APPROVED_KNOWLEDGE_STATUSES: frozenset[str] = frozenset(
    {
        "catalog_authoritative",
        "sme_approved",
    }
)

WORKING_KNOWLEDGE_STATUSES: frozenset[str] = frozenset(
    {
        "operational_unreviewed",
    }
)

_BRAIN_EXCERPT_MAX = 800


def is_approved_knowledge_status(status: str | None) -> bool:
    return str(status or "").strip().lower() in APPROVED_KNOWLEDGE_STATUSES


def is_working_knowledge_status(status: str | None) -> bool:
    return str(status or "").strip().lower() in WORKING_KNOWLEDGE_STATUSES


def filter_approved_excerpts(excerpts: list[dict] | None) -> list[dict]:
    rows: list[dict] = []
    for item in list(excerpts or []):
        if not isinstance(item, dict):
            continue
        if is_approved_knowledge_status(item.get("validation_status")):
            rows.append(item)
    return rows


def filter_working_excerpts(excerpts: list[dict] | None) -> list[dict]:
    rows: list[dict] = []
    for item in list(excerpts or []):
        if not isinstance(item, dict):
            continue
        if is_working_knowledge_status(item.get("validation_status")):
            rows.append(item)
    return rows


def excerpts_to_citations(
    excerpts: list[dict] | None,
    *,
    include_working: bool = False,
) -> list[dict]:
    citations: list[dict] = []
    rows = list(filter_approved_excerpts(excerpts))
    if include_working:
        rows.extend(filter_working_excerpts(excerpts))
    for item in rows:
        record_id = str(item.get("record_id") or "").strip()
        title = str(item.get("title") or record_id or "Brain").strip()
        text = str(item.get("text") or "").strip()
        status = str(item.get("validation_status") or "").strip()
        record_type = str(item.get("record_type") or "brain") or "brain"
        if is_working_knowledge_status(status):
            reference = f"{record_type}|operational_unreviewed"
            if "operational unreviewed" not in title.lower():
                title = f"{title} [operational unreviewed]"
        else:
            reference = record_type
        citations.append(
            {
                "source_id": record_id or title,
                "title": title,
                "reference": reference or None,
                "excerpt": text or None,
            }
        )
    return citations


def _normalize_synthesis_row(
    item: dict[str, Any],
    *,
    approved: bool,
) -> dict[str, Any] | None:
    record_id = str(item.get("record_id") or "").strip()
    title = str(item.get("title") or record_id or "Brain").strip()
    text = str(item.get("text") or item.get("excerpt") or item.get("snippet") or "").strip()
    if not text:
        return None
    status = str(item.get("validation_status") or "").strip()
    if not approved and not status:
        status = "operational_unreviewed"
    return {
        "title": title,
        "source_id": record_id or title,
        "source_record_id": record_id or title,
        "excerpt": text[:_BRAIN_EXCERPT_MAX],
        "snippet": text[:_BRAIN_EXCERPT_MAX],
        "record_type": str(item.get("record_type") or "brain") or "brain",
        "validation_status": status,
        "confidence": 1.0 if approved else 0.45,
        "combined_score": 1.0 if approved else 0.45,
        "origin": "brain",
        "review_state": "approved" if approved else "operational_unreviewed",
    }


def excerpts_for_synthesis(
    excerpts: list[dict] | None,
    *,
    working_excerpts: list[dict] | None = None,
    include_working: bool = True,
    limit: int = 8,
    approved_limit: int = 6,
    working_limit: int = 4,
) -> list[dict[str, Any]]:
    """Normalize Brain excerpts for retrieve answer synthesis.

    Approved rows first; optional operational_unreviewed working material follows
    and must be labeled as unreviewed in the composed answer.
    """
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in filter_approved_excerpts(excerpts):
        if len([r for r in rows if r.get("review_state") == "approved"]) >= approved_limit:
            break
        normalized = _normalize_synthesis_row(item, approved=True)
        if normalized is None:
            continue
        key = str(normalized["source_id"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(normalized)
        if len(rows) >= limit:
            return rows

    if not include_working:
        return rows

    working_src = list(working_excerpts or [])
    if not working_src:
        working_src = filter_working_excerpts(excerpts)
    else:
        working_src = filter_working_excerpts(working_src) or [
            item for item in working_src if isinstance(item, dict)
        ]

    working_added = 0
    for item in working_src:
        if working_added >= working_limit or len(rows) >= limit:
            break
        normalized = _normalize_synthesis_row(item, approved=False)
        if normalized is None:
            continue
        key = str(normalized["source_id"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(normalized)
        working_added += 1
    return rows


__all__ = [
    "APPROVED_KNOWLEDGE_STATUSES",
    "WORKING_KNOWLEDGE_STATUSES",
    "excerpts_for_synthesis",
    "excerpts_to_citations",
    "filter_approved_excerpts",
    "filter_working_excerpts",
    "is_approved_knowledge_status",
    "is_working_knowledge_status",
]
