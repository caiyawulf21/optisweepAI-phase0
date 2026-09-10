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
