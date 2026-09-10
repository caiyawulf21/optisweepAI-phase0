"""Shared Streamlit helpers for playbook runtime UI."""

from __future__ import annotations

import html
import re
from typing import Any

import requests
import streamlit as st

_GENERIC_OUTCOME_SUMMARY_RE = re.compile(
    r"^(?:select\s+\w+\s+for this check\.?|"
    r"checks for\s+.+?(?:do not indicate|indicate)\s+the fault condition)",
    re.IGNORECASE | re.DOTALL,
)
_EXPECTED_EVIDENCE_SEGMENT_RE = re.compile(
    r"(?P<label>Unhealthy|Healthy|Inconclusive)"
    r"(?:\s+or\s+(?:narrower|healthy|unhealthy|inconclusive))*"
    r"\s+(?:evidence|state|result|condition|path)?\s*"
    r"(?:includes?|would\s+(?:show|indicate)|(?:is|means|would be)|:)?\s*"
    r"(?P<body>.+?)(?=(?:Unhealthy|Healthy|Inconclusive)\b|$)",
    re.IGNORECASE | re.DOTALL,
)
_DEFAULT_INCONCLUSIVE_EVIDENCE = (
    "Evidence is missing, conflicting, or incomplete — you cannot confidently "
    "decide healthy vs unhealthy for this check yet."
)


def parse_expected_outcome_evidence(expected: Any) -> dict[str, str]:
    """Split expected_or_observed_result into per-outcome evidence strings."""
    text = str(expected or "").strip()
    if not text:
        return {}
    parsed: dict[str, str] = {}
    for match in _EXPECTED_EVIDENCE_SEGMENT_RE.finditer(text):
        label = str(match.group("label") or "").strip().lower()
        body = re.sub(r"\s+", " ", str(match.group("body") or "").strip(" .;,"))
        if label in {"healthy", "unhealthy", "inconclusive"} and body:
            parsed.setdefault(label, body)
    return parsed


def _is_generic_outcome_summary(text: Any) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    if _GENERIC_OUTCOME_SUMMARY_RE.match(value):
        return True
    return len(parse_expected_outcome_evidence(value)) >= 2


def _node_title_index(playbook: dict[str, Any] | None) -> dict[str, str]:
    titles: dict[str, str] = {}
    for item in list((playbook or {}).get("nodes") or []):
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("node_id") or "").strip()
        if node_id:
            titles[node_id] = str(item.get("title") or node_id).strip() or node_id
    return titles


def _branch_destination_map(
    node: dict[str, Any],
    playbook: dict[str, Any] | None = None,
) -> dict[str, str]:
    destinations: dict[str, str] = {}

    def add(label: Any, next_node_id: Any) -> None:
        key = str(label or "").strip().lower()
        destination = str(next_node_id or "").strip()
        if key and destination and key not in destinations:
            destinations[key] = destination

    for branch in node.get("branches") or []:
        if not isinstance(branch, dict):
            continue
        add(
            branch.get("outcome") or branch.get("condition_label"),
            branch.get("next_node_id")
            or branch.get("to_node_id")
            or branch.get("target_node_id"),
        )
    node_id = str(node.get("node_id") or "").strip()
    if node_id:
        for branch in list((playbook or {}).get("branches") or []):
            if not isinstance(branch, dict):
                continue
            source = str(
                branch.get("from_node_id") or branch.get("source_node_id") or ""
            ).strip()
            if source and source != node_id:
                continue
            add(
                branch.get("outcome") or branch.get("condition_label"),
                branch.get("next_node_id")
                or branch.get("to_node_id")
                or branch.get("target_node_id"),
            )
    for item in node.get("decision_outcomes") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("source") or "") == "runbook_step":
            continue
        add(item.get("outcome_label"), item.get("next_node_id"))
    return destinations


def branch_qualification_metrics(
    node: dict[str, Any] | None,
    runbook: dict[str, Any] | None = None,
    playbook: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del runbook
    metrics: dict[str, dict[str, Any]] = {
        "healthy": {"summary": None, "checks": [], "next_node_id": None, "next_node_title": None},
        "unhealthy": {"summary": None, "checks": [], "next_node_id": None, "next_node_title": None},
        "inconclusive": {
            "summary": None,
            "checks": [],
            "next_node_id": None,
            "next_node_title": None,
        },
    }
    node = node if isinstance(node, dict) else {}
    titles = _node_title_index(playbook)
    for item in node.get("decision_outcomes") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("source") or "") == "runbook_step":
            continue
        label = str(item.get("outcome_label") or "").strip().lower()
        if label not in metrics:
            continue
        text = str(item.get("descriptor") or item.get("observable_signal") or "").strip()
        if text and not metrics[label]["summary"]:
            metrics[label]["summary"] = text
        next_node_id = str(item.get("next_node_id") or "").strip() or None
        if next_node_id and not metrics[label]["next_node_id"]:
            metrics[label]["next_node_id"] = next_node_id
            metrics[label]["next_node_title"] = titles.get(next_node_id) or next_node_id
    for option in branch_options_from_node(node, playbook):
        label = str(option.get("label") or "").strip().lower()
        if label not in metrics:
            continue
        if option.get("next_node_id") and not metrics[label]["next_node_id"]:
            metrics[label]["next_node_id"] = option.get("next_node_id")
            metrics[label]["next_node_title"] = option.get("next_node_title")
    indicator_keys = {
        "healthy": "healthy_indicators",
        "unhealthy": "unhealthy_indicators",
        "inconclusive": "inconclusive_indicators",
    }
    for label, key in indicator_keys.items():
        checks = [
            str(item).strip()
            for item in list(node.get(key) or [])
            if str(item).strip()
        ]
        if checks:
            metrics[label]["checks"] = checks
            current = metrics[label]["summary"]
            if not current or _is_generic_outcome_summary(current):
                metrics[label]["summary"] = (
                    checks[0] if len(checks) == 1 else "; ".join(checks[:2])
                )
    expected = str(node.get("expected_or_observed_result") or "").strip()
    parsed = parse_expected_outcome_evidence(expected)
    for label in ("healthy", "unhealthy", "inconclusive"):
        current = metrics[label]["summary"]
        if current and not _is_generic_outcome_summary(current):
            continue
        if parsed.get(label):
            metrics[label]["summary"] = parsed[label]
        elif label == "inconclusive":
            metrics[label]["summary"] = _DEFAULT_INCONCLUSIVE_EVIDENCE
        else:
            metrics[label]["summary"] = f"Select {label} for this check."
    return metrics


def _as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple)):
        items: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = str(
                    item.get("text")
                    or item.get("field")
                    or item.get("name")
                    or item.get("quote_or_summary")
                    or item.get("title")
                    or ""
                ).strip()
            else:
                text = str(item or "").strip()
            if text:
                items.append(text)
        return items
    text = str(value).strip()
    return [text] if text else []


def _compact_procedure_ref(value: Any) -> str | None:
    if isinstance(value, dict):
        title = str(value.get("title") or "").strip()
        procedure_id = str(value.get("procedure_id") or "").strip()
        if title and procedure_id and title != procedure_id:
            return f"{title} (`{procedure_id}`)"
        return title or procedure_id or None
    text = str(value or "").strip()
    return text or None


def _normalize_check_fields(raw_fields: Any) -> list[str]:
    fields: list[str] = []
    for field in list(raw_fields or []):
        if isinstance(field, dict):
            text = str(field.get("meaning") or field.get("name") or "").strip()
        else:
            text = str(field or "").strip()
        if text and text not in fields:
            fields.append(text)
    return fields


def _append_database_check(
    checks: list[dict[str, Any]],
    *,
    database: Any,
    entity: Any,
    fields: Any,
    correlation_keys: Any = None,
    freshness_field: Any = None,
) -> None:
    database_text = str(database or "").strip() or None
    entity_text = str(entity or "").strip() or None
    field_names = _normalize_check_fields(fields)
    if not (database_text or entity_text or field_names):
        return
    key = (
        (database_text or "").lower(),
        (entity_text or "").lower(),
        tuple(name.lower() for name in field_names),
    )
    for existing in checks:
        existing_key = (
            str(existing.get("database") or "").lower(),
            str(existing.get("entity") or "").lower(),
            tuple(str(item).lower() for item in list(existing.get("fields") or [])),
        )
        if existing_key == key:
            return
    checks.append(
        {
            "database": database_text,
            "entity": entity_text,
            "fields": field_names,
            "correlation_keys": _as_text_list(correlation_keys),
            "freshness_field": str(freshness_field or "").strip() or None,
        }
    )


def _checks_from_support_sources(node: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    sources: list[Any] = []
    for capability in list(node.get("ontology_capabilities") or []):
        if not isinstance(capability, dict):
            continue
        for mapping in list(capability.get("backend_mappings") or []):
            if isinstance(mapping, dict):
                sources.extend(list(mapping.get("support_read_sources") or []))
    for mapping in list(node.get("backend_observability") or []):
        if isinstance(mapping, dict):
            sources.extend(list(mapping.get("support_read_sources") or []))
    for source in sources:
        if not isinstance(source, dict):
            continue
        _append_database_check(
            checks,
            database=source.get("database"),
            entity=source.get("model") or source.get("entity"),
            fields=source.get("fields"),
        )
    return checks


def _suggested_database_checks(node: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    existing = node.get("suggested_database_checks")
    if isinstance(existing, list):
        for check in existing:
            if not isinstance(check, dict):
                continue
            _append_database_check(
                checks,
                database=check.get("database"),
                entity=check.get("entity") or check.get("model"),
                fields=check.get("fields"),
                correlation_keys=check.get("correlation_keys"),
                freshness_field=check.get("freshness_field"),
            )
    mapping = node.get("technical_field_mapping")
    raw_checks: list[Any] = []
    if isinstance(mapping, dict):
        raw_checks = list(mapping.get("suggested_database_checks") or [])
    if not raw_checks and not checks:
        raw_checks = list(node.get("suggested_database_checks") or [])
    for check in raw_checks:
        if not isinstance(check, dict):
            continue
        _append_database_check(
            checks,
            database=check.get("database"),
            entity=check.get("entity") or check.get("model"),
            fields=check.get("fields"),
            correlation_keys=check.get("correlation_keys"),
            freshness_field=check.get("freshness_field"),
        )
    for check in _checks_from_support_sources(node):
        _append_database_check(
            checks,
            database=check.get("database"),
            entity=check.get("entity"),
            fields=check.get("fields"),
            correlation_keys=check.get("correlation_keys"),
            freshness_field=check.get("freshness_field"),
        )
    return checks


def _runbook_links(node: dict[str, Any]) -> list[dict[str, Any]]:
    title_by_id: dict[str, str] = {}
    audience_by_id: dict[str, str] = {}
    for key in ("evidence_collection_procedures", "linked_runbooks"):
        for procedure in list(node.get(key) or []):
            if not isinstance(procedure, dict):
                continue
            procedure_id = str(procedure.get("procedure_id") or "").strip()
            if not procedure_id:
                continue
            title = str(procedure.get("title") or "").strip()
            if title:
                title_by_id[procedure_id] = title
            roles = _as_text_list(procedure.get("audience_roles"))
            role = str(procedure.get("role_required") or "").strip()
            if role:
                audience_by_id[procedure_id] = role
            elif roles:
                audience_by_id[procedure_id] = roles[0]

    links: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _append_link(
        *,
        procedure_id: Any,
        title: Any = None,
        link_confidence: Any = None,
        link_role: Any = None,
        audience: Any = None,
        score: Any = None,
        link_rationale: Any = None,
    ) -> None:
        value = str(procedure_id or "").strip()
        if not value or value in seen:
            return
        seen.add(value)
        score_value = None
        if score is not None:
            try:
                score_value = float(score)
            except (TypeError, ValueError):
                score_value = None
        links.append(
            {
                "procedure_id": value,
                "title": str(title or title_by_id.get(value) or "").strip() or None,
                "link_confidence": str(link_confidence or "").strip() or None,
                "link_role": str(link_role or "").strip() or None,
                "audience": str(
                    audience or audience_by_id.get(value) or ""
                ).strip()
                or None,
                "score": score_value,
                "link_rationale": str(link_rationale or "").strip() or None,
            }
        )

    for link in sorted(
        [item for item in list(node.get("runbook_links") or []) if isinstance(item, dict)],
        key=lambda item: int(item.get("link_rank") or 999),
    ):
        score = link.get("score")
        if score is None:
            score = link.get("retrieval_combined_score")
        if score is None:
            score = link.get("boosted_score")
        _append_link(
            procedure_id=link.get("procedure_id"),
            title=link.get("title"),
            link_confidence=link.get("link_confidence"),
            link_role=link.get("link_role"),
            audience=link.get("audience") or link.get("role_required"),
            score=score,
            link_rationale=link.get("link_rationale"),
        )
    for procedure_id in list(node.get("resolved_runbook_ids") or []):
        _append_link(procedure_id=procedure_id, link_role="resolved")
    for key, role in (
        ("linked_runbooks", "linked"),
        ("evidence_collection_procedures", "evidence"),
        ("optional_corroboration", "corroboration"),
    ):
        for item in list(node.get(key) or []):
            if isinstance(item, dict):
                _append_link(
                    procedure_id=item.get("procedure_id"),
                    title=item.get("title"),
                    link_role=role,
                    audience=item.get("role_required"),
                )
            else:
                _append_link(procedure_id=item, link_role=role)
    primary = node.get("linked_primary_procedure")
    if isinstance(primary, dict):
        _append_link(
            procedure_id=primary.get("procedure_id"),
            title=primary.get("title"),
            link_role="primary",
        )
    else:
        _append_link(procedure_id=primary, link_role="primary")
    for outcome in list(node.get("decision_outcomes") or []):
        if isinstance(outcome, dict):
            _append_link(
                procedure_id=outcome.get("linked_runbook_id"),
                link_role=str(outcome.get("outcome_label") or "decision"),
            )
    return links


def project_playbook_node(
    node: dict[str, Any] | None,
    *,
    branch_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project Cosmos playbook node fields used by Guided Troubleshoot rendering."""
    node = node if isinstance(node, dict) else {}
    objective = str(
        node.get("purpose") or node.get("intent") or node.get("goal") or ""
    ).strip()
    performed_by = str(node.get("performed_by") or "").strip()
    audience_roles = _as_text_list(node.get("audience") or node.get("allowed_roles"))
    preferred_audience = _as_text_list(node.get("preferred_audience"))
    if performed_by and performed_by not in audience_roles:
        audience_roles = [performed_by, *audience_roles]
    display_audience = preferred_audience or audience_roles
    primary_action = str(
        node.get("primary_action") or node.get("action") or ""
    ).strip()
    primary_surface = str(node.get("primary_surface") or "").strip()
    mapping = node.get("technical_field_mapping")
    if isinstance(mapping, dict) and not primary_surface:
        primary_surface = str(mapping.get("primary_surface") or "").strip()
    query_mode = str(node.get("query_mode") or "").strip()
    if query_mode.lower() in {"", "none", "null", "n/a"}:
        query_mode = ""
    suggested_checks = _suggested_database_checks(node)
    runbook_links = _runbook_links(node)
    collect = _as_text_list(node.get("evidence_to_collect")) or _as_text_list(
        node.get("evidence_required")
    )
    source_evidence: list[dict[str, Any]] = []
    for item in list(node.get("source_evidence") or node.get("source_refs") or []):
        if not isinstance(item, dict):
            continue
        quote = str(item.get("quote_or_summary") or item.get("summary") or "").strip()
        support_type = str(item.get("support_type") or "").strip()
        page_ref = str(item.get("page_ref") or "").strip()
        artifact_id = str(item.get("artifact_id") or "").strip()
        if not (quote or support_type or page_ref or artifact_id):
            continue
        source_evidence.append(
            {
                "quote_or_summary": quote or None,
                "support_type": support_type or None,
                "page_ref": page_ref or None,
                "artifact_id": artifact_id or None,
            }
        )
    return {
        "node_id": node.get("node_id"),
        "node_order": node.get("node_order"),
        "node_type": node.get("node_type"),
        "title": node.get("title"),
        "intent": objective or None,
        "objective": objective or None,
        "purpose": node.get("purpose"),
        "diagnostic_reasoning": node.get("diagnostic_reasoning")
        or node.get("source_supported_description"),
        "expected_or_observed_result": node.get("expected_or_observed_result"),
        "stop_or_escalation_note": node.get("stop_or_escalation_note"),
        "allowed_roles": audience_roles,
        "audience": display_audience,
        "preferred_audience": preferred_audience,
        "performed_by": performed_by or None,
        "primary_action": primary_action or None,
        "primary_surface": primary_surface or None,
        "action": primary_action or None,
        "query_mode": query_mode or None,
        "database": query_mode or primary_surface or node.get("database") or None,
        "suggested_database_checks": suggested_checks,
        "runbook_links": runbook_links,
        "evidence_to_collect": collect,
        "linked_primary_procedure": _compact_procedure_ref(
            node.get("linked_primary_procedure")
        ),
        "optional_corroboration": [
            ref
            for ref in (
                _compact_procedure_ref(item)
                for item in list(node.get("optional_corroboration") or [])
            )
            if ref
        ],
        "healthy_indicators": _as_text_list(
            node.get("healthy_indicators")
        ),
        "unhealthy_indicators": _as_text_list(
            node.get("unhealthy_indicators")
        ),
        "inconclusive_indicators": _as_text_list(
            node.get("inconclusive_indicators")
        ),
        "source_evidence": source_evidence,
        "branch_qualification_metrics": branch_metrics,
    }


def _section_card_html(
    *,
    title: str,
    body_html: str,
    border: str = "#e5e7eb",
    bg: str = "#ffffff",
    accent: str = "#374151",
) -> str:
    return (
        f'<div style="border:1px solid {border};background:{bg};'
        f'border-left:3px solid {accent};border-radius:6px;'
        f'padding:0.7rem 0.85rem;margin:0.45rem 0 0.55rem 0;">'
        f'<div style="font-size:0.75rem;font-weight:600;letter-spacing:0.02em;'
        f'color:{accent};margin-bottom:0.3rem;">'
        f"{html.escape(title)}</div>"
        f"{body_html}"
        f"</div>"
    )


def _render_suggested_database_checks_table(
    checks: list[dict[str, Any]],
    *,
    query_mode: str | None = None,
) -> None:
    st.markdown("**Suggested database checks**")
    rows_html: list[str] = []
    for check in checks[:8]:
        if not isinstance(check, dict):
            continue
        database = str(check.get("database") or "—").strip() or "—"
        entity = str(check.get("entity") or "—").strip() or "—"
        fields = [str(field).strip() for field in list(check.get("fields") or []) if str(field).strip()]
        keys = [str(key).strip() for key in list(check.get("correlation_keys") or []) if str(key).strip()]
        freshness = str(check.get("freshness_field") or "").strip()
        field_html = (
            "<br/>".join(html.escape(field) for field in fields[:10])
            if fields
            else "—"
        )
        relate = html.escape(", ".join(keys)) if keys else "—"
        fresh = html.escape(freshness) if freshness else "—"
        rows_html.append(
            "<tr>"
            f"<td style='padding:0.45rem 0.55rem;border-bottom:1px solid #e5e7eb;"
            f"color:#111827;font-family:ui-monospace,Consolas,monospace;'>"
            f"{html.escape(database)}</td>"
            f"<td style='padding:0.45rem 0.55rem;border-bottom:1px solid #e5e7eb;"
            f"color:#111827;font-family:ui-monospace,Consolas,monospace;'>"
            f"{html.escape(entity)}</td>"
            f"<td style='padding:0.45rem 0.55rem;border-bottom:1px solid #e5e7eb;"
            f"color:#374151;line-height:1.45;'>{field_html}</td>"
            f"<td style='padding:0.45rem 0.55rem;border-bottom:1px solid #e5e7eb;"
            f"color:#4b5563;'>{relate}</td>"
            f"<td style='padding:0.45rem 0.55rem;border-bottom:1px solid #e5e7eb;"
            f"color:#4b5563;'>{fresh}</td>"
            "</tr>"
        )
    if not rows_html:
        return
    table = (
        "<div style='overflow-x:auto;border:1px solid #e5e7eb;border-radius:6px;"
        "background:#ffffff;margin:0.35rem 0 0.55rem 0;'>"
        "<table style='width:100%;border-collapse:collapse;font-size:0.9rem;'>"
        "<thead><tr style='background:#f9fafb;color:#374151;text-align:left;'>"
        "<th style='padding:0.5rem 0.55rem;font-weight:600;'>Database</th>"
        "<th style='padding:0.5rem 0.55rem;font-weight:600;'>Model</th>"
        "<th style='padding:0.5rem 0.55rem;font-weight:600;'>Inspect</th>"
        "<th style='padding:0.5rem 0.55rem;font-weight:600;'>Relate by</th>"
        "<th style='padding:0.5rem 0.55rem;font-weight:600;'>Freshness</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        "</table></div>"
    )
    st.markdown(table, unsafe_allow_html=True)
    if query_mode:
        st.caption(f"Query mode: {query_mode}")


def render_playbook_node_fields(node: dict[str, Any] | None) -> None:
    """Render objective / audience / action / database / source evidence for a node."""
    projected = project_playbook_node(node)
    objective = projected.get("objective") or projected.get("intent")
    if objective:
        st.markdown("**Objective**")
        st.write(objective)
    reasoning = str(projected.get("diagnostic_reasoning") or "").strip()
    if reasoning and reasoning != objective:
        st.caption(reasoning)
    audience = list(projected.get("audience") or [])
    if audience:
        st.caption("Audience: " + ", ".join(str(item) for item in audience))
    action = projected.get("action") or projected.get("primary_action")
    if action:
        st.markdown("**Action**")
        st.write(action)
    surface = projected.get("primary_surface")
    if surface:
        st.caption(f"Surface: {surface}")
    checks = list(projected.get("suggested_database_checks") or [])
    if checks:
        _render_suggested_database_checks_table(
            [item for item in checks if isinstance(item, dict)],
            query_mode=str(projected.get("query_mode") or "").strip() or None,
        )
    else:
        database = projected.get("database") or projected.get("query_mode")
        if database:
            st.markdown("**Database / query**")
            st.write(str(database))
    links = list(projected.get("runbook_links") or [])
    if links:
        st.markdown("**Runbook links**")
        for link in links[:12]:
            if not isinstance(link, dict):
                continue
            procedure_id = str(link.get("procedure_id") or "").strip()
            if not procedure_id:
                continue
            meta_parts: list[str] = []
            confidence = str(link.get("link_confidence") or "").strip()
            if confidence:
                meta_parts.append(confidence)
            audience_label = str(link.get("audience") or link.get("link_role") or "").strip()
            if audience_label:
                meta_parts.append(audience_label)
            score = link.get("score")
            if isinstance(score, (int, float)):
                meta_parts.append(f"score={score:g}")
            meta = f" ({', '.join(meta_parts)})" if meta_parts else ""
            title = str(link.get("title") or "").strip()
            suffix = f" — {title}" if title else ""
            st.markdown(f"- `{procedure_id}`{meta}{suffix}")
    collect = list(projected.get("evidence_to_collect") or [])
    if collect:
        st.markdown("**Evidence to collect**")
        for item in collect[:8]:
            st.write(f"- {item}")
    procedure = projected.get("linked_primary_procedure")
    if procedure and not links:
        st.caption(f"Primary procedure: {procedure}")
    for item in list(projected.get("optional_corroboration") or [])[:2]:
        st.caption(f"Corroboration: {item}")
    evidence = list(projected.get("source_evidence") or [])
    if evidence:
        with st.expander(f"Source evidence ({len(evidence)})", expanded=False):
            for item in evidence[:8]:
                if not isinstance(item, dict):
                    continue
                quote = str(item.get("quote_or_summary") or "").strip()
                support = str(item.get("support_type") or "").strip()
                page_ref = str(item.get("page_ref") or "").strip()
                artifact_id = str(item.get("artifact_id") or "").strip()
                label = support or page_ref or artifact_id or "source"
                if quote:
                    st.markdown(f"- **{label}:** {quote}")
                else:
                    st.caption(f"- {label}")


def branch_options_from_node(
    node: dict[str, Any] | None,
    playbook: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    titles = _node_title_index(playbook)
    node = node if isinstance(node, dict) else {}
    destinations = _branch_destination_map(node, playbook)

    def add(label: Any, next_node_id: Any = None) -> None:
        text = str(label or "").strip()
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        destination_id = str(next_node_id or "").strip() or destinations.get(key) or None
        options.append(
            {
                "label": text,
                "next_node_id": destination_id,
                "next_node_title": (titles.get(destination_id) if destination_id else None)
                or destination_id,
            }
        )

    playbook_outcomes = [
        item
        for item in (node.get("decision_outcomes") or [])
        if isinstance(item, dict) and str(item.get("source") or "") != "runbook_step"
    ]
    if playbook_outcomes:
        for item in playbook_outcomes:
            add(item.get("outcome_label"), item.get("next_node_id"))
        return options
    for branch in node.get("branches") or []:
        if isinstance(branch, dict):
            add(
                branch.get("outcome") or branch.get("condition_label"),
                branch.get("next_node_id")
                or branch.get("to_node_id")
                or branch.get("target_node_id"),
            )
    if options:
        return options
    for item in node.get("decision_outcomes") or []:
        if isinstance(item, dict):
            add(
                item.get("outcome_label") or item.get("descriptor"),
                item.get("next_node_id"),
            )
    return options


def _fetch_json(url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.get(url, params=params or {}, timeout=60)
    if response.status_code == 404:
        return {}
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _options_missing_destinations(options: Any) -> bool:
    if not isinstance(options, list) or not options:
        return True
    return all(not isinstance(item, dict) or not item.get("next_node_id") for item in options)


def _metrics_missing_option_destinations(metrics: Any, options: Any) -> bool:
    if not isinstance(options, list):
        return False
    if not isinstance(metrics, dict):
        return True
    for item in options:
        if not isinstance(item, dict) or not item.get("next_node_id"):
            continue
        label = str(item.get("label") or "").strip().lower()
        payload = metrics.get(label)
        if not isinstance(payload, dict) or not payload.get("next_node_id"):
            return True
    return False


def _apply_expected_evidence_to_metrics(
    metrics: dict[str, Any] | None,
    expected: Any,
) -> dict[str, Any] | None:
    if not isinstance(metrics, dict):
        return metrics
    refreshed: dict[str, Any] = {}
    for label in ("healthy", "unhealthy", "inconclusive"):
        payload = metrics.get(label)
        refreshed[label] = (
            dict(payload) if isinstance(payload, dict) else {
                "summary": None,
                "checks": [],
                "next_node_id": None,
                "next_node_title": None,
            }
        )
    parsed = parse_expected_outcome_evidence(expected)
    for label in ("healthy", "unhealthy", "inconclusive"):
        current = refreshed[label].get("summary")
        if current and not _is_generic_outcome_summary(current):
            continue
        if parsed.get(label):
            refreshed[label]["summary"] = parsed[label]
        elif label == "inconclusive":
            refreshed[label]["summary"] = _DEFAULT_INCONCLUSIVE_EVIDENCE
        elif not current:
            refreshed[label]["summary"] = f"Select {label} for this check."
    return refreshed


def enrich_troubleshoot_payload(
    payload: dict[str, Any],
    *,
    backend_url: str,
    variant: str = "prompt_a",
) -> dict[str, Any]:
    """Backfill node details, branch metrics, and images for sparse/legacy responses."""
    enriched = dict(payload)
    workflow = dict(enriched.get("workflow_state") or {})
    guided = dict(enriched.get("guided_question") or {})
    playbook_id = str(
        workflow.get("playbook_id") or enriched.get("selected_workflow_id") or ""
    ).strip()
    node_id = str(
        workflow.get("current_node_id") or guided.get("node_id") or ""
    ).strip()
    if node_id == "playbook_candidate_select":
        node_id = ""
    current_node = workflow.get("current_node") if isinstance(workflow.get("current_node"), dict) else {}
    runbook = workflow.get("runbook") if isinstance(workflow.get("runbook"), dict) else {}
    base = backend_url.rstrip("/")

    playbook_payload: dict[str, Any] = {}
    existing_metrics = (
        guided.get("branch_qualification_metrics")
        or current_node.get("branch_qualification_metrics")
    )
    existing_options = guided.get("branch_options")
    needs_playbook = playbook_id and (
        not workflow.get("playbook_title")
        or not current_node.get("title")
        or not existing_metrics
        or not guided.get("branch_qualification_metrics")
        or not guided.get("branch_options")
        or _options_missing_destinations(existing_options)
        or _metrics_missing_option_destinations(existing_metrics, existing_options)
    )
    if needs_playbook:
        try:
            viewer = _fetch_json(
                f"{base}/corpus/playbooks/{playbook_id}",
                params={"variant": variant},
            )
            playbook_payload = viewer.get("payload") if isinstance(viewer.get("payload"), dict) else {}
        except Exception:
            playbook_payload = {}
        if playbook_payload and not workflow.get("playbook_title"):
            workflow["playbook_title"] = playbook_payload.get("title")
        if playbook_payload and not workflow.get("case_id"):
            workflow["case_id"] = playbook_payload.get("case_id")
        if playbook_payload and not workflow.get("observed_entry_symptoms"):
            workflow["observed_entry_symptoms"] = list(
                playbook_payload.get("observed_entry_symptoms") or []
            )
        if playbook_payload and not workflow.get("user_facing_summary"):
            workflow["user_facing_summary"] = playbook_payload.get("user_facing_summary")
        if playbook_payload and node_id:
            node = next(
                (
                    item
                    for item in list(playbook_payload.get("nodes") or [])
                    if isinstance(item, dict) and str(item.get("node_id")) == node_id
                ),
                {},
            )
            if node:
                metrics = branch_qualification_metrics(node, runbook, playbook_payload)
                options = branch_options_from_node(node, playbook_payload)
                current_node = project_playbook_node(node, branch_metrics=metrics)
                workflow["current_node"] = current_node
                workflow["current_node_id"] = node_id
                if guided:
                    guided["branch_qualification_metrics"] = metrics
                    if options and (
                        not guided.get("branch_options")
                        or _options_missing_destinations(guided.get("branch_options"))
                    ):
                        guided["branch_options"] = options
                    if not guided.get("allowed_answers") and options:
                        guided["allowed_answers"] = [
                            str(item.get("label")) for item in options
                        ]
                    enriched["guided_question"] = guided

    def _enrich_one_runbook(item: dict[str, Any]) -> dict[str, Any]:
        procedure = str(item.get("procedure_id") or "").strip()
        steps_local = list(item.get("steps") or [])
        needs_images = (not steps_local and bool(procedure)) or any(
            isinstance(step, dict) and not list(step.get("images") or [])
            for step in steps_local
        )
        if not procedure or not (needs_images or not steps_local):
            return item
        try:
            out = dict(item)
            if not steps_local:
                runbook_view = _fetch_json(f"{base}/corpus/runbooks/{procedure}")
                remote = (
                    runbook_view.get("payload")
                    if isinstance(runbook_view.get("payload"), dict)
                    else {}
                )
                if remote:
                    out = {
                        **out,
                        "title": out.get("title") or remote.get("title"),
                        "summary": out.get("summary") or remote.get("summary"),
                        "when_to_use": out.get("when_to_use") or remote.get("when_to_use"),
                        "not_for": list(out.get("not_for") or remote.get("not_for") or []),
                        "safety_notes": list(
                            out.get("safety_notes") or remote.get("safety_notes") or []
                        ),
                        "access_or_tools_needed": list(
                            out.get("access_or_tools_needed")
                            or remote.get("access_or_tools_needed")
                            or []
                        ),
                        "role_required": out.get("role_required")
                        or remote.get("role_required")
                        or remote.get("responsible_role"),
                        "visual_references": list(
                            out.get("visual_references")
                            or remote.get("visual_references")
                            or []
                        ),
                        "steps": list(remote.get("steps") or []),
                    }
                    steps_local = list(out.get("steps") or [])
            image_payload = _fetch_json(f"{base}/corpus/runbooks/{procedure}/images")
            step_image_rows = list(image_payload.get("steps") or [])
            by_number = {
                str(row.get("step_number")): row
                for row in step_image_rows
                if isinstance(row, dict)
            }
            if steps_local:
                merged_steps = []
                for step in steps_local:
                    if not isinstance(step, dict):
                        continue
                    row = by_number.get(str(step.get("step_number"))) or {}
                    merged = dict(step)
                    if not merged.get("screens_or_images"):
                        merged["screens_or_images"] = list(row.get("screens_or_images") or [])
                    if not merged.get("images"):
                        images = list(row.get("images") or [])
                        if not images:
                            images = images_from_screen_refs(
                                list(merged.get("screens_or_images") or []),
                                backend_url=base,
                            )
                        merged["images"] = images
                    merged_steps.append(merged)
                out["steps"] = merged_steps
                current_step = out.get("current_step")
                if isinstance(current_step, dict) and not current_step.get("images"):
                    match = next(
                        (
                            step
                            for step in merged_steps
                            if str(step.get("step_number"))
                            == str(current_step.get("step_number"))
                        ),
                        merged_steps[0] if merged_steps else None,
                    )
                    if isinstance(match, dict):
                        current_step = dict(current_step)
                        current_step["images"] = list(match.get("images") or [])
                        if not current_step.get("screens_or_images"):
                            current_step["screens_or_images"] = list(
                                match.get("screens_or_images") or []
                            )
                        out["current_step"] = current_step
            return out
        except Exception:
            return item

    runbooks = [
        item
        for item in list(workflow.get("runbooks") or [])
        if isinstance(item, dict)
        and (item.get("procedure_id") or item.get("title") or item.get("steps"))
    ]
    if not runbooks and (runbook.get("procedure_id") or runbook.get("title") or runbook.get("steps")):
        runbooks = [runbook]

    linked_ids: list[str] = []
    current_node = (
        workflow.get("current_node") if isinstance(workflow.get("current_node"), dict) else {}
    )
    for link in list(current_node.get("runbook_links") or []):
        if not isinstance(link, dict):
            continue
        procedure = str(link.get("procedure_id") or "").strip()
        if procedure and procedure not in linked_ids:
            linked_ids.append(procedure)
    if playbook_id and node_id:
        try:
            link_payload = _fetch_json(
                f"{base}/corpus/playbooks/{playbook_id}/nodes/{node_id}/runbook",
                params={"variant": variant},
            )
            for procedure in list(link_payload.get("procedure_ids") or []):
                value = str(procedure or "").strip()
                if value and value not in linked_ids:
                    linked_ids.append(value)
            primary = str(link_payload.get("procedure_id") or "").strip()
            if primary and primary not in linked_ids:
                linked_ids.append(primary)
            for remote in list(link_payload.get("runbooks") or []):
                if not isinstance(remote, dict):
                    continue
                procedure = str(remote.get("procedure_id") or "").strip()
                if not procedure:
                    continue
                if not any(
                    str(item.get("procedure_id") or "").strip() == procedure for item in runbooks
                ):
                    runbooks.append(remote)
        except Exception:
            pass

    known_ids = {
        str(item.get("procedure_id") or "").strip()
        for item in runbooks
        if str(item.get("procedure_id") or "").strip()
    }
    for procedure in linked_ids:
        if procedure in known_ids:
            continue
        runbooks.append({"procedure_id": procedure})
        known_ids.add(procedure)

    enriched_runbooks = [_enrich_one_runbook(item) for item in runbooks]
    if enriched_runbooks:
        workflow["runbooks"] = enriched_runbooks
        workflow["runbook"] = enriched_runbooks[0]

    expected = (
        (workflow.get("current_node") or {}).get("expected_or_observed_result")
        if isinstance(workflow.get("current_node"), dict)
        else None
    )
    for target in (workflow.get("current_node"), guided):
        if not isinstance(target, dict):
            continue
        metrics = target.get("branch_qualification_metrics")
        refreshed = _apply_expected_evidence_to_metrics(
            metrics if isinstance(metrics, dict) else None,
            expected or target.get("expected_or_observed_result"),
        )
        if isinstance(refreshed, dict):
            target["branch_qualification_metrics"] = refreshed
    if isinstance(workflow.get("current_node"), dict):
        workflow["current_node"] = workflow["current_node"]
    if guided:
        enriched["guided_question"] = guided

    enriched["canonical_images"] = []
    enriched["workflow_state"] = workflow
    if playbook_id and not enriched.get("selected_workflow_id"):
        enriched["selected_workflow_id"] = playbook_id
    return enriched


def images_from_screen_refs(
    refs: list[Any],
    *,
    backend_url: str,
) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    seen: set[str] = set()
    base = backend_url.rstrip("/")
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        artifact_id = str(ref.get("artifact_id") or ref.get("image_id") or "").strip()
        if not artifact_id or artifact_id in seen:
            continue
        seen.add(artifact_id)
        images.append(
            {
                "image_id": artifact_id,
                "caption": ref.get("what_to_look_at") or ref.get("description"),
                "title": ref.get("what_to_look_at") or artifact_id,
                "render_uri": f"{base}/images/{artifact_id}",
            }
        )
    return images


def render_canonical_images(
    images: list[dict[str, Any]] | None,
    *,
    backend_url: str,
    heading: str | None = "**Reference images**",
    as_expander: bool = True,
    expanded: bool = False,
) -> None:
    if not images:
        return
    label = (heading or "Reference images").replace("**", "").strip() or "Reference images"
    container = st.expander(label, expanded=expanded) if as_expander else st.container()
    base = backend_url.rstrip("/")
    with container:
        if not as_expander and heading:
            st.markdown(heading)
        for image in images:
            if not isinstance(image, dict):
                continue
            title = str(
                image.get("caption")
                or image.get("title")
                or image.get("image_id")
                or "Screenshot"
            )
            image_id = str(image.get("image_id") or "").strip()
            candidates = []
            if image_id:
                candidates.append(f"{base}/images/{image_id}")
            direct = str(image.get("render_uri") or image.get("storage_uri") or "").strip()
            if direct and direct not in candidates:
                candidates.append(direct)
            loaded = False
            last_status = "no URI"
            for uri in candidates:
                try:
                    response = requests.get(uri, timeout=45, allow_redirects=True)
                    last_status = str(response.status_code)
                    if response.ok and response.content:
                        st.image(response.content, caption=title, use_container_width=True)
                        loaded = True
                        break
                except Exception as exc:
                    last_status = str(exc)
                    continue
            if not loaded:
                st.caption(f"{title} — unavailable ({last_status})")


def merge_runbook_step_images(
    runbook: dict[str, Any],
    *,
    backend_url: str,
    image_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged = dict(runbook)
    steps = [step for step in list(merged.get("steps") or []) if isinstance(step, dict)]
    by_number: dict[str, dict[str, Any]] = {}
    if isinstance(image_payload, dict):
        for item in list(image_payload.get("steps") or []):
            if isinstance(item, dict):
                by_number[str(item.get("step_number"))] = item
    if not steps:
        return merged
    out_steps: list[dict[str, Any]] = []
    for step in steps:
        row = by_number.get(str(step.get("step_number"))) or {}
        item = dict(step)
        if not item.get("screens_or_images"):
            item["screens_or_images"] = list(row.get("screens_or_images") or [])
        if not item.get("images"):
            images = list(row.get("images") or [])
            if not images:
                images = images_from_screen_refs(
                    list(item.get("screens_or_images") or []),
                    backend_url=backend_url,
                )
            item["images"] = images
        out_steps.append(item)
    merged["steps"] = out_steps
    return merged


def load_runbook_with_images(backend_url: str, procedure_id: str) -> dict[str, Any]:
    procedure_id = str(procedure_id or "").strip()
    if not procedure_id:
        return {}
    base = backend_url.rstrip("/")
    try:
        viewer = _fetch_json(f"{base}/corpus/runbooks/{procedure_id}")
    except Exception:
        return {}
    remote = viewer.get("payload") if isinstance(viewer.get("payload"), dict) else {}
    if not remote:
        return {}
    runbook = {
        "procedure_id": remote.get("procedure_id") or procedure_id,
        "title": remote.get("title"),
        "summary": remote.get("summary"),
        "when_to_use": remote.get("when_to_use"),
        "not_for": list(remote.get("not_for") or []),
        "safety_notes": list(remote.get("safety_notes") or []),
        "access_or_tools_needed": list(remote.get("access_or_tools_needed") or []),
        "role_required": remote.get("role_required"),
        "visual_references": list(remote.get("visual_references") or []),
        "steps": list(remote.get("steps") or []),
    }
    try:
        image_payload = _fetch_json(f"{base}/corpus/runbooks/{procedure_id}/images")
    except Exception:
        image_payload = {}
    return merge_runbook_step_images(
        runbook,
        backend_url=base,
        image_payload=image_payload if isinstance(image_payload, dict) else {},
    )


def render_runbook_panel(
    runbook: dict[str, Any] | None,
    *,
    backend_url: str,
    expanded: bool = False,
    load_images: bool = True,
    heading_prefix: str = "Runbook",
    score: float | None = None,
    detail_level: str = "full",
) -> None:
    runbook = runbook if isinstance(runbook, dict) else {}
    if not (
        runbook.get("title") or runbook.get("procedure_id") or runbook.get("steps")
    ):
        return
    title = runbook.get("title") or runbook.get("procedure_id")
    heading = f"{heading_prefix} — {title}"
    if score is not None:
        heading = f"{heading} · {float(score):.4f}"
    with st.expander(heading, expanded=expanded):
        overview_parts: list[str] = []
        if runbook.get("summary"):
            overview_parts.append(
                f"<div style='color:#111827;line-height:1.5;margin-bottom:0.35rem;'>"
                f"{html.escape(str(runbook.get('summary')))}</div>"
            )
        if runbook.get("when_to_use"):
            overview_parts.append(
                f"<div style='color:#4b5563;font-size:0.9rem;'>"
                f"<strong>When to use:</strong> {html.escape(str(runbook.get('when_to_use')))}"
                f"</div>"
            )
        if runbook.get("procedure_id"):
            overview_parts.append(
                f"<div style='margin-top:0.35rem;color:#6b7280;font-size:0.82rem;"
                f"font-family:ui-monospace,Consolas,monospace;word-break:break-all;'>"
                f"{html.escape(str(runbook.get('procedure_id')))}</div>"
            )
        if overview_parts:
            st.markdown(
                _section_card_html(
                    title="Overview",
                    body_html="".join(overview_parts),
                ),
                unsafe_allow_html=True,
            )
        elif not (runbook.get("title") or runbook.get("steps")):
            st.caption("Runbook document not loaded for this procedure id.")
        steps = [step for step in list(runbook.get("steps") or []) if isinstance(step, dict)]
        if detail_level != "full":
            if steps:
                st.caption(f"{len(steps)} documented steps available")
                preview = steps[0]
                if preview.get("title"):
                    st.caption(f"Starts with: {preview.get('title')}")
                if load_images:
                    preview_images = list(preview.get("images") or [])
                    if not preview_images:
                        preview_images = images_from_screen_refs(
                            list(preview.get("screens_or_images") or []),
                            backend_url=backend_url,
                        )
                    if not preview_images:
                        preview_images = images_from_screen_refs(
                            list(runbook.get("visual_references") or []),
                            backend_url=backend_url,
                        )
                    if preview_images:
                        render_canonical_images(
                            preview_images[:2],
                            backend_url=backend_url,
                            heading="Preview images",
                            as_expander=True,
                            expanded=False,
                        )
            elif load_images:
                preview_images = images_from_screen_refs(
                    list(runbook.get("visual_references") or []),
                    backend_url=backend_url,
                )
                if preview_images:
                    render_canonical_images(
                        preview_images[:2],
                        backend_url=backend_url,
                        heading="Preview images",
                        as_expander=True,
                        expanded=False,
                    )
            return
        not_for = list(runbook.get("not_for") or [])
        if not_for:
            body = "".join(
                f"<div style='color:#374151;margin:0.15rem 0;'>- {html.escape(str(item))}</div>"
                for item in not_for
            )
            st.markdown(
                _section_card_html(title="Not for", body_html=body, accent="#6b7280"),
                unsafe_allow_html=True,
            )
        safety = list(runbook.get("safety_notes") or [])
        if safety:
            body = "".join(
                f"<div style='color:#374151;margin:0.15rem 0;'>- {html.escape(str(item))}</div>"
                for item in safety
            )
            st.markdown(
                _section_card_html(
                    title="Safety notes",
                    body_html=body,
                    accent="#7f1d1d",
                    bg="#fffafa",
                ),
                unsafe_allow_html=True,
            )
        meta_parts: list[str] = []
        tools = list(runbook.get("access_or_tools_needed") or [])
        if tools:
            meta_parts.append(
                "<strong>Tools/access:</strong> "
                + html.escape(", ".join(str(item) for item in tools))
            )
        if runbook.get("role_required"):
            meta_parts.append(
                "<strong>Role required:</strong> "
                + html.escape(str(runbook.get("role_required")))
            )
        if meta_parts:
            st.markdown(
                _section_card_html(
                    title="Access & role",
                    body_html="<br/>".join(
                        f"<div style='color:#374151;margin:0.15rem 0;'>{part}</div>"
                        for part in meta_parts
                    ),
                ),
                unsafe_allow_html=True,
            )
        visuals = list(runbook.get("visual_references") or [])
        if visuals:
            body = ""
            for ref in visuals:
                if not isinstance(ref, dict):
                    continue
                level = ref.get("required_level") or ""
                desc = ref.get("description") or ref.get("artifact_id") or ""
                label = f"[{level}] {desc}" if level else str(desc)
                body += (
                    f"<div style='color:#374151;margin:0.15rem 0;'>"
                    f"- {html.escape(label)}</div>"
                )
            if body:
                st.markdown(
                    _section_card_html(title="Visual references", body_html=body),
                    unsafe_allow_html=True,
                )
        current = runbook.get("current_step") or {}
        if steps:
            st.markdown("**Procedure steps**")
            for step in steps:
                if not isinstance(step, dict):
                    continue
                step_label = step.get("step_number")
                heading_step = step.get("title") or "Step"
                title_text = (
                    f"Step {step_label} — {heading_step}"
                    if step_label is not None
                    else str(heading_step)
                )
                body_parts: list[str] = []
                if step.get("purpose"):
                    body_parts.append(
                        f"<div style='color:#4b5563;font-size:0.9rem;margin-bottom:0.35rem;'>"
                        f"{html.escape(str(step.get('purpose')))}</div>"
                    )
                if step.get("instruction"):
                    body_parts.append(
                        f"<div style='color:#111827;line-height:1.5;margin-bottom:0.35rem;'>"
                        f"{html.escape(str(step.get('instruction')))}</div>"
                    )
                for label, key in (
                    ("Expected", "expected_result"),
                    ("Healthy", "healthy_condition"),
                    ("Unhealthy", "failure_condition"),
                ):
                    value = step.get(key)
                    if value:
                        body_parts.append(
                            f"<div style='color:#374151;font-size:0.9rem;margin:0.2rem 0;'>"
                            f"<strong>{label}:</strong> {html.escape(str(value))}</div>"
                        )
                for stop in list(step.get("stop_or_escalate_if") or []):
                    body_parts.append(
                        f"<div style='color:#374151;font-size:0.9rem;margin:0.2rem 0;'>"
                        f"<strong>Stop/escalate:</strong> {html.escape(str(stop))}</div>"
                    )
                st.markdown(
                    _section_card_html(
                        title=title_text,
                        body_html="".join(body_parts)
                        or "<div style='color:#6b7280;'>No detail</div>",
                    ),
                    unsafe_allow_html=True,
                )
                if not load_images:
                    continue
                step_images = list(step.get("images") or [])
                if not step_images:
                    step_images = images_from_screen_refs(
                        list(step.get("screens_or_images") or []),
                        backend_url=backend_url,
                    )
                if step_images:
                    render_canonical_images(
                        step_images,
                        backend_url=backend_url,
                        heading="Step images",
                        as_expander=True,
                        expanded=False,
                    )
                else:
                    for ref in list(step.get("screens_or_images") or []):
                        if not isinstance(ref, dict):
                            continue
                        note = ref.get("what_to_look_at") or ref.get("artifact_id")
                        if note:
                            st.caption(f"Screen ref: {note}")
        elif current.get("instruction") or current.get("title"):
            step_label = current.get("step_number")
            heading_step = current.get("title") or "Current step"
            title_text = (
                f"Step {step_label} — {heading_step}"
                if step_label is not None
                else str(heading_step)
            )
            body_parts = []
            if current.get("instruction"):
                body_parts.append(
                    f"<div style='color:#0f172a;line-height:1.5;'>"
                    f"{html.escape(str(current.get('instruction')))}</div>"
                )
            for label, key in (
                ("Expected", "expected_result"),
                ("Healthy", "healthy_condition"),
                ("Unhealthy", "failure_condition"),
            ):
                value = current.get(key)
                if value:
                    body_parts.append(
                        f"<div style='color:#374151;font-size:0.9rem;margin:0.2rem 0;'>"
                        f"<strong>{label}:</strong> {html.escape(str(value))}</div>"
                    )
            st.markdown(
                _section_card_html(title=title_text, body_html="".join(body_parts)),
                unsafe_allow_html=True,
            )
            if load_images:
                current_images = list(current.get("images") or [])
                if not current_images:
                    current_images = images_from_screen_refs(
                        list(current.get("screens_or_images") or []),
                        backend_url=backend_url,
                    )
                if current_images:
                    render_canonical_images(
                        current_images, backend_url=backend_url, heading=None
                    )


def _friendly_metadata_lines(metadata: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    preferred = (
        ("category", "Category"),
        ("context_type", "Type"),
        ("topic", "Topic"),
        ("system", "System"),
        ("component", "Component"),
        ("source", "Source"),
        ("source_title", "Source"),
        ("audience", "Audience"),
    )
    seen: set[str] = set()
    for key, label in preferred:
        value = metadata.get(key)
        if value is None or value == "" or key in seen:
            continue
        if isinstance(value, (list, tuple)):
            text = ", ".join(str(item) for item in value if str(item).strip())
        else:
            text = str(value).strip()
        if not text or text.lower() in {key.lower(), "n/a", "none"}:
            continue
        seen.add(key)
        lines.append(f"{label}: {text}")
    return lines


def render_operational_context_panel(
    hit: dict[str, Any] | None,
    *,
    expanded: bool = False,
) -> None:
    hit = hit if isinstance(hit, dict) else {}
    metadata = (
        hit.get("filter_metadata") if isinstance(hit.get("filter_metadata"), dict) else {}
    )
    title = str(
        hit.get("title")
        or metadata.get("title")
        or hit.get("source_record_id")
        or "Operational context"
    ).strip()
    score = hit.get("combined_score")
    heading = f"Operational context — {title}"
    if score is not None:
        heading = f"{heading} · {float(score):.4f}"
    with st.expander(heading, expanded=expanded):
        body = str(
            hit.get("body")
            or hit.get("excerpt")
            or hit.get("snippet")
            or metadata.get("summary")
            or metadata.get("text")
            or ""
        ).strip()
        if body:
            st.write(body)
        for line in _friendly_metadata_lines(metadata):
            st.caption(line)
        source_id = str(hit.get("source_record_id") or "").strip()
        if source_id and source_id != title:
            st.caption(f"Record: `{source_id}`")


def post_troubleshoot(
    backend_url: str,
    *,
    session_id: str,
    user_message: str,
    playbook_variant: str,
    operator_role: str | None = None,
    attachment_ids: list[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "session_id": session_id,
        "user_message": user_message,
        "playbook_variant": playbook_variant,
        "attachment_ids": list(attachment_ids or []),
    }
    if operator_role:
        payload["operator_role"] = operator_role
    response = requests.post(f"{backend_url.rstrip('/')}/troubleshoot", json=payload, timeout=120)
    response.raise_for_status()
    return response.json()


def post_retrieve(
    backend_url: str,
    *,
    query: str,
    session_id: str | None,
    playbook_variant: str,
    record_types: list[str] | None = None,
    top_k: int = 8,
    search_context: dict[str, Any] | None = None,
    attachment_ids: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": query,
        "session_id": session_id,
        "playbook_variant": playbook_variant,
        "top_k": top_k,
        "attachment_ids": list(attachment_ids or []),
    }
    # Always keep operational context searchable for supplemental answer grounding.
    if record_types is None:
        payload_types = None
    else:
        payload_types = list(dict.fromkeys([*record_types, "operational_context"]))
    if payload_types is not None:
        payload["record_types"] = payload_types
    if search_context:
        payload["search_context"] = search_context
    response = requests.post(f"{backend_url.rstrip('/')}/retrieve", json=payload, timeout=120)
    response.raise_for_status()
    return response.json()


def build_search_context_from_troubleshoot(
    last_payload: dict[str, Any] | None,
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Build compact retrieval context from the active troubleshoot response."""
    payload = last_payload if isinstance(last_payload, dict) else {}
    workflow = payload.get("workflow_state") if isinstance(payload.get("workflow_state"), dict) else {}
    node = workflow.get("current_node") if isinstance(workflow.get("current_node"), dict) else {}
    runbook = workflow.get("runbook") if isinstance(workflow.get("runbook"), dict) else {}
    guided = payload.get("guided_question") if isinstance(payload.get("guided_question"), dict) else {}
    observed = payload.get("extracted_observed_signals")
    if not isinstance(observed, dict):
        observed = workflow.get("observed_signals") if isinstance(workflow.get("observed_signals"), dict) else {}
    symptoms = list(workflow.get("observed_entry_symptoms") or [])
    path_evidence = list(workflow.get("path_evidence") or [])
    completed = [
        str(item.get("title") or item.get("node_id") or "").strip()
        for item in path_evidence
        if isinstance(item, dict) and str(item.get("title") or item.get("node_id") or "").strip()
    ]
    allowed = [str(item) for item in list(guided.get("allowed_answers") or []) if str(item).strip()]
    context: dict[str, Any] = {
        "session_id": session_id or "",
        "active_playbook_id": str(workflow.get("playbook_id") or payload.get("selected_workflow_id") or ""),
        "active_playbook_version": str(workflow.get("playbook_variant") or ""),
        "playbook_title": str(workflow.get("playbook_title") or ""),
        "current_node_id": str(
            node.get("node_id") or workflow.get("current_node_id") or guided.get("node_id") or ""
        ),
        "current_node_title": str(node.get("title") or guided.get("question") or ""),
        "current_node_type": str(node.get("node_type") or ""),
        "current_runbook_id": str(runbook.get("procedure_id") or ""),
        "current_procedure_title": str(runbook.get("title") or ""),
        "symptoms": [str(item) for item in symptoms if str(item).strip()],
        "observed_signals": [
            str(key).replace("_", " ")
            for key, value in observed.items()
            if value and str(key).strip()
        ],
        "components": [],
        "systems": [],
        "completed_nodes": completed,
        "allowed_answers": allowed,
    }
    return {key: value for key, value in context.items() if value not in ("", [], None)}


_RUNBOOK_HIT_TYPES = {"canonical_runbook", "incident_source_runbook"}
_PLAYBOOK_HIT_TYPES = {"playbook_prompt_a", "playbook_prompt_b"}
_CONTEXT_HIT_TYPES = {"operational_context"}


def load_playbook_for_search(
    backend_url: str,
    playbook_id: str,
    *,
    variant: str = "prompt_a",
) -> dict[str, Any]:
    playbook_id = str(playbook_id or "").strip()
    if not playbook_id:
        return {}
    try:
        viewer = _fetch_json(
            f"{backend_url.rstrip('/')}/corpus/playbooks/{playbook_id}",
            params={"variant": variant},
        )
    except Exception:
        return {}
    payload = viewer.get("payload") if isinstance(viewer.get("payload"), dict) else {}
    return payload if isinstance(payload, dict) else {}


def _playbook_preview_artifact_ids(playbook: dict[str, Any], *, limit: int = 4) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        ids.append(text)

    for node in list(playbook.get("nodes") or [])[:3]:
        if not isinstance(node, dict):
            continue
        for item in list(node.get("related_artifact_ids") or []):
            add(item)
        for item in list(node.get("inherited_image_refs") or []):
            add(item)
        for item in list(node.get("source_evidence") or node.get("source_refs") or []):
            if isinstance(item, dict):
                add(item.get("artifact_id"))
        if len(ids) >= limit:
            break
    return ids[:limit]


def render_playbook_search_panel(
    playbook: dict[str, Any] | None,
    *,
    backend_url: str,
    score: float | None = None,
    expanded: bool = False,
    detail_level: str = "summary",
    load_images: bool = True,
    fallback_title: str | None = None,
    fallback_snippet: str | None = None,
) -> None:
    playbook = playbook if isinstance(playbook, dict) else {}
    title = str(
        playbook.get("title")
        or playbook.get("playbook_id")
        or fallback_title
        or "Playbook"
    ).strip()
    playbook_id = str(playbook.get("playbook_id") or "").strip()
    heading = f"Playbook — {title}"
    if score is not None:
        heading = f"{heading} · {float(score):.4f}"
    with st.expander(heading, expanded=expanded):
        if not playbook:
            snippet = str(fallback_snippet or "").strip()
            if snippet:
                st.write(snippet)
            return
        summary = str(
            playbook.get("user_facing_summary") or playbook.get("playbook_goal") or ""
        ).strip()
        if summary:
            st.write(summary)
        if playbook_id:
            st.caption(f"Playbook: `{playbook_id}`")
        case_id = str(playbook.get("case_id") or "").strip()
        if case_id:
            st.caption(f"Case: `{case_id}`")
        symptoms = list(playbook.get("observed_entry_symptoms") or [])
        if symptoms:
            st.markdown("**Entry symptoms**")
            for item in symptoms[:6]:
                st.write(f"- {item}")
        nodes = [node for node in list(playbook.get("nodes") or []) if isinstance(node, dict)]
        node_limit = len(nodes) if detail_level == "full" else min(3, len(nodes))
        if nodes:
            st.markdown("**Nodes**" if detail_level == "full" else "**Early nodes**")
            for node in nodes[:node_limit]:
                order = node.get("node_order")
                node_title = str(node.get("title") or node.get("node_id") or "Node").strip()
                prefix = f"{order}. " if order is not None else ""
                st.markdown(f"**{prefix}{node_title}**")
                if detail_level == "full":
                    render_playbook_node_fields(node)
                else:
                    projected = project_playbook_node(node)
                    objective = projected.get("objective") or projected.get("intent")
                    if objective:
                        st.caption(str(objective))
                    action = projected.get("action")
                    if action:
                        st.write(action)
                    checks = list(projected.get("suggested_database_checks") or [])
                    if checks:
                        st.caption(
                            "Database checks: "
                            + ", ".join(
                                str(check.get("entity") or check.get("database") or "check")
                                for check in checks[:3]
                                if isinstance(check, dict)
                            )
                        )
                    links = list(projected.get("runbook_links") or [])
                    if links:
                        st.caption(
                            "Runbook links: "
                            + ", ".join(
                                str(link.get("procedure_id") or "")
                                for link in links[:3]
                                if isinstance(link, dict) and link.get("procedure_id")
                            )
                        )
        if load_images:
            artifact_ids = _playbook_preview_artifact_ids(playbook)
            preview_images = images_from_screen_refs(
                [{"artifact_id": artifact_id} for artifact_id in artifact_ids],
                backend_url=backend_url,
            )
            if preview_images:
                render_canonical_images(
                    preview_images[:3],
                    backend_url=backend_url,
                    heading="Related images",
                    as_expander=True,
                    expanded=False,
                )


def citations_from_retrieve_entry(entry: dict[str, Any]) -> list[dict[str, Any]]:
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


def render_retrieve_sources_block(citations: list[dict[str, Any]]) -> None:
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


def render_retrieve_hit_detail_panels(
    hits: list[dict[str, Any]],
    *,
    backend: str,
    show_full_runbooks: bool,
    playbook_variant: str = "prompt_a",
    load_images: bool = True,
    retrieve_intent: str | None = None,
) -> None:
    playbook_hits = [
        hit
        for hit in hits
        if isinstance(hit, dict) and str(hit.get("record_type") or "") in _PLAYBOOK_HIT_TYPES
    ]
    runbook_hits = [
        hit
        for hit in hits
        if isinstance(hit, dict) and str(hit.get("record_type") or "") in _RUNBOOK_HIT_TYPES
    ]
    context_hits = [
        hit
        for hit in hits
        if isinstance(hit, dict) and str(hit.get("record_type") or "") in _CONTEXT_HIT_TYPES
    ]
    intent = str(retrieve_intent or "").strip().lower()
    prefer_runbooks = intent in {"howto", "maintenance"}
    detail_level = "full" if (show_full_runbooks or prefer_runbooks) else "summary"

    def _render_runbooks(*, expand_first: bool) -> None:
        if not runbook_hits:
            return
        st.markdown("**Related runbooks**")
        for index, hit in enumerate(runbook_hits[:4] if prefer_runbooks else runbook_hits[:3]):
            procedure_id = str(hit.get("source_record_id") or "").strip()
            runbook = load_runbook_with_images(backend, procedure_id) if procedure_id else {}
            score = hit.get("combined_score")
            if not runbook:
                title = hit.get("title") or procedure_id or "Runbook"
                with st.expander(f"Runbook — {title}", expanded=expand_first and index == 0):
                    snippet = str(hit.get("snippet") or "").strip()
                    if snippet:
                        st.write(snippet)
                continue
            render_runbook_panel(
                runbook,
                backend_url=backend,
                expanded=expand_first and index == 0,
                load_images=load_images,
                score=float(score) if score is not None else None,
                detail_level=detail_level,
            )

    def _render_playbooks(*, expand_first: bool) -> None:
        if not playbook_hits:
            return
        st.markdown("**Related playbooks**")
        for index, hit in enumerate(playbook_hits[:3]):
            playbook_id = str(hit.get("source_record_id") or "").strip()
            playbook = (
                load_playbook_for_search(
                    backend, playbook_id, variant=playbook_variant
                )
                if playbook_id
                else {}
            )
            score = hit.get("combined_score")
            render_playbook_search_panel(
                playbook,
                backend_url=backend,
                score=float(score) if score is not None else None,
                expanded=expand_first and index == 0 and not prefer_runbooks,
                detail_level=detail_level,
                load_images=load_images,
                fallback_title=str(hit.get("title") or playbook_id or "Playbook"),
                fallback_snippet=str(hit.get("snippet") or ""),
            )

    def _render_context() -> None:
        if not context_hits:
            return
        st.markdown("**Operational context**")
        for index, hit in enumerate(context_hits[:3]):
            render_operational_context_panel(
                hit, expanded=(index == 0 and not prefer_runbooks and not playbook_hits)
            )

    if prefer_runbooks:
        _render_runbooks(expand_first=True)
        _render_playbooks(expand_first=False)
        _render_context()
    else:
        _render_playbooks(expand_first=True)
        _render_context()
        _render_runbooks(expand_first=False)


def render_retrieve_assistant_entry(
    entry: dict[str, Any],
    *,
    backend: str,
    show_full_runbooks: bool,
    key_prefix: str = "retrieve",
    playbook_variant: str = "prompt_a",
    load_images: bool = True,
) -> dict[str, Any] | None:
    """Render a Search Chat assistant turn. Returns optional apply-bridge payload."""
    del key_prefix
    st.markdown(entry.get("text") or "")
    citations = citations_from_retrieve_entry(entry)
    hits = [hit for hit in list(entry.get("hits") or []) if isinstance(hit, dict)]
    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
    retrieve_intent = str(
        entry.get("retrieve_intent")
        or payload.get("retrieve_intent")
        or (payload.get("runtime_trace") or {}).get("retrieve_intent")
        or ""
    ).strip() or None
    answer_has_sources = "sources:" in str(entry.get("text") or "").lower()
    if (citations or hits) and not answer_has_sources:
        render_retrieve_sources_block(citations or citations_from_retrieve_entry({"hits": hits}))
    elif citations or hits:
        with st.expander("Source details", expanded=False):
            render_retrieve_sources_block(citations or citations_from_retrieve_entry({"hits": hits}))
    render_retrieve_hit_detail_panels(
        hits,
        backend=backend,
        show_full_runbooks=show_full_runbooks,
        playbook_variant=playbook_variant,
        load_images=load_images,
        retrieve_intent=retrieve_intent,
    )
    images = list(entry.get("canonical_images") or [])
    if images and load_images:
        render_canonical_images(
            images,
            backend_url=backend,
            heading="Reference images",
            as_expander=True,
            expanded=False,
        )
    relevance = entry.get("workflow_relevance")
    if not isinstance(relevance, dict):
        relevance = payload.get("workflow_relevance") if isinstance(payload, dict) else None
    if not isinstance(relevance, dict):
        return None
    update = relevance.get("possible_state_update")
    if not isinstance(update, dict) or not update.get("requires_user_confirmation"):
        return None
    value = str(update.get("value") or "").strip()
    if not value:
        return None
    return {"value": value, "field": update.get("field"), "node_id": update.get("node_id")}


def append_retrieve_history_entry(
    history: list[dict[str, Any]],
    *,
    query: str,
    payload: dict[str, Any],
) -> None:
    hits = list(payload.get("hits") or [])
    citations = list(payload.get("citations") or [])
    for citation, hit in zip(citations, hits):
        if isinstance(citation, dict) and isinstance(hit, dict):
            citation.setdefault("combined_score", hit.get("combined_score"))
    history.append({"role": "user", "text": query})
    history.append(
        {
            "role": "assistant",
            "text": payload.get("answer") or "",
            "hits": hits,
            "citations": citations,
            "canonical_images": list(payload.get("canonical_images") or []),
            "workflow_relevance": payload.get("workflow_relevance") or {},
            "retrieved_record_ids": list(payload.get("retrieved_record_ids") or []),
            "related_runbook_ids": list(payload.get("related_runbook_ids") or []),
            "related_playbook_ids": list(payload.get("related_playbook_ids") or []),
            "retrieve_intent": payload.get("retrieve_intent"),
            "payload": payload,
        }
    )


def get_corpus_status(backend_url: str) -> dict[str, Any]:
    try:
        response = requests.get(f"{backend_url.rstrip('/')}/corpus/status", timeout=30)
    except requests.RequestException as exc:
        return {"ok": False, "source": "unknown", "error": str(exc)}
    if not response.ok:
        return {"ok": False, "source": "unknown", "error": response.text}
    return response.json()


def get_interactions(backend_url: str, session_id: str, *, surface: str = "troubleshoot") -> list[dict[str, Any]]:
    prefix = "/troubleshoot" if surface == "troubleshoot" else "/retrieve"
    response = requests.get(
        f"{backend_url.rstrip('/')}{prefix}/sessions/{session_id}/interactions",
        timeout=60,
    )
    if response.status_code == 404:
        return []
    response.raise_for_status()
    payload = response.json()
    return list(payload.get("interactions") or [])


def get_playbook_viewer(backend_url: str, playbook_id: str, variant: str) -> dict[str, Any]:
    response = requests.get(
        f"{backend_url.rstrip('/')}/corpus/playbooks/{playbook_id}",
        params={"variant": variant},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def get_runbook_viewer(backend_url: str, procedure_id: str) -> dict[str, Any]:
    response = requests.get(
        f"{backend_url.rstrip('/')}/corpus/runbooks/{procedure_id}",
        timeout=60,
    )
    response.raise_for_status()
    return response.json()
