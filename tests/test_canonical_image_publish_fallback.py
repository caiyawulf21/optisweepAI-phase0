from __future__ import annotations

from backend.app.repositories import canonical_image_repository as cir


class _FakeContainer:
    def __init__(self, *, preferred_empty: bool = True) -> None:
        self.preferred_empty = preferred_empty
        self.calls: list[dict] = []

    def query_items(self, **kwargs):
        self.calls.append(kwargs)
        query = str(kwargs.get("query") or "")
        partition = kwargs.get("partition_key")
        if "ORDER BY c._ts DESC" in query and kwargs.get("enable_cross_partition_query"):
            return [{"publish_version_id": "publish_images_old"}]
        if partition == "publish_current" and self.preferred_empty:
            return []
        if partition == "publish_current":
            return [{"image_id": "img_current"}]
        if partition == "publish_images_old":
            return [{"image_id": "img_old"}]
        return []


def test_resolve_images_publish_version_falls_back_when_current_empty(monkeypatch) -> None:
    cir.reset_images_publish_version_cache()
    fake = _FakeContainer(preferred_empty=True)

    class _Settings:
        publish_version_id = "publish_current"
        container_canonical_images = "publish_canonical_images"
        cosmos_configured = True
        auto_publish_version = False

    monkeypatch.setattr(cir, "get_corpus_settings", lambda: _Settings())
    monkeypatch.setattr(cir, "resolve_publish_version_id", lambda _settings: "publish_current")
    monkeypatch.setattr(cir, "cosmos_container", lambda _name: fake)

    assert cir.resolve_images_publish_version_id() == "publish_images_old"
    cir.reset_images_publish_version_cache()


def test_resolve_images_publish_version_keeps_current_when_populated(monkeypatch) -> None:
    cir.reset_images_publish_version_cache()
    fake = _FakeContainer(preferred_empty=False)

    class _Settings:
        publish_version_id = "publish_current"
        container_canonical_images = "publish_canonical_images"
        cosmos_configured = True
        auto_publish_version = False

    monkeypatch.setattr(cir, "get_corpus_settings", lambda: _Settings())
    monkeypatch.setattr(cir, "resolve_publish_version_id", lambda _settings: "publish_current")
    monkeypatch.setattr(cir, "cosmos_container", lambda _name: fake)

    assert cir.resolve_images_publish_version_id() == "publish_current"
    cir.reset_images_publish_version_cache()
