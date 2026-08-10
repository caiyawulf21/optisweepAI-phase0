from __future__ import annotations

from backend.app.runtime.playbook_node_view import serialize_current_node


def test_serialize_current_node_keeps_database_checks_and_runbook_links() -> None:
    node = {
        "node_id": "node_1",
        "title": "Confirm the observable scope of the stoppage",
        "intent": "Determine whether the report is site-wide.",
        "preferred_audience": ["operator", "L1_support"],
        "allowed_roles": ["operator", "L1_support", "L2_support"],
        "query_mode": "conceptual_inspection_only",
        "technical_field_mapping": {
            "primary_surface": "rms_ui",
            "suggested_database_checks": [
                {
                    "database": "robotics",
                    "entity": "SortModel",
                    "fields": [
                        {"name": "SortName", "meaning": ""},
                        {"name": "SortGuid", "meaning": ""},
                        {"name": "CurrentSort", "meaning": ""},
                    ],
                }
            ],
        },
        "runbook_links": [
            {
                "procedure_id": "proc_wcs_helix_db_ssms_agv_state_inspection_v1",
                "link_confidence": "medium",
                "link_role": "alternate",
                "retrieval_combined_score": 0.5662,
            }
        ],
        "evidence_collection_procedures": [
            {
                "procedure_id": "proc_wcs_helix_db_ssms_agv_state_inspection_v1",
                "title": "WCS / Helix DB (SSMS) AGV state inspection",
                "role_required": "L1_support",
            }
        ],
    }
    projected = serialize_current_node(node)
    assert projected is not None
    assert projected["audience"] == ["operator", "L1_support"]
    assert projected["primary_surface"] == "rms_ui"
    assert projected["suggested_database_checks"][0]["entity"] == "SortModel"
    assert projected["suggested_database_checks"][0]["fields"] == [
        "SortName",
        "SortGuid",
        "CurrentSort",
    ]
    link = projected["runbook_links"][0]
    assert link["procedure_id"].endswith("agv_state_inspection_v1")
    assert link["title"].startswith("WCS / Helix DB")
    assert link["audience"] == "L1_support"
    assert link["score"] == 0.5662
