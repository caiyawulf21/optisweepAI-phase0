from __future__ import annotations

import pytest

from backend.app.config import (
    AppSettings,
    AzureKnowledgeSettings,
    INTERACTION_LOG_BACKEND_COSMOS,
    INTERACTION_LOG_BACKEND_DISABLED,
    INTERACTION_LOG_BACKEND_MEMORY,
    RETRIEVAL_BACKEND_COSMOS,
    RETRIEVAL_BACKEND_STUB,
    SESSION_BACKEND_COSMOS,
    SESSION_BACKEND_MEMORY,
    validate_runtime_mode,
)


_RUNTIME_ENV_VARS = (
    "APP_ENV",
    "DEMO_MODE",
    "WORKFLOW_CONFIDENCE_THRESHOLD",
    "USE_CANONICAL_ROUTING",
    "RETRIEVAL_BACKEND",
    "SESSION_BACKEND",
    "INTERACTION_LOG_BACKEND",
    "ENABLE_GUIDED_DIAGNOSTIC",
    "ENABLE_CANONICAL_WORKFLOW_RUNTIME",
    "COSMOS_ENDPOINT",
    "COSMOS_KEY",
    "AZURE_COSMOS_ENDPOINT",
    "AZURE_COSMOS_KEY",
)


@pytest.fixture(autouse=True)
def _clean_runtime_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _RUNTIME_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _empty_azure_settings() -> AzureKnowledgeSettings:
    return AzureKnowledgeSettings(
        cosmos_endpoint=None,
        cosmos_key=None,
        search_endpoint=None,
        search_key=None,
        storage_account_url=None,
        storage_connection_string=None,
    )


def _populated_azure_settings() -> AzureKnowledgeSettings:
    return AzureKnowledgeSettings(
        cosmos_endpoint="https://cosmos.example.com/",
        cosmos_key="cosmos-key",
        search_endpoint="https://search.example.com/",
        search_key="search-key",
        storage_account_url=None,
        storage_connection_string=None,
    )


def test_defaults_use_stub_retrieval() -> None:
    settings = AppSettings()
    assert settings.retrieval_backend == RETRIEVAL_BACKEND_STUB
    assert settings.session_backend == SESSION_BACKEND_MEMORY
    assert settings.interaction_log_backend == INTERACTION_LOG_BACKEND_MEMORY


def test_cosmos_creds_default_session_and_logs_to_cosmos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COSMOS_ENDPOINT", "https://cosmos.example.com/")
    monkeypatch.setenv("COSMOS_KEY", "cosmos-key")
    settings = AppSettings()
    assert settings.session_backend == SESSION_BACKEND_COSMOS
    assert settings.interaction_log_backend == INTERACTION_LOG_BACKEND_COSMOS
    assert settings.retrieval_backend == RETRIEVAL_BACKEND_COSMOS


def test_stub_mode_boots_without_azure_env() -> None:
    settings = AppSettings()
    validate_runtime_mode(settings, _empty_azure_settings())


def test_cosmos_retrieval_backend_requires_cosmos_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RETRIEVAL_BACKEND", "cosmos")
    settings = AppSettings()
    with pytest.raises(ValueError) as excinfo:
        validate_runtime_mode(settings, _empty_azure_settings())
    message = str(excinfo.value)
    assert "COSMOS_ENDPOINT" in message
    assert "COSMOS_KEY" in message


def test_cosmos_retrieval_backend_boots_with_cosmos_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RETRIEVAL_BACKEND", "cosmos")
    settings = AppSettings()
    validate_runtime_mode(settings, _populated_azure_settings())


def test_unknown_retrieval_backend_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RETRIEVAL_BACKEND", "azure_search")
    settings = AppSettings()
    with pytest.raises(ValueError) as excinfo:
        validate_runtime_mode(settings, _populated_azure_settings())
    assert "RETRIEVAL_BACKEND" in str(excinfo.value)
