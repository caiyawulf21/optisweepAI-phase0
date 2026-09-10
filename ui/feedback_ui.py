from __future__ import annotations

from typing import Any

import requests
import streamlit as st


def upload_attachments(
    backend_url: str,
    *,
    session_id: str,
    files: list[Any],
    source: str,
    user_description: str = "",
) -> list[dict[str, Any]]:
    uploaded: list[dict[str, Any]] = []
    for item in files or []:
        try:
            raw = item.getvalue() if hasattr(item, "getvalue") else item.read()
            filename = getattr(item, "name", "upload.bin")
            content_type = getattr(item, "type", None) or "application/octet-stream"
            response = requests.post(
                f"{backend_url.rstrip('/')}/attachments/upload",
                data={
                    "session_id": session_id,
                    "source": source,
                    "user_description": user_description or "",
                },
                files={"file": (filename, raw, content_type)},
                timeout=120,
            )
            response.raise_for_status()
            uploaded.append(response.json())
        except Exception as exc:
            st.warning(f"Image upload/vision failed for {getattr(item, 'name', 'file')}: {exc}")
    return uploaded


def post_feedback(
    backend_url: str,
    *,
    session_id: str,
    interaction_id: str,
    surface: str,
    sentiment: str,
    about: str = "",
    user_text: str = "",
    proposed_change: str = "",
    targets: dict[str, Any] | None = None,
    attachment_ids: list[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "session_id": session_id,
        "interaction_id": interaction_id,
        "surface": surface,
        "sentiment": sentiment,
        "about": about or None,
        "user_text": user_text or "",
        "proposed_change": proposed_change or "",
        "targets": targets or {},
        "attachment_ids": list(attachment_ids or []),
    }
    response = requests.post(
        f"{backend_url.rstrip('/')}/feedback",
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def _targets_from_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    workflow = data.get("workflow_state") if isinstance(data.get("workflow_state"), dict) else {}
    runbook = workflow.get("runbook") if isinstance(workflow.get("runbook"), dict) else {}
    node = workflow.get("current_node") if isinstance(workflow.get("current_node"), dict) else {}
    record_ids = list(data.get("retrieved_record_ids") or data.get("record_ids") or [])
    if not record_ids:
        for hit in list(data.get("hits") or []):
            if isinstance(hit, dict) and hit.get("source_record_id"):
                record_ids.append(str(hit["source_record_id"]))
    return {
        "playbook_id": workflow.get("playbook_id") or data.get("selected_workflow_id"),
        "runbook_id": runbook.get("procedure_id") or workflow.get("current_runbook_id"),
        "node_id": node.get("node_id") or workflow.get("current_node_id"),
        "record_ids": record_ids,
    }


def render_feedback_controls(
    *,
    backend_url: str,
    session_id: str,
    interaction_id: str | None,
    surface: str,
    payload: dict[str, Any] | None = None,
    key_prefix: str,
) -> None:
    if not interaction_id:
        st.caption("Feedback unavailable until this turn is logged.")
        return
    cols = st.columns(3)
    with cols[0]:
        if st.button("Helpful", key=f"{key_prefix}-helpful"):
            try:
                result = post_feedback(
                    backend_url,
                    session_id=session_id,
                    interaction_id=interaction_id,
                    surface=surface,
                    sentiment="helpful",
                    targets=_targets_from_payload(payload),
                )
                st.success(result.get("message") or "Saved in app audit.")
            except Exception as exc:
                st.warning(str(exc))
    with cols[1]:
        if st.button("Not helpful", key=f"{key_prefix}-not"):
            try:
                result = post_feedback(
                    backend_url,
                    session_id=session_id,
                    interaction_id=interaction_id,
                    surface=surface,
                    sentiment="not_helpful",
                    targets=_targets_from_payload(payload),
                )
                st.success(result.get("message") or "Saved in app audit.")
            except Exception as exc:
                st.warning(str(exc))
    with cols[2]:
        suggest = st.button("Suggest fix", key=f"{key_prefix}-suggest")
    if suggest or st.session_state.get(f"{key_prefix}-open"):
        st.session_state[f"{key_prefix}-open"] = True
        with st.form(f"{key_prefix}-form"):
            about = st.text_input(
                "About (optional)",
                placeholder="e.g. playbook step, runbook, answer",
            )
            user_text = st.text_area("What was wrong or missing?")
            proposed = st.text_area("Proposed correction (optional)")
            images = st.file_uploader(
                "Attach screenshot(s) (optional)",
                type=["png", "jpg", "jpeg", "webp"],
                accept_multiple_files=True,
                key=f"{key_prefix}-files",
            )
            submitted = st.form_submit_button("Submit suggestion")
            if submitted:
                attachment_ids: list[str] = []
                if images:
                    uploaded = upload_attachments(
                        backend_url,
                        session_id=session_id,
                        files=list(images),
                        source="feedback",
                        user_description=user_text or proposed or about,
                    )
                    attachment_ids = [
                        str(item.get("attachment_id"))
                        for item in uploaded
                        if item.get("attachment_id")
                    ]
                try:
                    result = post_feedback(
                        backend_url,
                        session_id=session_id,
                        interaction_id=interaction_id,
                        surface=surface,
                        sentiment="suggestion",
                        about=about,
                        user_text=user_text,
                        proposed_change=proposed,
                        targets=_targets_from_payload(payload),
                        attachment_ids=attachment_ids,
                    )
                    st.session_state[f"{key_prefix}-open"] = False
                    st.success(result.get("message") or "Saved in app audit.")
                except Exception as exc:
                    st.warning(str(exc))


def render_image_summaries(payload: dict[str, Any] | None) -> None:
    data = payload if isinstance(payload, dict) else {}
    summaries = list(data.get("image_summaries") or [])
    if not summaries:
        return
    with st.expander("Image summaries used this turn", expanded=False):
        for idx, summary in enumerate(summaries, start=1):
            st.markdown(f"**Image {idx}.** {summary}")
