from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import requests
import streamlit as st

from branding import apply_fortna_theme, render_brand_banner

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.app.services.review_ui import (
    format_affected_records,
    format_proposed_change_card,
    format_resolve_outcome,
    review_effective_id,
    review_queue_label,
)


DEFAULT_BACKEND = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _backend_settings(backend_url: str) -> dict[str, Any]:
    try:
        response = requests.get(f"{backend_url.rstrip('/')}/debug/settings", timeout=10)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _list_reviews(backend_url: str, *, status: str, limit: int) -> dict[str, Any]:
    response = requests.get(
        f"{backend_url.rstrip('/')}/reviews",
        params={"status": status, "limit": limit},
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {"reviews": [], "total": 0}


def _get_review(backend_url: str, review_id: str) -> dict[str, Any]:
    response = requests.get(
        f"{backend_url.rstrip('/')}/reviews/{review_id}",
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {}


def _resolve_review(
    backend_url: str,
    review_id: str,
    *,
    resolution: str,
    reviewer_id: str,
    notes: str,
    edited_proposed_change: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "resolution": resolution,
        "resolved_by": "human",
        "reviewer_id": reviewer_id or None,
        "notes": notes or None,
        "edited_proposed_change": edited_proposed_change,
    }
    response = requests.post(
        f"{backend_url.rstrip('/')}/reviews/{review_id}/resolve",
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {}


def _show_outcome(result: dict[str, Any]) -> None:
    level, message = format_resolve_outcome(result)
    if level == "success":
        st.success(message)
    elif level == "warning":
        st.warning(message)
    elif level == "error":
        st.error(message)
    else:
        st.info(message)
    if "applied" in result:
        st.caption(f"applied={result.get('applied')!r} (source of truth for corpus change)")
    mutated = result.get("mutated_record_ids") or []
    if mutated:
        st.caption("Mutated records: " + ", ".join(str(item) for item in mutated))


def _render_proposed_change(proposed: Any) -> None:
    card = format_proposed_change_card(proposed)
    st.markdown("**What Brain wants to do**")
    st.info(f"**{card.get('action') or 'CHANGE'}** — {card.get('headline')}")
    details = list(card.get("details") or [])
    if details:
        for label, value in details:
            st.markdown(f"- **{label}:** {value}")
    with st.expander("Proposed change (raw)", expanded=False):
        if isinstance(proposed, (dict, list)):
            st.json(proposed)
        else:
            st.write(proposed or "—")


def _render_affected_records(detail: dict[str, Any], proposed: Any) -> None:
    rows = format_affected_records(
        affected_records=detail.get("affected_records"),
        affected_record_ids=detail.get("affected_record_ids"),
        proposed=proposed,
    )
    st.markdown("**Affected records**")
    if not rows:
        st.caption("No affected records listed.")
        return
    st.dataframe(
        [
            {
                "Role": row["role"],
                "Record ID": row["record_id"],
                "Type": row["record_type"],
                "Validation": row["validation_status"],
            }
            for row in rows
        ],
        use_container_width=True,
        hide_index=True,
    )


st.set_page_config(page_title="SME Review", layout="wide")
apply_fortna_theme()
render_brand_banner("SME Review")

with st.sidebar:
    backend_url = st.text_input("Backend URL", value=DEFAULT_BACKEND)
    status_filter = st.selectbox(
        "Queue status",
        options=["open", "resolved"],
        index=0,
    )
    limit = st.number_input("Limit", min_value=1, max_value=200, value=50, step=1)
    reviewer_id = st.text_input(
        "Reviewer id", value=st.session_state.get("sme_reviewer_id", "")
    )
    if reviewer_id:
        st.session_state.sme_reviewer_id = reviewer_id
    refresh = st.button("Refresh queue", use_container_width=True)

settings = _backend_settings(backend_url)
reviews_on = bool(settings.get("brain_http_reviews")) and bool(
    settings.get("brain_http_enabled")
)
brain_url = settings.get("brain_http_base_url")

query_review_id = ""
try:
    query_review_id = str(st.query_params.get("review_id") or "").strip()
except Exception:
    query_review_id = ""

open_count: int | None = None
title_suffix = ""
if reviews_on:
    try:
        preview = _list_reviews(backend_url, status="open", limit=int(limit))
        open_count = int(preview.get("total") or len(preview.get("reviews") or []))
        if open_count > 0:
            title_suffix = f" ({open_count} open)"
    except Exception:
        open_count = None

st.title(f"SME Review{title_suffix}")
st.caption(
    "Pull queue for open BrainReviews. Approve / reject / edit via Brain HTTP resolve. "
    "Technicians are not approvers — knowledge SMEs only."
)

if not settings:
    st.error(
        f"Backend unreachable at {backend_url}. Start the API and check API_BASE_URL."
    )
    st.stop()

if not reviews_on:
    st.warning(
        "Brain reviews are disabled on the API. Enable "
        "`BRAIN_HTTP_ENABLED=true`, `BRAIN_HTTP_REVIEWS=true`, and set "
        "`BRAIN_HTTP_BASE_URL` to the Brain host, then restart the API."
    )
    st.json(
        {
            "brain_http_enabled": settings.get("brain_http_enabled"),
            "brain_http_reviews": settings.get("brain_http_reviews"),
            "brain_http_base_url": brain_url,
        }
    )
    st.stop()

if refresh:
    st.session_state.pop("sme_selected_review_id", None)

try:
    listing = _list_reviews(
        backend_url,
        status=status_filter,
        limit=int(limit),
    )
    reviews = list(listing.get("reviews") or [])
except Exception as exc:
    st.error(f"Failed to load review queue: {exc}")
    st.stop()

if query_review_id and "sme_selected_review_id" not in st.session_state:
    st.session_state.sme_selected_review_id = query_review_id

ids = [review_effective_id(row) for row in reviews if review_effective_id(row)]
labels = {
    review_effective_id(row): review_queue_label(row)
    for row in reviews
    if review_effective_id(row)
}

col_queue, col_detail = st.columns([1, 2], gap="large")

with col_queue:
    st.subheader("Queue")
    st.caption(f"{len(reviews)} row(s) · filter={status_filter}")
    if not reviews:
        st.info("No reviews in this queue.")
    else:
        default_index = 0
        selected_existing = st.session_state.get("sme_selected_review_id")
        if selected_existing in ids:
            default_index = ids.index(selected_existing)
        selected = st.radio(
            "Open reviews",
            options=ids,
            format_func=lambda rid: labels.get(rid, rid),
            index=default_index,
            key="sme_queue_radio",
        )
        st.session_state.sme_selected_review_id = selected

with col_detail:
    st.subheader("Detail")
    selected_id = str(st.session_state.get("sme_selected_review_id") or "").strip()
    if not selected_id:
        st.info("Select a review from the queue.")
        st.stop()

    try:
        detail = _get_review(backend_url, selected_id)
    except Exception as exc:
        st.error(f"Failed to load review {selected_id}: {exc}")
        st.stop()

    title = str(detail.get("title") or detail.get("summary") or selected_id).strip()
    st.markdown(f"### {title}")
    st.caption(f"Review ID: `{review_effective_id(detail) or selected_id}`")
    if detail.get("summary") and detail.get("title"):
        st.write(detail.get("summary"))

    meta_cols = st.columns(4)
    meta_cols[0].metric("Kind", str(detail.get("kind") or "—"))
    meta_cols[1].metric("Status", str(detail.get("status") or "—"))
    meta_cols[2].metric(
        "Priority", str(detail.get("priority") or detail.get("audit_action") or "—")
    )
    meta_cols[3].metric(
        "Resolution type",
        str(detail.get("resolution_type") or detail.get("audit_action") or "—"),
    )

    proposed = detail.get("proposed_change_detail")
    if proposed is None:
        proposed = detail.get("proposed_change")
    _render_proposed_change(proposed)
    _render_affected_records(detail, proposed)

    with st.expander("Raw review payload", expanded=False):
        st.json(detail.get("raw") or detail)

    st.divider()
    st.markdown("**Resolve**")
    resolution = st.radio(
        "Resolution",
        options=["approve", "reject", "edit"],
        horizontal=True,
        key=f"resolve_resolution_{selected_id}",
    )
    notes = st.text_area("Notes", key=f"resolve_notes_{selected_id}")
    edited_change = None
    if resolution == "edit":
        default_edit = (
            json.dumps(proposed, indent=2)
            if isinstance(proposed, (dict, list))
            else str(proposed or "")
        )
        edited_change = st.text_area(
            "Edited proposed change",
            value=default_edit,
            key=f"resolve_edit_{selected_id}",
            height=160,
        )

    st.caption(
        "Use `applied` from Brain as the source of truth for corpus change. "
        "MERGE and RETYPE may set applied=true and mutate the corpus. "
        "RECLASSIFY stays applied=false with an explanation; refused RETYPE returns HTTP 400."
    )

    if st.button(
        "Submit resolution", type="primary", key=f"resolve_submit_{selected_id}"
    ):
        try:
            result = _resolve_review(
                backend_url,
                selected_id,
                resolution=resolution,
                reviewer_id=str(st.session_state.get("sme_reviewer_id") or ""),
                notes=notes,
                edited_proposed_change=edited_change if resolution == "edit" else None,
            )
            _show_outcome(result)
            status_val = str(result.get("status") or "").lower()
            if status_val in {
                "resolved",
                "rejected",
                "needs_human",
                "accepted_not_executed",
            } or result.get("mutated_record_ids"):
                st.session_state.pop("sme_selected_review_id", None)
                st.rerun()
        except Exception as exc:
            st.error(f"Resolve failed: {exc}")
