import json
from pathlib import Path

from backend.app.schemas.procedure import ProcedureCandidate
from backend.app.services.procedure_merge_service import ProcedureMergeService


def restart_candidate(incident_id: str) -> ProcedureCandidate:
    return ProcedureCandidate(
        procedure_id=f"case_{incident_id}_restart_service_candidate",
        title="Restart Optisweep service after heartbeat timeout",
        operational_intent="restart optisweep service after heartbeat timeout",
        role_required="engineer",
        support_safe=False,
        steps=[
            {
                "step_id": "restart_service",
                "instruction": "Engineer restarts the Optisweep service.",
                "validation_check": "Service returns to running state.",
            }
        ],
        validation_checks=["Service returns to running state."],
        escalation_conditions=["Escalate if remote access is unavailable."],
        related_incidents=[incident_id],
        evidence_refs=[
            {
                "incident_id": incident_id,
                "evidence_id": f"timeline_{incident_id}_restart",
                "source_artifact_id": f"artifact_{incident_id}",
            }
        ],
    )


def test_merges_recurring_restart_procedure_candidates():
    candidates = [restart_candidate("229374"), restart_candidate("229716"), restart_candidate("229777")]

    reusable, reports = ProcedureMergeService().merge_candidates(candidates)

    assert len(reusable) == 1
    procedure = reusable[0]
    assert procedure.procedure_id == "restart_optisweep_service_after_heartbeat_timeout_v1"
    assert procedure.status == "needs_sme_review"
    assert procedure.related_incidents == ["229374", "229716", "229777"]
    assert len(procedure.evidence_refs) == 3
    assert reports[0].status == "merged_candidate"


def test_does_not_merge_candidates_without_evidence_backed_overlap():
    raw = json.loads(Path("data/procedures/procedure_candidates.json").read_text(encoding="utf-8"))
    candidates = [ProcedureCandidate(**item) for item in raw[:2]]
    unsupported = [candidate.model_copy(update={"evidence_refs": []}) for candidate in candidates]

    reusable, reports = ProcedureMergeService().merge_candidates(unsupported)

    assert reusable == []
    assert reports == []
