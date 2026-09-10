"""HTTP client for the ingestion-hosted Brain API.

App is client-only: never upsert brain_* containers. All calls are gated by
BRAIN_HTTP_ENABLED and per-route BRAIN_HTTP_* flags (default off). Contract:
docs/brain/HTTP_BOUNDARY.md. Brain HTTP v4 cold retrieve is ~40-50s (warm ~2s);
default BRAIN_HTTP_TIMEOUT_SECONDS is 90. Optional startup warmup (background)
fires a probe retrieve so the first user question is more likely to hit warm cache.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from backend.app.config import AppSettings, get_app_settings
from backend.app.services.brain_cite import filter_approved_excerpts


logger = logging.getLogger(__name__)

_WARMUP_QUERY = "optisweep warmup"
_warmup_lock = threading.Lock()
_warmup_status: dict[str, Any] = {
    "started": False,
    "completed": False,
    "ok": None,
    "elapsed_seconds": None,
    "error": None,
    "skipped_reason": None,
}


class ContextPacket(BaseModel):
    task: str = ""
    current_state: dict[str, Any] = Field(default_factory=dict)
    entities: list[str] = Field(default_factory=list)
    approved_knowledge: list[str] = Field(default_factory=list)
    evidence_excerpts: list[str] = Field(default_factory=list)
    relevant_incidents: list[str] = Field(default_factory=list)
    policies: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    required_output_schema: Any | None = None


class HydratedExcerpt(BaseModel):
    record_id: str
    record_type: str = ""
    validation_status: str = ""
    title: str | None = None
    text: str = ""
    source_refs: list[str] = Field(default_factory=list)


class BrainContextResponse(BaseModel):
    packet: ContextPacket = Field(default_factory=ContextPacket)
    approved_excerpts: list[HydratedExcerpt] = Field(default_factory=list)
    working_material: list[HydratedExcerpt] = Field(default_factory=list)
    conflicts: list[HydratedExcerpt] = Field(default_factory=list)
    query_echo: str = ""
    brain_backend: str | None = None
    trace: dict[str, Any] = Field(default_factory=dict)

    def approved_excerpt_dicts(self) -> list[dict[str, Any]]:
        raw = [item.model_dump() for item in self.approved_excerpts]
        return filter_approved_excerpts(raw)

    def working_excerpt_dicts(self) -> list[dict[str, Any]]:
        return [item.model_dump() for item in self.working_material]

    def synthesis_excerpt_dicts(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return self.approved_excerpt_dicts(), self.working_excerpt_dicts()


class RetrieveContextRequest(BaseModel):
    query: str
    session_id: str | None = None
    limit: int = 12
    entity_ids: list[str] = Field(default_factory=list)
    include_working_material: bool = False


class TroubleshootContextRequest(BaseModel):
    query: str
    session_id: str
    playbook_id: str | None = None
    node_id: str | None = None
    runbook_id: str | None = None
    observed_signals: dict[str, Any] = Field(default_factory=dict)
    entity_ids: list[str] = Field(default_factory=list)
    attachment_summaries: list[str] = Field(default_factory=list)
    limit: int = 12
    include_working_material: bool = False
    playbook_resolution: Literal["pinned", "awaiting_candidate", "unpinned"] | None = None
    awaiting_playbook_selection: bool = False
    candidate_playbook_ids: list[str] = Field(default_factory=list)
    case_id: str | None = None


class BrainFeedbackRequest(BaseModel):
    session_id: str
    interaction_id: str
    surface: Literal["troubleshoot", "retrieve"] = "troubleshoot"
    sentiment: Literal["helpful", "not_helpful", "suggestion"] = "suggestion"
    about: str | None = None
    user_text: str = ""
    proposed_change: str = ""
    targets: dict[str, Any] = Field(default_factory=dict)
    attachment_ids: list[str] = Field(default_factory=list)
    image_summaries: list[str] = Field(default_factory=list)
    context_snapshot: dict[str, Any] = Field(default_factory=dict)
    app_feedback_id: str | None = None


class BrainFeedbackResponse(BaseModel):
    accepted: bool = False
    brain_review_id: str | None = None
    ingestion_run_id: str | None = None
    status: str = ""
    mutated_record_ids: list[str] = Field(default_factory=list)
    message: str = ""
    errors: list[str] = Field(default_factory=list)


class BrainReviewSummary(BaseModel):
    review_id: str = ""
    id: str = ""
    kind: str = ""
    status: str = "open"
    title: str | None = None
    summary: str | None = None
    proposed_change: Any = None
    affected_record_ids: list[str] = Field(default_factory=list)
    created_at: str | None = None
    priority: str | None = None
    resolution_type: str | None = None
    audit_action: str | None = None

    def effective_id(self) -> str:
        return self.review_id or self.id


class BrainReviewDetail(BrainReviewSummary):
    resolution: str | None = None
    resolved_by: str | None = None
    reviewer_id: str | None = None
    notes: str | None = None
    affected_records: list[dict[str, Any]] = Field(default_factory=list)
    proposed_change_detail: Any = None
    raw: dict[str, Any] = Field(default_factory=dict)


class BrainReviewListResponse(BaseModel):
    reviews: list[BrainReviewSummary] = Field(default_factory=list)
    total: int | None = None
    status_filter: str | None = None


class BrainResolveRequest(BaseModel):
    resolution: Literal["approve", "reject", "edit"] | str = "approve"
    resolved_by: Literal["human", "agent"] = "human"
    reviewer_id: str | None = None
    notes: str | None = None
    edited_proposed_change: Any = None
    winner_record_id: str | None = None


class BrainResolveResponse(BaseModel):
    review_id: str = ""
    status: str = ""
    resolution: str = ""
    mutated_record_ids: list[str] = Field(default_factory=list)
    message: str = ""
    applied: bool | None = None
    apply_status: str | None = None
    execution_status: str | None = None
    errors: list[str] = Field(default_factory=list)


class BrainHttpError(RuntimeError):
    pass


class BrainHttpClient:
    """HTTP client for ingestion-hosted Brain API. No-ops when disabled."""

    def __init__(
        self,
        settings: AppSettings | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings or get_app_settings()
        self._transport = transport

    @property
    def enabled(self) -> bool:
        return bool(self.settings.brain_http_enabled)

    @property
    def reviews_enabled(self) -> bool:
        return self.enabled and bool(self.settings.brain_http_reviews)

    @property
    def base_url(self) -> str:
        return (self.settings.brain_http_base_url or "").rstrip("/")

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url or "http://invalid.local",
            timeout=self.settings.brain_http_timeout_seconds,
            transport=self._transport,
        )

    def _require_live(self) -> None:
        if not self.enabled:
            raise BrainHttpError("Brain HTTP is disabled")
        if not self.base_url:
            raise BrainHttpError("BRAIN_HTTP_BASE_URL is not set")

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_live()
        try:
            with self._client() as client:
                response = client.post(path, json=payload)
                response.raise_for_status()
                data = response.json()
        except BrainHttpError:
            raise
        except Exception as exc:
            raise BrainHttpError(f"Brain HTTP {path} failed: {exc}") from exc
        if not isinstance(data, dict):
            raise BrainHttpError(f"Brain HTTP {path} returned non-object JSON")
        return data

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self._require_live()
        try:
            with self._client() as client:
                response = client.get(path, params=params or {})
                response.raise_for_status()
                return response.json()
        except BrainHttpError:
            raise
        except Exception as exc:
            raise BrainHttpError(f"Brain HTTP {path} failed: {exc}") from exc

    def get_retrieve_context(
        self, request: RetrieveContextRequest
    ) -> BrainContextResponse | None:
        if not self.enabled or not self.settings.brain_http_retrieve:
            return None
        raw = self._post_json(
            "/brain/v1/context/retrieve",
            _to_live_retrieve_payload(request),
        )
        return _from_live_context_response(raw, query_echo=request.query, task="retrieve")

    def warmup(self) -> dict[str, Any]:
        """Probe Brain so cold cache/load happens before the first user turn.

        Prefer retrieve when that flag is on; otherwise troubleshoot. Returns a
        status dict; never raises.
        """
        if not self.enabled:
            return {"ok": False, "skipped_reason": "brain_http_disabled"}
        if not self.base_url:
            return {"ok": False, "skipped_reason": "missing_base_url"}
        started = time.monotonic()
        try:
            if self.settings.brain_http_retrieve:
                result = self.get_retrieve_context(
                    RetrieveContextRequest(
                        query=_WARMUP_QUERY,
                        session_id="brain-warmup",
                        limit=1,
                    )
                )
                path = "retrieve"
            elif self.settings.brain_http_troubleshoot:
                result = self.get_troubleshoot_context(
                    TroubleshootContextRequest(
                        query=_WARMUP_QUERY,
                        session_id="brain-warmup",
                        limit=1,
                    )
                )
                path = "troubleshoot"
            else:
                return {
                    "ok": False,
                    "skipped_reason": "retrieve_and_troubleshoot_disabled",
                }
            elapsed = round(time.monotonic() - started, 2)
            return {
                "ok": result is not None,
                "path": path,
                "elapsed_seconds": elapsed,
                "excerpt_count": (
                    len(result.approved_excerpts) if result is not None else 0
                ),
            }
        except Exception as exc:
            elapsed = round(time.monotonic() - started, 2)
            logger.warning("brain_http_warmup_failed after %.1fs: %s", elapsed, exc)
            return {
                "ok": False,
                "elapsed_seconds": elapsed,
                "error": str(exc)[:300],
            }

    def get_troubleshoot_context(
        self, request: TroubleshootContextRequest
    ) -> BrainContextResponse | None:
        if not self.enabled or not self.settings.brain_http_troubleshoot:
            return None
        raw = self._post_json(
            "/brain/v1/context/troubleshoot",
            _to_live_troubleshoot_payload(request),
        )
        return _from_live_context_response(
            raw, query_echo=request.query, task="troubleshoot"
        )

    def submit_feedback(
        self, request: BrainFeedbackRequest
    ) -> BrainFeedbackResponse | None:
        if not self.enabled or not self.settings.brain_http_feedback:
            return None
        raw = self._post_json(
            "/brain/v1/feedback",
            _to_live_feedback_payload(request),
        )
        return _from_live_feedback_response(raw)

    def list_reviews(
        self,
        *,
        status: str = "open",
        limit: int = 50,
    ) -> BrainReviewListResponse | None:
        if not self.reviews_enabled:
            return None
        raw = self._get_json(
            "/brain/v1/reviews",
            params={"status": status},
        )
        parsed = _parse_review_list(raw, status_filter=status)
        if limit and parsed.reviews and len(parsed.reviews) > limit:
            parsed = BrainReviewListResponse(
                reviews=parsed.reviews[:limit],
                total=parsed.total,
                status_filter=parsed.status_filter,
            )
        return parsed

    def get_review(self, review_id: str) -> BrainReviewDetail | None:
        if not self.reviews_enabled:
            return None
        rid = (review_id or "").strip()
        if not rid:
            raise BrainHttpError("review_id is required")
        try:
            raw = self._get_json(f"/brain/v1/reviews/{rid}")
            return _parse_review_detail(raw)
        except BrainHttpError:
            listed = self.list_reviews(status="open", limit=200)
            if listed is None:
                raise
            for item in listed.reviews:
                if item.effective_id() == rid:
                    payload = item.model_dump(mode="json")
                    payload["review_id"] = rid
                    payload["raw"] = payload
                    return BrainReviewDetail.model_validate(payload)
            listed_all = self.list_reviews(status="resolved", limit=200)
            if listed_all is not None:
                for item in listed_all.reviews:
                    if item.effective_id() == rid:
                        payload = item.model_dump(mode="json")
                        payload["review_id"] = rid
                        payload["raw"] = payload
                        return BrainReviewDetail.model_validate(payload)
            raise

    def resolve_review(
        self,
        review_id: str,
        request: BrainResolveRequest,
    ) -> BrainResolveResponse | None:
        if not self.reviews_enabled:
            return None
        rid = (review_id or "").strip()
        if not rid:
            raise BrainHttpError("review_id is required")
        raw = self._post_json(
            f"/brain/v1/reviews/{rid}/resolve",
            _to_live_resolve_payload(request),
        )
        return _from_live_resolve_response(raw, review_id=rid)


def _to_live_retrieve_payload(request: RetrieveContextRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {"query_text": request.query}
    if request.entity_ids:
        payload["entity_ids"] = list(request.entity_ids)
    return payload


def _to_live_troubleshoot_payload(request: TroubleshootContextRequest) -> dict[str, Any]:
    signals: list[str] = []
    for key, value in (request.observed_signals or {}).items():
        if value is True or str(value).strip().lower() in {"1", "true", "yes", "on"}:
            signals.append(str(key))
        elif value not in (False, None, "", 0):
            signals.append(f"{key}={value}")
    if request.query:
        signals.append(str(request.query))
    for item in request.attachment_summaries or []:
        text = str(item or "").strip()
        if text:
            signals.append(text)
    if request.playbook_resolution and request.playbook_resolution != "pinned":
        signals.append(f"playbook_resolution={request.playbook_resolution}")
    for cid in request.candidate_playbook_ids or []:
        signals.append(f"candidate:{cid}")
    payload: dict[str, Any] = {
        "session_id": request.session_id,
        "observed_signals": signals,
    }
    if request.playbook_id:
        payload["playbook_id"] = request.playbook_id
    if request.node_id:
        payload["current_node_id"] = request.node_id
    if request.entity_ids:
        payload["entity_ids"] = list(request.entity_ids)
    return payload


def _to_live_feedback_payload(request: BrainFeedbackRequest) -> dict[str, Any]:
    text_parts = [
        str(request.user_text or "").strip(),
        str(request.proposed_change or "").strip(),
    ]
    if request.about:
        text_parts.insert(0, f"about={request.about}")
    text = "\n".join(part for part in text_parts if part).strip() or (
        f"sentiment={request.sentiment}"
    )
    targets: list[str] = []
    raw_targets = request.targets or {}
    if isinstance(raw_targets, dict):
        for key, value in raw_targets.items():
            if value is None or value == "" or value == []:
                continue
            if isinstance(value, list):
                for item in value:
                    if item:
                        targets.append(str(item))
            else:
                targets.append(f"{key}:{value}" if key else str(value))
    elif isinstance(raw_targets, list):
        targets = [str(item) for item in raw_targets if item]
    return {
        "session_id": request.session_id,
        "interaction_id": request.interaction_id,
        "sentiment": request.sentiment,
        "text": text,
        "targets": targets,
        "image_summaries": list(request.image_summaries or []),
    }


def _to_live_resolve_payload(request: BrainResolveRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    resolution = str(request.resolution or "").strip()
    lowered = resolution.lower()
    # Live SME resolve: omit resolution to accept Tool-6 proposal (typical MERGE approve).
    if resolution and lowered not in {"approve", "approved", "edit"}:
        payload["resolution"] = resolution
    elif lowered == "edit" and request.edited_proposed_change is not None:
        payload["resolution"] = str(request.edited_proposed_change)
    if request.winner_record_id:
        payload["winner_record_id"] = request.winner_record_id
    return payload


def _excerpt_from_live(item: dict[str, Any]) -> HydratedExcerpt:
    refs_raw = item.get("source_refs") or item.get("refs") or item.get("evidence_refs") or []
    source_refs = [str(ref).strip() for ref in list(refs_raw) if str(ref).strip()]
    return HydratedExcerpt(
        record_id=str(item.get("id") or item.get("record_id") or ""),
        record_type=str(item.get("type") or item.get("record_type") or ""),
        validation_status=str(item.get("validation_status") or ""),
        title=str(item.get("label") or item.get("title") or "") or None,
        text=str(item.get("text") or ""),
        source_refs=source_refs,
    )


def _from_live_context_response(
    raw: dict[str, Any],
    *,
    query_echo: str,
    task: str,
) -> BrainContextResponse:
    # Live shape: {task, excerpts[], excerpt_count, ...} OR already-normalized packet shape.
    if "approved_excerpts" in raw or "packet" in raw:
        return BrainContextResponse.model_validate(raw)

    excerpts_raw = raw.get("excerpts") or []
    approved: list[HydratedExcerpt] = []
    working: list[HydratedExcerpt] = []
    conflicts: list[HydratedExcerpt] = []
    for item in excerpts_raw:
        if not isinstance(item, dict):
            continue
        excerpt = _excerpt_from_live(item)
        status = (excerpt.validation_status or "").strip().lower()
        if status in {"sme_approved", "catalog_authoritative"}:
            approved.append(excerpt)
        elif status in {"conflicting"}:
            conflicts.append(excerpt)
        else:
            working.append(excerpt)

    packet = ContextPacket(
        task=str((raw.get("task") or {}).get("name") if isinstance(raw.get("task"), dict) else task),
        current_state=dict(raw.get("task") or {}) if isinstance(raw.get("task"), dict) else {},
        entities=[str(item) for item in (raw.get("entity_ids") or [])],
        approved_knowledge=[str(item) for item in (raw.get("approved_knowledge_ids") or [])],
        evidence_excerpts=[item.record_id for item in approved if item.record_id],
        conflicts=[item.record_id for item in conflicts if item.record_id],
    )
    return BrainContextResponse(
        packet=packet,
        approved_excerpts=approved,
        working_material=working,
        conflicts=conflicts,
        query_echo=query_echo,
        brain_backend="azure",
        trace={
            "excerpt_count": raw.get("excerpt_count"),
            "truncated_excerpt_count": raw.get("truncated_excerpt_count"),
        },
    )


def _from_live_feedback_response(raw: dict[str, Any]) -> BrainFeedbackResponse:
    if "accepted" in raw or "brain_review_id" in raw:
        return BrainFeedbackResponse.model_validate(raw)
    review_ids = [str(item) for item in (raw.get("review_ids") or []) if item]
    written = [str(item) for item in (raw.get("written_record_ids") or []) if item]
    status = str(raw.get("status") or "")
    accepted = status.lower() not in {"error", "failed", "rejected"}
    return BrainFeedbackResponse(
        accepted=accepted,
        brain_review_id=review_ids[0] if review_ids else None,
        status=status,
        mutated_record_ids=written,
        message=str(raw.get("detail") or ""),
        errors=[] if accepted else [str(raw.get("detail") or status)],
    )


def _from_live_resolve_response(
    raw: dict[str, Any], *, review_id: str
) -> BrainResolveResponse:
    if "message" in raw and "apply_status" in raw:
        return BrainResolveResponse.model_validate(raw)
    applied = raw.get("applied")
    return BrainResolveResponse(
        review_id=str(raw.get("review_id") or review_id),
        status="resolved" if applied is True else ("needs_human" if applied is False else str(raw.get("status") or "resolved")),
        resolution=str(raw.get("resolution") or ""),
        mutated_record_ids=[str(item) for item in (raw.get("mutated_record_ids") or [])],
        message=str(raw.get("detail") or raw.get("message") or ""),
        applied=bool(applied) if applied is not None else None,
        apply_status="applied" if applied is True else ("accepted_not_executed" if applied is False else None),
    )


def _parse_review_list(raw: Any, *, status_filter: str | None = None) -> BrainReviewListResponse:
    if isinstance(raw, list):
        rows = raw
        total = len(rows)
    elif isinstance(raw, dict):
        rows = raw.get("reviews") or raw.get("items") or raw.get("results") or []
        total = raw.get("total")
        if total is None:
            total = len(rows) if isinstance(rows, list) else 0
    else:
        raise BrainHttpError("Brain review list returned unexpected JSON")
    if not isinstance(rows, list):
        raise BrainHttpError("Brain review list missing reviews array")
    reviews: list[BrainReviewSummary] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        normalized = dict(item)
        if not normalized.get("review_id") and normalized.get("id"):
            normalized["review_id"] = normalized["id"]
        if not normalized.get("title"):
            normalized["title"] = (
                normalized.get("check_name")
                or str(normalized.get("proposed_change") or "")[:120]
                or normalized.get("review_id")
            )
        reviews.append(BrainReviewSummary.model_validate(normalized))
    open_count = None
    if isinstance(raw, dict) and raw.get("open_count") is not None:
        open_count = int(raw["open_count"])
        total = open_count if status_filter == "open" else total
    return BrainReviewListResponse(
        reviews=reviews,
        total=int(total) if total is not None else len(reviews),
        status_filter=status_filter,
    )


def _parse_review_detail(raw: Any) -> BrainReviewDetail:
    if not isinstance(raw, dict):
        raise BrainHttpError("Brain review detail returned non-object JSON")
    payload = dict(raw)
    if "review" in raw and isinstance(raw["review"], dict):
        payload = {**raw["review"], **{k: v for k, v in raw.items() if k != "review"}}
    if not payload.get("review_id") and payload.get("id"):
        payload["review_id"] = payload["id"]
    payload["raw"] = raw
    return BrainReviewDetail.model_validate(payload)


def build_brain_http_client(
    settings: AppSettings | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
) -> BrainHttpClient:
    return BrainHttpClient(settings=settings, transport=transport)


def safe_retrieve_context(
    client: BrainHttpClient,
    request: RetrieveContextRequest,
) -> BrainContextResponse | None:
    try:
        return client.get_retrieve_context(request)
    except Exception:
        logger.warning("brain_http_retrieve_failed", exc_info=True)
        return None


def safe_troubleshoot_context(
    client: BrainHttpClient,
    request: TroubleshootContextRequest,
) -> BrainContextResponse | None:
    try:
        return client.get_troubleshoot_context(request)
    except Exception:
        logger.warning("brain_http_troubleshoot_failed", exc_info=True)
        return None


def safe_submit_feedback(
    client: BrainHttpClient,
    request: BrainFeedbackRequest,
) -> BrainFeedbackResponse | None:
    try:
        return client.submit_feedback(request)
    except Exception as exc:
        logger.warning("brain_http_feedback_failed", exc_info=True)
        return BrainFeedbackResponse(
            accepted=False,
            status="forward_failed",
            message=str(exc),
            errors=[str(exc)],
        )


def safe_list_reviews(
    client: BrainHttpClient,
    *,
    status: str = "open",
    limit: int = 50,
) -> BrainReviewListResponse | None:
    try:
        return client.list_reviews(status=status, limit=limit)
    except Exception:
        logger.warning("brain_http_list_reviews_failed", exc_info=True)
        return None


def safe_get_review(
    client: BrainHttpClient,
    review_id: str,
) -> BrainReviewDetail | None:
    try:
        return client.get_review(review_id)
    except Exception:
        logger.warning("brain_http_get_review_failed", exc_info=True)
        return None


def safe_resolve_review(
    client: BrainHttpClient,
    review_id: str,
    request: BrainResolveRequest,
) -> BrainResolveResponse | None:
    try:
        return client.resolve_review(review_id, request)
    except Exception:
        logger.warning("brain_http_resolve_review_failed", exc_info=True)
        return None


def get_brain_warmup_status() -> dict[str, Any]:
    with _warmup_lock:
        return dict(_warmup_status)


def _set_warmup_status(**updates: Any) -> None:
    with _warmup_lock:
        _warmup_status.update(updates)


def warmup_brain_http(
    client: BrainHttpClient | None = None,
    *,
    settings: AppSettings | None = None,
) -> dict[str, Any]:
    """Run a Brain cold-start probe (blocking). Safe to call when Brain is off."""
    active = settings or get_app_settings()
    if not active.brain_http_enabled:
        status = {"ok": False, "skipped_reason": "brain_http_disabled"}
        _set_warmup_status(
            started=True,
            completed=True,
            ok=False,
            skipped_reason=status["skipped_reason"],
            error=None,
            elapsed_seconds=0,
        )
        return status
    if not active.brain_http_warmup_on_startup:
        status = {"ok": False, "skipped_reason": "warmup_disabled"}
        _set_warmup_status(
            started=True,
            completed=True,
            ok=False,
            skipped_reason=status["skipped_reason"],
            error=None,
            elapsed_seconds=0,
        )
        return status
    brain = client or build_brain_http_client(active)
    _set_warmup_status(
        started=True,
        completed=False,
        ok=None,
        error=None,
        skipped_reason=None,
        elapsed_seconds=None,
    )
    logger.info("Brain HTTP warmup starting (cold retrieve can take ~40-50s)")
    result = brain.warmup()
    _set_warmup_status(
        completed=True,
        ok=bool(result.get("ok")),
        error=result.get("error"),
        skipped_reason=result.get("skipped_reason"),
        elapsed_seconds=result.get("elapsed_seconds"),
        path=result.get("path"),
    )
    if result.get("ok"):
        logger.info(
            "Brain HTTP warmup ok in %ss via %s",
            result.get("elapsed_seconds"),
            result.get("path"),
        )
    elif result.get("skipped_reason"):
        logger.info("Brain HTTP warmup skipped: %s", result.get("skipped_reason"))
    else:
        logger.warning("Brain HTTP warmup failed: %s", result.get("error"))
    return result


def start_brain_warmup_background(
    *,
    settings: AppSettings | None = None,
) -> bool:
    """Kick Brain warmup on a daemon thread so API startup stays responsive."""
    active = settings or get_app_settings()
    if not active.brain_http_enabled or not active.brain_http_warmup_on_startup:
        warmup_brain_http(settings=active)
        return False
    if not (active.brain_http_retrieve or active.brain_http_troubleshoot):
        warmup_brain_http(settings=active)
        return False

    def _run() -> None:
        warmup_brain_http(settings=active)

    thread = threading.Thread(
        target=_run,
        name="brain-http-warmup",
        daemon=True,
    )
    thread.start()
    logger.info("Brain HTTP warmup scheduled in background")
    return True


__all__ = [
    "BrainContextResponse",
    "BrainFeedbackRequest",
    "BrainFeedbackResponse",
    "BrainHttpClient",
    "BrainHttpError",
    "BrainResolveRequest",
    "BrainResolveResponse",
    "BrainReviewDetail",
    "BrainReviewListResponse",
    "BrainReviewSummary",
    "ContextPacket",
    "HydratedExcerpt",
    "RetrieveContextRequest",
    "TroubleshootContextRequest",
    "build_brain_http_client",
    "get_brain_warmup_status",
    "safe_get_review",
    "safe_list_reviews",
    "safe_resolve_review",
    "safe_retrieve_context",
    "safe_submit_feedback",
    "safe_troubleshoot_context",
    "start_brain_warmup_background",
    "warmup_brain_http",
]
