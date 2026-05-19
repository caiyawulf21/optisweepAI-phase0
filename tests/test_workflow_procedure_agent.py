import json
import shutil
from pathlib import Path

from backend.app.graph.nodes.workflow_procedure import workflow_procedure_node
from backend.app.schemas.workflow_candidate import WorkflowCandidate
from backend.app.services.workflow_candidate_service import WorkflowCandidateService


def test_workflow_procedure_agent_writes_drafts_for_review(tmp_path):
    (tmp_path / "procedures").mkdir()
    (tmp_path / "workflows").mkdir()
    (tmp_path / "review").mkdir()
    shutil.copyfile("data/procedures/procedure_candidates.json", tmp_path / "procedures" / "procedure_candidates.json")
    shutil.copyfile("data/workflows/workflow_candidates.json", tmp_path / "workflows" / "workflow_candidates.json")

    result = workflow_procedure_node({"data_root": str(tmp_path)})

    procedures = json.loads((tmp_path / "procedures" / "reusable_procedures.json").read_text(encoding="utf-8"))
    workflows = json.loads((tmp_path / "workflows" / "workflow_definitions.json").read_text(encoding="utf-8"))
    queue = json.loads((tmp_path / "review" / "sme_review_queue.json").read_text(encoding="utf-8"))

    assert result["reusable_procedure_count"] == 1
    assert procedures[0]["procedure_id"] == "restart_optisweep_service_after_heartbeat_timeout_v1"
    assert procedures[0]["status"] == "needs_sme_review"
    assert workflows[0]["workflow_id"] == "heartbeat_timeout_no_rms_alarm_v1"
    assert workflows[0]["status"] == "draft"
    assert len(queue) == 2
    assert all(item["status"] == "needs_sme_review" for item in queue)


def test_workflow_candidate_service_requires_evidence_backed_overlap():
    raw = json.loads(Path("data/workflows/workflow_candidates.json").read_text(encoding="utf-8"))
    candidates = [WorkflowCandidate(**item).model_copy(update={"evidence_refs": []}) for item in raw]

    workflows = WorkflowCandidateService().merge_candidates(candidates)

    assert workflows == []
