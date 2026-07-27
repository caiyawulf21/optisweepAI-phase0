from __future__ import annotations

import logging
import threading

from backend.app.corpus.cosmos_client import CosmosCorpusClient
from backend.app.corpus.models import CorpusIndex
from backend.app.corpus.publish_version import (
    reset_publish_version_cache,
    resolve_publish_version_id,
)

logger = logging.getLogger(__name__)

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


def _install_gate_extractor(index: CorpusIndex) -> None:
    from backend.app.services.gate_phrase_loader import (
        install_extractor_from_gate_phrase_table,
    )

    source = install_extractor_from_gate_phrase_table(index.gate_phrase_table)
    logger.info(
        "First-turn gate extractor source=%s publish_version=%s",
        source,
        index.publish_version_id,
    )


def get_corpus_index(*, force: bool = False) -> CorpusIndex:
    global _index
    if _index is None or force:
        with _index_lock:
            if _index is None or force:
                _index = get_corpus_client().load_index(force=force)
                _install_gate_extractor(_index)
    return _index


def reload_corpus_index() -> CorpusIndex:
    global _index
    reset_publish_version_cache()
    with _index_lock:
        client = get_corpus_client()
        client._publish_version_id = resolve_publish_version_id(client.settings)
        _index = client.load_index(force=True)
        _install_gate_extractor(_index)
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
    from backend.app.services.keyword_signal_extractor import reset_for_tests

    reset_images_publish_version_cache()
    reset_for_tests()
