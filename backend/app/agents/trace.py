from __future__ import annotations

from typing import Any


def append_agent_trace(state: dict[str, Any], agent: str, action: str, **details: Any) -> None:
    trace = state.setdefault("runtime_trace", {})
    agents = trace.setdefault("agents", [])
    agents.append({"agent": agent, "action": action, **details})
