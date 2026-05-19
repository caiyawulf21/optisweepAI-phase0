from __future__ import annotations

from backend.app.graph.state import AssistantState
from backend.app.services.azure_openai_client import AzureOpenAIClient


def symptom_extraction_node(state: AssistantState) -> AssistantState:
    client = AzureOpenAIClient()
    signals = client.extract_signals(state["user_message"])
    issue_signals = {
        "agvs_stopped",
        "tipper_heartbeat_timeout",
        "hospital_tote_removal_hangs",
        "system_active_but_frozen",
        "ignition_or_wcs_down",
    }
    state["extracted_signals"] = signals
    state["issue_category"] = "CAT-1" if any(signals.get(signal) for signal in issue_signals) else None
    return state
