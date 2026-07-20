from __future__ import annotations

from types import SimpleNamespace

from backend.app.corpus import publish_version as pv


def _settings(*, auto: bool, configured: str = "publish_old") -> SimpleNamespace:
    return SimpleNamespace(
        cosmos_configured=True,
        auto_publish_version=auto,
        publish_version_id=configured,
        container_playbooks_a="playbooks_prompt_a",
    )


def test_auto_publish_prefers_latest_even_when_configured_has_embeddings(monkeypatch):
    pv.reset_publish_version_cache()
    monkeypatch.setattr(pv, "_version_has_embeddings", lambda _s, _v: True)
    monkeypatch.setattr(pv, "_discover_latest_publish_version", lambda _s: "publish_new")

    resolved = pv.resolve_publish_version_id(_settings(auto=True, configured="publish_old"))
    assert resolved == "publish_new"


def test_auto_publish_falls_back_to_configured_when_discovery_empty(monkeypatch):
    pv.reset_publish_version_cache()
    monkeypatch.setattr(pv, "_discover_latest_publish_version", lambda _s: None)

    resolved = pv.resolve_publish_version_id(_settings(auto=True, configured="publish_old"))
    assert resolved == "publish_old"


def test_pinned_publish_keeps_configured_when_it_has_embeddings(monkeypatch):
    pv.reset_publish_version_cache()
    monkeypatch.setattr(pv, "_version_has_embeddings", lambda _s, _v: True)
    monkeypatch.setattr(pv, "_discover_latest_publish_version", lambda _s: "publish_new")

    resolved = pv.resolve_publish_version_id(_settings(auto=False, configured="publish_old"))
    assert resolved == "publish_old"


def test_pinned_publish_discovers_when_configured_empty(monkeypatch):
    pv.reset_publish_version_cache()
    monkeypatch.setattr(pv, "_version_has_embeddings", lambda _s, _v: False)
    monkeypatch.setattr(pv, "_discover_latest_publish_version", lambda _s: "publish_new")

    resolved = pv.resolve_publish_version_id(_settings(auto=False, configured="publish_old"))
    assert resolved == "publish_new"


def test_resolve_caches_until_reset(monkeypatch):
    pv.reset_publish_version_cache()
    calls = {"n": 0}

    def _discover(_s):
        calls["n"] += 1
        return "publish_new"

    monkeypatch.setattr(pv, "_discover_latest_publish_version", _discover)
    settings = _settings(auto=True)
    assert pv.resolve_publish_version_id(settings) == "publish_new"
    assert pv.resolve_publish_version_id(settings) == "publish_new"
    assert calls["n"] == 1
    pv.reset_publish_version_cache()
    assert pv.resolve_publish_version_id(settings) == "publish_new"
    assert calls["n"] == 2
