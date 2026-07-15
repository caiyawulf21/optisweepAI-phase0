from __future__ import annotations

import threading
from typing import Any

from backend.app.corpus.publish_version import resolve_publish_version_id
from backend.app.corpus.settings import get_corpus_settings
from backend.app.repositories.base_repository import CosmosRepository
from backend.app.repositories.cosmos_client import cosmos_container

_images_version_lock = threading.Lock()
_images_publish_version: str | None = None


def reset_images_publish_version_cache() -> None:
    global _images_publish_version
    with _images_version_lock:
        _images_publish_version = None


def resolve_images_publish_version_id(settings: Any | None = None) -> str:
    """Prefer the corpus publish that actually contains canonical image docs.

    Playbook/runbook publishes can advance before images are recopied into
    ``publish_canonical_images``. Lookup then falls back to the newest image
    partition that still has rows.
    """
    global _images_publish_version
    active = settings or get_corpus_settings()
    preferred = resolve_publish_version_id(active)
    if _images_publish_version:
        return _images_publish_version
    with _images_version_lock:
        if _images_publish_version:
            return _images_publish_version
        container = cosmos_container(
            active.container_canonical_images or "publish_canonical_images"
        )
        if preferred and _partition_has_images(container, preferred):
            _images_publish_version = preferred
            return preferred
        rows = list(
            container.query_items(
                query=(
                    "SELECT TOP 1 c.publish_version_id FROM c "
                    "WHERE IS_DEFINED(c.publish_version_id) AND IS_DEFINED(c.image_id) "
                    "ORDER BY c._ts DESC"
                ),
                enable_cross_partition_query=True,
            )
        )
        discovered = str((rows[0] or {}).get("publish_version_id") or "").strip() if rows else ""
        _images_publish_version = discovered or preferred
        return _images_publish_version


def _partition_has_images(container: Any, version: str) -> bool:
    if not version:
        return False
    try:
        rows = list(
            container.query_items(
                query=(
                    "SELECT TOP 1 c.image_id FROM c "
                    "WHERE c.publish_version_id = @version AND IS_DEFINED(c.image_id)"
                ),
                parameters=[{"name": "@version", "value": version}],
                partition_key=version,
            )
        )
        return bool(rows)
    except Exception:
        return False


class CanonicalImageRepository(CosmosRepository):
    container_name = "publish_canonical_images"

    def __init__(self, container: Any | None = None) -> None:
        settings = get_corpus_settings()
        self.container_name = settings.container_canonical_images or self.container_name
        self._publish_version_id = resolve_images_publish_version_id(settings)
        super().__init__(container=container or cosmos_container(self.container_name))

    @property
    def publish_version_id(self) -> str:
        return self._publish_version_id

    def get_by_image_id(self, image_id: str) -> dict[str, Any] | None:
        if not image_id:
            return None
        records = self.query(
            """
            SELECT TOP 1 * FROM c
            WHERE c.publish_version_id = @version
              AND c.image_id = @image_id
            """,
            parameters=[
                {"name": "@version", "value": self._publish_version_id},
                {"name": "@image_id", "value": image_id},
            ],
        )
        if records:
            return records[0]
        # Last-resort lookup when image partitions are newer/older than cache.
        rows = list(
            self.container.query_items(
                query=(
                    "SELECT TOP 1 * FROM c WHERE c.image_id = @image_id "
                    "ORDER BY c._ts DESC"
                ),
                parameters=[{"name": "@image_id", "value": image_id}],
                enable_cross_partition_query=True,
            )
        )
        return rows[0] if rows else None

    def query(
        self,
        query: str,
        parameters: list[dict[str, Any]] | None = None,
        cross_partition: bool = True,
    ) -> list[dict[str, Any]]:
        del cross_partition
        return list(
            self.container.query_items(
                query=query,
                parameters=parameters or [],
                partition_key=self._publish_version_id,
            )
        )
