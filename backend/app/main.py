"""OptiSweep AI Support Assistant — FastAPI entry.

Primary runtime: Cosmos publish-corpus playbook troubleshoot + retrieve.
Optional Brain HTTP overlays are feature-flagged (see GET /debug/settings).
This process does not host Brain and does not write brain_* containers.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from backend.app.api.corpus import router as corpus_router
from backend.app.api.images import router as images_router
from backend.app.api.attachments import router as attachments_router
from backend.app.api.feedback import router as feedback_router
from backend.app.api.reviews import router as reviews_router
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


app = FastAPI(title="OptiSweep AI Support Assistant")
app.include_router(troubleshoot_router)
app.include_router(retrieve_router)
app.include_router(corpus_router)
app.include_router(images_router)
app.include_router(attachments_router)
app.include_router(feedback_router)
app.include_router(reviews_router)


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
        "Runtime settings: session_backend=%s interaction_log_backend=%s feedback_backend=%s retrieval_backend=%s",
        app_settings.session_backend,
        app_settings.interaction_log_backend,
        app_settings.feedback_backend,
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
    try:
        from backend.app.services.brain_http_client import start_brain_warmup_background

        start_brain_warmup_background(settings=app_settings)
    except Exception as exc:
        logger.warning("Brain HTTP warmup schedule skipped: %s", exc)


@app.get("/health")
def health() -> dict[str, object]:
    corpus = get_corpus_settings()
    payload: dict[str, object] = {
        "status": "ok",
        "retrieval_backend": get_app_settings().retrieval_backend,
        "corpus_source": corpus.corpus_source,
        "cosmos_configured": corpus.cosmos_configured,
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
    from backend.app.services.brain_http_client import get_brain_warmup_status
    from backend.app.services.llm_playbook_client import llm_available

    return {
        "session_backend": settings.session_backend,
        "interaction_log_backend": settings.interaction_log_backend,
        "feedback_backend": settings.feedback_backend,
        "retrieval_backend": settings.retrieval_backend,
        "brain_http_enabled": settings.brain_http_enabled,
        "brain_http_retrieve": settings.brain_http_retrieve,
        "brain_http_troubleshoot": settings.brain_http_troubleshoot,
        "brain_http_feedback": settings.brain_http_feedback,
        "brain_http_reviews": settings.brain_http_reviews,
        "brain_http_base_url": settings.brain_http_base_url or None,
        "brain_http_timeout_seconds": settings.brain_http_timeout_seconds,
        "brain_http_warmup_on_startup": settings.brain_http_warmup_on_startup,
        "brain_http_warmup_status": get_brain_warmup_status(),
        "corpus_source": corpus.corpus_source,
        "cosmos_configured": corpus.cosmos_configured,
        "publish_version_id": corpus.publish_version_id,
        "auto_publish_version": corpus.auto_publish_version,
        "enable_llm_retrieve_synthesis": corpus.enable_llm_retrieve_synthesis,
        "llm_available": llm_available(),
        "demo_mode": settings.demo_mode,
    }
