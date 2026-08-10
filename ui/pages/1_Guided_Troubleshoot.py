from __future__ import annotations

import os
import uuid
from typing import Any

import requests
import streamlit as st

from playbook_graph import (
    render_branch_decision_controls,
    render_node_evidence_panel,
    render_playbook_graph,
)
from playbook_ui import (
    append_retrieve_history_entry,
    build_search_context_from_troubleshoot,
    enrich_troubleshoot_payload,
    get_interactions,
    get_playbook_viewer,
    get_runbook_viewer,
    post_retrieve,
    post_troubleshoot,
    render_playbook_node_fields,
    render_retrieve_assistant_entry,
    render_runbook_panel,
)
from branding import apply_fortna_theme, render_brand_banner
from streamlit_helpers import (
    allowed_answers_with_unknown,
    answer_button_key,
    derive_progress_label,
    display_answer_label,
    format_signal_badges,
    is_latest_assistant_turn,
    select_confidence_value,
)


DEFAULT_BACKEND = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _ensure_session() -> None:
    if "troubleshoot_session_id" not in st.session_state:
        st.session_state.troubleshoot_session_id = f"ts-{uuid.uuid4().hex[:12]}"
    if "troubleshoot_history" not in st.session_state:
        st.session_state.troubleshoot_history = []
    if "troubleshoot_last" not in st.session_state:
        st.session_state.troubleshoot_last = {}
    if "search_chat_session_id" not in st.session_state:
        st.session_state.search_chat_session_id = (
            f"{st.session_state.troubleshoot_session_id}-search"
        )
    if "search_chat_history" not in st.session_state:
        st.session_state.search_chat_history = []
    if "search_chat_last" not in st.session_state:
        st.session_state.search_chat_last = {}
    if "search_chat_bridge_events" not in st.session_state:
        st.session_state.search_chat_bridge_events = []
    if "show_search_chat_panel" not in st.session_state:
        st.session_state.show_search_chat_panel = True


def _reset_troubleshoot_session() -> None:
    st.session_state.troubleshoot_session_id = f"ts-{uuid.uuid4().hex[:12]}"
    st.session_state.troubleshoot_history = []
    st.session_state.troubleshoot_last = {}
    st.session_state.search_chat_session_id = (
        f"{st.session_state.troubleshoot_session_id}-search"
    )
    st.session_state.search_chat_history = []
    st.session_state.search_chat_last = {}
    st.session_state.search_chat_bridge_events = []


def _submit_user_message(backend_url: str, message: str, variant: str) -> None:
    st.session_state.troubleshoot_history.append({"role": "user", "text": message})
    payload = post_troubleshoot(
        backend_url,
        session_id=st.session_state.troubleshoot_session_id,
        user_message=message,
        playbook_variant=variant,
    )
    try:
        payload = enrich_troubleshoot_payload(
            payload, backend_url=backend_url, variant=variant
        )
    except Exception:
        pass
    st.session_state.troubleshoot_last = payload
    st.session_state.troubleshoot_history.append(
        {"role": "assistant", "text": payload.get("final_response") or "", "payload": payload}
    )


def _submit_search_message(backend_url: str, message: str, variant: str) -> None:
    search_context = build_search_context_from_troubleshoot(
        st.session_state.troubleshoot_last,
        session_id=st.session_state.troubleshoot_session_id,
    )
    payload = post_retrieve(
        backend_url,
        query=message,
        session_id=st.session_state.search_chat_session_id,
        playbook_variant=variant,
        search_context=search_context or None,
    )
    append_retrieve_history_entry(
        st.session_state.search_chat_history,
        query=message,
        payload=payload,
    )
    st.session_state.search_chat_last = payload


def _apply_bridge_to_playbook(backend_url: str, value: str, variant: str) -> None:
    st.session_state.search_chat_bridge_events.append(
        {
            "value": value,
            "session_id": st.session_state.troubleshoot_session_id,
            "search_session_id": st.session_state.search_chat_session_id,
            "node_id": (
                ((st.session_state.troubleshoot_last or {}).get("workflow_state") or {}).get(
                    "current_node_id"
                )
            ),
        }
    )
    _submit_user_message(backend_url, value, variant)


def _render_branch_metrics(metrics: dict[str, Any] | None) -> None:
    render_node_evidence_panel(metrics)


def _render_playbook_panel(
    payload: dict[str, Any],
    *,
    expanded: bool,
    backend_url: str | None = None,
    variant: str = "prompt_a",
) -> None:
    del backend_url, variant
    workflow = payload.get("workflow_state") or {}
    title = workflow.get("playbook_title") or (payload.get("workflow") or {}).get("title")
    playbook_id = workflow.get("playbook_id") or payload.get("selected_workflow_id")
    if not title and not playbook_id:
        return
    heading = f"Playbook — {title or playbook_id}"
    with st.expander(heading, expanded=expanded):
        node = workflow.get("current_node") or {}
        guided = payload.get("guided_question") or {}
        if not isinstance(node, dict) or not (node.get("title") or node.get("node_id")):
            if guided.get("node_id") and guided.get("node_id") != "playbook_candidate_select":
                node = {
                    "node_id": guided.get("node_id"),
                    "title": guided.get("question") or guided.get("node_id"),
                    "intent": payload.get("final_response"),
                    "branch_qualification_metrics": guided.get("branch_qualification_metrics"),
                }
        node_id = ""
        node_title = ""
        node_order = None
        if isinstance(node, dict):
            node_id = str(node.get("node_id") or workflow.get("current_node_id") or "").strip()
            node_title = str(node.get("title") or node_id).strip()
            node_order = node.get("node_order")
        if node_title or node_id:
            order_prefix = f"Node {node_order} — " if node_order is not None else ""
            st.markdown(f"**{order_prefix}{node_title or node_id}**")
            if node_id and node_id != node_title:
                st.caption(f"`{node_id}`")
        else:
            st.caption("No current node selected.")
            return
        if isinstance(node, dict):
            if node.get("node_type"):
                st.caption(f"Type: {node.get('node_type')}")
            render_playbook_node_fields(node)
            if node.get("stop_or_escalation_note"):
                st.caption(f"Stop/escalate: {node.get('stop_or_escalation_note')}")
            metrics = node.get("branch_qualification_metrics")
            if not isinstance(metrics, dict):
                metrics = guided.get("branch_qualification_metrics")
            if isinstance(metrics, dict):
                _render_branch_metrics(metrics)


def _render_observed_signals(payload: dict[str, Any]) -> None:
    observed = payload.get("extracted_observed_signals") or {}
    badges = format_signal_badges(observed)
    if not badges:
        return
    true_labels = [badge["signal"] for badge in badges if badge.get("value")]
    if true_labels:
        st.caption("Observed signals: " + ", ".join(true_labels))


def _render_confidence(payload: dict[str, Any]) -> None:
    confidence = payload.get("retrieval_confidence")
    reason = payload.get("retrieval_confidence_reason") or (
        (payload.get("workflow_state") or {}).get("retrieval_confidence_reason")
    )
    if confidence is None:
        selected = select_confidence_value(payload)
        if selected:
            st.caption(
                f"{selected['source'].title()}: {float(selected['confidence']):.2f}"
            )
        if reason:
            st.caption(str(reason))
        return
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return
    if value <= 0.0 and not payload.get("selected_workflow_id") and not reason:
        return
    st.caption(f"Retrieval confidence: {value:.2f}")
    if reason:
        st.caption(str(reason))
    if payload.get("response_type") == "playbook_candidates":
        return
    results = payload.get("retrieval_results") or []
    if results:
        top = results[0]
        st.caption(
            f"Top hit: `{top.get('title') or top.get('record_id')}` "
            f"({float(top.get('confidence') or 0.0):.2f})"
        )


def _render_runbook(
    payload: dict[str, Any],
    *,
    backend_url: str,
    expanded: bool,
    load_images: bool = True,
) -> None:
    workflow = payload.get("workflow_state") or {}
    runbooks = [
        item
        for item in list(workflow.get("runbooks") or [])
        if isinstance(item, dict)
        and (item.get("title") or item.get("procedure_id") or item.get("steps"))
    ]
    if not runbooks:
        primary = workflow.get("runbook") or {}
        if isinstance(primary, dict) and (
            primary.get("title") or primary.get("procedure_id") or primary.get("steps")
        ):
            runbooks = [primary]
    for index, runbook in enumerate(runbooks):
        prefix = "Runbook" if len(runbooks) == 1 else f"Runbook {index + 1}"
        render_runbook_panel(
            runbook,
            backend_url=backend_url,
            expanded=expanded and index == 0,
            load_images=load_images,
            heading_prefix=prefix,
        )


def _render_candidates(payload: dict[str, Any]) -> None:
    workflow = payload.get("workflow_state") or {}
    candidates = list(workflow.get("playbook_candidates") or [])
    correlated = list(workflow.get("correlated_symptoms") or [])
    if correlated:
        with st.expander("Correlated symptoms to check", expanded=False):
            for symptom in correlated[:8]:
                st.write(f"- {symptom}")
    if not candidates:
        return
    st.markdown("**Candidate playbooks** — select one that matches the site report")
    for candidate in candidates:
        title = candidate.get("title") or candidate.get("playbook_id")
        score = float(candidate.get("score") or 0.0)
        incidence_id = candidate.get("incidence_id") or candidate.get("case_id") or "n/a"
        st.markdown(f"- **{title}** (score {score:.2f}, incidence `{incidence_id}`)")
        incidence_summary = candidate.get("incidence_summary") or candidate.get("summary")
        if incidence_summary:
            st.caption(f"Incidence: {incidence_summary}")
        when_to_choose = candidate.get("when_to_choose")
        if when_to_choose:
            st.caption(f"When to choose: {when_to_choose}")
        symptoms = candidate.get("observed_entry_symptoms") or []
        if symptoms and not when_to_choose:
            st.caption("Entry symptoms: " + "; ".join(str(s) for s in symptoms[:6]))


def _render_playbook_conversation(*, backend_url: str, variant: str) -> None:
    history = st.session_state.troubleshoot_history
    for index, entry in enumerate(history):
        with st.chat_message(entry["role"]):
            st.write(entry["text"])
            payload = entry.get("payload") if entry.get("role") == "assistant" else None
            if not isinstance(payload, dict):
                continue
            latest = is_latest_assistant_turn(history, index)
            if latest and (
                payload.get("selected_workflow_id")
                or (payload.get("workflow_state") or {}).get("playbook_id")
            ):
                try:
                    payload = enrich_troubleshoot_payload(
                        payload, backend_url=backend_url, variant=variant
                    )
                    history[index]["payload"] = payload
                    st.session_state.troubleshoot_last = payload
                except Exception:
                    pass
            _render_observed_signals(payload)
            _render_confidence(payload)
            if payload.get("response_type") == "playbook_candidates":
                _render_candidates(payload)
            _render_playbook_panel(
                payload,
                expanded=latest,
                backend_url=backend_url,
                variant=variant,
            )
            _render_runbook(
                payload,
                backend_url=backend_url,
                expanded=False,
                load_images=latest,
            )
            guided = payload.get("guided_question") or {}
            raw_answers = list(guided.get("allowed_answers") or [])
            add_unknown = guided.get("mode") != "playbook_candidates"
            answers = (
                allowed_answers_with_unknown(raw_answers)
                if add_unknown
                else [str(item) for item in raw_answers if str(item).strip()]
            )
            if guided and latest:
                if guided.get("mode") != "playbook_candidates":
                    metrics = guided.get("branch_qualification_metrics")
                    if not isinstance(metrics, dict):
                        metrics = (
                            (payload.get("workflow_state") or {}).get("current_node") or {}
                        ).get("branch_qualification_metrics")
                    branch_options = list(guided.get("branch_options") or [])
                    del branch_options

                    def _button_key(answer_index: int, answer: Any) -> str:
                        return answer_button_key(
                            "branch",
                            index,
                            guided.get("node_id"),
                            answer_index,
                            answer,
                        )

                    def _button_label(answer: Any) -> str:
                        return display_answer_label(answer)

                    selected = render_branch_decision_controls(
                        answers,
                        metrics=metrics if isinstance(metrics, dict) else None,
                        button_key_fn=_button_key,
                        button_label_fn=_button_label,
                    )
                    if selected is not None:
                        try:
                            _submit_user_message(backend_url, str(selected), variant)
                            st.rerun()
                        except requests.RequestException as exc:
                            st.error(str(exc))
                else:
                    st.markdown("**Select playbook**")
                    cols = st.columns(min(len(answers), 3) or 1)
                    for answer_index, answer in enumerate(answers):
                        with cols[answer_index % len(cols)]:
                            if st.button(
                                display_answer_label(answer),
                                key=answer_button_key(
                                    "branch",
                                    index,
                                    guided.get("node_id"),
                                    answer_index,
                                    answer,
                                ),
                                use_container_width=True,
                            ):
                                try:
                                    _submit_user_message(backend_url, str(answer), variant)
                                    st.rerun()
                                except requests.RequestException as exc:
                                    st.error(str(exc))
            elif guided.get("allowed_answers"):
                metrics = guided.get("branch_qualification_metrics")
                if isinstance(metrics, dict):
                    _render_branch_metrics(metrics)
                else:
                    st.caption(
                        "Branch choices: "
                        + ", ".join(str(item) for item in guided.get("allowed_answers") or [])
                    )
            if payload.get("workflow_step") and not guided:
                ws = payload["workflow_step"]
                st.info(f"Node {ws.get('node_id')} — {ws.get('instruction')}")
    prompt = st.chat_input("Describe the issue or answer the current playbook step")
    if prompt:
        try:
            _submit_user_message(backend_url, prompt, variant)
            st.rerun()
        except requests.RequestException as exc:
            st.error(str(exc))


def _render_search_chat_panel(*, backend_url: str, variant: str) -> None:
    st.markdown("#### Search / Ask OptiSweep AI")
    context = build_search_context_from_troubleshoot(
        st.session_state.troubleshoot_last,
        session_id=st.session_state.troubleshoot_session_id,
    )
    if context.get("current_node_title") or context.get("active_playbook_id"):
        bits = []
        if context.get("playbook_title") or context.get("active_playbook_id"):
            bits.append(str(context.get("playbook_title") or context.get("active_playbook_id")))
        if context.get("current_node_title"):
            bits.append(str(context.get("current_node_title")))
        st.caption("Context: " + " · ".join(bits))
    else:
        st.caption("Ask corpus questions anytime — context attaches once a playbook is active.")

    history = st.session_state.search_chat_history
    if not history:
        st.caption(
            "Examples: How do I check this in RMS? · What should this value look like? · "
            "Where is this screen in Ignition?"
        )
    for index, entry in enumerate(history):
        with st.chat_message(entry["role"]):
            if entry["role"] != "assistant":
                st.write(entry["text"])
                continue
            bridge = render_retrieve_assistant_entry(
                entry,
                backend=backend_url,
                show_full_runbooks=False,
                key_prefix=f"embedded-search-{index}",
                playbook_variant=variant,
                load_images=True,
            )
            latest = index == len(history) - 1
            if latest and bridge and bridge.get("value"):
                label = f"Use this result in current troubleshooting step (`{bridge['value']}`)"
                if st.button(label, key=f"search-bridge-{index}-{bridge['value']}"):
                    try:
                        _apply_bridge_to_playbook(backend_url, str(bridge["value"]), variant)
                        st.rerun()
                    except requests.RequestException as exc:
                        st.error(str(exc))

    with st.form("embedded_search_chat_form", clear_on_submit=True):
        question = st.text_area(
            "Ask OptiSweep AI",
            height=80,
            placeholder="Ask without leaving the playbook…",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Ask", use_container_width=True)
    if submitted and str(question or "").strip():
        try:
            _submit_search_message(backend_url, str(question).strip(), variant)
            st.rerun()
        except requests.RequestException as exc:
            st.error(str(exc))


def _render_turns(backend_url: str, session_id: str) -> None:
    interactions = get_interactions(backend_url, session_id, surface="troubleshoot")
    if not interactions:
        st.caption("No turns logged yet.")
        return
    for idx, item in enumerate(interactions, start=1):
        trace = item.get("runtime_trace") or {}
        agents = trace.get("agents") or []
        title = f"Turn {idx}: {item.get('response_type', 'answer')}"
        with st.expander(title, expanded=idx == len(interactions)):
            st.write("**User:**", item.get("user_message") or "")
            st.write("**Assistant:**", item.get("final_response") or "")
            if agents:
                st.caption("Agent steps")
                for step in agents:
                    st.write(f"- `{step.get('agent')}` → {step.get('action')}")


def _render_viewer(backend_url: str, last: dict[str, Any], variant: str) -> None:
    workflow = last.get("workflow_state") or {}
    playbook_id = workflow.get("playbook_id")
    if not playbook_id:
        st.caption("No active playbook to inspect.")
        return
    viewer = get_playbook_viewer(backend_url, playbook_id, variant)
    payload = viewer.get("payload") or {}
    nodes = list(payload.get("nodes") or [])
    node_ids = [str(node.get("node_id")) for node in nodes]
    current = workflow.get("current_node_id") or (node_ids[0] if node_ids else None)
    render_playbook_graph(
        payload if isinstance(payload, dict) else None,
        current_node_id=str(current or ""),
        key_prefix=f"viewer-{playbook_id}",
    )
    selected = st.selectbox("Node", node_ids, index=node_ids.index(current) if current in node_ids else 0)
    node = next((item for item in nodes if str(item.get("node_id")) == selected), {})
    st.subheader(node.get("title") or selected)
    render_playbook_node_fields(node if isinstance(node, dict) else {})
    current_from_payload = workflow.get("current_node") or {}
    metrics = None
    if str(current_from_payload.get("node_id")) == str(selected):
        metrics = current_from_payload.get("branch_qualification_metrics")
    if not isinstance(metrics, dict) and isinstance(node, dict):
        from playbook_ui import branch_qualification_metrics

        metrics = branch_qualification_metrics(node, playbook=payload if isinstance(payload, dict) else None)
    if isinstance(metrics, dict):
        _render_branch_metrics(metrics)
    link = requests.get(
        f"{backend_url}/corpus/playbooks/{playbook_id}/nodes/{selected}/runbook",
        params={"variant": variant},
        timeout=60,
    )
    procedure_ids: list[str] = []
    if link.ok:
        payload_link = link.json() or {}
        for procedure in list(payload_link.get("procedure_ids") or []):
            value = str(procedure or "").strip()
            if value and value not in procedure_ids:
                procedure_ids.append(value)
        fallback = str(payload_link.get("procedure_id") or "").strip()
        if fallback and fallback not in procedure_ids:
            procedure_ids.append(fallback)
    if not procedure_ids and str(current or "") == str(selected):
        for item in list(workflow.get("runbooks") or []):
            if isinstance(item, dict):
                procedure = str(item.get("procedure_id") or "").strip()
                if procedure and procedure not in procedure_ids:
                    procedure_ids.append(procedure)
        primary = str((workflow.get("runbook") or {}).get("procedure_id") or "").strip()
        if primary and primary not in procedure_ids:
            procedure_ids.insert(0, primary)
    for index, procedure_id in enumerate(procedure_ids):
        runbook_view = get_runbook_viewer(backend_url, procedure_id)
        runbook = runbook_view.get("payload") or {}
        images_resp = requests.get(
            f"{backend_url}/corpus/runbooks/{procedure_id}/images",
            timeout=60,
        )
        step_images = {}
        if images_resp.ok:
            for row in list((images_resp.json() or {}).get("steps") or []):
                if isinstance(row, dict):
                    step_images[str(row.get("step_number"))] = row
        if isinstance(runbook, dict) and step_images:
            merged_steps = []
            for step in list(runbook.get("steps") or []):
                if not isinstance(step, dict):
                    continue
                row = step_images.get(str(step.get("step_number"))) or {}
                merged = dict(step)
                if not merged.get("images"):
                    merged["images"] = list(row.get("images") or [])
                if not merged.get("screens_or_images"):
                    merged["screens_or_images"] = list(row.get("screens_or_images") or [])
                merged_steps.append(merged)
            runbook = {**runbook, "steps": merged_steps}
        prefix = "Runbook" if len(procedure_ids) == 1 else f"Runbook {index + 1}"
        render_runbook_panel(
            runbook if isinstance(runbook, dict) else {},
            backend_url=backend_url,
            expanded=index == 0,
            load_images=True,
            heading_prefix=prefix,
        )


st.set_page_config(page_title="Guided Troubleshoot", layout="wide")
apply_fortna_theme()
render_brand_banner("Guided Troubleshoot")
_ensure_session()
st.title("Guided Troubleshoot")

with st.sidebar:
    backend_url = st.text_input("Backend URL", value=DEFAULT_BACKEND)
    variant = st.radio("Prompt variant", ["prompt_a", "prompt_b"], horizontal=True)
    st.session_state.show_search_chat_panel = st.checkbox(
        "Show Search Chat panel",
        value=bool(st.session_state.show_search_chat_panel),
    )
    if st.button("New troubleshoot session"):
        _reset_troubleshoot_session()
        st.rerun()
    st.caption(f"Session: `{st.session_state.troubleshoot_session_id}`")
    st.caption(f"Search Chat: `{st.session_state.search_chat_session_id}`")
    last = st.session_state.troubleshoot_last or {}
    workflow = last.get("workflow_state") if isinstance(last.get("workflow_state"), dict) else {}
    summary = last.get("workflow") if isinstance(last.get("workflow"), dict) else {}
    playbook_title = (
        workflow.get("playbook_title")
        or summary.get("title")
        or last.get("selected_workflow_id")
    )
    playbook_id = workflow.get("playbook_id") or last.get("selected_workflow_id")
    current_node = workflow.get("current_node") if isinstance(workflow.get("current_node"), dict) else {}
    node_title = current_node.get("title") or summary.get("current_node_id") or workflow.get(
        "current_node_id"
    )
    progress = derive_progress_label(summary)
    st.markdown("**Active playbook**")
    if playbook_title or playbook_id:
        st.write(str(playbook_title or playbook_id))
        if playbook_id and str(playbook_title or "") != str(playbook_id):
            st.caption(f"id `{playbook_id}`")
        if node_title:
            st.caption(f"Current node: {node_title}")
        if progress:
            st.caption(progress)
    else:
        st.caption("No playbook selected yet")
    st.caption(
        "Search Chat uses `POST /retrieve` with compact playbook context. "
        "It never advances playbook nodes unless you confirm **Use this result**."
    )

conversation_tab, turns_tab, viewer_tab, trace_tab = st.tabs(
    ["Conversation", "Turns", "Playbook / Runbook", "Trace"]
)

with conversation_tab:
    if st.session_state.show_search_chat_panel:
        playbook_col, search_col = st.columns([1.55, 1], gap="large")
        with playbook_col:
            st.markdown("#### Troubleshooting Playbook")
            _render_playbook_conversation(backend_url=backend_url, variant=variant)
        with search_col:
            _render_search_chat_panel(backend_url=backend_url, variant=variant)
    else:
        st.markdown("#### Troubleshooting Playbook")
        _render_playbook_conversation(backend_url=backend_url, variant=variant)

with turns_tab:
    _render_turns(backend_url, st.session_state.troubleshoot_session_id)
    st.divider()
    st.markdown("**Search Chat turns**")
    search_interactions = get_interactions(
        backend_url,
        st.session_state.search_chat_session_id,
        surface="retrieve",
    )
    if not search_interactions:
        st.caption("No Search Chat turns logged yet.")
    else:
        for idx, item in enumerate(search_interactions, start=1):
            with st.expander(f"Search turn {idx}", expanded=idx == len(search_interactions)):
                st.write("**User:**", item.get("user_message") or "")
                st.write("**Assistant:**", item.get("final_response") or "")

with viewer_tab:
    _render_viewer(backend_url, st.session_state.troubleshoot_last, variant)

with trace_tab:
    last = st.session_state.troubleshoot_last or {}
    if last:
        hits = list(last.get("retrieval_results") or [])
        top = hits[0] if hits and isinstance(hits[0], dict) else None
        agents = ((last.get("runtime_trace") or {}).get("agents") or [])
        score_steps = [
            step
            for step in agents
            if isinstance(step, dict)
            and any(key in step for key in ("cosine", "jaccard", "symptom", "coverage", "combined"))
        ]
        breakdown_source = score_steps[-1] if score_steps else None
        cosine = (breakdown_source or {}).get("cosine")
        jaccard = (breakdown_source or {}).get("jaccard")
        symptom = (breakdown_source or {}).get("symptom")
        coverage = (breakdown_source or {}).get("coverage")
        combined = (breakdown_source or {}).get("combined")
        if top:
            if cosine is None:
                cosine = top.get("cosine_score")
            if jaccard is None:
                jaccard = top.get("jaccard_score")
            if symptom is None:
                symptom = top.get("symptom_score")
            if coverage is None:
                coverage = top.get("coverage")
            if combined is None:
                combined = top.get("combined_score", top.get("confidence"))
        if any(value is not None for value in (cosine, jaccard, symptom, coverage, combined)):
            st.markdown("**Score breakdown** (rank ≠ pin confidence)")
            cols = st.columns(5)
            cols[0].metric("cosine", f"{float(cosine or 0):.3f}")
            cols[1].metric("jaccard", f"{float(jaccard or 0):.3f}")
            cols[2].metric("symptom", f"{float(symptom or 0):.3f}")
            cols[3].metric("coverage", f"{float(coverage or 0):.3f}")
            cols[4].metric("combined", f"{float(combined or 0):.3f}")
            st.caption(
                "Auto-pin requires combined ≥ PLAYBOOK_MATCH_THRESHOLD (~0.80) and coverage ≥ "
                "PLAYBOOK_PIN_COVERAGE_THRESHOLD (~0.40). Candidate pick is the default path."
            )
        st.json(last)
    search_last = st.session_state.search_chat_last or {}
    if search_last:
        st.markdown("**Search Chat last response**")
        st.json(search_last)
    if st.session_state.search_chat_bridge_events:
        st.markdown("**Confirmed Search → Playbook bridge events**")
        st.json(st.session_state.search_chat_bridge_events)
