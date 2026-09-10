from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from backend.app.config.settings import AzureKnowledgeSettings, get_settings
from backend.app.services.vision_service import (
    AzureComputerVisionClient,
    VisionAnalysis,
    build_vision_client,
    compose_image_summary,
)


logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_attachment_id() -> str:
    return f"att:{uuid.uuid4().hex}"


@dataclass
class UserAttachment:
    attachment_id: str = field(default_factory=_new_attachment_id)
    session_id: str = ""
    content_type: str = "application/octet-stream"
    filename: str = "upload.bin"
    blob_container: str = ""
    blob_path: str = ""
    storage_uri: str | None = None
    created_at: str = field(default_factory=_utcnow_iso)
    source: str = "troubleshoot"
    user_description: str = ""
    vision: dict[str, Any] = field(default_factory=dict)
    image_summary: str = ""
    vision_status: str = "skipped"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.attachment_id,
            "attachment_id": self.attachment_id,
            "session_id": self.session_id,
            "content_type": self.content_type,
            "filename": self.filename,
            "blob_container": self.blob_container,
            "blob_path": self.blob_path,
            "storage_uri": self.storage_uri,
            "created_at": self.created_at,
            "source": self.source,
            "user_description": self.user_description,
            "vision": dict(self.vision),
            "image_summary": self.image_summary,
            "vision_status": self.vision_status,
        }

    @classmethod
    def from_dict(cls, document: dict[str, Any]) -> "UserAttachment":
        return cls(
            attachment_id=str(
                document.get("attachment_id") or document.get("id") or _new_attachment_id()
            ),
            session_id=str(document.get("session_id") or ""),
            content_type=str(document.get("content_type") or "application/octet-stream"),
            filename=str(document.get("filename") or "upload.bin"),
            blob_container=str(document.get("blob_container") or ""),
            blob_path=str(document.get("blob_path") or ""),
            storage_uri=document.get("storage_uri"),
            created_at=str(document.get("created_at") or _utcnow_iso()),
            source=str(document.get("source") or "troubleshoot"),
            user_description=str(document.get("user_description") or ""),
            vision=dict(document.get("vision") or {}),
            image_summary=str(document.get("image_summary") or ""),
            vision_status=str(document.get("vision_status") or "skipped"),
        )


class AttachmentStore:
    def save(self, attachment: UserAttachment, image_bytes: bytes | None = None) -> None:
        raise NotImplementedError

    def get(self, attachment_id: str) -> UserAttachment | None:
        return None

    def get_bytes(self, attachment_id: str) -> bytes | None:
        return None


class InMemoryAttachmentStore(AttachmentStore):
    def __init__(self) -> None:
        self._items: dict[str, UserAttachment] = {}
        self._bytes: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def save(self, attachment: UserAttachment, image_bytes: bytes | None = None) -> None:
        with self._lock:
            self._items[attachment.attachment_id] = attachment
            if image_bytes is not None:
                self._bytes[attachment.attachment_id] = image_bytes

    def get(self, attachment_id: str) -> UserAttachment | None:
        with self._lock:
            return self._items.get(attachment_id)

    def get_bytes(self, attachment_id: str) -> bytes | None:
        with self._lock:
            return self._bytes.get(attachment_id)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._bytes.clear()


class BlobAttachmentStore(AttachmentStore):
    """Persists metadata in-process and bytes in Azure Blob (MVP metadata cache)."""

    def __init__(
        self,
        *,
        settings: AzureKnowledgeSettings | None = None,
        memory: InMemoryAttachmentStore | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._memory = memory or InMemoryAttachmentStore()

    def save(self, attachment: UserAttachment, image_bytes: bytes | None = None) -> None:
        if image_bytes is not None:
            try:
                self._upload_blob(attachment, image_bytes)
            except Exception:
                logger.warning(
                    "attachment_blob_upload_failed id=%s",
                    attachment.attachment_id,
                    exc_info=True,
                )
                raise
        self._memory.save(attachment, image_bytes)

    def get(self, attachment_id: str) -> UserAttachment | None:
        return self._memory.get(attachment_id)

    def get_bytes(self, attachment_id: str) -> bytes | None:
        cached = self._memory.get_bytes(attachment_id)
        if cached is not None:
            return cached
        attachment = self._memory.get(attachment_id)
        if attachment is None or not attachment.blob_path:
            return None
        try:
            from backend.app.storage.blob_client import blob_service_client

            service = blob_service_client(self._settings)
            container = service.get_container_client(
                attachment.blob_container or self._settings.user_attachments_container
            )
            downloader = container.download_blob(attachment.blob_path)
            data = downloader.readall()
            self._memory.save(attachment, data)
            return data
        except Exception:
            logger.warning(
                "attachment_blob_download_failed id=%s",
                attachment_id,
                exc_info=True,
            )
            return None

    def _upload_blob(self, attachment: UserAttachment, image_bytes: bytes) -> None:
        from backend.app.storage.blob_client import blob_service_client

        container_name = self._settings.user_attachments_container
        blob_path = (
            f"sessions/{attachment.session_id}/{attachment.attachment_id}/"
            f"{attachment.filename}"
        )
        service = blob_service_client(self._settings)
        container = service.get_container_client(container_name)
        try:
            container.create_container()
        except Exception as exc:
            if exc.__class__.__name__ != "ResourceExistsError":
                raise
        container.upload_blob(name=blob_path, data=image_bytes, overwrite=True)
        attachment.blob_container = container_name
        attachment.blob_path = blob_path
        account = (self._settings.storage_account_url or "").rstrip("/")
        if account:
            attachment.storage_uri = f"{account}/{container_name}/{blob_path}"


class AttachmentService:
    def __init__(
        self,
        store: AttachmentStore | None = None,
        vision_client: AzureComputerVisionClient | None = None,
    ) -> None:
        self._store = store or InMemoryAttachmentStore()
        self._vision = vision_client or build_vision_client()

    @property
    def store(self) -> AttachmentStore:
        return self._store

    def upload(
        self,
        *,
        session_id: str,
        filename: str,
        content_type: str,
        image_bytes: bytes,
        source: str = "troubleshoot",
        user_description: str = "",
    ) -> UserAttachment:
        attachment = UserAttachment(
            session_id=session_id,
            filename=filename or "upload.bin",
            content_type=content_type or "application/octet-stream",
            source=source,
            user_description=str(user_description or ""),
        )
        vision = self._vision.analyze_bytes(
            image_bytes, content_type=attachment.content_type
        )
        attachment.vision = vision.to_dict()
        attachment.vision_status = vision.status
        attachment.image_summary = compose_image_summary(
            user_description=attachment.user_description,
            vision=vision if vision.status == "ok" else VisionAnalysis(status="failed"),
        )
        self._store.save(attachment, image_bytes)
        return attachment

    def get(self, attachment_id: str) -> UserAttachment | None:
        return self._store.get(attachment_id)

    def summarize(
        self,
        attachment_id: str,
        *,
        user_description: str | None = None,
        reanalyze: bool = False,
    ) -> UserAttachment | None:
        attachment = self._store.get(attachment_id)
        if attachment is None:
            return None
        if user_description is not None:
            attachment.user_description = str(user_description)
        vision: VisionAnalysis | None = None
        if reanalyze or not attachment.vision:
            image_bytes = self._store.get_bytes(attachment_id)
            if image_bytes:
                vision = self._vision.analyze_bytes(
                    image_bytes, content_type=attachment.content_type
                )
                attachment.vision = vision.to_dict()
                attachment.vision_status = vision.status
        if vision is None and attachment.vision:
            vision = VisionAnalysis(
                provider=str(attachment.vision.get("provider") or "azure_ai_vision"),
                caption=str(attachment.vision.get("caption") or ""),
                ocr_text=str(attachment.vision.get("ocr_text") or ""),
                tags=list(attachment.vision.get("tags") or []),
                status=attachment.vision_status or "ok",
            )
        attachment.image_summary = compose_image_summary(
            user_description=attachment.user_description,
            vision=vision if vision and vision.status == "ok" else VisionAnalysis(status="failed"),
        )
        self._store.save(attachment)
        return attachment

    def resolve_summaries(self, attachment_ids: list[str]) -> list[str]:
        summaries: list[str] = []
        for attachment_id in attachment_ids:
            item = self.get(str(attachment_id))
            if item and item.image_summary:
                summaries.append(item.image_summary)
        return summaries


def enrich_user_message(user_message: str, image_summaries: list[str]) -> str:
    text = str(user_message or "").strip()
    summaries = [str(item).strip() for item in image_summaries if str(item).strip()]
    if not summaries:
        return text
    block = "\n".join(f"[Image summary] {summary}" for summary in summaries)
    if not text:
        return block
    return f"{text}\n\n{block}"


_singleton_lock = threading.Lock()
_service_singleton: AttachmentService | None = None
_memory_store_singleton: InMemoryAttachmentStore | None = None


def build_attachment_service(
    *,
    use_blob: bool | None = None,
    vision_client: AzureComputerVisionClient | None = None,
) -> AttachmentService:
    global _service_singleton, _memory_store_singleton
    with _singleton_lock:
        if _service_singleton is not None and vision_client is None and use_blob is None:
            return _service_singleton
        if _memory_store_singleton is None:
            _memory_store_singleton = InMemoryAttachmentStore()
        settings = get_settings()
        blob_enabled = use_blob
        if blob_enabled is None:
            blob_enabled = bool(
                settings.storage_connection_string or settings.storage_account_url
            )
        store: AttachmentStore
        if blob_enabled:
            store = BlobAttachmentStore(settings=settings, memory=_memory_store_singleton)
        else:
            store = _memory_store_singleton
        service = AttachmentService(store=store, vision_client=vision_client)
        if vision_client is None and use_blob is None:
            _service_singleton = service
        return service


def reset_attachment_service_for_tests() -> None:
    global _service_singleton, _memory_store_singleton
    with _singleton_lock:
        if _memory_store_singleton is not None:
            _memory_store_singleton.clear()
        _memory_store_singleton = None
        _service_singleton = None


__all__ = [
    "AttachmentService",
    "AttachmentStore",
    "BlobAttachmentStore",
    "InMemoryAttachmentStore",
    "UserAttachment",
    "build_attachment_service",
    "enrich_user_message",
    "reset_attachment_service_for_tests",
]
