from __future__ import annotations

import os
import sys

from backend.app.config.env import load_local_env


load_local_env()

os.environ.setdefault("ENABLE_LLM_WORKFLOW_REASONING", "true")
os.environ.setdefault("USE_CANONICAL_ROUTING", "true")
os.environ.setdefault("ENABLE_CANONICAL_WORKFLOW_RUNTIME", "true")
os.environ.setdefault("ENABLE_GUIDED_DIAGNOSTIC", "true")
os.environ.setdefault("RETRIEVAL_BACKEND", "local")
os.environ.setdefault("DEMO_MODE", "true")

from backend.app.config import AppSettings
from backend.app.graph.graph import run_troubleshooting
from backend.app.services.workflow_reasoning_agent import WorkflowReasoningAgent


def main() -> int:
    cfg = AppSettings()
    print("enable_llm_workflow_reasoning:", cfg.enable_llm_workflow_reasoning)
    agent = WorkflowReasoningAgent()
    print("agent.available():", agent.available())
    if not cfg.enable_llm_workflow_reasoning:
        print("FAIL: set ENABLE_LLM_WORKFLOW_REASONING=true", file=sys.stderr)
        return 1
    if not agent.available():
        print(
            "SKIP: no Azure OpenAI (config/azure_openai.local.json or AZURE_OPENAI_*)",
            file=sys.stderr,
        )
        return 2

    print("running full graph (symptom -> retrieval -> orchestration + LLM)...")
    state = run_troubleshooting(
        "workflow-reasoning-smoke",
        "AGVs are stopped after tipper heartbeat timeout. No RMS fault showing.",
    )
    print("retrieval_results:", len(state.get("retrieval_results") or []))
    print("canonical_route_mode:", state.get("canonical_route_mode"))
    print("workflow_reasoning_applied:", state.get("workflow_reasoning_applied"))
    print("workflow_reasoning_fallback_reason:", state.get("workflow_reasoning_fallback_reason"))
    decision = state.get("workflow_reasoning_decision")
    if decision:
        print(
            "decision:",
            decision.get("action"),
            "confidence:",
            decision.get("confidence"),
            "workflow_id:",
            decision.get("workflow_id"),
        )
    return 0 if state.get("workflow_reasoning_applied") else 3


if __name__ == "__main__":
    raise SystemExit(main())
