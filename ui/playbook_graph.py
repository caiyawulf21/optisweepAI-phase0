"""Interactive playbook graph helpers for Streamlit."""

from __future__ import annotations

import html
from typing import Any, Callable

import streamlit as st


BRANCH_COLORS = {
    "healthy": {
        "bg": "#e8f6ee",
        "border": "#1f7a45",
        "text": "#14532d",
        "label": "#166534",
        "eyebrow": "Healthy",
    },
    "unhealthy": {
        "bg": "#fdecec",
        "border": "#b42318",
        "text": "#7f1d1d",
        "label": "#991b1b",
        "eyebrow": "Unhealthy",
    },
    "inconclusive": {
        "bg": "#fff7e6",
        "border": "#b45309",
        "text": "#7c2d12",
        "label": "#92400e",
        "eyebrow": "Inconclusive",
    },
    "unknown": {
        "bg": "#f1f5f9",
        "border": "#64748b",
        "text": "#334155",
        "label": "#475569",
        "eyebrow": "Other",
    },
}

BRANCH_ORDER = ("healthy", "unhealthy", "inconclusive")


def _inject_branch_button_css() -> None:
    if st.session_state.get("_branch_button_css"):
        return
    st.session_state["_branch_button_css"] = True
    st.markdown(
        """
<style>
div[data-testid="stVerticalBlock"]:has(span.branch-btn-healthy) button {
  background-color: #e8f6ee !important;
  border: 2px solid #1f7a45 !important;
  color: #14532d !important;
  font-weight: 700 !important;
}
div[data-testid="stVerticalBlock"]:has(span.branch-btn-unhealthy) button {
  background-color: #fdecec !important;
  border: 2px solid #b42318 !important;
  color: #7f1d1d !important;
  font-weight: 700 !important;
}
div[data-testid="stVerticalBlock"]:has(span.branch-btn-inconclusive) button {
  background-color: #fff7e6 !important;
  border: 2px solid #b45309 !important;
  color: #7c2d12 !important;
  font-weight: 700 !important;
}
div[data-testid="stVerticalBlock"]:has(span.branch-btn-unknown) button {
  background-color: #f1f5f9 !important;
  border: 2px solid #64748b !important;
  color: #334155 !important;
  font-weight: 700 !important;
}
</style>
""",
        unsafe_allow_html=True,
    )


def branch_color_key(answer: Any) -> str:
    key = str(answer or "").strip().lower()
    if key in BRANCH_COLORS:
        return key
    return "unknown"


def _evidence_summary(metrics: dict[str, Any] | None, label: str) -> str:
    if not isinstance(metrics, dict):
        return ""
    payload = metrics.get(label) if isinstance(metrics.get(label), dict) else {}
    return str((payload or {}).get("summary") or "").strip()


def _evidence_checks(metrics: dict[str, Any] | None, label: str) -> list[str]:
    if not isinstance(metrics, dict):
        return []
    payload = metrics.get(label) if isinstance(metrics.get(label), dict) else {}
    checks: list[str] = []
    for item in list((payload or {}).get("checks") or []):
        text = str(item or "").strip()
        if text:
            checks.append(text)
    return checks


def _shorten(text: str, limit: int = 110) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def render_node_evidence_panel(metrics: dict[str, Any] | None) -> None:
    """Scannable evidence criteria for the playbook node panel (healthy/unhealthy/inconclusive)."""
    if not isinstance(metrics, dict) or not metrics:
        return
    st.markdown("**Evidence criteria**")
    for label in BRANCH_ORDER:
        summary = _evidence_summary(metrics, label)
        checks = _evidence_checks(metrics, label)
        if not summary and not checks:
            continue
        colors = BRANCH_COLORS[label]
        body_parts: list[str] = []
        if summary:
            body_parts.append(html.escape(_shorten(summary, 280)))
        for check in checks[:4]:
            if summary and check == summary:
                continue
            body_parts.append(f"• {html.escape(_shorten(check, 220))}")
        body_html = "<br/>".join(body_parts)
        next_title = ""
        payload = metrics.get(label) if isinstance(metrics.get(label), dict) else {}
        if isinstance(payload, dict) and payload.get("next_node_title"):
            next_title = (
                f'<div style="color:{colors["text"]};font-size:0.78rem;margin-top:0.25rem;'
                f'opacity:0.85;">Next: {html.escape(str(payload.get("next_node_title")))}</div>'
            )
        st.markdown(
            f"""
<div style="
  border-left:4px solid {colors['border']};
  background:{colors['bg']};
  padding:0.45rem 0.7rem;
  margin:0.35rem 0;
  border-radius:0 8px 8px 0;
">
  <div style="font-weight:700;color:{colors['label']};font-size:0.8rem;
    text-transform:uppercase;letter-spacing:0.03em;">{html.escape(label)}</div>
  <div style="color:{colors['text']};font-size:0.9rem;line-height:1.35;margin-top:0.15rem;">
    {body_html}
  </div>
  {next_title}
</div>
""",
            unsafe_allow_html=True,
        )


def render_branch_evidence_strip(metrics: dict[str, Any] | None) -> None:
    """Short evidence block immediately above the branch buttons."""
    if not isinstance(metrics, dict) or not metrics:
        return
    cols = st.columns(3)
    for index, label in enumerate(BRANCH_ORDER):
        colors = BRANCH_COLORS[label]
        summary = _shorten(_evidence_summary(metrics, label) or f"Select {label}.", 100)
        with cols[index]:
            st.markdown(
                f"""
<div style="
  border-left:4px solid {colors['border']};
  background:{colors['bg']};
  padding:0.5rem 0.65rem;
  border-radius:0 8px 8px 0;
  min-height:4.6rem;
">
  <div style="font-weight:700;color:{colors['label']};font-size:0.75rem;
    text-transform:uppercase;letter-spacing:0.03em;">{html.escape(label)}</div>
  <div style="color:{colors['text']};font-size:0.82rem;line-height:1.3;margin-top:0.2rem;">
    {html.escape(summary)}
  </div>
</div>
""",
                unsafe_allow_html=True,
            )


def render_colored_branch_button(
    label: str,
    *,
    answer: Any,
    key: str,
    help_text: str | None = None,
) -> bool:
    """Render an st.button with branch-colored CSS."""
    _inject_branch_button_css()
    color_key = branch_color_key(answer)
    st.markdown(f'<span class="branch-btn-{color_key}"></span>', unsafe_allow_html=True)
    return st.button(
        label,
        key=key,
        use_container_width=True,
        help=help_text or None,
    )


def render_branch_choice_cards(metrics: dict[str, Any] | None) -> None:
    """Compatibility wrapper: scannable evidence criteria."""
    render_node_evidence_panel(metrics)


def render_branch_decision_controls(
    answers: list[Any],
    *,
    metrics: dict[str, Any] | None,
    button_key_fn: Callable[[int, Any], str],
    button_label_fn: Callable[[Any], str],
) -> Any | None:
    """Short evidence strip + thin colored buttons. Returns selected answer."""
    if not answers:
        return None
    _inject_branch_button_css()
    st.markdown("**Choose the matching outcome**")
    render_branch_evidence_strip(metrics)

    answer_by_key = {str(answer).strip().lower(): answer for answer in answers}
    ordered: list[Any] = [
        answer_by_key[label] for label in BRANCH_ORDER if label in answer_by_key
    ]
    for answer in answers:
        if answer not in ordered:
            ordered.append(answer)

    cols = st.columns(min(len(ordered), 3) or 1)
    selected: Any | None = None
    for index, answer in enumerate(ordered):
        label = str(answer).strip().lower()
        with cols[index % len(cols)]:
            help_text = _evidence_summary(metrics, label) or None
            if render_colored_branch_button(
                button_label_fn(answer),
                answer=answer,
                key=button_key_fn(index, answer),
                help_text=_shorten(help_text, 160) if help_text else None,
            ):
                selected = answer
    return selected


def _branch_targets(playbook: dict[str, Any]) -> dict[str, list[tuple[str, str]]]:
    edges: dict[str, list[tuple[str, str]]] = {}
    for branch in list(playbook.get("branches") or []):
        if not isinstance(branch, dict):
            continue
        source = str(branch.get("from_node_id") or branch.get("source_node_id") or "").strip()
        target = str(branch.get("to_node_id") or branch.get("target_node_id") or branch.get("next_node_id") or "").strip()
        outcome = str(branch.get("outcome") or branch.get("outcome_label") or "").strip() or "next"
        if source and target:
            edges.setdefault(source, []).append((outcome, target))
    for node in list(playbook.get("nodes") or []):
        if not isinstance(node, dict):
            continue
        source = str(node.get("node_id") or "")
        for branch in list(node.get("branches") or []):
            if not isinstance(branch, dict):
                continue
            target = str(
                branch.get("next_node_id")
                or branch.get("to_node_id")
                or branch.get("target_node_id")
                or ""
            ).strip()
            outcome = str(branch.get("outcome") or branch.get("condition_label") or "").strip() or "next"
            if source and target:
                edges.setdefault(source, []).append((outcome, target))
        for item in list(node.get("decision_outcomes") or []):
            if not isinstance(item, dict):
                continue
            if str(item.get("source") or "") == "runbook_step":
                continue
            target = str(item.get("next_node_id") or "").strip()
            outcome = str(item.get("outcome_label") or "").strip() or "next"
            if source and target:
                edges.setdefault(source, []).append((outcome, target))
    return edges


def _node_popup(node: dict[str, Any], metrics: dict[str, Any] | None) -> None:
    @st.dialog(str(node.get("title") or node.get("node_id") or "Playbook node"))
    def _dialog() -> None:
        st.caption(
            " · ".join(
                part
                for part in [
                    f"id `{node.get('node_id')}`" if node.get("node_id") else "",
                    str(node.get("node_type") or ""),
                    f"order {node.get('node_order')}" if node.get("node_order") is not None else "",
                ]
                if part
            )
        )
        if node.get("intent") or node.get("goal"):
            st.write(node.get("intent") or node.get("goal"))
        if node.get("stop_or_escalation_note"):
            st.markdown("**Stop / escalate**")
            st.write(node.get("stop_or_escalation_note"))
        roles = list(node.get("allowed_roles") or [])
        if roles:
            st.caption("Allowed roles: " + ", ".join(str(item) for item in roles))
        render_node_evidence_panel(metrics if isinstance(metrics, dict) else None)

    _dialog()


def render_playbook_graph(
    playbook: dict[str, Any] | None,
    *,
    current_node_id: str | None = None,
    key_prefix: str = "pbgraph",
) -> None:
    if not isinstance(playbook, dict):
        return
    nodes = [
        item
        for item in list(playbook.get("nodes") or [])
        if isinstance(item, dict) and item.get("node_id")
    ]
    if not nodes:
        return
    nodes = sorted(nodes, key=lambda item: int(item.get("node_order") or 999))
    edges = _branch_targets(playbook)
    title_by_id = {
        str(item.get("node_id")): str(item.get("title") or item.get("node_id"))
        for item in nodes
    }
    st.markdown("**Playbook graph**")
    st.caption("Click a node to open its full details.")

    chip_html = ['<div style="display:flex;flex-wrap:wrap;gap:0.55rem;align-items:stretch;">']
    for node in nodes:
        node_id = str(node.get("node_id"))
        active = str(current_node_id or "") == node_id
        border = "#2563eb" if active else "#94a3b8"
        background = "#eff6ff" if active else "#f8fafc"
        title = html.escape(str(node.get("title") or node_id)[:72])
        order = html.escape(str(node.get("node_order") or ""))
        outs = edges.get(node_id) or []
        edge_bits = ", ".join(
            f"{html.escape(outcome)}→{html.escape(str(title_by_id.get(target) or target)[:40])}"
            for outcome, target in outs[:4]
        )
        chip_html.append(
            f"""
<div style="
  flex:1 1 220px;
  max-width:280px;
  background:{background};
  border:2px solid {border};
  border-radius:12px;
  padding:0.7rem 0.8rem;
">
  <div style="font-size:0.75rem;color:#64748b;">Node {order}</div>
  <div style="font-weight:650;color:#0f172a;margin-top:0.15rem;">{title}</div>
  <div style="font-size:0.75rem;color:#475569;margin-top:0.35rem;">{edge_bits or "terminal / no mapped branch"}</div>
</div>
"""
        )
    chip_html.append("</div>")
    st.markdown("".join(chip_html), unsafe_allow_html=True)

    cols = st.columns(min(4, len(nodes)) or 1)
    for index, node in enumerate(nodes):
        node_id = str(node.get("node_id"))
        label = str(node.get("title") or node_id)
        if len(label) > 34:
            label = label[:31] + "…"
        with cols[index % len(cols)]:
            if st.button(
                label,
                key=f"{key_prefix}-{node_id}",
                use_container_width=True,
                type="primary" if str(current_node_id or "") == node_id else "secondary",
            ):
                from playbook_ui import branch_qualification_metrics

                _node_popup(node, branch_qualification_metrics(node, playbook=playbook))
