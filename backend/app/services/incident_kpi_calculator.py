from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable


KPI_BASIS_PRECEDENCE = {"computed": 4, "extracted": 3, "inferred": 2, "unavailable": 1}
ALLOWED_KPI_BASIS = set(KPI_BASIS_PRECEDENCE)
DEFAULT_COMPUTED_CONFIDENCE = 0.95

CASE_OPEN_ACTION_SIGNALS = {"case_opened", "case_created"}
CASE_CLOSE_ACTION_SIGNALS = {"case_closed", "case_resolved"}


def empty_kpi() -> dict[str, Any]:
    return {
        "value_minutes": None,
        "kpi_basis": "unavailable",
        "source_event_ids": [],
        "narrative_excerpt": None,
        "confidence": None,
        "requires_manual_review": True,
    }


def empty_incident_kpis() -> dict[str, Any]:
    return {
        "time_to_resolve_minutes": empty_kpi(),
        "time_to_recover_minutes": empty_kpi(),
    }


def parse_event_timestamp(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None


def event_timestamp(event: dict[str, Any]) -> tuple[datetime | None, str | None]:
    occurred = parse_event_timestamp(event.get("event_occurred_at"))
    if occurred is not None:
        return occurred, "event_occurred_at"
    documented = parse_event_timestamp(event.get("event_documented_at"))
    if documented is not None:
        return documented, "event_documented_at"
    return None, None


def event_id_or_order(event: dict[str, Any]) -> str:
    for field_name in ("event_id", "local_dataset_id", "id"):
        value = event.get(field_name)
        if value:
            return str(value)
    return f"event_order_{event.get('event_order', 'unknown')}"


def event_has_any_signal(event: dict[str, Any], bucket: str, signal_set: set[str] | None = None) -> bool:
    values = event.get(bucket) or []
    if not isinstance(values, list):
        return False
    if signal_set is None:
        return bool(values)
    return any(str(item) in signal_set for item in values)


def sorted_incident_events(incident_id: str, timeline_events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    matched = [
        event
        for event in timeline_events
        if isinstance(event, dict) and str(event.get("incident_id")) == str(incident_id)
    ]
    return sorted(matched, key=lambda event: event.get("event_order") or 0)


def compute_minutes_between(start: datetime, end: datetime) -> float:
    delta_seconds = (end - start).total_seconds()
    return round(delta_seconds / 60.0, 2)


def first_event_matching(events: list[dict[str, Any]], predicate) -> dict[str, Any] | None:
    for event in events:
        if predicate(event):
            return event
    return None


def last_event_matching(events: list[dict[str, Any]], predicate) -> dict[str, Any] | None:
    last = None
    for event in events:
        if predicate(event):
            last = event
    return last


def compute_time_to_resolve(events: list[dict[str, Any]]) -> dict[str, Any]:
    opened = first_event_matching(
        events,
        lambda event: event_has_any_signal(event, "action_signals", CASE_OPEN_ACTION_SIGNALS),
    )
    closed = last_event_matching(
        events,
        lambda event: event_has_any_signal(event, "action_signals", CASE_CLOSE_ACTION_SIGNALS),
    )
    if opened is None or closed is None:
        return empty_kpi()
    start, _ = event_timestamp(opened)
    end, _ = event_timestamp(closed)
    if start is None or end is None or end < start:
        return empty_kpi()
    return {
        "value_minutes": compute_minutes_between(start, end),
        "kpi_basis": "computed",
        "source_event_ids": [event_id_or_order(opened), event_id_or_order(closed)],
        "narrative_excerpt": None,
        "confidence": DEFAULT_COMPUTED_CONFIDENCE,
        "requires_manual_review": True,
    }


def compute_time_to_recover(events: list[dict[str, Any]]) -> dict[str, Any]:
    failure = first_event_matching(
        events,
        lambda event: event_has_any_signal(event, "observed_failure_signals"),
    )
    if failure is None:
        return empty_kpi()
    failure_order = failure.get("event_order") or 0
    recovery = first_event_matching(
        [event for event in events if (event.get("event_order") or 0) >= failure_order],
        lambda event: event_has_any_signal(event, "recovery_validation_signals"),
    )
    if recovery is None:
        return empty_kpi()
    start, _ = event_timestamp(failure)
    end, _ = event_timestamp(recovery)
    if start is None or end is None or end < start:
        return empty_kpi()
    return {
        "value_minutes": compute_minutes_between(start, end),
        "kpi_basis": "computed",
        "source_event_ids": [event_id_or_order(failure), event_id_or_order(recovery)],
        "narrative_excerpt": None,
        "confidence": DEFAULT_COMPUTED_CONFIDENCE,
        "requires_manual_review": True,
    }


def compute_incident_kpis(
    incident: dict[str, Any],
    timeline_events: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    incident_id = incident.get("incident_id") or incident.get("case_id")
    if not incident_id:
        return empty_incident_kpis()
    events = sorted_incident_events(str(incident_id), timeline_events)
    return {
        "time_to_resolve_minutes": compute_time_to_resolve(events),
        "time_to_recover_minutes": compute_time_to_recover(events),
    }


def normalize_kpi_block(block: Any) -> dict[str, Any]:
    if not isinstance(block, dict):
        return empty_kpi()
    normalized = empty_kpi()
    for field_name in normalized:
        if field_name in block:
            normalized[field_name] = block[field_name]
    basis = normalized.get("kpi_basis")
    if basis not in ALLOWED_KPI_BASIS:
        normalized["kpi_basis"] = "unavailable"
    if not isinstance(normalized.get("source_event_ids"), list):
        normalized["source_event_ids"] = []
    return normalized


def merge_kpi_block(existing: Any, incoming: Any) -> dict[str, Any]:
    existing_block = normalize_kpi_block(existing)
    incoming_block = normalize_kpi_block(incoming)
    existing_rank = KPI_BASIS_PRECEDENCE[existing_block["kpi_basis"]]
    incoming_rank = KPI_BASIS_PRECEDENCE[incoming_block["kpi_basis"]]
    if incoming_rank > existing_rank:
        return incoming_block
    if incoming_rank == existing_rank and incoming_block["value_minutes"] is not None:
        return incoming_block
    return existing_block


def merge_incident_kpis(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any] | None,
) -> dict[str, Any]:
    existing = existing or {}
    incoming = incoming or {}
    merged = empty_incident_kpis()
    for kpi_name in merged:
        merged[kpi_name] = merge_kpi_block(existing.get(kpi_name), incoming.get(kpi_name))
    return merged


def apply_computed_kpis_to_incident(
    incident: dict[str, Any],
    timeline_events: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    computed = compute_incident_kpis(incident, timeline_events)
    incident["incident_kpis"] = merge_incident_kpis(incident.get("incident_kpis"), computed)
    return incident["incident_kpis"]
