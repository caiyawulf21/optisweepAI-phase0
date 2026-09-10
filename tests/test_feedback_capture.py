from __future__ import annotations

from backend.app.config import (
    FEEDBACK_BACKEND_MEMORY,
    INTERACTION_LOG_BACKEND_MEMORY,
    AppSettings,
)
from backend.app.services.attachment_service import (
    AttachmentService,
    InMemoryAttachmentStore,
    enrich_user_message,
    reset_attachment_service_for_tests,
)
from backend.app.services.feedback_service import (
    FeedbackEvent,
    build_feedback_service,
    reset_feedback_for_tests,
)
from backend.app.services.interaction_log_service import (
    InteractionLog,
    build_interaction_log_service,
    reset_for_tests as reset_interaction_logs,
)
from backend.app.services.vision_service import (
    AzureComputerVisionClient,
    VisionAnalysis,
    compose_image_summary,
)


def setup_function() -> None:
    reset_attachment_service_for_tests()
    reset_feedback_for_tests()
    reset_interaction_logs()


def test_compose_image_summary_fuses_description_and_vision() -> None:
    summary = compose_image_summary(
        user_description="Heartbeat Max is red on Operator Station",
        vision=VisionAnalysis(
            caption="industrial HMI screen",
            ocr_text="Heartbeat Max 12.4",
            tags=["monitor", "dashboard"],
            status="ok",
        ),
    )
    assert "User description: Heartbeat Max is red on Operator Station." in summary
    assert "Image appears to show: industrial HMI screen." in summary
    assert "Visible text includes: Heartbeat Max 12.4." in summary
    assert "Detected tags: monitor, dashboard." in summary


def test_compose_image_summary_falls_back_when_vision_fails() -> None:
    summary = compose_image_summary(
        user_description="RMS shows a fault",
        vision=VisionAnalysis(status="failed"),
    )
    assert "RMS shows a fault" in summary
    assert "Computer Vision analysis failed" in summary


def test_enrich_user_message_appends_image_summaries() -> None:
    enriched = enrich_user_message("AGVs stopped", ["screen shows fault code 12"])
    assert enriched.startswith("AGVs stopped")
    assert "[Image summary] screen shows fault code 12" in enriched


def test_attachment_upload_uses_vision_client_and_stores_summary() -> None:
    def _transport(url, image_bytes, headers):
        del url, image_bytes, headers
        return {
            "captionResult": {"text": "server rack"},
            "tagsResult": {"values": [{"name": "electronics"}]},
            "readResult": {"blocks": [{"lines": [{"text": "WCS ONLINE"}]}]},
        }

    vision = AzureComputerVisionClient(
        endpoint="https://example.cognitiveservices.azure.com",
        key="fake",
        transport=_transport,
    )
    service = AttachmentService(store=InMemoryAttachmentStore(), vision_client=vision)
    attachment = service.upload(
        session_id="ts-1",
        filename="shot.png",
        content_type="image/png",
        image_bytes=b"fake-bytes",
        source="troubleshoot",
        user_description="WCS looks stuck",
    )
    assert attachment.vision_status == "ok"
    assert "WCS looks stuck" in attachment.image_summary
    assert "server rack" in attachment.image_summary
    assert "WCS ONLINE" in attachment.image_summary
    assert service.get(attachment.attachment_id) is not None


def test_attachment_upload_degrades_when_vision_not_configured() -> None:
    vision = AzureComputerVisionClient(endpoint="", key="")
    service = AttachmentService(store=InMemoryAttachmentStore(), vision_client=vision)
    attachment = service.upload(
        session_id="ts-1",
        filename="shot.png",
        content_type="image/png",
        image_bytes=b"fake-bytes",
        user_description="tipper timeout",
    )
    assert attachment.vision_status == "failed"
    assert "tipper timeout" in attachment.image_summary


def test_feedback_service_records_and_lists() -> None:
    settings = AppSettings(
        interaction_log_backend=INTERACTION_LOG_BACKEND_MEMORY,
        feedback_backend=FEEDBACK_BACKEND_MEMORY,
    )
    service = build_feedback_service(settings)
    event = FeedbackEvent(
        session_id="ts-1",
        interaction_id="int-1",
        sentiment="suggestion",
        user_text="Step is wrong",
        proposed_change="Check RMS first",
    )
    assert service.record(event) is True
    rows = service.list_for_session("ts-1")
    assert len(rows) == 1
    assert rows[0].user_text == "Step is wrong"


def test_interaction_log_links_feedback_id() -> None:
    settings = AppSettings(interaction_log_backend=INTERACTION_LOG_BACKEND_MEMORY)
    logs = build_interaction_log_service(settings)
    log = InteractionLog(session_id="ts-1", user_message="hello", surface="troubleshoot")
    assert logs.record(log) is True
    assert logs.append_feedback_id("ts-1", log.interaction_id, "feedback:abc") is True
    stored = logs.get("ts-1", log.interaction_id)
    assert stored is not None
    assert "feedback:abc" in stored.feedback_event_ids


def test_feedback_api_and_attachment_api(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    reset_attachment_service_for_tests()
    reset_feedback_for_tests()
    reset_interaction_logs()
    monkeypatch.setenv("INTERACTION_LOG_BACKEND", "memory")
    monkeypatch.setenv("FEEDBACK_BACKEND", "memory")
    monkeypatch.setenv("SESSION_BACKEND", "memory")
    monkeypatch.setenv("RETRIEVAL_BACKEND", "stub")

    from backend.app.main import app
    from backend.app.services.attachment_service import build_attachment_service
    from backend.app.services.interaction_log_service import build_interaction_log_service
    from backend.app.services.vision_service import AzureComputerVisionClient

    def _transport(url, image_bytes, headers):
        del url, image_bytes, headers
        return {"captionResult": {"text": "hmi"}, "tagsResult": {"values": []}, "readResult": {}}

    vision = AzureComputerVisionClient(
        endpoint="https://example.cognitiveservices.azure.com",
        key="fake",
        transport=_transport,
    )
    monkeypatch.setattr(
        "backend.app.api.attachments.build_attachment_service",
        lambda: build_attachment_service(use_blob=False, vision_client=vision),
    )
    monkeypatch.setattr(
        "backend.app.api.feedback.build_attachment_service",
        lambda: build_attachment_service(use_blob=False, vision_client=vision),
    )

    client = TestClient(app)
    logs = build_interaction_log_service(
        AppSettings(interaction_log_backend=INTERACTION_LOG_BACKEND_MEMORY)
    )
    log = InteractionLog(session_id="ts-api", user_message="agvs stopped")
    logs.record(log)

    upload = client.post(
        "/attachments/upload",
        data={
            "session_id": "ts-api",
            "source": "troubleshoot",
            "user_description": "red alarm",
        },
        files={"file": ("shot.png", b"abc", "image/png")},
    )
    assert upload.status_code == 200, upload.text
    body = upload.json()
    assert body["vision_status"] == "ok"
    assert "red alarm" in body["image_summary"]

    feedback = client.post(
        "/feedback",
        json={
            "session_id": "ts-api",
            "interaction_id": log.interaction_id,
            "surface": "troubleshoot",
            "sentiment": "suggestion",
            "user_text": "wrong step",
            "proposed_change": "restart tipper service",
            "attachment_ids": [body["attachment_id"]],
        },
    )
    assert feedback.status_code == 200, feedback.text
    assert feedback.json()["accepted"] is True
    assert feedback.json()["brain_handoff_status"] == "deferred"

    listed = client.get(f"/feedback/sessions/ts-api")
    assert listed.status_code == 200
    assert len(listed.json()["feedback"]) == 1
