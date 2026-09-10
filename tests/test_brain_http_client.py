from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from backend.app.config import AppSettings
from backend.app.services.brain_cite import (
    APPROVED_KNOWLEDGE_STATUSES,
    excerpts_to_citations,
    filter_approved_excerpts,
    is_approved_knowledge_status,
)
from backend.app.services.brain_http_client import (
    BrainFeedbackRequest,
    BrainHttpClient,
    BrainHttpError,
    RetrieveContextRequest,
    TroubleshootContextRequest,
    build_brain_http_client,
    safe_retrieve_context,
    safe_submit_feedback,
)


FIXTURES = Path(__file__).parent / "fixtures" / "brain_http"


def _settings(**overrides) -> AppSettings:
    base = dict(
        brain_http_base_url="http://brain.test",
        brain_http_enabled=True,
        brain_http_retrieve=True,
        brain_http_troubleshoot=True,
        brain_http_feedback=True,
        brain_http_reviews=False,
        brain_http_timeout_seconds=5.0,
        interaction_log_backend="memory",
        feedback_backend="memory",
        session_backend="memory",
        retrieval_backend="stub",
    )
    base.update(overrides)
    return AppSettings(**base)


def test_approved_knowledge_statuses() -> None:
    assert is_approved_knowledge_status("sme_approved")
    assert is_approved_knowledge_status("catalog_authoritative")
    assert not is_approved_knowledge_status("operational_unreviewed")
    assert not is_approved_knowledge_status("conflicting")
    assert "sme_approved" in APPROVED_KNOWLEDGE_STATUSES


def test_filter_approved_excerpts() -> None:
    rows = filter_approved_excerpts(
        [
            {"record_id": "a", "validation_status": "sme_approved", "text": "ok"},
            {"record_id": "b", "validation_status": "operational_unreviewed", "text": "no"},
        ]
    )
    assert [item["record_id"] for item in rows] == ["a"]
    citations = excerpts_to_citations(
        [{"record_id": "a", "validation_status": "sme_approved", "title": "T", "text": "body"}]
    )
    assert citations[0]["source_id"] == "a"
    assert citations[0]["excerpt"] == "body"


def test_excerpts_for_synthesis_skips_unapproved() -> None:
    from backend.app.services.brain_cite import excerpts_for_synthesis

    rows = excerpts_for_synthesis(
        [
            {
                "record_id": "claim:ok",
                "validation_status": "sme_approved",
                "title": "Heartbeat",
                "text": "Heartbeat Max above threshold may indicate tipper/WCS sync risk.",
                "record_type": "claim",
            },
            {
                "record_id": "claim:no",
                "validation_status": "operational_unreviewed",
                "title": "Skip when include_working false",
                "text": "Should not synthesize when working disabled.",
            },
        ],
        include_working=False,
    )
    assert len(rows) == 1
    assert rows[0]["source_id"] == "claim:ok"
    assert rows[0]["origin"] == "brain"
    assert "Heartbeat Max" in rows[0]["excerpt"]


def test_excerpts_for_synthesis_includes_working_labeled() -> None:
    from backend.app.services.brain_cite import excerpts_for_synthesis, excerpts_to_citations

    rows = excerpts_for_synthesis(
        [
            {
                "record_id": "claim:ok",
                "validation_status": "sme_approved",
                "title": "Approved claim",
                "text": "Approved tipper guidance.",
            }
        ],
        working_excerpts=[
            {
                "record_id": "entity:system:tipper_heartbeat_communication",
                "validation_status": "operational_unreviewed",
                "title": "tipper heartbeat communication",
                "text": "tipper heartbeat communication working note.",
                "record_type": "entity",
            }
        ],
        include_working=True,
    )
    assert len(rows) == 2
    working = rows[1]
    assert working["review_state"] == "operational_unreviewed"
    assert working["confidence"] < 1.0
    citations = excerpts_to_citations(
        [
            {
                "record_id": "entity:system:tipper_heartbeat_communication",
                "validation_status": "operational_unreviewed",
                "title": "tipper heartbeat communication",
                "text": "tipper heartbeat communication working note.",
                "record_type": "entity",
            }
        ],
        include_working=True,
    )
    assert citations
    assert "operational unreviewed" in citations[0]["title"].lower()
    assert "operational_unreviewed" in str(citations[0]["reference"])


def test_client_noop_when_disabled() -> None:
    client = build_brain_http_client(
        _settings(brain_http_enabled=False),
    )
    assert client.get_retrieve_context(RetrieveContextRequest(query="x")) is None
    assert (
        client.get_troubleshoot_context(
            TroubleshootContextRequest(query="x", session_id="s1")
        )
        is None
    )
    assert (
        client.submit_feedback(
            BrainFeedbackRequest(session_id="s1", interaction_id="i1")
        )
        is None
    )


def test_client_retrieve_parses_fixture() -> None:
    payload = json.loads((FIXTURES / "context_retrieve_response.json").read_text(encoding="utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/brain/v1/context/retrieve")
        body = json.loads(request.content.decode("utf-8"))
        assert body["query_text"] == "agv heartbeat"
        assert "query" not in body
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    client = BrainHttpClient(_settings(), transport=transport)
    result = client.get_retrieve_context(RetrieveContextRequest(query="agv heartbeat"))
    assert result is not None
    assert result.query_echo == "agv heartbeat"
    assert len(result.approved_excerpt_dicts()) == 1
    assert result.approved_excerpt_dicts()[0]["record_id"] == "claim:agv:heartbeat"


def test_client_troubleshoot_and_feedback_fixtures() -> None:
    retrieve = json.loads(
        (FIXTURES / "context_retrieve_response.json").read_text(encoding="utf-8")
    )
    feedback = json.loads(
        (FIXTURES / "feedback_response.json").read_text(encoding="utf-8")
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/brain/v1/context/troubleshoot"):
            body = json.loads(request.content.decode("utf-8"))
            assert body["session_id"] == "ts-1"
            assert "observed_signals" in body
            return httpx.Response(200, json=retrieve)
        if request.url.path.endswith("/brain/v1/feedback"):
            body = json.loads(request.content.decode("utf-8"))
            assert body["text"]
            assert body["interaction_id"] == "int-1"
            return httpx.Response(200, json=feedback)
        return httpx.Response(404, json={"detail": "missing"})

    client = BrainHttpClient(_settings(), transport=httpx.MockTransport(handler))
    ctx = client.get_troubleshoot_context(
        TroubleshootContextRequest(query="stuck tote", session_id="ts-1")
    )
    assert ctx is not None
    assert ctx.query_echo == "stuck tote"
    fb = client.submit_feedback(
        BrainFeedbackRequest(
            session_id="ts-1",
            interaction_id="int-1",
            sentiment="suggestion",
            user_text="wrong step",
        )
    )
    assert fb is not None
    assert fb.accepted is True
    assert fb.brain_review_id == "brain_review:demo"


def test_safe_helpers_swallow_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    client = BrainHttpClient(_settings(), transport=httpx.MockTransport(handler))
    assert (
        safe_retrieve_context(client, RetrieveContextRequest(query="x")) is None
    )
    failed = safe_submit_feedback(
        client, BrainFeedbackRequest(session_id="s", interaction_id="i")
    )
    assert failed is not None
    assert failed.accepted is False
    assert failed.status == "forward_failed"


def test_missing_base_url_raises_when_enabled() -> None:
    client = BrainHttpClient(_settings(brain_http_base_url=""))
    with pytest.raises(BrainHttpError):
        client.get_retrieve_context(RetrieveContextRequest(query="x"))


def test_warmup_skipped_when_disabled() -> None:
    from backend.app.services.brain_http_client import warmup_brain_http

    status = warmup_brain_http(settings=_settings(brain_http_enabled=False))
    assert status["ok"] is False
    assert status["skipped_reason"] == "brain_http_disabled"


def test_warmup_retrieve_probe(monkeypatch) -> None:
    from backend.app.services import brain_http_client as mod

    fixture = json.loads((FIXTURES / "context_retrieve_response.json").read_text(encoding="utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/brain/v1/context/retrieve")
        body = json.loads(request.content.decode("utf-8"))
        query = str(body.get("query_text") or body.get("query") or "")
        assert "warmup" in query.lower()
        return httpx.Response(200, json=fixture)

    client = BrainHttpClient(_settings(), transport=httpx.MockTransport(handler))
    result = client.warmup()
    assert result["ok"] is True
    assert result["path"] == "retrieve"
    assert result["elapsed_seconds"] is not None

    scheduled = mod.start_brain_warmup_background(
        settings=_settings(brain_http_enabled=False)
    )
    assert scheduled is False
