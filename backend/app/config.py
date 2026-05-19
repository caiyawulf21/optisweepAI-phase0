from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppSettings:
    app_env: str = os.getenv("APP_ENV", "local")
    demo_mode: bool = os.getenv("DEMO_MODE", "true").lower() in {"1", "true", "yes", "on"}
    local_data_root: str = os.getenv("LOCAL_DATA_ROOT", "data")
    workflow_confidence_threshold: float = float(os.getenv("WORKFLOW_CONFIDENCE_THRESHOLD", "0.65"))


def get_app_settings() -> AppSettings:
    return AppSettings()
