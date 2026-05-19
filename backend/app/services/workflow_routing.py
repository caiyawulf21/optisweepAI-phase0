from __future__ import annotations

import os
from typing import Any


ROUTABLE_WORKFLOW_STATUSES = {"approved_for_workflow", "sme_reviewed", "approved"}
DRAFT_WORKFLOW_STATUSES = {"proposed", "draft"}
TRUTHY_VALUES = {"1", "true", "yes", "y", "on"}


def demo_mode_enabled() -> bool:
    return os.getenv("DEMO_MODE", "").strip().lower() in TRUTHY_VALUES


def workflow_status(workflow: Any) -> str:
    if isinstance(workflow, dict):
        return str(workflow.get("status") or "").strip().lower()
    return str(getattr(workflow, "status", "") or "").strip().lower()


def is_workflow_routable(workflow: Any, allow_draft_workflows: bool = False) -> bool:
    status = workflow_status(workflow)
    if status in ROUTABLE_WORKFLOW_STATUSES:
        return True
    return status in DRAFT_WORKFLOW_STATUSES and (allow_draft_workflows or demo_mode_enabled())
