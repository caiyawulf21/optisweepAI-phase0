from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from backend.app.config import (
    FEEDBACK_BACKEND_COSMOS,
    FEEDBACK_BACKEND_DISABLED,
    FEEDBACK_BACKEND_MEMORY,
    AppSettings,
    get_app_settings,
)


logger = logging.getLogger(__name__)

Sentiment = Literal["helpful", "not_helpful", "suggestion"]


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_feedback_id() -> str:
    return f"feedback:{uuid.uuid4().hex}"


@dataclass
class FeedbackEvent:
    feedback_id: str = field(default_factory=_new_feedback_id)
    session_id: str = ""
    interaction_id: str = ""
    surface: str = "troubleshoot"
    created_at: str = field(default_factory=_utcnow_iso)
    sentiment: str = "suggestion"
    about: str | None = None
    targets: dict[str, Any] = field(default_factory=dict)
    user_text: str = ""
    proposed_change: str = ""
    attachment_ids: list[str] = field(default_factory=list)
    image_summaries: list[str] = field(default_factory=list)
    context_snapshot: dict[str, Any] = field(default_factory=dict)
    status: str = "captured"
    brain_handoff_status: str = "deferred"
    brain_review_id: str | None = None
    brain_apply_status: str | None = None
    brain_mutated_record_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.feedback_id,
            "feedback_id": self.feedback_id,
            "session_id": self.session_id,
            "interaction_id": self.interaction_id,
            "surface": self.surface,
            "created_at": self.created_at,
            "sentiment": self.sentiment,
            "about": self.about,
            "targets": dict(self.targets),
            "user_text": self.user_text,
            "proposed_change": self.proposed_change,
            "attachment_ids": list(self.attachment_ids),
            "image_summaries": list(self.image_summaries),
            "context_snapshot": dict(self.context_snapshot),
            "status": self.status,
            "brain_handoff_status": self.brain_handoff_status,
            "brain_review_id": self.brain_review_id,
            "brain_apply_status": self.brain_apply_status,
            "brain_mutated_record_ids": list(self.brain_mutated_record_ids),
        }

    @classmethod
    def from_dict(cls, document: dict[str, Any]) -> "FeedbackEvent":
        return cls(
            feedback_id=str(
                document.get("feedback_id") or document.get("id") or _new_feedback_id()
            ),
            session_id=str(document.get("session_id") or ""),
            interaction_id=str(document.get("interaction_id") or ""),
            surface=str(document.get("surface") or "troubleshoot"),
            created_at=str(document.get("created_at") or _utcnow_iso()),
            sentiment=str(document.get("sentiment") or "suggestion"),
            about=document.get("about"),
            targets=dict(document.get("targets") or {}),
            user_text=str(document.get("user_text") or ""),
            proposed_change=str(document.get("proposed_change") or ""),
            attachment_ids=[str(item) for item in list(document.get("attachment_ids") or [])],
            image_summaries=[
                str(item) for item in list(document.get("image_summaries") or [])
            ],
            context_snapshot=dict(document.get("context_snapshot") or {}),
            status=str(document.get("status") or "captured"),
            brain_handoff_status=str(document.get("brain_handoff_status") or "deferred"),
            brain_review_id=document.get("brain_review_id"),
            brain_apply_status=document.get("brain_apply_status"),
            brain_mutated_record_ids=[
                str(item) for item in list(document.get("brain_mutated_record_ids") or [])
            ],
        )


class FeedbackServiceError(RuntimeError):
    pass


class FeedbackStore:
    def record(self, event: FeedbackEvent) -> None:
        raise NotImplementedError

    def list_for_session(self, session_id: str) -> list[FeedbackEvent]:
        return []


class InMemoryFeedbackStore(FeedbackStore):
    def __init__(self) -> None:
        self._events: list[FeedbackEvent] = []
        self._lock = threading.Lock()

    def record(self, event: FeedbackEvent) -> None:
        with self._lock:
            for index, existing in enumerate(self._events):
                if existing.feedback_id == event.feedback_id:
                    self._events[index] = event
                    return
            self._events.append(event)

    def list_for_session(self, session_id: str) -> list[FeedbackEvent]:
        with self._lock:
            return [item for item in self._events if item.session_id == session_id]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


class CosmosFeedbackStore(FeedbackStore):
    def __init__(self, repository: Any | None = None) -> None:
        self._repository = repository

    def _repo(self) -> Any:
        if self._repository is None:
            from backend.app.repositories.feedback_repository import FeedbackEventRepository

            self._repository = FeedbackEventRepository()
        return self._repository

    def record(self, event: FeedbackEvent) -> None:
        try:
            self._repo().upsert(event.to_dict())
        except Exception as exc:
            raise FeedbackServiceError(
                f"Failed to upsert feedback {event.feedback_id!r}: {exc}"
            ) from exc

    def list_for_session(self, session_id: str) -> list[FeedbackEvent]:
        try:
            rows = self._repo().list_for_session(session_id)
        except Exception as exc:
            raise FeedbackServiceError(
                f"Failed to list feedback for session={session_id!r}: {exc}"
            ) from exc
        return [
            FeedbackEvent.from_dict(row) for row in rows if isinstance(row, dict)
        ]


class DisabledFeedbackStore(FeedbackStore):
    def record(self, event: FeedbackEvent) -> None:
        return None


class FeedbackService:
    def __init__(self, store: FeedbackStore | None = None) -> None:
        self._store = store or InMemoryFeedbackStore()

    @property
    def store(self) -> FeedbackStore:
        return self._store

    def record(self, event: FeedbackEvent) -> bool:
        try:
            self._store.record(event)
        except Exception:
            logger.warning(
                "feedback_record_failed session=%s feedback=%s",
                event.session_id,
                event.feedback_id,
                exc_info=True,
            )
            return False
        return True

    def list_for_session(self, session_id: str) -> list[FeedbackEvent]:
        try:
            return self._store.list_for_session(session_id)
        except Exception:
            logger.warning(
                "feedback_list_failed session=%s",
                session_id,
                exc_info=True,
            )
            return []


_singleton_lock = threading.Lock()
_memory_store_singleton: InMemoryFeedbackStore | None = None
_service_singleton: FeedbackService | None = None
_service_singleton_backend: str | None = None


def build_feedback_service(settings: AppSettings | None = None) -> FeedbackService:
    cfg = settings or get_app_settings()
    backend = cfg.feedback_backend
    global _service_singleton, _service_singleton_backend, _memory_store_singleton
    with _singleton_lock:
        if _service_singleton is not None and _service_singleton_backend == backend:
            return _service_singleton
        if backend == FEEDBACK_BACKEND_MEMORY:
            if _memory_store_singleton is None:
                _memory_store_singleton = InMemoryFeedbackStore()
            service = FeedbackService(store=_memory_store_singleton)
        elif backend == FEEDBACK_BACKEND_COSMOS:
            service = FeedbackService(store=CosmosFeedbackStore())
        elif backend == FEEDBACK_BACKEND_DISABLED:
            service = FeedbackService(store=DisabledFeedbackStore())
        else:
            raise FeedbackServiceError(
                f"Unsupported FEEDBACK_BACKEND={backend!r}."
            )
        _service_singleton = service
        _service_singleton_backend = backend
        return service


def reset_feedback_for_tests() -> None:
    global _service_singleton, _service_singleton_backend, _memory_store_singleton
    with _singleton_lock:
        _service_singleton = None
        _service_singleton_backend = None
        if _memory_store_singleton is not None:
            _memory_store_singleton.clear()
        _memory_store_singleton = None


__all__ = [
    "CosmosFeedbackStore",
    "DisabledFeedbackStore",
    "FeedbackEvent",
    "FeedbackService",
    "FeedbackServiceError",
    "FeedbackStore",
    "InMemoryFeedbackStore",
    "build_feedback_service",
    "reset_feedback_for_tests",
]
