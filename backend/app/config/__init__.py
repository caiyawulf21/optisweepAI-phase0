"""Process-level configuration for the assistant runtime.

AzureKnowledgeSettings (settings.py): Cosmos / Blob / Vision / embedding dims.
AppSettings (below): session/log/feedback backends, playbook thresholds, and
optional Brain HTTP client flags (default off).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from backend.app.config.settings import AzureKnowledgeSettings, get_settings

RETRIEVAL_BACKEND_STUB = "stub"
RETRIEVAL_BACKEND_COSMOS = "cosmos"
SESSION_BACKEND_MEMORY = "memory"
SESSION_BACKEND_COSMOS = "cosmos"
INTERACTION_LOG_BACKEND_MEMORY = "memory"
INTERACTION_LOG_BACKEND_COSMOS = "cosmos"
INTERACTION_LOG_BACKEND_DISABLED = "disabled"
FEEDBACK_BACKEND_MEMORY = "memory"
FEEDBACK_BACKEND_COSMOS = "cosmos"
FEEDBACK_BACKEND_DISABLED = "disabled"

_VALID_RETRIEVAL_BACKENDS = frozenset(
    {
        RETRIEVAL_BACKEND_STUB,
        RETRIEVAL_BACKEND_COSMOS,
    }
)
_VALID_SESSION_BACKENDS = frozenset(
    {SESSION_BACKEND_MEMORY, SESSION_BACKEND_COSMOS}
)
_VALID_INTERACTION_LOG_BACKENDS = frozenset(
    {
        INTERACTION_LOG_BACKEND_MEMORY,
        INTERACTION_LOG_BACKEND_COSMOS,
        INTERACTION_LOG_BACKEND_DISABLED,
    }
)
_VALID_FEEDBACK_BACKENDS = frozenset(
    {
        FEEDBACK_BACKEND_MEMORY,
        FEEDBACK_BACKEND_COSMOS,
        FEEDBACK_BACKEND_DISABLED,
    }
)


def _env_truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _cosmos_creds_present() -> bool:
    return bool(
        (os.getenv("COSMOS_ENDPOINT") or os.getenv("AZURE_COSMOS_ENDPOINT"))
        and (os.getenv("COSMOS_KEY") or os.getenv("AZURE_COSMOS_KEY"))
    )


@dataclass(frozen=True)
class AppSettings:
    app_env: str = field(default_factory=lambda: os.getenv("APP_ENV", "local"))
    demo_mode: bool = field(
        default_factory=lambda: _env_truthy(os.getenv("DEMO_MODE"), default=True)
    )
    retrieval_backend: str = field(
        default_factory=lambda: os.getenv(
            "RETRIEVAL_BACKEND",
            RETRIEVAL_BACKEND_COSMOS if _cosmos_creds_present() else RETRIEVAL_BACKEND_STUB,
        ).strip().lower()
    )
    session_backend: str = field(
        default_factory=lambda: os.getenv(
            "SESSION_BACKEND",
            SESSION_BACKEND_COSMOS if _cosmos_creds_present() else SESSION_BACKEND_MEMORY,
        ).strip().lower()
    )
    interaction_log_backend: str = field(
        default_factory=lambda: os.getenv(
            "INTERACTION_LOG_BACKEND",
            INTERACTION_LOG_BACKEND_COSMOS
            if _cosmos_creds_present()
            else INTERACTION_LOG_BACKEND_MEMORY,
        ).strip().lower()
    )
    feedback_backend: str = field(
        default_factory=lambda: os.getenv(
            "FEEDBACK_BACKEND",
            FEEDBACK_BACKEND_COSMOS
            if _cosmos_creds_present()
            else FEEDBACK_BACKEND_MEMORY,
        ).strip().lower()
    )
    enable_llm_symptom_extraction: bool = field(
        default_factory=lambda: _env_truthy(
            os.getenv("ENABLE_LLM_SYMPTOM_EXTRACTION"), default=True
        )
    )
    enable_semantic_signal_prior: bool = field(
        default_factory=lambda: _env_truthy(
            os.getenv("ENABLE_SEMANTIC_SIGNAL_PRIOR"), default=False
        )
    )
    brain_http_base_url: str = field(
        default_factory=lambda: (os.getenv("BRAIN_HTTP_BASE_URL") or "").strip()
    )
    brain_http_enabled: bool = field(
        default_factory=lambda: _env_truthy(
            os.getenv("BRAIN_HTTP_ENABLED"), default=False
        )
    )
    brain_http_retrieve: bool = field(
        default_factory=lambda: _env_truthy(
            os.getenv("BRAIN_HTTP_RETRIEVE"), default=False
        )
    )
    brain_http_troubleshoot: bool = field(
        default_factory=lambda: _env_truthy(
            os.getenv("BRAIN_HTTP_TROUBLESHOOT"), default=False
        )
    )
    brain_http_feedback: bool = field(
        default_factory=lambda: _env_truthy(
            os.getenv("BRAIN_HTTP_FEEDBACK"), default=False
        )
    )
    brain_http_reviews: bool = field(
        default_factory=lambda: _env_truthy(
            os.getenv("BRAIN_HTTP_REVIEWS"), default=False
        )
    )
    brain_http_timeout_seconds: float = field(
        default_factory=lambda: float(
            os.getenv("BRAIN_HTTP_TIMEOUT_SECONDS") or "180"
        )
    )
    brain_http_warmup_on_startup: bool = field(
        default_factory=lambda: _env_truthy(
            os.getenv("BRAIN_HTTP_WARMUP_ON_STARTUP"), default=True
        )
    )


def get_app_settings() -> AppSettings:
    return AppSettings()


def validate_runtime_mode(
    app_settings: AppSettings | None = None,
    azure_settings: AzureKnowledgeSettings | None = None,
) -> None:
    """Validate that the selected runtime backends have their required env wired.

    Stub/memory defaults must boot without Azure credentials. Selecting an
    Azure-backed backend requires the corresponding Azure env vars.
    """
    settings = app_settings if app_settings is not None else get_app_settings()
    azure = azure_settings if azure_settings is not None else get_settings()

    if settings.retrieval_backend not in _VALID_RETRIEVAL_BACKENDS:
        raise ValueError(
            "Invalid RETRIEVAL_BACKEND="
            f"{settings.retrieval_backend!r}. Valid values: "
            f"{sorted(_VALID_RETRIEVAL_BACKENDS)}."
        )
    if settings.session_backend not in _VALID_SESSION_BACKENDS:
        raise ValueError(
            "Invalid SESSION_BACKEND="
            f"{settings.session_backend!r}. Valid values: "
            f"{sorted(_VALID_SESSION_BACKENDS)}."
        )
    if settings.interaction_log_backend not in _VALID_INTERACTION_LOG_BACKENDS:
        raise ValueError(
            "Invalid INTERACTION_LOG_BACKEND="
            f"{settings.interaction_log_backend!r}. Valid values: "
            f"{sorted(_VALID_INTERACTION_LOG_BACKENDS)}."
        )
    if settings.feedback_backend not in _VALID_FEEDBACK_BACKENDS:
        raise ValueError(
            "Invalid FEEDBACK_BACKEND="
            f"{settings.feedback_backend!r}. Valid values: "
            f"{sorted(_VALID_FEEDBACK_BACKENDS)}."
        )

    if settings.retrieval_backend == RETRIEVAL_BACKEND_COSMOS:
        azure.require_cosmos()
    if (
        settings.session_backend == SESSION_BACKEND_COSMOS
        or settings.interaction_log_backend == INTERACTION_LOG_BACKEND_COSMOS
        or settings.feedback_backend == FEEDBACK_BACKEND_COSMOS
    ):
        azure.require_cosmos()


__all__ = [
    "AppSettings",
    "AzureKnowledgeSettings",
    "FEEDBACK_BACKEND_COSMOS",
    "FEEDBACK_BACKEND_DISABLED",
    "FEEDBACK_BACKEND_MEMORY",
    "INTERACTION_LOG_BACKEND_COSMOS",
    "INTERACTION_LOG_BACKEND_DISABLED",
    "INTERACTION_LOG_BACKEND_MEMORY",
    "RETRIEVAL_BACKEND_COSMOS",
    "RETRIEVAL_BACKEND_STUB",
    "SESSION_BACKEND_COSMOS",
    "SESSION_BACKEND_MEMORY",
    "get_app_settings",
    "get_settings",
    "validate_runtime_mode",
]
