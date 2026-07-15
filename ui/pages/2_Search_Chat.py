from __future__ import annotations

import os
import uuid
from typing import Any

import requests
import streamlit as st

from playbook_ui import (
    get_corpus_status,
    get_interactions,
    load_runbook_with_images,
    post_retrieve,
    render_canonical_images,
    render_operational_context_panel,
    render_runbook_panel,
)


DEFAULT_BACKEND = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
_RUNBOOK_TYPES = {"canonical_runbook", "incident_source_runbook"}
_CONTEXT_TYPES = {"operational_context"}

if "retrieve_session_id" not in st.session_state:
    st.session_state.retrieve_session_id = f"rt-{uuid.uuid4().hex[:12]}"
if "retrieve_history" not in st.session_state:
    st.session_state.retrieve_history = []

st.set_page_config(page_title="Search / Chat", layout="wide")
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
        st.caption(
            " · ".join(
                f"{name}: {count}"
                for name, count in sorted(dict(corpus.get("embedding_counts") or {}).items())
            )
        )

    search_all = st.checkbox("Search all published embeddings", value=True)
    show_full_runbooks = st.checkbox("Expand full runbook steps", value=False)
    variant = st.radio("Prompt variant (for playbook hits)", ["prompt_a", "prompt_b"], horizontal=True)
    record_types: list[str] | None = None
    if not search_all:
        include_playbooks = st.checkbox("Include playbooks", value=True)
        record_types = ["canonical_runbook", "operational_context", "incident_source_runbook"]
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
        "Chatbot over the live Cosmos publish with LangChain-trimmed multi-turn memory "
        "(≤6 messages, sticky intent). Answers cite sources. Runbook panels stay summarized "
        "unless expanded."
    )

conversation_tab, turns_tab, trace_tab = st.tabs(["Conversation", "Turns", "Trace"])


def _citations_from_entry(entry: dict[str, Any]) -> list[dict[str, Any]]:
    citations = [item for item in list(entry.get("citations") or []) if isinstance(item, dict)]
    if citations:
        return citations
    built: list[dict[str, Any]] = []
    for hit in list(entry.get("hits") or []):
        if not isinstance(hit, dict):
            continue
        built.append(
            {
                "title": hit.get("title") or hit.get("source_record_id"),
                "source_id": hit.get("source_record_id"),
                "reference": hit.get("record_type"),
                "excerpt": hit.get("snippet"),
                "combined_score": hit.get("combined_score"),
            }
        )
    return built


def _render_sources_block(citations: list[dict[str, Any]]) -> None:
    st.markdown("**Sources**")
    if not citations:
        st.caption("No retrieval hits for this turn.")
        return
    for idx, citation in enumerate(citations, start=1):
        title = citation.get("title") or citation.get("source_id") or f"Source {idx}"
        ref = citation.get("reference") or ""
        label = f"{idx}. {title}"
        if ref:
            label = f"{label} · `{ref}`"
        with st.expander(label, expanded=False):
            excerpt = str(citation.get("excerpt") or "").strip()
            if excerpt:
                st.write(excerpt)
            meta = citation.get("source_id") or ""
            if meta:
                st.caption(f"Record: `{meta}`")
            score = citation.get("combined_score")
            if score is not None:
                st.caption(f"Hybrid score: {float(score):.4f}")


def _render_hit_detail_panels(
    hits: list[dict[str, Any]],
    *,
    backend: str,
    show_full_runbooks: bool,
) -> None:
    runbook_hits = [
        hit
        for hit in hits
        if isinstance(hit, dict) and str(hit.get("record_type") or "") in _RUNBOOK_TYPES
    ]
    context_hits = [
        hit
        for hit in hits
        if isinstance(hit, dict) and str(hit.get("record_type") or "") in _CONTEXT_TYPES
    ]
    if context_hits:
        st.markdown("**Operational context**")
        for index, hit in enumerate(context_hits[:3]):
            render_operational_context_panel(hit, expanded=index == 0)
    if runbook_hits:
        st.markdown("**Related runbooks**")
        for index, hit in enumerate(runbook_hits[:3]):
            procedure_id = str(hit.get("source_record_id") or "").strip()
            runbook = load_runbook_with_images(backend, procedure_id) if procedure_id else {}
            score = hit.get("combined_score")
            if not runbook:
                title = hit.get("title") or procedure_id or "Runbook"
                with st.expander(f"Runbook — {title}", expanded=False):
                    snippet = str(hit.get("snippet") or "").strip()
                    if snippet:
                        st.write(snippet)
                continue
            render_runbook_panel(
                runbook,
                backend_url=backend,
                expanded=False,
                load_images=show_full_runbooks,
                score=float(score) if score is not None else None,
                detail_level="full" if show_full_runbooks else "summary",
            )


def _render_assistant_entry(
    entry: dict,
    *,
    backend: str,
    show_full_runbooks: bool,
) -> None:
    st.markdown(entry.get("text") or "")
    citations = _citations_from_entry(entry)
    hits = [hit for hit in list(entry.get("hits") or []) if isinstance(hit, dict)]
    answer_has_sources = "sources:" in str(entry.get("text") or "").lower()
    if (citations or hits) and not answer_has_sources:
        _render_sources_block(citations or _citations_from_entry({"hits": hits}))
    elif citations or hits:
        with st.expander("Source details", expanded=False):
            _render_sources_block(citations or _citations_from_entry({"hits": hits}))
    _render_hit_detail_panels(
        hits,
        backend=backend,
        show_full_runbooks=show_full_runbooks,
    )
    images = list(entry.get("canonical_images") or [])
    if images:
        render_canonical_images(
            images,
            backend_url=backend,
            heading="Reference images",
            as_expander=True,
            expanded=False,
        )


with conversation_tab:
    for entry in st.session_state.retrieve_history:
        with st.chat_message(entry["role"]):
            if entry["role"] == "assistant":
                _render_assistant_entry(
                    entry,
                    backend=backend_url,
                    show_full_runbooks=show_full_runbooks,
                )
            else:
                st.write(entry["text"])
    prompt = st.chat_input("Ask a question")
    if prompt:
        st.session_state.retrieve_history.append({"role": "user", "text": prompt})
        try:
            payload = post_retrieve(
                backend_url,
                query=prompt,
                session_id=st.session_state.retrieve_session_id,
                playbook_variant=variant,
                record_types=record_types,
            )
            hits = list(payload.get("hits") or [])
            citations = list(payload.get("citations") or [])
            for citation, hit in zip(citations, hits):
                if isinstance(citation, dict) and isinstance(hit, dict):
                    citation.setdefault("combined_score", hit.get("combined_score"))
            st.session_state.retrieve_history.append(
                {
                    "role": "assistant",
                    "text": payload.get("answer") or "",
                    "hits": hits,
                    "citations": citations,
                    "canonical_images": list(payload.get("canonical_images") or []),
                    "payload": payload,
                }
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
