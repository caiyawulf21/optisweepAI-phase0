from __future__ import annotations

import os
import uuid

import requests
import streamlit as st

from branding import apply_fortna_theme, render_brand_banner
from playbook_ui import (
    append_retrieve_history_entry,
    get_corpus_status,
    get_interactions,
    post_retrieve,
    render_retrieve_assistant_entry,
)


DEFAULT_BACKEND = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

if "retrieve_session_id" not in st.session_state:
    st.session_state.retrieve_session_id = f"rt-{uuid.uuid4().hex[:12]}"
if "retrieve_history" not in st.session_state:
    st.session_state.retrieve_history = []

st.set_page_config(page_title="Search / Chat", layout="wide")
apply_fortna_theme()
render_brand_banner("Search / Chat")
st.title("Search / Chat")

with st.sidebar:
    backend_url = st.text_input("Backend URL", value=DEFAULT_BACKEND)
    corpus = get_corpus_status(backend_url)
    source = str(corpus.get("source") or "unknown")
    embedding_total = int(corpus.get("embedding_total") or 0)
    if source != "cosmos":
        st.error(
            "Corpus is not reporting live Cosmos. "
            "Set `RETRIEVAL_BACKEND=cosmos` and Cosmos credentials, then restart the API."
        )
    elif corpus.get("ok"):
        st.success(
            f"Azure Cosmos · `{corpus.get('publish_version_id')}` · "
            f"{embedding_total} embeddings"
        )
    else:
        st.warning(f"Corpus status: `{source}` ({corpus.get('error') or 'check backend'})")
    if corpus.get("embedding_counts"):
        counts = dict(corpus.get("embedding_counts") or {})
        st.caption(
            " · ".join(f"{name}: {count}" for name, count in sorted(counts.items()))
        )
        if int(counts.get("operational_context") or 0) <= 0:
            st.warning(
                "No `operational_context` embeddings loaded from Azure. "
                "Check `COSMOS_CONTAINER_OPERATIONAL_CONTEXT` and publish version."
            )
    search_all = st.checkbox("Search all published embeddings", value=True)
    show_full_details = st.checkbox("Expand full playbook/runbook details", value=False)
    show_images = st.checkbox("Show reference images", value=True)
    variant = st.radio("Prompt variant (for playbook hits)", ["prompt_a", "prompt_b"], horizontal=True)
    record_types: list[str] | None = None
    if not search_all:
        include_playbooks = st.checkbox("Include playbooks", value=True)
        record_types = [
            "canonical_runbook",
            "operational_context",
            "incident_source_runbook",
        ]
        if include_playbooks:
            record_types.append(
                "playbook_prompt_a" if variant == "prompt_a" else "playbook_prompt_b"
            )
    if st.button("New retrieve session"):
        st.session_state.retrieve_session_id = f"rt-{uuid.uuid4().hex[:12]}"
        st.session_state.retrieve_history = []
        st.rerun()
    st.caption(f"Session: `{st.session_state.retrieve_session_id}`")
    st.caption(
        "Standalone corpus Q&A. For contextual search beside an active playbook, use "
        "Guided Troubleshoot → Search Chat panel."
    )

conversation_tab, turns_tab, trace_tab = st.tabs(["Conversation", "Turns", "Trace"])

with conversation_tab:
    for entry in st.session_state.retrieve_history:
        with st.chat_message(entry["role"]):
            if entry["role"] == "assistant":
                render_retrieve_assistant_entry(
                    entry,
                    backend=backend_url,
                    show_full_runbooks=show_full_details,
                    playbook_variant=variant,
                    load_images=show_images,
                )
            else:
                st.write(entry["text"])
    prompt = st.chat_input("Ask a question")
    if prompt:
        try:
            payload = post_retrieve(
                backend_url,
                query=prompt,
                session_id=st.session_state.retrieve_session_id,
                playbook_variant=variant,
                record_types=record_types,
            )
            append_retrieve_history_entry(
                st.session_state.retrieve_history,
                query=prompt,
                payload=payload,
            )
            st.rerun()
        except requests.RequestException as exc:
            st.error(str(exc))

with turns_tab:
    interactions = get_interactions(
        backend_url, st.session_state.retrieve_session_id, surface="retrieve"
    )
    if not interactions:
        st.caption("No turns logged yet.")
    for idx, item in enumerate(interactions, start=1):
        with st.expander(f"Turn {idx}"):
            st.write(item.get("user_message") or item.get("final_response"))

with trace_tab:
    last = (
        st.session_state.retrieve_history[-1]["payload"]
        if st.session_state.retrieve_history
        else None
    )
    if last:
        st.json(last)
