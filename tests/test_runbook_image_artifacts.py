from __future__ import annotations

from backend.app.agents.runtime import _attach_runbook_images, _collect_runbook_artifact_ids, _step_screen_refs


def test_collect_runbook_artifact_ids_from_visual_refs_and_steps() -> None:
    runbook = {
        "visual_references": [
            {"artifact_id": "artifact_fig_4_42_hospital_hmi_alarms_screen"},
            {"artifact_id": "artifact_fig_4_29_hospital_hmi_main_menu"},
        ],
        "steps": [],
    }
    step = {
        "screens_or_images": [
            {"artifact_id": "artifact_fig_4_42_hospital_hmi_alarms_screen"},
        ]
    }
    node = {
        "inherited_image_refs": ["artifact_fig_4_42_hospital_hmi_alarms_screen"],
        "related_artifact_ids": ["artifact_extra"],
    }
    artifacts = _collect_runbook_artifact_ids(runbook=runbook, step=step, node=node)
    assert artifacts == [
        "artifact_fig_4_42_hospital_hmi_alarms_screen",
        "artifact_fig_4_29_hospital_hmi_main_menu",
        "artifact_extra",
    ]


def test_step_screen_refs_extracts_artifact_and_caption() -> None:
    refs = _step_screen_refs(
        {
            "screens_or_images": [
                {
                    "artifact_id": "artifact_fig_4_42_hospital_hmi_alarms_screen",
                    "what_to_look_at": "Alarms list on the left",
                }
            ]
        }
    )
    assert refs == [
        {
            "artifact_id": "artifact_fig_4_42_hospital_hmi_alarms_screen",
            "what_to_look_at": "Alarms list on the left",
        }
    ]


def test_attach_runbook_images_binds_screens_to_steps_only(monkeypatch) -> None:
    class _Lookup:
        def resolve_for_artifacts(self, *, artifact_ids=None, embedded_images=None, **_kwargs):
            ids = list(artifact_ids or [])
            if not ids:
                return []
            return [
                {
                    "image_id": ids[0],
                    "title": ids[0],
                    "storage_uri": f"https://example.test/{ids[0]}.jpg",
                    "source_artifact_ids": [ids[0]],
                }
            ]

        def get_by_image_id(self, image_id: str, **_kwargs):
            return None

    monkeypatch.setattr(
        "backend.app.agents.runtime.get_corpus_settings",
        lambda: type(
            "S",
            (),
            {"cosmos_configured": True},
        )(),
    )
    monkeypatch.setattr(
        "backend.app.agents.runtime.build_canonical_image_lookup",
        lambda: _Lookup(),
    )
    state = {
        "runtime_trace": {"agents": []},
        "runbook_payload": {
            "procedure_id": "proc_1",
            "steps": [
                {
                    "step_number": 1,
                    "title": "Open alarms",
                    "screens_or_images": [
                        {
                            "artifact_id": "artifact_fig_4_42_hospital_hmi_alarms_screen",
                            "what_to_look_at": "Alarms list",
                        }
                    ],
                }
            ],
        },
        "runbook_step": {"step_number": 1, "title": "Open alarms"},
    }
    _attach_runbook_images(state)
    assert state["canonical_images"] == []
    step = state["runbook_payload"]["steps"][0]
    assert step["images"][0]["image_id"] == "artifact_fig_4_42_hospital_hmi_alarms_screen"
    assert step["images"][0]["caption"] == "Alarms list"


def test_attach_runbook_images_falls_back_to_get_by_image_id(monkeypatch) -> None:
    class _Lookup:
        def resolve_for_artifacts(self, *, artifact_ids=None, embedded_images=None, **_kwargs):
            return []

        def get_by_image_id(self, image_id: str, **_kwargs):
            return {
                "image_id": image_id,
                "title": image_id,
                "storage_uri": f"https://example.test/{image_id}.jpg",
                "source_artifact_ids": [image_id],
            }

    monkeypatch.setattr(
        "backend.app.agents.runtime.get_corpus_settings",
        lambda: type("S", (), {"cosmos_configured": True})(),
    )
    monkeypatch.setattr(
        "backend.app.agents.runtime.build_canonical_image_lookup",
        lambda: _Lookup(),
    )
    state = {
        "runtime_trace": {"agents": []},
        "runbook_payload": {
            "procedure_id": "proc_1",
            "steps": [
                {
                    "step_number": 1,
                    "screens_or_images": [
                        {"artifact_id": "artifact_training_video_frame_1", "what_to_look_at": "RMS"}
                    ],
                }
            ],
        },
    }
    _attach_runbook_images(state)
    assert state["runbook_payload"]["steps"][0]["images"][0]["image_id"] == (
        "artifact_training_video_frame_1"
    )
