from __future__ import annotations

from backend.app.services.incident_kpi_calculator import (
    apply_computed_kpis_to_incident,
    compute_incident_kpis,
    empty_incident_kpis,
    merge_incident_kpis,
)


def _event(
    event_id: str,
    event_order: int,
    *,
    incident_id: str = "999",
    occurred_at: str | None = None,
    documented_at: str | None = None,
    observed_failure_signals: list[str] | None = None,
    recovery_validation_signals: list[str] | None = None,
    action_signals: list[str] | None = None,
) -> dict:
    return {
        "event_id": event_id,
        "incident_id": incident_id,
        "event_order": event_order,
        "event_occurred_at": occurred_at,
        "event_documented_at": documented_at,
        "observed_failure_signals": observed_failure_signals or [],
        "recovery_validation_signals": recovery_validation_signals or [],
        "action_signals": action_signals or [],
    }


def test_mttr_computed_from_case_open_and_close():
    incident = {"incident_id": "999"}
    timeline = [
        _event(
            "evt_999_01",
            1,
            documented_at="2025-09-26T02:00:00",
            action_signals=["case_opened"],
            observed_failure_signals=["hospital_station_unable_to_induct_totes"],
        ),
        _event(
            "evt_999_02",
            2,
            documented_at="2025-09-26T02:30:00",
            recovery_validation_signals=["hospital_can_add_and_remove_totes"],
        ),
        _event(
            "evt_999_03",
            3,
            documented_at="2025-09-26T03:30:00",
            action_signals=["case_closed"],
        ),
    ]
    kpis = compute_incident_kpis(incident, timeline)
    mttr = kpis["time_to_resolve_minutes"]
    assert mttr["kpi_basis"] == "computed"
    assert mttr["value_minutes"] == 90.0
    assert mttr["source_event_ids"] == ["evt_999_01", "evt_999_03"]


def test_time_to_recover_uses_first_recovery_validation():
    incident = {"incident_id": "999"}
    timeline = [
        _event(
            "evt_999_01",
            1,
            documented_at="2025-09-26T02:00:00",
            observed_failure_signals=["robot_shutdown_state"],
        ),
        _event(
            "evt_999_02",
            2,
            documented_at="2025-09-26T02:45:00",
            recovery_validation_signals=["system_running_now"],
        ),
        _event(
            "evt_999_03",
            3,
            documented_at="2025-09-26T03:00:00",
            recovery_validation_signals=["case_closed"],
        ),
    ]
    ttrec = compute_incident_kpis(incident, timeline)["time_to_recover_minutes"]
    assert ttrec["kpi_basis"] == "computed"
    assert ttrec["value_minutes"] == 45.0
    assert ttrec["source_event_ids"] == ["evt_999_01", "evt_999_02"]


def test_missing_timestamps_returns_unavailable():
    incident = {"incident_id": "999"}
    timeline = [
        _event(
            "evt_999_01",
            1,
            observed_failure_signals=["robot_shutdown_state"],
            action_signals=["case_opened"],
        ),
        _event(
            "evt_999_02",
            2,
            recovery_validation_signals=["system_running_now"],
            action_signals=["case_closed"],
        ),
    ]
    kpis = compute_incident_kpis(incident, timeline)
    assert kpis["time_to_resolve_minutes"]["kpi_basis"] == "unavailable"
    assert kpis["time_to_resolve_minutes"]["value_minutes"] is None
    assert kpis["time_to_recover_minutes"]["kpi_basis"] == "unavailable"


def test_event_occurred_at_takes_priority_over_documented_at():
    incident = {"incident_id": "999"}
    timeline = [
        _event(
            "evt_999_01",
            1,
            occurred_at="2025-09-26T01:55:00",
            documented_at="2025-09-26T02:00:00",
            action_signals=["case_opened"],
        ),
        _event(
            "evt_999_02",
            2,
            occurred_at="2025-09-26T03:55:00",
            documented_at="2025-09-26T04:30:00",
            action_signals=["case_closed"],
        ),
    ]
    mttr = compute_incident_kpis(incident, timeline)["time_to_resolve_minutes"]
    assert mttr["value_minutes"] == 120.0


def test_computed_overrides_llm_extracted():
    extracted_kpis = {
        "time_to_resolve_minutes": {
            "value_minutes": 45.0,
            "kpi_basis": "extracted",
            "source_event_ids": [],
            "narrative_excerpt": "case took about 45 minutes",
            "confidence": 0.6,
            "requires_manual_review": True,
        },
        "time_to_recover_minutes": empty_incident_kpis()["time_to_recover_minutes"],
    }
    computed_kpis = {
        "time_to_resolve_minutes": {
            "value_minutes": 90.0,
            "kpi_basis": "computed",
            "source_event_ids": ["evt_999_01", "evt_999_03"],
            "narrative_excerpt": None,
            "confidence": 0.95,
            "requires_manual_review": True,
        },
        "time_to_recover_minutes": empty_incident_kpis()["time_to_recover_minutes"],
    }
    merged = merge_incident_kpis(extracted_kpis, computed_kpis)
    assert merged["time_to_resolve_minutes"]["kpi_basis"] == "computed"
    assert merged["time_to_resolve_minutes"]["value_minutes"] == 90.0


def test_llm_extracted_survives_when_no_timeline_match():
    extracted_kpis = {
        "time_to_resolve_minutes": {
            "value_minutes": 45.0,
            "kpi_basis": "extracted",
            "source_event_ids": [],
            "narrative_excerpt": "case took about 45 minutes",
            "confidence": 0.6,
            "requires_manual_review": True,
        },
        "time_to_recover_minutes": empty_incident_kpis()["time_to_recover_minutes"],
    }
    computed_kpis = empty_incident_kpis()
    merged = merge_incident_kpis(extracted_kpis, computed_kpis)
    assert merged["time_to_resolve_minutes"]["kpi_basis"] == "extracted"
    assert merged["time_to_resolve_minutes"]["value_minutes"] == 45.0
    assert merged["time_to_recover_minutes"]["kpi_basis"] == "unavailable"


def test_inferred_loses_to_extracted_loses_to_computed():
    inferred = {
        "time_to_resolve_minutes": {
            "value_minutes": 30.0,
            "kpi_basis": "inferred",
            "source_event_ids": [],
            "narrative_excerpt": None,
            "confidence": 0.4,
            "requires_manual_review": True,
        },
        "time_to_recover_minutes": empty_incident_kpis()["time_to_recover_minutes"],
    }
    extracted = {
        "time_to_resolve_minutes": {
            "value_minutes": 50.0,
            "kpi_basis": "extracted",
            "source_event_ids": [],
            "narrative_excerpt": "fifty minutes",
            "confidence": 0.7,
            "requires_manual_review": True,
        },
        "time_to_recover_minutes": empty_incident_kpis()["time_to_recover_minutes"],
    }
    merged_one = merge_incident_kpis(inferred, extracted)
    assert merged_one["time_to_resolve_minutes"]["kpi_basis"] == "extracted"
    assert merged_one["time_to_resolve_minutes"]["value_minutes"] == 50.0


def test_apply_computed_kpis_writes_back_to_incident():
    incident = {
        "incident_id": "999",
        "incident_kpis": {
            "time_to_resolve_minutes": {
                "value_minutes": 45.0,
                "kpi_basis": "extracted",
                "source_event_ids": [],
                "narrative_excerpt": "around 45 minutes",
                "confidence": 0.6,
                "requires_manual_review": True,
            },
            "time_to_recover_minutes": empty_incident_kpis()["time_to_recover_minutes"],
        },
    }
    timeline = [
        _event(
            "evt_999_01",
            1,
            documented_at="2025-09-26T02:00:00",
            action_signals=["case_opened"],
            observed_failure_signals=["robot_shutdown_state"],
        ),
        _event(
            "evt_999_02",
            2,
            documented_at="2025-09-26T02:30:00",
            recovery_validation_signals=["system_running_now"],
        ),
        _event(
            "evt_999_03",
            3,
            documented_at="2025-09-26T03:30:00",
            action_signals=["case_closed"],
        ),
    ]
    result = apply_computed_kpis_to_incident(incident, timeline)
    assert result["time_to_resolve_minutes"]["kpi_basis"] == "computed"
    assert incident["incident_kpis"]["time_to_resolve_minutes"]["value_minutes"] == 90.0
    assert incident["incident_kpis"]["time_to_recover_minutes"]["value_minutes"] == 30.0


def test_unrelated_incident_events_are_ignored():
    incident = {"incident_id": "999"}
    timeline = [
        _event(
            "other_evt_01",
            1,
            incident_id="888",
            documented_at="2025-09-26T02:00:00",
            action_signals=["case_opened"],
        ),
        _event(
            "other_evt_02",
            2,
            incident_id="888",
            documented_at="2025-09-26T03:00:00",
            action_signals=["case_closed"],
        ),
    ]
    kpis = compute_incident_kpis(incident, timeline)
    assert kpis["time_to_resolve_minutes"]["kpi_basis"] == "unavailable"
