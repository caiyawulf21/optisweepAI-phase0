"""Process-level configuration for the assistant runtime.

``AzureKnowledgeSettings`` lives in :mod:`backend.app.config.settings` and
covers the Azure-side knowledge plane. ``AppSettings`` (re-exported below)
covers the Phase 0 graph runtime, including the Phase 11
``USE_CANONICAL_ROUTING`` feature flag that gates the canonical layer behind
opt-in, and the Phase 1 runtime backend selectors
(``RETRIEVAL_BACKEND``/``SESSION_BACKEND``) plus guarded feature toggles
(``ENABLE_GUIDED_DIAGNOSTIC``/``ENABLE_CANONICAL_WORKFLOW_RUNTIME``).
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
    workflow_confidence_threshold: float = field(
        default_factory=lambda: float(
            os.getenv("WORKFLOW_CONFIDENCE_THRESHOLD", "0.65")
        )
    )
    use_canonical_routing: bool = field(
        default_factory=lambda: _env_truthy(
            os.getenv("USE_CANONICAL_ROUTING"), default=False
        )
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
    enable_guided_diagnostic: bool = field(
        default_factory=lambda: _env_truthy(
            os.getenv("ENABLE_GUIDED_DIAGNOSTIC"), default=False
        )
    )
    enable_canonical_workflow_runtime: bool = field(
        default_factory=lambda: _env_truthy(
            os.getenv("ENABLE_CANONICAL_WORKFLOW_RUNTIME"), default=False
        )
    )
    enable_dynamic_procedure_guidance: bool = field(
        default_factory=lambda: _env_truthy(
            os.getenv("ENABLE_DYNAMIC_PROCEDURE_GUIDANCE"), default=False
        )
    )
    canonical_workflow_high_confidence_threshold: float = field(
        default_factory=lambda: float(
            os.getenv("CANONICAL_WORKFLOW_HIGH_CONFIDENCE_THRESHOLD", "0.75")
        )
    )
    dynamic_procedure_guidance_threshold: float = field(
        default_factory=lambda: float(
            os.getenv("DYNAMIC_PROCEDURE_GUIDANCE_THRESHOLD", "0.55")
        )
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
    enable_llm_workflow_reasoning: bool = field(
        default_factory=lambda: _env_truthy(
            os.getenv("ENABLE_LLM_WORKFLOW_REASONING"), default=False
        )
    )
    workflow_reasoning_confidence_threshold: float = field(
        default_factory=lambda: float(
            os.getenv("WORKFLOW_REASONING_CONFIDENCE_THRESHOLD", "0.70")
        )
    )
    workflow_reasoning_disagree_threshold: float = field(
        default_factory=lambda: float(
            os.getenv("WORKFLOW_REASONING_DISAGREE_THRESHOLD", "0.85")
        )
    )
    workflow_reasoning_max_tool_turns: int = field(
        default_factory=lambda: int(
            os.getenv("WORKFLOW_REASONING_MAX_TOOL_TURNS", "1")
        )
    )
    workflow_reasoning_single_shot: bool = field(
        default_factory=lambda: _env_truthy(
            os.getenv("WORKFLOW_REASONING_SINGLE_SHOT"), default=True
        )
    )


def get_app_settings() -> AppSettings:
    return AppSettings()


def validate_runtime_mode(
    app_settings: AppSettings | None = None,
    azure_settings: AzureKnowledgeSettings | None = None,
) -> None:
    """Validate that the selected runtime backends have their required env wired.

    Local-only defaults (``RETRIEVAL_BACKEND=local`` + ``SESSION_BACKEND=memory``)
    must always boot successfully without any Azure credentials. Selecting an
    Azure-backed backend requires the corresponding Azure env vars; otherwise we
    raise ``ValueError`` with a clear message naming the missing variables so
    misconfiguration surfaces at startup instead of at first request.
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

    if settings.retrieval_backend == RETRIEVAL_BACKEND_COSMOS:
        azure.require_cosmos()
    if (
        settings.session_backend == SESSION_BACKEND_COSMOS
        or settings.interaction_log_backend == INTERACTION_LOG_BACKEND_COSMOS
    ):
        azure.require_cosmos()


__all__ = [
    "AppSettings",
    "AzureKnowledgeSettings",
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
