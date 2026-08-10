from __future__ import annotations

from ui.playbook_ui import (
    branch_options_from_node,
    branch_qualification_metrics,
    enrich_troubleshoot_payload,
    images_from_screen_refs,
    parse_expected_outcome_evidence,
    project_playbook_node,
)


def test_parse_expected_outcome_evidence_splits_healthy_and_unhealthy() -> None:
    parsed = parse_expected_outcome_evidence(
        "Unhealthy evidence includes site reports that nothing is moving, "
        "small sort is stopped, hospital tote removal is blocked, or RMS/HMI "
        "is visibly abnormal. Healthy or narrower evidence would indicate "
        "movement is limited to one robot or one localized area only."
    )
    assert "nothing is moving" in parsed["unhealthy"]
    assert "one robot" in parsed["healthy"]
    assert "inconclusive" not in parsed


def test_ui_branch_metrics_prefer_parsed_expected_over_generic_descriptors() -> None:
    node = {
        "expected_or_observed_result": (
            "Unhealthy evidence includes site reports that nothing is moving. "
            "Healthy or narrower evidence would indicate movement is limited "
            "to one robot only."
        ),
        "decision_outcomes": [
            {
                "outcome_label": "healthy",
                "source": "playbook_expected_result",
                "descriptor": (
                    "Checks for 'Confirm stoppage' do not indicate the fault "
                    "condition being evaluated."
                ),
            },
            {
                "outcome_label": "unhealthy",
                "source": "playbook_expected_result",
                "descriptor": (
                    "Checks for 'Confirm stoppage' indicate the fault "
                    "condition being evaluated."
                ),
            },
            {
                "outcome_label": "inconclusive",
                "source": "playbook_expected_result",
                "descriptor": (
                    "Unhealthy evidence includes site reports that nothing is "
                    "moving. Healthy or narrower evidence would indicate "
                    "movement is limited to one robot only."
                ),
            },
        ],
    }
    metrics = branch_qualification_metrics(node)
    assert "nothing is moving" in metrics["unhealthy"]["summary"]
    assert "one robot" in metrics["healthy"]["summary"]
    assert "Unhealthy evidence" not in metrics["inconclusive"]["summary"]
    assert "missing" in metrics["inconclusive"]["summary"].lower() or (
        "incomplete" in metrics["inconclusive"]["summary"].lower()
    )



def test_ui_branch_metrics_prefer_indicator_lists() -> None:
    node = {
        "healthy_indicators": ["RMS page renders normally with AGVs in sync."],
        "unhealthy_indicators": [
            "Site-wide stoppage with blank RMS or question-mark HMI.",
            "Hospital tote removal blocked across the area.",
        ],
        "inconclusive_indicators": ["Impact looks localized to one robot only."],
        "decision_outcomes": [
            {
                "outcome_label": "healthy",
                "descriptor": "Select healthy for this check.",
                "source": "playbook_expected_result",
            },
            {
                "outcome_label": "unhealthy",
                "descriptor": "Select unhealthy for this check.",
                "source": "playbook_expected_result",
            },
        ],
    }
    metrics = branch_qualification_metrics(node)
    assert "blank RMS" in metrics["unhealthy"]["summary"]
    assert metrics["unhealthy"]["checks"][0].startswith("Site-wide stoppage")
    assert "AGVs in sync" in metrics["healthy"]["summary"]


def test_project_playbook_node_exposes_action_audience_and_source_evidence() -> None:
    node = {
        "node_id": "node_1",
        "title": "Confirm stoppage",
        "purpose": "Confirm site-wide stoppage pattern.",
        "allowed_roles": ["L1_support"],
        "performed_by": "L1_support",
        "primary_action": "Ask the site whether movement has stopped across the area.",
        "primary_surface": "RMS / HMI",
        "query_mode": "conceptual_inspection_only",
        "evidence_to_collect": ["site movement status", "RMS blank-page observation"],
        "source_evidence": [
            {
                "support_type": "teams_message",
                "quote_or_summary": "question marks on hmi",
                "page_ref": "case_228086:page_2",
            }
        ],
    }
    projected = project_playbook_node(node)
    assert projected["objective"] == "Confirm site-wide stoppage pattern."
    assert projected["action"].startswith("Ask the site")
    assert projected["database"] == "conceptual_inspection_only"
    assert projected["audience"] == ["L1_support"]
    assert projected["source_evidence"][0]["quote_or_summary"] == "question marks on hmi"
    assert "site movement status" in projected["evidence_to_collect"]


def test_project_playbook_node_exposes_database_checks_and_runbook_links() -> None:
    node = {
        "node_id": "node_1",
        "title": "Confirm the observable scope of the stoppage",
        "intent": "Determine whether the report is site-wide.",
        "preferred_audience": ["operator", "L1_support"],
        "query_mode": "conceptual_inspection_only",
        "technical_field_mapping": {
            "suggested_database_checks": [
                {
                    "database": "robotics",
                    "entity": "SystemDatabaseModel",
                    "fields": [
                        {"name": "Id", "meaning": ""},
                        {"name": "EntityInserted", "meaning": ""},
                    ],
                },
                {
                    "database": "robotics",
                    "entity": "SystemStateModel",
                    "fields": [
                        {"name": "SystemStatus", "meaning": ""},
                        {"name": "Keep chutes closed after bag-out", "meaning": ""},
                    ],
                },
            ]
        },
        "runbook_links": [
            {
                "procedure_id": "proc_check_rms_map_monitor_system_emergency_stop_status_v1",
                "link_confidence": "medium",
                "link_role": "primary",
                "retrieval_combined_score": 0.611,
            }
        ],
        "evidence_collection_procedures": [
            {
                "procedure_id": "proc_check_rms_map_monitor_system_emergency_stop_status_v1",
                "title": "Check RMS Map Monitor for System Emergency-Stop Status",
                "role_required": "operator",
            }
        ],
    }
    projected = project_playbook_node(node)
    assert projected["audience"] == ["operator", "L1_support"]
    assert projected["suggested_database_checks"][0]["entity"] == "SystemDatabaseModel"
    assert "EntityInserted" in projected["suggested_database_checks"][0]["fields"]
    assert (
        projected["suggested_database_checks"][1]["fields"][1]
        == "Keep chutes closed after bag-out"
    )
    link = projected["runbook_links"][0]
    assert link["procedure_id"].startswith("proc_check_rms_map_monitor")
    assert link["title"].startswith("Check RMS Map Monitor")
    assert link["audience"] == "operator"
    assert link["score"] == 0.611


def test_ui_branch_metrics_fill_next_from_node_branches() -> None:
    playbook = {
        "nodes": [
            {"node_id": "node_1", "title": "Confirm stoppage"},
            {"node_id": "node_6", "title": "Check residual AGV sync"},
        ]
    }
    node = {
        "node_id": "node_1",
        "decision_outcomes": [
            {
                "outcome_label": "healthy",
                "next_node_id": "",
                "source": "playbook_expected_result",
                "descriptor": "No site-wide stoppage.",
            },
            {
                "outcome_label": "unhealthy",
                "next_node_id": "",
                "source": "playbook_expected_result",
                "descriptor": "Site-wide stoppage.",
            },
            {
                "outcome_label": "inconclusive",
                "next_node_id": "",
                "source": "playbook_expected_result",
            },
        ],
        "branches": [{"outcome": "healthy", "next_node_id": "node_6"}],
    }
    metrics = branch_qualification_metrics(node, {}, playbook)
    options = branch_options_from_node(node, playbook)
    assert metrics["healthy"]["next_node_title"] == "Check residual AGV sync"
    assert options[0]["next_node_id"] == "node_6"
    assert metrics["unhealthy"]["next_node_id"] is None


def test_images_from_screen_refs_builds_proxy_uris() -> None:
    images = images_from_screen_refs(
        [
            {
                "artifact_id": "artifact_training_video_frame_1",
                "what_to_look_at": "RMS layout",
            }
        ],
        backend_url="http://127.0.0.1:8000",
    )
    assert images == [
        {
            "image_id": "artifact_training_video_frame_1",
            "caption": "RMS layout",
            "title": "RMS layout",
            "render_uri": "http://127.0.0.1:8000/images/artifact_training_video_frame_1",
        }
    ]


def test_enrich_troubleshoot_payload_merges_step_images(monkeypatch) -> None:
    calls: list[str] = []

    def fake_fetch(url: str, *, params=None):
        del params
        calls.append(url)
        if url.endswith("/images"):
            return {
                "steps": [
                    {
                        "step_number": 1,
                        "screens_or_images": [
                            {
                                "artifact_id": "artifact_training_video_frame_1",
                                "what_to_look_at": "RMS",
                            }
                        ],
                        "images": [
                            {
                                "image_id": "artifact_training_video_frame_1",
                                "title": "RMS",
                                "storage_uri": "https://example.test/a.jpg",
                            }
                        ],
                    }
                ]
            }
        return {}

    monkeypatch.setattr("ui.playbook_ui._fetch_json", fake_fetch)
    payload = {
        "selected_workflow_id": "playbook_x",
        "workflow_state": {
            "playbook_id": "playbook_x",
            "playbook_title": "X",
            "current_node_id": "node_1",
            "current_node": {
                "node_id": "node_1",
                "title": "Node 1",
                "branch_qualification_metrics": {
                    "healthy": {
                        "summary": "ok",
                        "next_node_id": "node_6",
                        "next_node_title": "Next",
                    },
                    "unhealthy": {"summary": "bad", "next_node_id": None},
                    "inconclusive": {"summary": "?", "next_node_id": None},
                },
            },
            "runbook": {
                "procedure_id": "proc_rms",
                "steps": [{"step_number": 1, "title": "Open RMS", "instruction": "Open"}],
            },
        },
        "guided_question": {
            "node_id": "node_1",
            "allowed_answers": ["healthy", "unhealthy", "inconclusive"],
            "branch_options": [
                {
                    "label": "healthy",
                    "next_node_id": "node_6",
                    "next_node_title": "Next",
                }
            ],
            "branch_qualification_metrics": {
                "healthy": {
                    "summary": "ok",
                    "next_node_id": "node_6",
                    "next_node_title": "Next",
                },
                "unhealthy": {"summary": "bad", "next_node_id": None},
                "inconclusive": {"summary": "?", "next_node_id": None},
            },
        },
    }
    enriched = enrich_troubleshoot_payload(
        payload, backend_url="http://127.0.0.1:8000", variant="prompt_a"
    )
    steps = ((enriched.get("workflow_state") or {}).get("runbook") or {}).get("steps") or []
    assert steps[0]["images"][0]["image_id"] == "artifact_training_video_frame_1"
    assert any(url.endswith("/images") for url in calls)
