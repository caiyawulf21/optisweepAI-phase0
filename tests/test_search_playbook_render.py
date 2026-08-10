from __future__ import annotations

from ui.playbook_ui import (
    _playbook_preview_artifact_ids,
    project_playbook_node,
    render_playbook_search_panel,
)


def test_playbook_preview_artifact_ids_collects_related_and_source_artifacts() -> None:
    playbook = {
        "nodes": [
            {
                "node_id": "node_1",
                "related_artifact_ids": ["artifact_a", "artifact_b"],
                "source_refs": [
                    {"artifact_id": "artifact_c", "quote_or_summary": "blank RMS"},
                    {"artifact_id": None},
                ],
            },
            {
                "node_id": "node_2",
                "inherited_image_refs": ["artifact_d"],
            },
        ]
    }
    assert _playbook_preview_artifact_ids(playbook, limit=3) == [
        "artifact_a",
        "artifact_b",
        "artifact_c",
    ]


def test_project_playbook_node_still_exposes_checks_for_search_summary() -> None:
    node = {
        "intent": "Confirm scope",
        "primary_action": "Ask whether multiple robots are stopped.",
        "technical_field_mapping": {
            "suggested_database_checks": [
                {
                    "database": "robotics",
                    "entity": "SystemStateModel",
                    "fields": [{"name": "SystemStatus"}],
                }
            ]
        },
        "runbook_links": [
            {
                "procedure_id": "proc_check_rms_map_monitor_system_emergency_stop_status_v1",
                "link_confidence": "medium",
                "retrieval_combined_score": 0.61,
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
    assert projected["suggested_database_checks"][0]["entity"] == "SystemStateModel"
    assert projected["runbook_links"][0]["title"].startswith("Check RMS Map Monitor")
    assert callable(render_playbook_search_panel)


def test_attach_retrieve_hit_images_includes_playbook_artifacts(monkeypatch) -> None:
    from backend.app.agents import runtime as runtime_mod

    class FakeClient:
        def get_runbook(self, procedure_id: str):
            del procedure_id
            return {}

        def get_playbook(self, playbook_id: str, variant: str = "prompt_a"):
            del variant
            assert playbook_id == "playbook_incident_228086_sitewide_robotic_stoppage"
            return {
                "playbook_id": playbook_id,
                "title": "Site-wide robotic stoppage",
                "nodes": [
                    {
                        "node_id": "node_1",
                        "related_artifact_ids": [
                            "artifact_incident_228086_page_005_embedded_image_01"
                        ],
                    }
                ],
            }

    class FakeLookup:
        def resolve_for_artifacts(self, *, artifact_ids=None, embedded_images=None, limit=12):
            del embedded_images, limit
            return [
                {
                    "image_id": artifact_ids[0],
                    "title": "Blank RMS page",
                    "render_uri": f"http://example.test/images/{artifact_ids[0]}",
                }
            ]

    monkeypatch.setattr(
        "backend.app.corpus.bootstrap.get_corpus_client", lambda: FakeClient()
    )
    monkeypatch.setattr(
        "backend.app.services.canonical_image_lookup.build_canonical_image_lookup",
        lambda: FakeLookup(),
    )

    state = {
        "playbook_variant": "prompt_a",
        "retrieval_hits": [
            {
                "record_type": "playbook_prompt_a",
                "source_record_id": "playbook_incident_228086_sitewide_robotic_stoppage",
                "title": "Site-wide robotic stoppage",
                "combined_score": 0.9,
            }
        ],
        "runtime_trace": {"agents": []},
    }
    runtime_mod._attach_retrieve_hit_images(state)
    images = state.get("canonical_images") or []
    assert images
    assert images[0]["image_id"].endswith("page_005_embedded_image_01")
    assert images[0]["source_playbook_id"].startswith("playbook_incident_228086")
