from __future__ import annotations

from ui.playbook_ui import (
    branch_options_from_node,
    branch_qualification_metrics,
    enrich_troubleshoot_payload,
    images_from_screen_refs,
    parse_expected_outcome_evidence,
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
