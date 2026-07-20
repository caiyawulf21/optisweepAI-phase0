from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from backend.app.retrieval.hybrid_retriever import RetrievalHit


PlaybookVariant = Literal["prompt_a", "prompt_b"]
ResponseSurface = Literal["troubleshoot", "retrieve"]


class PlaybookGraphState(TypedDict, total=False):
    session_id: str
    user_message: str
    operator_role: str | None
    playbook_variant: str
    publish_version_id: str
    active_playbook_id: str | None
    active_case_id: str | None
    current_node_id: str | None
    branch_state: dict[str, Any]
    completed_node_ids: list[str]
    response_type: str
    final_response: str
    retrieval_hits: list[dict[str, Any]]
    playbook_payload: dict[str, Any]
    runbook_payload: dict[str, Any]
    runbook_step: dict[str, Any]
    guided_question: dict[str, Any]
    escalation_required: bool
    escalation_reason: str | None
    runtime_trace: dict[str, Any]
    surface: str


@dataclass
class PlaybookSessionSlice:
    publish_version_id: str
    playbook_variant: str = "prompt_a"
    active_playbook_id: str | None = None
    active_case_id: str | None = None
    current_node_id: str | None = None
    branch_state: dict[str, Any] = field(default_factory=dict)
    completed_node_ids: list[str] = field(default_factory=list)
    current_procedure_id: str | None = None
    current_step_index: int = 0
    last_retrieval_confidence: float = 0.0
    observed_signals: dict[str, bool] = field(default_factory=dict)
    path_evidence: list[dict[str, Any]] = field(default_factory=list)
    pin_source: str | None = None
    extraction_memory: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "publish_version_id": self.publish_version_id,
            "playbook_variant": self.playbook_variant,
            "active_playbook_id": self.active_playbook_id,
            "active_case_id": self.active_case_id,
            "current_node_id": self.current_node_id,
            "branch_state": dict(self.branch_state),
            "completed_node_ids": list(self.completed_node_ids),
            "current_procedure_id": self.current_procedure_id,
            "current_step_index": self.current_step_index,
            "last_retrieval_confidence": self.last_retrieval_confidence,
            "observed_signals": dict(self.observed_signals),
            "path_evidence": list(self.path_evidence),
            "pin_source": self.pin_source,
            "extraction_memory": dict(self.extraction_memory or {}),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None, *, default_version: str) -> PlaybookSessionSlice:
        payload = payload or {}
        evidence_rows = []
        for item in list(payload.get("path_evidence") or []):
            if isinstance(item, dict) and item.get("node_id"):
                evidence_rows.append(
                    {
                        "node_id": str(item.get("node_id") or ""),
                        "title": str(item.get("title") or "")[:80],
                        "outcome": str(item.get("outcome") or "")[:40],
                        "evidence": str(item.get("evidence") or "")[:160],
                    }
                )
        return cls(
            publish_version_id=str(payload.get("publish_version_id") or default_version),
            playbook_variant=str(payload.get("playbook_variant") or "prompt_a"),
            active_playbook_id=payload.get("active_playbook_id"),
            active_case_id=payload.get("active_case_id"),
            current_node_id=payload.get("current_node_id"),
            branch_state=dict(payload.get("branch_state") or {}),
            completed_node_ids=list(payload.get("completed_node_ids") or []),
            current_procedure_id=payload.get("current_procedure_id"),
            current_step_index=int(payload.get("current_step_index") or 0),
            last_retrieval_confidence=float(payload.get("last_retrieval_confidence") or 0.0),
            observed_signals=dict(payload.get("observed_signals") or {}),
            path_evidence=evidence_rows,
            pin_source=payload.get("pin_source"),
            extraction_memory=dict(payload.get("extraction_memory") or {}),
        )


def hits_to_dict(hits: list[RetrievalHit]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for hit in hits:
        snippet_len = 800 if hit.record_type == "operational_context" else 240
        rows.append(
            {
                "record_id": hit.record_id,
                "record_type": hit.record_type,
                "source_record_id": hit.source_record_id,
                "title": hit.title,
                "combined_score": hit.combined_score,
                "cosine_score": hit.cosine_score,
                "jaccard_score": hit.jaccard_score,
                "symptom_score": hit.symptom_score,
                "coverage": hit.coverage,
                "snippet": hit.embedded_text[:snippet_len],
                "filter_metadata": hit.filter_metadata,
            }
        )
    return rows
