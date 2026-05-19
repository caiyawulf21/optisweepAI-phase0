from __future__ import annotations

from pathlib import Path

import yaml

from backend.app.schemas.workflow import WorkflowDefinition
from backend.app.services.workflow_routing import is_workflow_routable


class WorkflowLoader:
    def __init__(self, workflow_dir: str | Path = "data/workflows") -> None:
        self.workflow_dir = Path(workflow_dir)

    def load_workflow(self, workflow_id: str) -> WorkflowDefinition:
        path = self.workflow_dir / f"{workflow_id}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Workflow not found: {workflow_id}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return WorkflowDefinition(**raw)

    def list_workflows(self) -> list[WorkflowDefinition]:
        workflows: list[WorkflowDefinition] = []
        if not self.workflow_dir.exists():
            return workflows
        for path in sorted(self.workflow_dir.glob("*.yaml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            workflows.append(WorkflowDefinition(**raw))
        return workflows

    def select_workflow(self, signals: dict[str, bool], retrieval_confidence: float, allow_draft_workflows: bool = False) -> WorkflowDefinition | None:
        active_signals = {key for key, value in signals.items() if value}
        for workflow in self.list_workflows():
            if not is_workflow_routable(workflow, allow_draft_workflows=allow_draft_workflows):
                continue
            required_signals = set(workflow.required_signals)
            if required_signals.issubset(active_signals) and retrieval_confidence >= workflow.minimum_confidence:
                return workflow
        return None
