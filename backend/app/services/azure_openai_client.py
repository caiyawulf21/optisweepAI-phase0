from __future__ import annotations

import os
import re

from backend.app.schemas.assistant import INITIAL_CAT1_SIGNALS


class AzureOpenAIClient:
    def __init__(self) -> None:
        self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.api_key = os.getenv("AZURE_OPENAI_API_KEY")
        self.deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
        self.api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

    def extract_signals(self, user_message: str) -> dict[str, bool]:
        text = user_message.lower()
        signals = {signal: False for signal in INITIAL_CAT1_SIGNALS}

        signals["agvs_stopped"] = _has_any(text, ["agv stopped", "agvs stopped", "agvs are stopped", "agv not moving", "agvs not moving"])
        signals["no_rms_alarm"] = _has_any(text, ["no rms alarm", "no active rms", "without rms alarm", "rms has no alarm"])
        signals["tipper_heartbeat_timeout"] = _has_any(text, ["tipper heartbeat", "tippers heartbeat", "heartbeat timeout", "all tippers"])
        signals["hospital_tote_removal_hangs"] = _has_any(text, ["hospital tote", "tote removal hangs", "removal hang", "remove hangs"])
        signals["system_active_but_frozen"] = _has_any(text, ["active but frozen", "system frozen", "appears active", "frozen"])
        signals["ignition_or_wcs_down"] = _has_any(text, ["ignition down", "wcs down", "wcs offline", "ignition offline"])
        signals["service_restart_required"] = _has_any(text, ["restart service", "service restart", "restart optisweep", "restart ignition"])
        signals["remote_access_unavailable"] = _has_any(text, ["remote access unavailable", "cannot remote", "no remote access", "vpn unavailable"])
        signals["ot_hardware_alarm_present"] = _has_any(text, ["ot hardware alarm", "plc alarm", "hardware alarm", "controls alarm"])
        signals["safety_risk_present"] = _has_any(text, ["safety risk", "unsafe", "injury", "e-stop required"])
        signals["engineer_only_action_required"] = _has_any(text, ["engineer required", "engineer-only", "needs engineer", "escalate to engineer"])
        signals["heartbeat_recovered_after_restart"] = _has_any(text, ["heartbeat recovered", "heartbeat restored", "recovered after restart"])
        signals["user_requests_escalation"] = bool(re.search(r"\b(escalate|need help from engineering|call engineer)\b", text))
        return signals


def _has_any(text: str, phrases: list[str]) -> bool:
    return any(phrase in text for phrase in phrases)
