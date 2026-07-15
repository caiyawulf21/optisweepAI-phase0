"""Phase 1 Step 13 — runtime interaction logging.

Persists every ``/troubleshoot`` interaction as an :class:`InteractionLog`
document following the build-prompt schema:

.. code-block:: json

    {
      "interaction_id": "",
      "session_id": "",
      "timestamp": "",
      "user_message": "",
      "response_type": "",
      "selected_workflow_id": "",
      "current_node_id": "",
      "observed_signals": {},
      "retrieval_result_ids": [],
      "escalation_triggered": false
    }

Two acceptance rules drive every design choice in this module:

1. **every troubleshooting interaction logged** -- the ``/troubleshoot``
   endpoint calls :meth:`InteractionLogService.record` exactly once per
   request right after :func:`backend.app.api.troubleshoot._build_troubleshoot_response`.
2. **logging failures do not crash runtime** -- :meth:`record` is the
   single funnel for every backend, and it ALWAYS swallows
   exceptions, logs a warning, and returns ``False``. No store ever
   surfaces an exception to the endpoint.

Three interchangeable backends mirror the Step 9
:mod:`backend.app.services.session_service` pattern:

* :class:`InMemoryInteractionLogStore` -- default
  (``INTERACTION_LOG_BACKEND=memory``); process-local list, safe for tests
  and any environment without Cosmos credentials. Multi-turn demos see a
  single shared store via :func:`build_interaction_log_service` (the same
  process-singleton pattern used for the session store).
* :class:`CosmosInteractionLogStore` -- backed by
  :class:`backend.app.repositories.interaction_log_repository.InteractionLogRepository`
  (Cosmos container ``interaction_logs``, partition ``/session_id``);
  opt-in via ``INTERACTION_LOG_BACKEND=cosmos``.
* :class:`DisabledInteractionLogStore` -- explicit kill switch via
  ``INTERACTION_LOG_BACKEND=disabled``; ``record`` is a no-op.
"""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from backend.app.config import (
    INTERACTION_LOG_BACKEND_COSMOS,
    INTERACTION_LOG_BACKEND_DISABLED,
    INTERACTION_LOG_BACKEND_MEMORY,
    AppSettings,
    get_app_settings,
)


logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_interaction_id() -> str:
    return uuid.uuid4().hex


@dataclass
class InteractionLog:
    """Runtime interaction log -- the canonical Phase 1 Step 13 schema.

    Matches the build prompt's 10-field shape verbatim. The Cosmos ``id``
    is mirrored from ``interaction_id`` (same trick
    :class:`backend.app.services.session_service.WorkflowSession` uses for
    its ``session_id``) so the document round-trips through
    :class:`InteractionLogRepository` (partition ``/session_id``) without
    an extra mapping step.
    """

    interaction_id: str = field(default_factory=_new_interaction_id)
    session_id: str = ""
    timestamp: str = field(default_factory=_utcnow_iso)
    user_message: str = ""
    response_type: str = "answer"
    selected_workflow_id: str | None = None
    current_node_id: str | None = None
    observed_signals: dict[str, bool] = field(default_factory=dict)
    retrieval_result_ids: list[str] = field(default_factory=list)
    escalation_triggered: bool = False
    final_response: str | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    assistant_response: dict[str, Any] = field(default_factory=dict)
    runtime_trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.interaction_id,
            "interaction_id": self.interaction_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "user_message": self.user_message,
            "response_type": self.response_type,
            "selected_workflow_id": self.selected_workflow_id,
            "current_node_id": self.current_node_id,
            "observed_signals": dict(self.observed_signals),
            "retrieval_result_ids": list(self.retrieval_result_ids),
            "escalation_triggered": bool(self.escalation_triggered),
            "final_response": self.final_response,
            "citations": list(self.citations),
            "assistant_response": dict(self.assistant_response),
            "runtime_trace": dict(self.runtime_trace),
        }

    @classmethod
    def from_state(
        cls,
        *,
        session_id: str,
        user_message: str,
        state: dict[str, Any] | None,
        response: Any,
    ) -> "InteractionLog":
        """Build a log entry from the runtime triple (request, state, response).

        ``state`` is the final :class:`backend.app.graph.state.AssistantState`
        emitted by :func:`backend.app.graph.graph.run_troubleshooting`;
        ``response`` is the :class:`backend.app.schemas.assistant.TroubleshootResponse`
        instance produced by :func:`backend.app.api.troubleshoot._build_troubleshoot_response`.

        The factory deliberately leans on the response for ``response_type``
        (so the discriminator lives in one place) and on the state for
        every other field (so we capture the deepest available
        information per turn -- the Step 10 runtime payload when present,
        falling back to legacy fields otherwise).
        """
        state = state or {}
        response_type = (
            getattr(response, "response_type", None) or "answer"
        )
        workflow_state = state.get("workflow_state") or {}
        runtime_step = workflow_state.get("workflow_step") or {}
        if not isinstance(runtime_step, dict):
            runtime_step = {}

        selected_workflow_id = (
            state.get("selected_workflow_id")
            or state.get("canonical_workflow_id")
            or workflow_state.get("workflow_id")
            or runtime_step.get("workflow_id")
        )

        current_node_id = (
            runtime_step.get("current_node_id")
            or workflow_state.get("current_node_id")
            or state.get("canonical_next_node_id")
        )

        observed_signals: dict[str, Any]
        if isinstance(runtime_step.get("observed_signals"), dict):
            observed_signals = runtime_step["observed_signals"]
        elif isinstance(workflow_state.get("observed_signals"), dict):
            observed_signals = workflow_state["observed_signals"]
        else:
            observed_signals = state.get("extracted_signals") or {}

        retrieval_result_ids = _collect_retrieval_ids(
            state.get("retrieval_results") or []
        )

        escalation_triggered = bool(state.get("escalation_required")) or (
            response_type == "escalation"
        )
        assistant_response = _response_to_dict(response)

        return cls(
            interaction_id=_new_interaction_id(),
            session_id=str(session_id or state.get("session_id") or ""),
            timestamp=_utcnow_iso(),
            user_message=str(user_message or state.get("user_message") or ""),
            response_type=str(response_type),
            selected_workflow_id=selected_workflow_id,
            current_node_id=current_node_id,
            observed_signals={str(k): bool(v) for k, v in observed_signals.items()},
            retrieval_result_ids=retrieval_result_ids,
            escalation_triggered=escalation_triggered,
            final_response=_string_or_none(assistant_response.get("final_response")),
            citations=_list_of_dicts(assistant_response.get("citations")),
            assistant_response=assistant_response,
            runtime_trace=_dict_or_empty(assistant_response.get("runtime_trace")),
        )

    @classmethod
    def from_dict(cls, document: dict[str, Any]) -> "InteractionLog":
        return cls(
            interaction_id=str(document.get("interaction_id") or document.get("id") or ""),
            session_id=str(document.get("session_id") or ""),
            timestamp=str(document.get("timestamp") or ""),
            user_message=str(document.get("user_message") or ""),
            response_type=str(document.get("response_type") or "answer"),
            selected_workflow_id=document.get("selected_workflow_id"),
            current_node_id=document.get("current_node_id"),
            observed_signals={
                str(k): bool(v)
                for k, v in (document.get("observed_signals") or {}).items()
            },
            retrieval_result_ids=[
                str(item) for item in (document.get("retrieval_result_ids") or [])
            ],
            escalation_triggered=bool(document.get("escalation_triggered")),
            final_response=_string_or_none(document.get("final_response")),
            citations=_list_of_dicts(document.get("citations")),
            assistant_response=_dict_or_empty(document.get("assistant_response")),
            runtime_trace=_dict_or_empty(document.get("runtime_trace")),
        )


def _collect_retrieval_ids(results: Iterable[Any]) -> list[str]:
    ids: list[str] = []
    for item in results:
        record_id = getattr(item, "record_id", None)
        if record_id:
            ids.append(str(record_id))
            continue
        if isinstance(item, dict) and item.get("record_id"):
            ids.append(str(item["record_id"]))
    return ids


def _response_to_dict(response: Any) -> dict[str, Any]:
    if response is None:
        return {}
    if hasattr(response, "model_dump"):
        return response.model_dump(mode="json")
    if isinstance(response, dict):
        return dict(response)
    raw = getattr(response, "__dict__", None)
    if isinstance(raw, dict):
        return dict(raw)
    return {}


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


class InteractionLogServiceError(RuntimeError):
    """Raised by stores when persistence fails.

    The :class:`InteractionLogService` catches and converts these (and
    any other exception) into a ``False`` return value -- callers never
    see them. The class exists primarily so unit tests can assert that
    the Cosmos store wraps SDK errors uniformly.
    """


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------


class InteractionLogStore:
    """Backend-agnostic interaction-log store contract."""

    def record(self, log: InteractionLog) -> None:
        raise NotImplementedError

    def list_for_session(self, session_id: str) -> list[InteractionLog]:
        return []

    def clear(self) -> None:
        return None


class InMemoryInteractionLogStore(InteractionLogStore):
    """Process-local list-backed store. Default ``INTERACTION_LOG_BACKEND=memory``.

    The store keeps the inserted :class:`InteractionLog` objects in
    insertion order so multi-turn demos can replay the conversation by
    iterating :meth:`list_for_session`.
    """

    def __init__(self) -> None:
        self._logs: list[InteractionLog] = []
        self._lock = threading.Lock()

    def record(self, log: InteractionLog) -> None:
        with self._lock:
            self._logs.append(log)

    def list_for_session(self, session_id: str) -> list[InteractionLog]:
        with self._lock:
            return [entry for entry in self._logs if entry.session_id == session_id]

    def all(self) -> list[InteractionLog]:
        with self._lock:
            return list(self._logs)

    def clear(self) -> None:
        with self._lock:
            self._logs.clear()


class CosmosInteractionLogStore(InteractionLogStore):
    """Cosmos-backed store. Selected via ``INTERACTION_LOG_BACKEND=cosmos``.

    Lazily constructs :class:`InteractionLogRepository` on first ``record``
    so importing this module never forces Cosmos credentials to be
    present. Cosmos transport errors are wrapped in
    :class:`InteractionLogServiceError`, but the
    :class:`InteractionLogService` layer above always swallows them so
    they never reach the endpoint.
    """

    def __init__(self, repository: Any | None = None) -> None:
        self._repository = repository

    def _repo(self) -> Any:
        if self._repository is None:
            from backend.app.repositories.interaction_log_repository import (
                InteractionLogRepository,
            )

            self._repository = InteractionLogRepository()
        return self._repository

    def record(self, log: InteractionLog) -> None:
        try:
            self._repo().upsert(log.to_dict())
        except Exception as exc:
            raise InteractionLogServiceError(
                f"Failed to upsert interaction log "
                f"{log.interaction_id!r} (session={log.session_id!r}): {exc}"
            ) from exc

    def list_for_session(self, session_id: str) -> list[InteractionLog]:
        try:
            rows = self._repo().list_for_session(session_id)
        except Exception as exc:
            raise InteractionLogServiceError(
                f"Failed to list interaction logs for session={session_id!r}: {exc}"
            ) from exc
        return [
            InteractionLog.from_dict(row)
            for row in rows
            if isinstance(row, dict)
        ]


class DisabledInteractionLogStore(InteractionLogStore):
    """Explicit no-op store. Selected via ``INTERACTION_LOG_BACKEND=disabled``."""

    def record(self, log: InteractionLog) -> None:
        return None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class InteractionLogService:
    """High-level interaction-log facade used by the API layer.

    The single rule callers care about: :meth:`record` ALWAYS returns
    ``True/False`` and NEVER raises. The build-prompt's "logging
    failures do not crash runtime" guarantee lives here -- the
    endpoint can call ``service.record(log)`` without a ``try/except``
    and the request will still succeed.
    """

    def __init__(self, store: InteractionLogStore | None = None) -> None:
        self._store = store or InMemoryInteractionLogStore()

    @property
    def store(self) -> InteractionLogStore:
        return self._store

    def record(self, log: InteractionLog) -> bool:
        try:
            self._store.record(log)
        except Exception:
            logger.warning(
                "interaction_log_failed session=%s interaction=%s",
                log.session_id,
                log.interaction_id,
                exc_info=True,
            )
            return False
        return True

    def list_for_session(self, session_id: str) -> list[InteractionLog]:
        try:
            return self._store.list_for_session(session_id)
        except Exception:
            logger.warning(
                "interaction_log_list_failed session=%s",
                session_id,
                exc_info=True,
            )
            return []


# ---------------------------------------------------------------------------
# Process-singleton factory
# ---------------------------------------------------------------------------


_singleton_lock = threading.Lock()
_memory_store_singleton: InMemoryInteractionLogStore | None = None
_service_singleton: InteractionLogService | None = None
_service_singleton_backend: str | None = None


def build_interaction_log_service(
    settings: AppSettings | None = None,
) -> InteractionLogService:
    """Factory: build (or reuse) the per-process :class:`InteractionLogService`.

    Behaviour per backend:

    * ``memory`` -- returns a service wrapping a process-wide singleton
      :class:`InMemoryInteractionLogStore`. The singleton is necessary
      because :func:`backend.app.graph.graph.run_troubleshooting` builds
      a fresh graph per HTTP request; without a shared store the
      multi-turn demo would lose every prior log. Use
      :func:`reset_for_tests` to clear between tests.
    * ``cosmos`` -- returns a new :class:`InteractionLogService` wrapping
      a fresh :class:`CosmosInteractionLogStore`. The Cosmos client
      handles connection pooling underneath, so no singleton is needed
      here. We DO still cache the service object so the lazy repo build
      only fires once per process.
    * ``disabled`` -- returns a service wrapping a
      :class:`DisabledInteractionLogStore`. Cached too.

    Validation of unknown backends is done at startup via
    :func:`backend.app.config.validate_runtime_mode`; this factory still
    raises :class:`InteractionLogServiceError` if it sees an unknown
    value (defence in depth, e.g. when tests construct
    :class:`AppSettings` directly).
    """
    cfg = settings or get_app_settings()
    backend = cfg.interaction_log_backend

    global _service_singleton, _service_singleton_backend, _memory_store_singleton
    with _singleton_lock:
        if (
            _service_singleton is not None
            and _service_singleton_backend == backend
        ):
            return _service_singleton

        if backend == INTERACTION_LOG_BACKEND_MEMORY:
            if _memory_store_singleton is None:
                _memory_store_singleton = InMemoryInteractionLogStore()
            service = InteractionLogService(store=_memory_store_singleton)
        elif backend == INTERACTION_LOG_BACKEND_COSMOS:
            service = InteractionLogService(store=CosmosInteractionLogStore())
        elif backend == INTERACTION_LOG_BACKEND_DISABLED:
            service = InteractionLogService(store=DisabledInteractionLogStore())
        else:
            raise InteractionLogServiceError(
                f"Unsupported INTERACTION_LOG_BACKEND={backend!r}. "
                f"Valid values: "
                f"{INTERACTION_LOG_BACKEND_MEMORY!r}, "
                f"{INTERACTION_LOG_BACKEND_COSMOS!r}, "
                f"{INTERACTION_LOG_BACKEND_DISABLED!r}."
            )

        _service_singleton = service
        _service_singleton_backend = backend
        return service


def reset_for_tests() -> None:
    """Clear the process-wide service + store singletons.

    Required between tests that toggle ``INTERACTION_LOG_BACKEND`` env
    vars or assert on the contents of the in-memory store across runs.
    """
    global _service_singleton, _service_singleton_backend, _memory_store_singleton
    with _singleton_lock:
        _service_singleton = None
        _service_singleton_backend = None
        if _memory_store_singleton is not None:
            _memory_store_singleton.clear()
        _memory_store_singleton = None


__all__ = [
    "CosmosInteractionLogStore",
    "DisabledInteractionLogStore",
    "InMemoryInteractionLogStore",
    "InteractionLog",
    "InteractionLogService",
    "InteractionLogServiceError",
    "InteractionLogStore",
    "build_interaction_log_service",
    "reset_for_tests",
]
