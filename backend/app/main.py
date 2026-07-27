from __future__ import annotations

import logging

from fastapi import FastAPI

from backend.app.api.corpus import router as corpus_router
from backend.app.api.images import router as images_router
from backend.app.api.retrieve import router as retrieve_router
from backend.app.api.troubleshoot import router as troubleshoot_router
from backend.app.corpus.bootstrap import reload_corpus_index
from backend.app.config.env import load_local_env
from backend.app.config import (
    get_app_settings,
    get_settings,
    RETRIEVAL_BACKEND_COSMOS,
    validate_runtime_mode,
)
from backend.app.corpus.settings import get_corpus_settings


logger = logging.getLogger(__name__)

load_local_env()


app = FastAPI(title="Optisweep AI Support Assistant Phase 0")
app.include_router(troubleshoot_router)
app.include_router(retrieve_router)
app.include_router(corpus_router)
app.include_router(images_router)


@app.on_event("startup")
def _validate_runtime_configuration() -> None:
    try:
        app_settings = get_app_settings()
        validate_runtime_mode(app_settings, get_settings())
    except ValueError as exc:
        logger.error(
            "Runtime configuration invalid; refusing to start: %s", exc
        )
        raise
    logger.info(
        "Runtime settings: session_backend=%s interaction_log_backend=%s retrieval_backend=%s",
        app_settings.session_backend,
        app_settings.interaction_log_backend,
        app_settings.retrieval_backend,
    )
    try:
        index = reload_corpus_index()
        corpus = get_corpus_settings()
        logger.info(
            "Corpus index loaded: source=%s version=%s embeddings=%s links=%s",
            corpus.corpus_source,
            index.publish_version_id,
            len(index.embeddings),
            len(index.links),
        )
        if app_settings.retrieval_backend == RETRIEVAL_BACKEND_COSMOS and len(index.embeddings) == 0:
            raise ValueError(
                "Cosmos corpus loaded zero embeddings. Check PUBLISH_VERSION_ID or set AUTO_PUBLISH_VERSION=true. "
                f"Resolved version={index.publish_version_id!r}."
            )
    except ValueError:
        raise
    except Exception as exc:
        logger.warning("Corpus index preload skipped: %s", exc)


@app.get("/health")
def health() -> dict[str, object]:
    corpus = get_corpus_settings()
    payload: dict[str, object] = {
        "status": "ok",
        "retrieval_backend": get_app_settings().retrieval_backend,
        "corpus_source": corpus.corpus_source,
    }
    try:
        from backend.app.corpus.bootstrap import get_corpus_index

        index = get_corpus_index()
        payload["publish_version_id"] = index.publish_version_id
        payload["embedding_total"] = len(index.embeddings)
        payload["gate_phrase_table_loaded"] = bool(index.gate_phrase_table)
    except Exception:
        payload["publish_version_id"] = corpus.publish_version_id
        payload["embedding_total"] = 0
    return payload


@app.get("/debug/settings")
def debug_settings() -> dict[str, object]:
    settings = get_app_settings()
    corpus = get_corpus_settings()
    return {
        "session_backend": settings.session_backend,
        "interaction_log_backend": settings.interaction_log_backend,
        "retrieval_backend": settings.retrieval_backend,
        "corpus_source": corpus.corpus_source,
        "publish_version_id": corpus.publish_version_id,
    }
