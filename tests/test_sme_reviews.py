from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.config import AppSettings
from backend.app.main import app
from backend.app.services.brain_http_client import (
    BrainHttpClient,
    BrainResolveRequest,
    build_brain_http_client,
)
from backend.app.services.review_ui import (
    format_resolve_outcome,
    review_effective_id,
    review_queue_label,
)


FIXTURES = Path(__file__).parent / "fixtures" / "brain_http"


def _settings(**overrides) -> AppSettings:
    base = dict(
        brain_http_base_url="http://brain.test",
        brain_http_enabled=True,
        brain_http_retrieve=True,
        brain_http_troubleshoot=True,
        brain_http_feedback=True,
        brain_http_reviews=True,
        brain_http_timeout_seconds=5.0,
        interaction_log_backend="memory",
        feedback_backend="memory",
        session_backend="memory",
        retrieval_backend="stub",
    )
    base.update(overrides)
    return AppSettings(**base)


def test_format_resolve_outcome_merge_and_retype() -> None:
    merge = json.loads((FIXTURES / "resolve_merge_response.json").read_text(encoding="utf-8"))
    level, message = format_resolve_outcome(merge)
    assert level == "success"
    assert "entity:symptom:agv_heartbeat" in message

    retype = json.loads((FIXTURES / "resolve_retype_response.json").read_text(encoding="utf-8"))
    level, message = format_resolve_outcome(retype)
    assert level == "warning"
    assert "not" in message.lower()

    level, message = format_resolve_outcome(
        {
            "status": "resolved",
            "resolution": "approve",
            "applied": False,
            "message": "RECLASSIFY not applied",
            "mutated_record_ids": [],
        }
    )
    assert level == "warning"

    level, message = format_resolve_outcome(
        {"status": "resolved", "resolution": "reject", "applied": False, "mutated_record_ids": []}
    )
    assert level == "info"


def test_review_queue_helpers() -> None:
    row = {
        "review_id": "brain_review:x",
        "kind": "conflict",
        "status": "open",
        "title": "Disputed claim",
    }
    assert review_effective_id(row) == "brain_review:x"
    assert "conflict" in review_queue_label(row)
    assert "Disputed claim" in review_queue_label(row)


def test_format_proposed_change_and_affected_records() -> None:
    from backend.app.services.review_ui import (
        format_affected_records,
        format_proposed_change_card,
    )

    detail = json.loads((FIXTURES / "review_detail_response.json").read_text(encoding="utf-8"))
    card = format_proposed_change_card(detail["proposed_change"])
    assert card["action"] == "MERGE"
    assert "agv_heartbeat" in card["headline"]
    rows = format_affected_records(
        affected_records=detail["affected_records"],
        affected_record_ids=detail["affected_record_ids"],
        proposed=detail["proposed_change"],
    )
    assert any(row["role"] == "Keep" for row in rows)
    assert any(row["role"] == "Merge away" for row in rows)


def test_client_list_get_resolve_reviews() -> None:
    listing = json.loads((FIXTURES / "reviews_list_response.json").read_text(encoding="utf-8"))
    merge = json.loads((FIXTURES / "resolve_merge_response.json").read_text(encoding="utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/brain/v1/reviews") and request.method == "GET":
            return httpx.Response(200, json=listing)
        if path.endswith("/brain/v1/reviews/brain_review:merge-1") and request.method == "GET":
            return httpx.Response(404, json={"detail": "no detail route"})
        if path.endswith("/brain/v1/reviews/brain_review:merge-1/resolve"):
            body = json.loads(request.content.decode("utf-8"))
            assert "resolution" not in body  # approve omits → use proposed MERGE
            return httpx.Response(200, json=merge)
        return httpx.Response(404, json={"detail": path})

    client = BrainHttpClient(_settings(), transport=httpx.MockTransport(handler))
    listed = client.list_reviews(status="open", limit=50)
    assert listed is not None
    assert listed.total == 2
    assert listed.reviews[0].effective_id() == "brain_review:merge-1"

    got = client.get_review("brain_review:merge-1")
    assert got is not None
    assert got.effective_id() == "brain_review:merge-1"

    resolved = client.resolve_review(
        "brain_review:merge-1",
        BrainResolveRequest(resolution="approve", reviewer_id="sme-1"),
    )
    assert resolved is not None
    assert resolved.applied is True
    assert resolved.mutated_record_ids


def test_client_reviews_noop_when_flag_off() -> None:
    client = build_brain_http_client(_settings(brain_http_reviews=False))
    assert client.list_reviews() is None
    assert client.get_review("brain_review:x") is None
    assert (
        client.resolve_review("brain_review:x", BrainResolveRequest(resolution="approve"))
        is None
    )


def test_reviews_api_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    listing = json.loads((FIXTURES / "reviews_list_response.json").read_text(encoding="utf-8"))
    detail = json.loads((FIXTURES / "review_detail_response.json").read_text(encoding="utf-8"))
    retype = json.loads((FIXTURES / "resolve_retype_response.json").read_text(encoding="utf-8"))
    settings = _settings()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/brain/v1/reviews") and request.method == "GET":
            return httpx.Response(200, json=listing)
        if "/brain/v1/reviews/" in path and path.endswith("/resolve"):
            return httpx.Response(200, json=retype)
        if "/brain/v1/reviews/" in path and request.method == "GET":
            return httpx.Response(200, json=detail)
        return httpx.Response(404, json={"detail": path})

    transport = httpx.MockTransport(handler)

    monkeypatch.setattr(
        "backend.app.api.reviews.get_app_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "backend.app.api.reviews.build_brain_http_client",
        lambda settings=None: BrainHttpClient(settings or _settings(), transport=transport),
    )

    client = TestClient(app)
    listed = client.get("/reviews", params={"status": "open", "limit": 20})
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 2
    assert body["reviews"][0]["review_id"] == "brain_review:merge-1"

    got = client.get("/reviews/brain_review:merge-1")
    assert got.status_code == 200
    assert got.json()["kind"] == "audit_finding"

    resolved = client.post(
        "/reviews/brain_review:retype-1/resolve",
        json={"resolution": "approve", "reviewer_id": "sme-1", "notes": "ok later"},
    )
    assert resolved.status_code == 200
    payload = resolved.json()
    assert payload["outcome_level"] == "warning"
    assert "not" in payload["outcome_message"].lower()


def test_reviews_api_disabled() -> None:
    with patch(
        "backend.app.api.reviews.get_app_settings",
        return_value=_settings(brain_http_reviews=False),
    ):
        client = TestClient(app)
        response = client.get("/reviews")
        assert response.status_code == 503
