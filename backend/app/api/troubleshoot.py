from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from backend.app.runtime.playbook_runtime import run_playbook_troubleshoot
from backend.app.runtime.playbook_node_view import serialize_current_node
from backend.app.agents.runtime import _branch_qualification_metrics
from backend.app.schemas.assistant import (
    Citation,
    ConversationInteraction,
    ConversationReplayResponse,
    EscalationSummaryRequest,
    EscalationSummaryResponse,
    RetrievalResult,
    TroubleshootRequest,
    TroubleshootResponse,
    WorkflowSummary,
)
from backend.app.services.escalation_templates import build_manual_escalation_summary
from backend.app.services.interaction_log_service import (
    InteractionLog,
    InteractionLogService,
    build_interaction_log_service,
)
from backend.app.services.session_service import build_session_service


logger = logging.getLogger(__name__)
router = APIRouter()
interaction_log_service: InteractionLogService = build_interaction_log_service()


@router.post("/troubleshoot", response_model=TroubleshootResponse)
def troubleshoot(request: TroubleshootRequest) -> TroubleshootResponse:
    state = run_playbook_troubleshoot(
        request.session_id,
        request.user_message,
        operator_role=request.operator_role,
        playbook_variant=request.playbook_variant,
    )
    response = _build_troubleshoot_response(state)
    _record_interaction_log(request, state, response)
    return response


@router.get(
    "/troubleshoot/sessions/{session_id}/interactions",
    response_model=ConversationReplayResponse,
)
def get_conversation_interactions(session_id: str) -> ConversationReplayResponse:
    logs = interaction_log_service.list_for_session(session_id)
    interactions = [
        ConversationInteraction(
            interaction_id=log.interaction_id,
            session_id=log.session_id,
            timestamp=log.timestamp,
            user_message=log.user_message,
            response_type=log.response_type,
            selected_workflow_id=log.selected_workflow_id,
            current_node_id=log.current_node_id,
            observed_signals=dict(log.observed_signals),
            retrieval_result_ids=list(log.retrieval_result_ids),
            escalation_triggered=log.escalation_triggered,
            final_response=log.final_response,
            citations=list(log.citations),
            assistant_response=dict(log.assistant_response),
            runtime_trace=dict(log.runtime_trace),
        )
        for log in logs
    ]
    interactions.sort(key=lambda item: item.timestamp)
    return ConversationReplayResponse(session_id=session_id, interactions=interactions)


@router.post(
    "/troubleshoot/escalation-summary",
    response_model=EscalationSummaryResponse,
)
def generate_escalation_summary(
    request: EscalationSummaryRequest,
) -> EscalationSummaryResponse:
    summary = _generate_escalation_summary(request)
    return EscalationSummaryResponse(
        session_id=request.session_id,
        escalation_summary=summary,
    )


def _generate_escalation_summary(request: EscalationSummaryRequest) -> dict[str, Any]:
    session = None
    try:
        session = build_session_service().get(request.session_id)
    except Exception:
        session = None
    playbook_id = request.workflow_id or (
        getattr(session, "active_playbook_id", None) if session else None
    ) or (getattr(session, "active_workflow_id", None) if session else None)
    return build_manual_escalation_summary(
        session_id=request.session_id,
        workflow_id=playbook_id,
        playbook_id=playbook_id,
        playbook_variant=(
            getattr(session, "playbook_variant", None) if session else None
        )
        or "prompt_a",
        current_node_id=request.current_node_id
        or (getattr(session, "current_node_id", None) if session else None),
        escalation_reason=request.escalation_reason,
        observed_signals=(
            dict(getattr(session, "observed_signals", {}) or {}) if session else None
        ),
        observed_canonical_signals=(
            dict(getattr(session, "observed_canonical_signals", {}) or {})
            if session
            else None
        ),
        observed_components=(
            list(getattr(session, "observed_components", []) or []) if session else None
        ),
        steps_attempted=(
            list(getattr(session, "steps_attempted", []) or []) if session else None
        ),
        retrieval_result_ids=(
            list(getattr(session, "retrieval_result_ids", []) or []) if session else None
        ),
        escalation_domains=(
            list(getattr(session, "escalation_triggers", []) or []) if session else None
        ),
    )


def _record_interaction_log(
    request: TroubleshootRequest,
    state: dict[str, Any],
    response: TroubleshootResponse,
) -> None:
    try:
        log = InteractionLog.from_state(
            session_id=request.session_id,
            user_message=request.user_message,
            state=state,
            response=response,
        )
        interaction_log_service.record(log)
    except Exception:
        logger.exception(
            "interaction_log_record_unexpected_failure session=%s",
            request.session_id,
        )


def _hits_to_retrieval_results(
    hits: list[dict[str, Any]] | None,
    *,
    matched_signals: list[str] | None = None,
) -> list[RetrievalResult]:
    results: list[RetrievalResult] = []
    for hit in hits or []:
        if not isinstance(hit, dict):
            continue
        metadata = hit.get("filter_metadata") if isinstance(hit.get("filter_metadata"), dict) else {}
        record_id = str(hit.get("record_id") or hit.get("source_record_id") or "")
        title = str(hit.get("title") or hit.get("source_record_id") or record_id)
        confidence = float(hit.get("combined_score") or 0.0)
        results.append(
            RetrievalResult(
                record_id=record_id,
                source_case_id=str(metadata.get("case_id") or "") or None,
                title=title,
                issue_category=None,
                failure_signature=None,
                matched_signals=list(matched_signals or []),
                confidence=confidence,
                citation=Citation(
                    source_id=str(hit.get("source_record_id") or record_id),
                    title=title,
                    reference=str(hit.get("record_type") or "") or None,
                    excerpt=str(hit.get("snippet") or "") or None,
                ),
                source_notes=None,
                cosine_score=float(hit.get("cosine_score") or 0.0),
                jaccard_score=float(hit.get("jaccard_score") or 0.0),
                symptom_score=float(hit.get("symptom_score") or 0.0),
                coverage=float(hit.get("coverage") or 0.0),
                combined_score=confidence,
            )
        )
    return results


def _build_troubleshoot_response(state: dict[str, Any]) -> TroubleshootResponse:
    playbook = state.get("playbook_payload") or {}
    runbook = state.get("runbook_payload") or {}
    runbook_step = state.get("runbook_step") or {}
    observed = dict(state.get("extracted_observed_signals") or {})
    matched_signals = [key for key, value in observed.items() if value]
    hits = list(state.get("retrieval_hits") or [])
    retrieval_confidence = float(state.get("retrieval_confidence") or 0.0)
    if not retrieval_confidence and hits:
        retrieval_confidence = float(hits[0].get("combined_score") or 0.0)

    workflow_step = None
    if state.get("response_type") == "workflow_step":
        workflow_step = {
            "playbook_id": state.get("active_playbook_id"),
            "case_id": state.get("active_case_id"),
            "node_id": state.get("current_node_id"),
            "procedure_id": runbook.get("procedure_id"),
            "step_number": runbook_step.get("step_number"),
            "instruction": runbook_step.get("instruction") or state.get("final_response"),
            "expected_result": runbook_step.get("expected_result"),
            "title": playbook.get("title"),
            "allowed_answers": list(
                (state.get("guided_question") or {}).get("allowed_answers") or []
            ),
        }

    playbook_id = state.get("active_playbook_id")
    workflow_summary = None
    if playbook_id:
        workflow_summary = WorkflowSummary(
            workflow_id=str(playbook_id),
            title=str(playbook.get("title") or playbook_id),
            current_node_id=state.get("current_node_id"),
            progress_label=(
                f"Node {state.get('current_node_id')}"
                if state.get("current_node_id")
                else None
            ),
            role_required=None,
        )

    def _serialize_runbook_step(step: dict[str, Any]) -> dict[str, Any]:
        return {
            "step_number": step.get("step_number"),
            "title": step.get("title"),
            "instruction": step.get("instruction"),
            "expected_result": step.get("expected_result"),
            "healthy_condition": step.get("healthy_condition"),
            "failure_condition": step.get("failure_condition"),
            "purpose": step.get("purpose"),
            "stop_or_escalate_if": list(step.get("stop_or_escalate_if") or []),
            "screens_or_images": list(step.get("screens_or_images") or []),
            "images": list(step.get("images") or []),
        }

    current_step = None
    if isinstance(runbook_step, dict) and (
        runbook_step.get("instruction") or runbook_step.get("step_number") or runbook_step.get("title")
    ):
        current_step = {
            "step_number": runbook_step.get("step_number"),
            "title": runbook_step.get("title"),
            "instruction": runbook_step.get("instruction"),
            "expected_result": runbook_step.get("expected_result"),
            "healthy_condition": runbook_step.get("healthy_condition"),
            "failure_condition": runbook_step.get("failure_condition"),
            "purpose": runbook_step.get("purpose"),
            "screens_or_images": list(runbook_step.get("screens_or_images") or []),
            "images": list(runbook_step.get("images") or []),
        }

    def _serialize_runbook(
        payload: dict[str, Any],
        *,
        include_current_step: bool = False,
    ) -> dict[str, Any]:
        steps = [
            _serialize_runbook_step(step)
            for step in list(payload.get("steps") or [])
            if isinstance(step, dict)
        ]
        return {
            "procedure_id": payload.get("procedure_id"),
            "title": payload.get("title"),
            "summary": payload.get("summary"),
            "when_to_use": payload.get("when_to_use"),
            "not_for": list(payload.get("not_for") or []),
            "safety_notes": list(payload.get("safety_notes") or []),
            "access_or_tools_needed": list(payload.get("access_or_tools_needed") or []),
            "role_required": payload.get("role_required") or payload.get("responsible_role"),
            "visual_references": [
                {
                    "artifact_id": ref.get("artifact_id"),
                    "description": ref.get("description"),
                    "required_level": ref.get("required_level"),
                }
                for ref in list(payload.get("visual_references") or [])
                if isinstance(ref, dict)
            ],
            "current_step": current_step if include_current_step else None,
            "steps": steps,
            "step_count": len(steps),
        }

    runbook_payloads = [
        item
        for item in list(state.get("runbook_payloads") or [])
        if isinstance(item, dict)
    ]
    if not runbook_payloads and isinstance(runbook, dict) and (
        runbook.get("procedure_id") or runbook.get("title") or runbook.get("steps")
    ):
        runbook_payloads = [runbook]
    serialized_runbooks = [
        _serialize_runbook(item, include_current_step=(index == 0))
        for index, item in enumerate(runbook_payloads)
    ]
    primary_runbook = (
        serialized_runbooks[0]
        if serialized_runbooks
        else _serialize_runbook(
            runbook if isinstance(runbook, dict) else {},
            include_current_step=True,
        )
    )

    current_node = state.get("current_node_payload")
    if not isinstance(current_node, dict) or not current_node:
        node_id = state.get("current_node_id")
        current_node = next(
            (
                item
                for item in list(playbook.get("nodes") or [])
                if isinstance(item, dict) and str(item.get("node_id")) == str(node_id)
            ),
            {},
        )
    branch_metrics = state.get("branch_qualification_metrics")
    if not isinstance(branch_metrics, dict):
        branch_metrics = _branch_qualification_metrics(
            current_node if isinstance(current_node, dict) else {},
            runbook if isinstance(runbook, dict) else {},
            playbook if isinstance(playbook, dict) else {},
        )

    return TroubleshootResponse(
        session_id=str(state.get("session_id") or ""),
        issue_category=None,
        extracted_signals=dict(state.get("extracted_observed_signals") or observed),
        extracted_observed_signals=observed,
        retrieval_results=_hits_to_retrieval_results(hits, matched_signals=matched_signals),
        retrieval_confidence=retrieval_confidence,
        retrieval_confidence_reason=state.get("retrieval_confidence_reason"),
        canonical_images=list(state.get("canonical_images") or []),
        selected_workflow_id=str(playbook_id) if playbook_id else None,
        final_response=str(state.get("final_response") or ""),
        guided_question=state.get("guided_question"),
        response_type=state.get("response_type") or "answer",
        workflow=workflow_summary,
        workflow_step=workflow_step,
        workflow_state={
            "playbook_id": playbook_id,
            "playbook_title": playbook.get("title"),
            "case_id": state.get("active_case_id"),
            "current_node_id": state.get("current_node_id"),
            "playbook_variant": state.get("playbook_variant"),
            "validation_status": playbook.get("validation_status"),
            "confidence": playbook.get("confidence"),
            "confidence_reason": playbook.get("confidence_reason"),
            "retrieval_confidence_reason": state.get("retrieval_confidence_reason"),
            "playbook_goal": playbook.get("playbook_goal"),
            "observed_entry_symptoms": list(playbook.get("observed_entry_symptoms") or []),
            "affected_systems_or_components": list(
                playbook.get("affected_systems_or_components") or []
            ),
            "user_facing_summary": playbook.get("user_facing_summary"),
            "playbook_candidates": list(state.get("playbook_candidates") or []),
            "correlated_symptoms": list(state.get("correlated_symptoms") or []),
            "path_evidence": list(state.get("path_evidence") or []),
            "current_node": serialize_current_node(
                current_node if isinstance(current_node, dict) else {},
                branch_metrics=branch_metrics,
            ),
            "runbook": primary_runbook,
            "runbooks": serialized_runbooks,
        },
        runtime_trace=dict(state.get("runtime_trace") or {}),
    )


__all__ = ["router", "_build_troubleshoot_response", "interaction_log_service"]
