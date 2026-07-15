"""Phase 1 runtime session persistence — Step 9 of the build prompt.

Provides a single :class:`SessionService` abstraction with two interchangeable
backends:

* :class:`InMemorySessionStore` — process-local dict, the default
  (``SESSION_BACKEND=memory``). Safe for tests, single-process demos, and
  any environment without Cosmos credentials.
* :class:`CosmosSessionStore` — backed by
  :class:`backend.app.repositories.workflow_session_repository.WorkflowSessionRepository`
  (Cosmos container ``workflow_sessions``, partition key ``/session_id``).
  Selected when ``SESSION_BACKEND=cosmos``.

The session schema matches the build prompt exactly::

    {
      "session_id": "",
      "user_id": "",
      "created_at": "",
      "updated_at": "",
      "active_workflow_id": "",
      "current_node_id": "",
      "observed_signals": {},
      "answered_questions": [],
      "retrieval_result_ids": [],
      "steps_attempted": [],
      "workflow_history": [],
      "escalation_state": {},
      "status": "active | escalated | resolved | abandoned"
    }

The service does not touch the graph state directly. Phase 1 Step 10 (the
canonical workflow runtime) and Step 11 (the runtime response contract) own
the marshalling between :class:`WorkflowSession` and
:class:`backend.app.graph.state.AssistantState`.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Literal

from backend.app.config import (
    SESSION_BACKEND_COSMOS,
    SESSION_BACKEND_MEMORY,
    AppSettings,
    get_app_settings,
)


SessionStatus = Literal["active", "escalated", "resolved", "abandoned"]


VALID_SESSION_STATUSES: tuple[SessionStatus, ...] = (
    "active",
    "escalated",
    "resolved",
    "abandoned",
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class WorkflowSession:
    """Runtime workflow session — the canonical Phase 1 session schema.

    Matches the build prompt's "Minimum session schema" verbatim. The
    ``id`` Cosmos field is mirrored from ``session_id`` so the document
    round-trips through ``WorkflowSessionRepository`` (partition key
    ``/session_id``) without an additional mapping step.
    """

    session_id: str
    user_id: str = ""
    operator_role: str | None = None
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)
    active_workflow_id: str | None = None
    current_node_id: str | None = None
    observed_signals: dict[str, bool] = field(default_factory=dict)
    observed_canonical_signals: dict[str, bool] = field(default_factory=dict)
    observed_components: list[str] = field(default_factory=list)
    answered_questions: list[dict[str, Any]] = field(default_factory=list)
    retrieval_result_ids: list[str] = field(default_factory=list)
    steps_attempted: list[str] = field(default_factory=list)
    workflow_history: list[dict[str, Any]] = field(default_factory=list)
    escalation_state: dict[str, Any] = field(default_factory=dict)
    status: SessionStatus = "active"
    mode: str | None = None
    dynamic_path: dict[str, Any] | None = None
    current_procedure_id: str | None = None
    current_step_index: int = 0
    completed_procedures: list[str] = field(default_factory=list)
    failed_procedures: list[str] = field(default_factory=list)
    produced_signals: dict[str, bool] = field(default_factory=dict)
    escalation_triggers: list[str] = field(default_factory=list)
    shown_citation_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a Cosmos-ready document.

        Includes ``id`` (mirrors ``session_id``) so the document satisfies
        Cosmos's required document-id field without forcing callers to
        supply a separate identifier.
        """
        return {
            "id": self.session_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "operator_role": self.operator_role,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "active_workflow_id": self.active_workflow_id,
            "current_node_id": self.current_node_id,
            "observed_signals": dict(self.observed_signals),
            "observed_canonical_signals": dict(self.observed_canonical_signals),
            "observed_components": list(self.observed_components),
            "answered_questions": [dict(a) for a in self.answered_questions],
            "retrieval_result_ids": list(self.retrieval_result_ids),
            "steps_attempted": list(self.steps_attempted),
            "workflow_history": [dict(h) for h in self.workflow_history],
            "escalation_state": dict(self.escalation_state),
            "status": self.status,
            "mode": self.mode,
            "dynamic_path": (
                dict(self.dynamic_path) if self.dynamic_path is not None else None
            ),
            "current_procedure_id": self.current_procedure_id,
            "current_step_index": int(self.current_step_index),
            "completed_procedures": list(self.completed_procedures),
            "failed_procedures": list(self.failed_procedures),
            "produced_signals": dict(self.produced_signals),
            "escalation_triggers": list(self.escalation_triggers),
            "shown_citation_ids": list(self.shown_citation_ids),
        }

    @classmethod
    def from_dict(cls, document: dict[str, Any]) -> "WorkflowSession":
        if not isinstance(document, dict):
            raise SessionServiceError(
                f"WorkflowSession.from_dict expected dict, got {type(document)!r}"
            )
        session_id = document.get("session_id") or document.get("id")
        if not isinstance(session_id, str) or not session_id:
            raise SessionServiceError(
                "WorkflowSession document is missing a non-empty 'session_id'"
            )
        status = document.get("status", "active")
        if status not in VALID_SESSION_STATUSES:
            status = "active"
        observed_signals = document.get("observed_signals") or {}
        if not isinstance(observed_signals, dict):
            observed_signals = {}
        observed_canonical_signals = document.get("observed_canonical_signals") or {}
        if not isinstance(observed_canonical_signals, dict):
            observed_canonical_signals = {}
        observed_components_raw = document.get("observed_components") or []
        if not isinstance(observed_components_raw, list):
            observed_components_raw = []
        produced_signals_raw = document.get("produced_signals") or {}
        if not isinstance(produced_signals_raw, dict):
            produced_signals_raw = {}
        dynamic_path_raw = document.get("dynamic_path")
        if dynamic_path_raw is not None and not isinstance(dynamic_path_raw, dict):
            dynamic_path_raw = None
        try:
            current_step_index = int(document.get("current_step_index") or 0)
        except (TypeError, ValueError):
            current_step_index = 0
        return cls(
            session_id=session_id,
            user_id=str(document.get("user_id") or ""),
            operator_role=document.get("operator_role"),
            created_at=str(document.get("created_at") or _utcnow_iso()),
            updated_at=str(document.get("updated_at") or _utcnow_iso()),
            active_workflow_id=document.get("active_workflow_id"),
            current_node_id=document.get("current_node_id"),
            observed_signals={
                str(k): bool(v) for k, v in observed_signals.items()
            },
            observed_canonical_signals={
                str(k): bool(v) for k, v in observed_canonical_signals.items()
            },
            observed_components=[
                str(c) for c in observed_components_raw if c
            ],
            answered_questions=[
                dict(a) for a in document.get("answered_questions") or []
                if isinstance(a, dict)
            ],
            retrieval_result_ids=[
                str(rid) for rid in document.get("retrieval_result_ids") or []
            ],
            steps_attempted=[
                str(sid) for sid in document.get("steps_attempted") or []
            ],
            workflow_history=[
                dict(h) for h in document.get("workflow_history") or []
                if isinstance(h, dict)
            ],
            escalation_state=dict(document.get("escalation_state") or {}),
            status=status,
            mode=document.get("mode") if isinstance(document.get("mode"), str) else None,
            dynamic_path=dict(dynamic_path_raw) if dynamic_path_raw else None,
            current_procedure_id=(
                str(document["current_procedure_id"])
                if document.get("current_procedure_id")
                else None
            ),
            current_step_index=current_step_index,
            completed_procedures=[
                str(pid) for pid in document.get("completed_procedures") or []
            ],
            failed_procedures=[
                str(pid) for pid in document.get("failed_procedures") or []
            ],
            produced_signals={
                str(k): bool(v) for k, v in produced_signals_raw.items()
            },
            escalation_triggers=[
                str(t) for t in document.get("escalation_triggers") or []
            ],
            shown_citation_ids=[
                str(cid) for cid in document.get("shown_citation_ids") or []
            ],
        )

    def merge_signals(self, signals: dict[str, bool] | None) -> None:
        """Idempotently merge ``signals`` into ``observed_signals``.

        Truthy observations are sticky; absent keys are left untouched.
        A False value records an explicit negative only when the signal
        has not already been observed as True. Non-bool values are
        coerced via :func:`bool`.
        """
        if not signals:
            return
        for name, value in signals.items():
            key = str(name)
            new_value = bool(value)
            if new_value:
                self.observed_signals[key] = True
            else:
                self.observed_signals.setdefault(key, False)

    def merge_canonical_signals(
        self, canonical_signals: dict[str, bool] | None
    ) -> None:
        """Idempotently merge ``canonical_signals`` into
        ``observed_canonical_signals``.

        Truthy values are sticky (a True observation is never demoted by
        a later False), so accumulated canonical-vocabulary observations
        survive turns. Absent keys are left untouched.
        """
        if not canonical_signals:
            return
        for name, value in canonical_signals.items():
            key = str(name)
            new_value = bool(value)
            if new_value:
                self.observed_canonical_signals[key] = True
            else:
                self.observed_canonical_signals.setdefault(key, False)

    def merge_components(self, components: Iterable[str] | None) -> None:
        """Idempotently merge ``components`` into ``observed_components``.

        The list is kept order-stable on first observation. Empty / None
        entries are dropped.
        """
        if not components:
            return
        existing = set(self.observed_components)
        for c in components:
            cs = str(c).strip()
            if not cs or cs in existing:
                continue
            self.observed_components.append(cs)
            existing.add(cs)

    def record_step(self, node_id: str | None) -> None:
        if node_id is None:
            return
        node_id = str(node_id)
        if not self.steps_attempted or self.steps_attempted[-1] != node_id:
            self.steps_attempted.append(node_id)

    def record_answer(
        self,
        *,
        node_id: str | None,
        question: str | None,
        answer: str | None,
        resulting_signals: dict[str, bool] | None = None,
    ) -> None:
        self.answered_questions.append(
            {
                "node_id": node_id,
                "question": question,
                "answer": answer,
                "resulting_signals": dict(resulting_signals or {}),
                "answered_at": _utcnow_iso(),
            }
        )

    def record_history(
        self,
        *,
        from_node_id: str | None,
        to_node_id: str | None,
        condition_signal: str | None = None,
        condition_value: Any = None,
        workflow_id: str | None = None,
    ) -> None:
        self.workflow_history.append(
            {
                "workflow_id": workflow_id,
                "from_node_id": from_node_id,
                "to_node_id": to_node_id,
                "condition_signal": condition_signal,
                "condition_value": condition_value,
                "transitioned_at": _utcnow_iso(),
            }
        )

    def record_retrieval_ids(self, ids: Iterable[str] | None) -> None:
        if not ids:
            return
        existing = set(self.retrieval_result_ids)
        for rid in ids:
            rid_str = str(rid)
            if rid_str and rid_str not in existing:
                self.retrieval_result_ids.append(rid_str)
                existing.add(rid_str)

    def touch(self) -> None:
        self.updated_at = _utcnow_iso()


class SessionServiceError(RuntimeError):
    """Raised on session persistence failures the runtime cannot recover from."""


class SessionStore:
    """Backend-agnostic session store contract."""

    def get(self, session_id: str) -> WorkflowSession | None:
        raise NotImplementedError

    def save(self, session: WorkflowSession) -> WorkflowSession:
        raise NotImplementedError

    def delete(self, session_id: str) -> None:
        raise NotImplementedError


class InMemorySessionStore(SessionStore):
    """Process-local dict-backed store. Default ``SESSION_BACKEND=memory``."""

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}

    def get(self, session_id: str) -> WorkflowSession | None:
        document = self._sessions.get(session_id)
        if document is None:
            return None
        return WorkflowSession.from_dict(document)

    def save(self, session: WorkflowSession) -> WorkflowSession:
        session.touch()
        self._sessions[session.session_id] = session.to_dict()
        return session

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def clear(self) -> None:
        self._sessions.clear()


class CosmosSessionStore(SessionStore):
    """Cosmos-backed session store. Selected via ``SESSION_BACKEND=cosmos``.

    The store is intentionally thin: it serialises :class:`WorkflowSession`
    through :meth:`WorkflowSession.to_dict` and delegates persistence to
    :class:`WorkflowSessionRepository` (container ``workflow_sessions``,
    partition key ``/session_id``). All Cosmos transport errors are wrapped
    in :class:`SessionServiceError` so callers can decide whether to retry
    or fall back.
    """

    def __init__(self, repository: Any | None = None) -> None:
        self._repository = repository
        self._lazy_loaded = repository is not None

    def _repo(self) -> Any:
        if self._repository is None:
            from backend.app.repositories.workflow_session_repository import (
                WorkflowSessionRepository,
            )

            self._repository = WorkflowSessionRepository()
            self._lazy_loaded = True
        return self._repository

    def get(self, session_id: str) -> WorkflowSession | None:
        try:
            document = self._repo().get(session_id, session_id)
        except Exception as exc:
            from azure.cosmos.exceptions import CosmosResourceNotFoundError  # type: ignore

            if isinstance(exc, CosmosResourceNotFoundError):
                return None
            raise SessionServiceError(
                f"Failed to load workflow session {session_id!r} from Cosmos: {exc}"
            ) from exc
        if document is None:
            return None
        return WorkflowSession.from_dict(document)

    def save(self, session: WorkflowSession) -> WorkflowSession:
        session.touch()
        try:
            self._repo().upsert(session.to_dict())
        except Exception as exc:
            raise SessionServiceError(
                f"Failed to upsert workflow session {session.session_id!r} to Cosmos: {exc}"
            ) from exc
        return session

    def delete(self, session_id: str) -> None:
        try:
            self._repo().delete(session_id, session_id)
        except Exception as exc:
            from azure.cosmos.exceptions import CosmosResourceNotFoundError  # type: ignore

            if isinstance(exc, CosmosResourceNotFoundError):
                return
            raise SessionServiceError(
                f"Failed to delete workflow session {session_id!r} from Cosmos: {exc}"
            ) from exc


class SessionService:
    """High-level session lifecycle helper used by the graph + API layers.

    Concrete backend selection is delegated to :class:`SessionStore`
    implementations. The service owns:

    * ``get_or_create`` semantics keyed by ``session_id``.
    * idempotent ``save``.
    * status transitions consistent with the build-prompt vocabulary.

    The service deliberately does not import the graph state — Step 10 owns
    the marshalling between :class:`WorkflowSession` and
    :class:`AssistantState`.
    """

    def __init__(self, store: SessionStore | None = None) -> None:
        self._store = store or InMemorySessionStore()

    @property
    def store(self) -> SessionStore:
        return self._store

    def get(self, session_id: str) -> WorkflowSession | None:
        return self._store.get(session_id)

    def get_or_create(
        self,
        session_id: str,
        *,
        user_id: str = "",
    ) -> WorkflowSession:
        existing = self._store.get(session_id)
        if existing is not None:
            return existing
        session = WorkflowSession(session_id=session_id, user_id=user_id)
        return self._store.save(session)

    def save(self, session: WorkflowSession) -> WorkflowSession:
        return self._store.save(session)

    def delete(self, session_id: str) -> None:
        self._store.delete(session_id)

    def mark_escalated(
        self,
        session: WorkflowSession,
        *,
        escalation_state: dict[str, Any] | None = None,
    ) -> WorkflowSession:
        if escalation_state is not None:
            session.escalation_state = dict(escalation_state)
        session.status = "escalated"
        return self.save(session)

    def mark_resolved(self, session: WorkflowSession) -> WorkflowSession:
        session.status = "resolved"
        return self.save(session)

    def mark_abandoned(self, session: WorkflowSession) -> WorkflowSession:
        session.status = "abandoned"
        return self.save(session)


_singleton_lock = threading.Lock()
_memory_store_singleton: InMemorySessionStore | None = None


def build_session_service(settings: AppSettings | None = None) -> SessionService:
    """Factory: select the session-store backend from ``AppSettings``.

    When Cosmos credentials are present, ``SESSION_BACKEND`` defaults to
    ``cosmos`` so playbook memory survives restarts. Override with
    ``SESSION_BACKEND=memory`` for offline tests. FastAPI startup validates
    Cosmos creds via :func:`backend.app.config.validate_runtime_mode`.

    For ``SESSION_BACKEND=memory`` the factory returns a
    :class:`SessionService` wrapping a process-wide singleton
    :class:`InMemorySessionStore` so multi-turn requests share state in one
    process. Tests that depend on the singleton should call
    :func:`reset_for_tests` between runs.
    """
    cfg = settings or get_app_settings()
    backend = cfg.session_backend
    if backend == SESSION_BACKEND_COSMOS:
        return SessionService(store=CosmosSessionStore())
    if backend == SESSION_BACKEND_MEMORY:
        global _memory_store_singleton
        with _singleton_lock:
            if _memory_store_singleton is None:
                _memory_store_singleton = InMemorySessionStore()
            return SessionService(store=_memory_store_singleton)
    raise SessionServiceError(
        f"Unsupported SESSION_BACKEND={backend!r}. "
        f"Valid values: {SESSION_BACKEND_MEMORY!r}, {SESSION_BACKEND_COSMOS!r}."
    )


def reset_for_tests() -> None:
    """Clear the process-wide memory-store singleton.

    Required between tests that exercise :func:`build_session_service`
    with ``SESSION_BACKEND=memory`` and want a clean slate; without
    this, sessions written by one test bleed into the next.
    """
    global _memory_store_singleton
    with _singleton_lock:
        if _memory_store_singleton is not None:
            _memory_store_singleton.clear()
        _memory_store_singleton = None


__all__ = [
    "CosmosSessionStore",
    "InMemorySessionStore",
    "SessionService",
    "SessionServiceError",
    "SessionStatus",
    "SessionStore",
    "VALID_SESSION_STATUSES",
    "WorkflowSession",
    "build_session_service",
    "reset_for_tests",
]
