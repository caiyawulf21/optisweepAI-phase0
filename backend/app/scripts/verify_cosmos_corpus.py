#!/usr/bin/env python3
"""Verify live Cosmos corpus connectivity and load counts.

Usage:
  python -m backend.app.scripts.verify_cosmos_corpus

Requires COSMOS_ENDPOINT, COSMOS_KEY, and container env vars.
Set RETRIEVAL_BACKEND=cosmos for production mode.
"""
from __future__ import annotations

import json
import sys

from backend.app.config.env import load_local_env
from backend.app.corpus.bootstrap import get_corpus_client, reload_corpus_index
from backend.app.corpus.settings import get_corpus_settings
from backend.app.repositories.canonical_image_repository import CanonicalImageRepository


def main() -> int:
    load_local_env()
    settings = get_corpus_settings()
    if not settings.cosmos_configured:
        print("FAIL: Cosmos not configured. Set COSMOS_ENDPOINT, COSMOS_KEY.")
        return 1
    try:
        index = reload_corpus_index()
    except Exception as exc:
        print(f"FAIL: Could not load corpus from Cosmos: {exc}")
        return 1
    playbook_a = [e for e in index.embeddings if e.record_type == "playbook_prompt_a"]
    playbook_b = [e for e in index.embeddings if e.record_type == "playbook_prompt_b"]
    runbooks = [e for e in index.embeddings if e.record_type == "canonical_runbook"]
    operational = [e for e in index.embeddings if e.record_type == "operational_context"]
    client = get_corpus_client()
    image_repo = CanonicalImageRepository()
    image_rows = image_repo.query(
        "SELECT TOP 1 c.image_id FROM c",
        parameters=[],
    )
    image_count = len(
        image_repo.query(
            "SELECT c.image_id FROM c",
            parameters=[],
        )
    )
    configured_version = settings.publish_version_id
    resolved_version = client.publish_version_id
    report = {
        "status": "ok" if index.embeddings else "empty",
        "source": settings.corpus_source,
        "configured_publish_version_id": configured_version,
        "resolved_publish_version_id": resolved_version,
        "auto_publish_version": settings.auto_publish_version,
        "embedding_counts": {
            "playbook_prompt_a": len(playbook_a),
            "playbook_prompt_b": len(playbook_b),
            "canonical_runbook": len(runbooks),
            "operational_context": len(operational),
            "total": len(index.embeddings),
        },
        "link_count": len(index.links),
        "canonical_images_container": settings.container_canonical_images,
        "canonical_image_count": image_count,
    }
    print(json.dumps(report, indent=2))
    if not index.embeddings:
        print(
            "FAIL: zero embeddings loaded. Update PUBLISH_VERSION_ID or keep AUTO_PUBLISH_VERSION=true."
        )
        return 1
    sample_playbook = playbook_a[0].source_record_id if playbook_a else None
    if sample_playbook:
        payload = client.get_playbook(sample_playbook, variant="prompt_a")
        print(f"sample_playbook_ok={payload is not None} id={sample_playbook}")
    if image_count == 0:
        print(
            f"WARN: container {settings.container_canonical_images!r} returned zero images."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
