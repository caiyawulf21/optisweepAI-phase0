from __future__ import annotations

import threading

from backend.app.corpus.cosmos_client import CosmosCorpusClient
from backend.app.corpus.models import CorpusIndex
from backend.app.corpus.publish_version import reset_publish_version_cache

_client_lock = threading.Lock()
_index_lock = threading.Lock()
_client: CosmosCorpusClient | None = None
_index: CorpusIndex | None = None


def get_corpus_client() -> CosmosCorpusClient:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = CosmosCorpusClient()
    return _client


def get_corpus_index(*, force: bool = False) -> CorpusIndex:
    global _index
    if _index is None or force:
        with _index_lock:
            if _index is None or force:
                _index = get_corpus_client().load_index(force=force)
    return _index


def reload_corpus_index() -> CorpusIndex:
    global _index
    with _index_lock:
        _index = get_corpus_client().load_index(force=True)
    return _index


def reset_corpus_cache() -> None:
    global _client, _index
    with _client_lock:
        with _index_lock:
            _client = None
            _index = None
    reset_publish_version_cache()
    from backend.app.repositories.canonical_image_repository import (
        reset_images_publish_version_cache,
    )

    reset_images_publish_version_cache()
