from __future__ import annotations

import os

import pytest

from backend.app.corpus.bootstrap import reset_corpus_cache
from backend.app.services.session_service import reset_for_tests as reset_session_service

_PLAYBOOK_TEST_ENV = {
    "RETRIEVAL_BACKEND": "stub",
    "SESSION_BACKEND": "memory",
    "INTERACTION_LOG_BACKEND": "memory",
    "AUTO_PUBLISH_VERSION": "false",
    "COSMOS_ENDPOINT": "",
    "COSMOS_KEY": "",
    "AZURE_COSMOS_ENDPOINT": "",
    "AZURE_COSMOS_KEY": "",
}


@pytest.fixture(autouse=True)
def _playbook_test_env(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("cosmos_e2e"):
        yield
        return
    if os.getenv("COSMOS_E2E", "").strip().lower() in {"1", "true", "yes"}:
        yield
        return
    for name, value in _PLAYBOOK_TEST_ENV.items():
        monkeypatch.setenv(name, value)
    reset_corpus_cache()
    reset_session_service()
    yield
    reset_corpus_cache()
    reset_session_service()
