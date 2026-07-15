from __future__ import annotations

from typing import Any

from backend.app.graph.state import AssistantState
from backend.app.services.escalation_rules import EscalationRules
from backend.app.services.escalation_templates import build_manual_escalation_summary
from backend.app.services.session_service import build_session_service


def _retrieval_result_ids(state: AssistantState) -> list[str]:
    ids: list[str] = []
    for result in state.get("retrieval_results") or []:
        record_id = getattr(result, "record_id", None)
        if record_id:
            ids.append(str(record_id))
            continue
        if isinstance(result, dict) and result.get("record_id"):
            ids.append(str(result["record_id"]))
    return ids


def _observed_signals(state: AssistantState) -> list[str]:
    workflow_state = state.get("workflow_state") or {}
    workflow_step = workflow_state.get("workflow_step")
    if isinstance(workflow_step, dict):
        runtime_signals = workflow_step.get("observed_signals")
        if isinstance(runtime_signals, dict):
            return sorted(
                signal for signal, observed in runtime_signals.items() if bool(observed)
            )
    state_signals = workflow_state.get("observed_signals")
    if isinstance(state_signals, dict):
        return sorted(
            signal for signal, observed in state_signals.items() if bool(observed)
        )
    signals = state.get("extracted_signals") or {}
    return sorted(
        signal for signal, observed in signals.items() if bool(observed)
    )


def _steps_attempted(state: AssistantState) -> list[str]:
    workflow_state = state.get("workflow_state") or {}
    steps = workflow_state.get("steps_attempted")
    if isinstance(steps, list):
        return [str(item) for item in steps]
    return []


def _attach_escalation_summary(
    state: AssistantState,
    *,
    reason: str | None,
    domains: list[str],
) -> None:
    session_id = str(state.get("session_id") or "")
    if not session_id:
        return
    session_ctx = _load_session_context(state)
    state["escalation_summary"] = build_manual_escalation_summary(
        session_id=session_id,
        workflow_id=state.get("selected_workflow_id"),
        current_node_id=(
            state.get("canonical_next_node_id")
            or (state.get("workflow_state") or {}).get("current_node_id")
        ),
        escalation_reason=reason,
        observed_signals=_observed_signals(state) or session_ctx.get("observed_signals"),
        observed_canonical_signals=session_ctx.get("observed_canonical_signals"),
        observed_components=session_ctx.get("observed_components"),
        steps_attempted=_steps_attempted(state),
        retrieval_result_ids=_retrieval_result_ids(state),
        escalation_domains=domains,
    )


def escalation_node(state: AssistantState) -> AssistantState:
    workflow_state = state.get("workflow_state") or {}
    workflow_step = workflow_state.get("workflow_step")
    if isinstance(workflow_step, dict) and workflow_step.get("node_type") == "escalation":
        domain = workflow_step.get("escalation_domain")
        domains = [str(domain)] if domain else []
        reason = (
            workflow_step.get("instruction")
            or workflow_step.get("question")
            or "Canonical workflow escalation node reached"
        )
        state["escalation_required"] = True
        state["escalation_reason"] = str(reason)
        state["workflow_state"] = {
            **workflow_state,
            "escalation_domains": domains,
        }
        state["final_response"] = str(reason)
        _attach_escalation_summary(state, reason=str(reason), domains=domains)
        return state

    if isinstance(workflow_step, dict) and workflow_step.get("node_type") in {
        "question",
        "instruction",
        "validation",
        "terminal",
    }:
        state["escalation_required"] = False
        state["escalation_reason"] = None
        state["escalation_summary"] = None
        return state

    required, reason, domains = EscalationRules().evaluate(
        state.get("extracted_signals", {}),
        state.get("retrieval_confidence", 0.0),
        state.get("selected_workflow_id"),
    )
    state["escalation_required"] = required
    state["escalation_reason"] = reason
    state["escalation_summary"] = None
    if not required:
        return state

    state["workflow_state"] = {
        **state.get("workflow_state", {}),
        "escalation_domains": domains,
    }
    state["final_response"] = (
        f"{state.get('final_response', '')} Escalation required: {reason}."
    )
    _attach_escalation_summary(state, reason=reason, domains=domains)
    return state


def _load_session_context(state: AssistantState) -> dict[str, Any]:
    session_id = state.get("session_id") or ""
    if not session_id:
        return {}
    try:
        session = build_session_service().get(session_id)
    except Exception:
        return {}
    if session is None:
        return {}
    return {
        "observed_signals": dict(session.observed_signals or {}),
        "observed_canonical_signals": dict(session.observed_canonical_signals or {}),
        "observed_components": list(session.observed_components or []),
    }
