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


def test_serialize_merges_ontology_agv_checks_and_decision_runbooks() -> None:
    node = {
        "node_id": "node_5",
        "title": "Inspect AGV state",
        "resolved_runbook_ids": [
            "proc_query_active_agv_errors_from_the_wcs_database_v1",
        ],
        "runbook_links": [
            {
                "procedure_id": "proc_query_active_agv_errors_from_the_wcs_database_v1",
                "link_rank": 1,
                "link_role": "primary",
            }
        ],
        "decision_outcomes": [
            {
                "outcome_label": "unhealthy",
                "linked_runbook_id": "proc_wcs_helix_db_ssms_agv_state_inspection_v1",
            }
        ],
        "technical_field_mapping": {
            "suggested_database_checks": [
                {
                    "database": "robotics",
                    "entity": "RobotDatabaseModel",
                    "fields": [{"name": "RobotId"}],
                }
            ]
        },
        "ontology_capabilities": [
            {
                "id": "capability:agv_active_errors",
                "backend_mappings": [
                    {
                        "support_read_sources": [
                            {
                                "surface": "wcs_sql",
                                "database": "robotics",
                                "model": "AgvActiveErrorDatabaseModel",
                                "fields": ["Name", "Error code", "Description"],
                            }
                        ]
                    }
                ],
            }
        ],
    }
    projected = serialize_current_node(node)
    assert projected is not None
    entities = [item["entity"] for item in projected["suggested_database_checks"]]
    assert "RobotDatabaseModel" in entities
    assert "AgvActiveErrorDatabaseModel" in entities
    procedure_ids = [item["procedure_id"] for item in projected["runbook_links"]]
    assert procedure_ids == [
        "proc_query_active_agv_errors_from_the_wcs_database_v1",
        "proc_wcs_helix_db_ssms_agv_state_inspection_v1",
    ]
