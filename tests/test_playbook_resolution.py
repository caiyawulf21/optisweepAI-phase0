from __future__ import annotations

from backend.app.services.playbook_resolution import (
    candidate_playbook_ids,
    classify_playbook_resolution,
    needs_brain_routing_learning,
)
from backend.app.services.interaction_log_service import InteractionLog


def test_classify_playbook_resolution() -> None:
    assert classify_playbook_resolution({"active_playbook_id": "pb-1"}) == "pinned"
    assert (
        classify_playbook_resolution(
            {"branch_state": {"awaiting_candidate": True}}
        )
        == "awaiting_candidate"
    )
    assert (
        classify_playbook_resolution({}, response_type="playbook_candidates")
        == "awaiting_candidate"
    )
    assert classify_playbook_resolution({}) == "unpinned"
    assert needs_brain_routing_learning("unpinned")
    assert needs_brain_routing_learning("awaiting_candidate")
    assert not needs_brain_routing_learning("pinned")


def test_candidate_playbook_ids() -> None:
    ids = candidate_playbook_ids(
        {
            "playbook_candidates": [
                {"playbook_id": "a"},
                {"workflow_id": "b"},
                {"playbook_id": "a"},
            ]
        }
    )
    assert ids == ["a", "b"]


def test_interaction_log_from_state_flags_awaiting_candidate() -> None:
    class _Resp:
        response_type = "playbook_candidates"
        final_response = "Pick a playbook"
        citations = []
        runtime_trace = {}

        def model_dump(self, mode="json"):
            return {
                "response_type": self.response_type,
                "final_response": self.final_response,
                "citations": [],
                "runtime_trace": {},
                "retrieval_results": [{"source_record_id": "hit-1"}],
            }

    log = InteractionLog.from_state(
        session_id="s1",
        user_message="AGV stuck",
        state={
            "interaction_surface": "troubleshoot",
            "branch_state": {"awaiting_candidate": True},
            "playbook_candidates": [{"playbook_id": "pb-x"}],
            "retrieval_hits": [{"source_record_id": "hit-2"}],
        },
        response=_Resp(),
    )
    assert log.playbook_resolution == "awaiting_candidate"
    assert log.awaiting_playbook_selection is True
    assert log.candidate_playbook_ids == ["pb-x"]
    assert "hit-2" in log.retrieval_result_ids or "hit-1" in log.retrieval_result_ids
