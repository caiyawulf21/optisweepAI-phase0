from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.app.corpus.settings import CorpusSettings

_lock = threading.Lock()
_resolved_version: str | None = None


def resolve_publish_version_id(settings: CorpusSettings) -> str:
    global _resolved_version
    configured = settings.publish_version_id
    if not settings.cosmos_configured:
        return configured
    if _resolved_version:
        return _resolved_version
    with _lock:
        if _resolved_version:
            return _resolved_version
        if settings.auto_publish_version and not _version_has_embeddings(settings, configured):
            discovered = _discover_latest_publish_version(settings)
            if discovered:
                _resolved_version = discovered
                return discovered
        if _version_has_embeddings(settings, configured):
            _resolved_version = configured
            return configured
        discovered = _discover_latest_publish_version(settings)
        _resolved_version = discovered or configured
        return _resolved_version


def reset_publish_version_cache() -> None:
    global _resolved_version
    with _lock:
        _resolved_version = None


def _version_has_embeddings(settings: CorpusSettings, version: str) -> bool:
    if not version:
        return False
    try:
        from backend.app.repositories.cosmos_client import cosmos_container

        container = cosmos_container(settings.container_playbooks_a)
        rows = list(
            container.query_items(
                query=(
                    "SELECT TOP 1 c.id FROM c WHERE c.publish_version_id = @version "
                    "AND c.doc_type = 'embedding'"
                ),
                parameters=[{"name": "@version", "value": version}],
                partition_key=version,
            )
        )
        return bool(rows)
    except Exception:
        return False


def _discover_latest_publish_version(settings: CorpusSettings) -> str | None:
    try:
        from backend.app.repositories.cosmos_client import cosmos_container

        container = cosmos_container(settings.container_playbooks_a)
        rows = list(
            container.query_items(
                query=(
                    "SELECT TOP 1 c.publish_version_id FROM c "
                    "WHERE IS_DEFINED(c.publish_version_id) AND c.doc_type = 'embedding' "
                    "ORDER BY c._ts DESC"
                ),
                enable_cross_partition_query=True,
            )
        )
        if not rows:
            return None
        value = str(rows[0].get("publish_version_id") or "").strip()
        return value or None
    except Exception:
        return None
