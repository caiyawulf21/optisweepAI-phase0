from __future__ import annotations

from typing import Any


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


def _suggested_database_checks(node: dict[str, Any]) -> list[dict[str, Any]]:
    mapping = node.get("technical_field_mapping")
    raw_checks: list[Any] = []
    if isinstance(mapping, dict):
        raw_checks = list(mapping.get("suggested_database_checks") or [])
    if not raw_checks:
        raw_checks = list(node.get("suggested_database_checks") or [])
    checks: list[dict[str, Any]] = []
    for check in raw_checks:
        if not isinstance(check, dict):
            continue
        fields: list[str] = []
        for field in list(check.get("fields") or []):
            if isinstance(field, dict):
                text = str(field.get("meaning") or field.get("name") or "").strip()
            else:
                text = str(field or "").strip()
            if text:
                fields.append(text)
        database = str(check.get("database") or "").strip() or None
        entity = str(check.get("entity") or "").strip() or None
        if not (database or entity or fields):
            continue
        checks.append(
            {
                "database": database,
                "entity": entity,
                "fields": fields,
                "correlation_keys": _as_text_list(check.get("correlation_keys")),
                "freshness_field": str(check.get("freshness_field") or "").strip()
                or None,
            }
        )
    return checks


def _runbook_links(node: dict[str, Any]) -> list[dict[str, Any]]:
    title_by_id: dict[str, str] = {}
    audience_by_id: dict[str, str] = {}
    for procedure in list(node.get("evidence_collection_procedures") or []):
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
    for link in list(node.get("runbook_links") or []):
        if not isinstance(link, dict):
            continue
        procedure_id = str(link.get("procedure_id") or "").strip()
        if not procedure_id:
            continue
        score = link.get("retrieval_combined_score")
        if score is None:
            score = link.get("boosted_score")
        try:
            score_value = float(score) if score is not None else None
        except (TypeError, ValueError):
            score_value = None
        title = str(
            link.get("title") or title_by_id.get(procedure_id) or ""
        ).strip() or None
        audience = str(
            link.get("audience")
            or link.get("role_required")
            or audience_by_id.get(procedure_id)
            or ""
        ).strip() or None
        links.append(
            {
                "procedure_id": procedure_id,
                "title": title,
                "link_confidence": str(link.get("link_confidence") or "").strip()
                or None,
                "link_role": str(link.get("link_role") or "").strip() or None,
                "audience": audience,
                "score": score_value,
                "link_rationale": str(link.get("link_rationale") or "").strip()
                or None,
            }
        )
    return links


def serialize_current_node(
    node: dict[str, Any] | None,
    *,
    branch_metrics: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Project playbook node fields the Guided Troubleshoot UI renders."""
    if not isinstance(node, dict) or not node:
        return None

    objective = str(
        node.get("purpose") or node.get("intent") or node.get("goal") or ""
    ).strip() or None
    performed_by = str(node.get("performed_by") or "").strip() or None
    audience_roles = _as_text_list(node.get("allowed_roles"))
    preferred_audience = _as_text_list(node.get("preferred_audience"))
    if performed_by and performed_by not in audience_roles:
        audience_roles = [performed_by, *audience_roles]
    display_audience = preferred_audience or audience_roles

    primary_action = str(node.get("primary_action") or "").strip() or None
    primary_surface = str(node.get("primary_surface") or "").strip() or None
    mapping = node.get("technical_field_mapping")
    if isinstance(mapping, dict) and not primary_surface:
        primary_surface = str(mapping.get("primary_surface") or "").strip() or None
    query_mode = str(node.get("query_mode") or "").strip()
    if query_mode.lower() in {"", "none", "null", "n/a"}:
        query_mode = ""
    suggested_checks = _suggested_database_checks(node)
    runbook_links = _runbook_links(node)

    evidence_to_collect = _as_text_list(node.get("evidence_to_collect"))
    evidence_required = _as_text_list(node.get("evidence_required"))
    collect = evidence_to_collect or evidence_required

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
        "intent": objective,
        "objective": objective,
        "purpose": node.get("purpose"),
        "diagnostic_reasoning": node.get("diagnostic_reasoning")
        or node.get("source_supported_description"),
        "expected_or_observed_result": node.get("expected_or_observed_result"),
        "stop_or_escalation_note": node.get("stop_or_escalation_note"),
        "allowed_roles": audience_roles,
        "audience": display_audience,
        "preferred_audience": preferred_audience,
        "performed_by": performed_by,
        "primary_action": primary_action,
        "primary_surface": primary_surface,
        "action": primary_action,
        "query_mode": query_mode or None,
        "database": query_mode or primary_surface or None,
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
        "healthy_indicators": _as_text_list(node.get("healthy_indicators")),
        "unhealthy_indicators": _as_text_list(node.get("unhealthy_indicators")),
        "inconclusive_indicators": _as_text_list(node.get("inconclusive_indicators")),
        "source_evidence": source_evidence,
        "branch_qualification_metrics": branch_metrics,
    }
