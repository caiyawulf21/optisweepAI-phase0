from __future__ import annotations

from fastapi import APIRouter, Query

from backend.app.corpus.bootstrap import get_corpus_client
from backend.app.services.canonical_image_lookup import build_canonical_image_lookup


router = APIRouter(prefix="/corpus", tags=["corpus"])


@router.get("/status")
def get_corpus_status() -> dict:
    """Report live Cosmos corpus load status."""
    from collections import Counter

    from backend.app.corpus.bootstrap import get_corpus_index
    from backend.app.corpus.settings import get_corpus_settings
    from backend.app.config import get_app_settings

    settings = get_corpus_settings()
    app_settings = get_app_settings()
    try:
        index = get_corpus_index()
        counts = dict(Counter(item.record_type for item in index.embeddings))
        embedding_total = len(index.embeddings)
        link_count = len(index.links)
        publish_version_id = index.publish_version_id
    except Exception as exc:
        return {
            "source": settings.corpus_source,
            "retrieval_backend": app_settings.retrieval_backend,
            "ok": False,
            "error": str(exc),
            "embedding_counts": {},
            "embedding_total": 0,
            "link_count": 0,
            "publish_version_id": settings.publish_version_id,
        }
    return {
        "source": settings.corpus_source,
        "retrieval_backend": app_settings.retrieval_backend,
        "ok": settings.corpus_source == "cosmos" and embedding_total > 0,
        "publish_version_id": publish_version_id,
        "embedding_counts": counts,
        "embedding_total": embedding_total,
        "link_count": link_count,
    }


@router.get("/playbooks/{playbook_id}")
def get_playbook(
    playbook_id: str,
    variant: str = Query(default="prompt_a"),
) -> dict:
    client = get_corpus_client()
    payload = client.get_playbook(playbook_id, variant=variant)
    if payload is None:
        return {"playbook_id": playbook_id, "found": False}
    return {"playbook_id": playbook_id, "found": True, "payload": payload}


@router.get("/runbooks/{procedure_id}/images")
def get_runbook_images(
    procedure_id: str,
    case_id: str | None = None,
    playbook_id: str | None = None,
    node_id: str | None = None,
    variant: str = Query(default="prompt_a"),
) -> dict:
    del case_id, playbook_id, node_id, variant
    from backend.app.agents.runtime import _resolve_step_images, _step_screen_refs

    client = get_corpus_client()
    runbook = client.get_runbook(procedure_id) or {}
    lookup = build_canonical_image_lookup()
    steps_out = []
    fallback_refs = _step_screen_refs(
        {"screens_or_images": list(runbook.get("screens_or_images") or [])}
    )
    if not fallback_refs:
        fallback_refs = [
            {
                "artifact_id": str(ref.get("artifact_id") or "").strip(),
                "what_to_look_at": ref.get("description") or ref.get("what_to_look_at"),
            }
            for ref in list(runbook.get("visual_references") or [])
            if isinstance(ref, dict) and str(ref.get("artifact_id") or "").strip()
        ]
    for index, step in enumerate(list(runbook.get("steps") or [])):
        if not isinstance(step, dict):
            continue
        screen_refs = _step_screen_refs(step)
        if not screen_refs and index == 0 and fallback_refs:
            screen_refs = list(fallback_refs)
        images = _resolve_step_images(
            lookup,
            screen_refs=screen_refs,
            embedded_images=list(step.get("canonical_images") or step.get("images") or []),
        )
        steps_out.append(
            {
                "step_number": step.get("step_number"),
                "title": step.get("title"),
                "screens_or_images": screen_refs,
                "images": images,
            }
        )
    return {
        "procedure_id": procedure_id,
        "steps": steps_out,
        "images": [],
    }


@router.get("/images/{image_id}")
def get_image_metadata(image_id: str) -> dict:
    lookup = build_canonical_image_lookup()
    record = lookup.get_by_image_id(image_id)
    if record is None:
        return {"image_id": image_id, "found": False}
    return {"image_id": image_id, "found": True, "image": record}


@router.get("/runbooks/{procedure_id}")
def get_runbook(procedure_id: str) -> dict:
    client = get_corpus_client()
    payload = client.get_runbook(procedure_id)
    if payload is None:
        return {"procedure_id": procedure_id, "found": False}
    return {"procedure_id": procedure_id, "found": True, "payload": payload}


@router.get("/playbooks/{playbook_id}/nodes/{node_id}/runbook")
def get_node_runbook(playbook_id: str, node_id: str, variant: str = Query(default="prompt_a")) -> dict:
    client = get_corpus_client()
    procedure_id = client.resolve_runbook_for_node(playbook_id, node_id)
    runbook = client.get_runbook(procedure_id) if procedure_id else None
    return {
        "playbook_id": playbook_id,
        "node_id": node_id,
        "procedure_id": procedure_id,
        "runbook": runbook,
    }
