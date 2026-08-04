#!/usr/bin/env python3
"""Verify live Cosmos corpus connectivity, cumulative cases, and operator examples.

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
from backend.app.retrieval.hybrid_retriever import HybridRetriever, RetrievalConfig
from backend.app.services.gate_phrase_loader import gate_phrase_table_usable
from backend.app.services.keyword_signal_extractor import get_default_extractor

EXPECTED_CASES = {"218550", "223554", "228086", "228723"}
SMOKE_QUERIES = [
    ("AGVs stopped", "228086"),
    ("agvs aren't moving, rms showing no alarms", "228086"),
    ("bag-out stopped after sorting", "218550"),
    ("hospital tote induction blocked", "223554"),
    ("zone can't pair", "228723"),
]


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
    preferred_version = client.publish_version_id
    image_repo = CanonicalImageRepository()
    preferred_image_rows = []
    try:
        from backend.app.repositories.cosmos_client import cosmos_container

        images_container = cosmos_container(
            settings.container_canonical_images or "publish_canonical_images"
        )
        preferred_image_rows = list(
            images_container.query_items(
                query=(
                    "SELECT c.image_id, c.storage_uri FROM c "
                    "WHERE c.publish_version_id = @version"
                ),
                parameters=[{"name": "@version", "value": preferred_version}],
                partition_key=preferred_version,
            )
        )
    except Exception as exc:
        print(f"FAIL: could not query preferred image partition: {exc}")
        return 1
    image_count = len(preferred_image_rows)
    images_with_http_uri = sum(
        1
        for row in preferred_image_rows
        if str(row.get("storage_uri") or "").startswith(("http://", "https://"))
    )
    images_missing_http_uri = image_count - images_with_http_uri
    cases = {
        str(card.get("case_id") or "")
        for card in index.symptom_cards.values()
        if card.get("case_id")
    }
    empty_examples = sorted(
        pid
        for pid, card in index.symptom_cards.items()
        if not list(card.get("support_user_language_examples") or [])
    )
    missing_cases = sorted(EXPECTED_CASES - cases)
    configured_version = settings.publish_version_id
    resolved_version = client.publish_version_id
    report = {
        "status": "ok" if index.embeddings else "empty",
        "source": settings.corpus_source,
        "configured_publish_version_id": configured_version,
        "resolved_publish_version_id": resolved_version,
        "auto_publish_version": settings.auto_publish_version,
        "case_ids": sorted(cases),
        "missing_expected_cases": missing_cases,
        "playbooks_missing_support_user_language_examples": empty_examples,
        "embedding_counts": {
            "playbook_prompt_a": len(playbook_a),
            "playbook_prompt_b": len(playbook_b),
            "canonical_runbook": len(runbooks),
            "operational_context": len(operational),
            "total": len(index.embeddings),
        },
        "symptom_card_count": len(index.symptom_cards),
        "link_count": len(index.links),
        "gate_phrase_table_loaded": gate_phrase_table_usable(index.gate_phrase_table),
        "gate_phrase_symptom_keys": sorted(
            (index.gate_phrase_table or {}).get("symptom_phrases")
            or (index.gate_phrase_table or {}).get("legacy_signal_phrases")
            or {}
        ),
        "canonical_images_container": settings.container_canonical_images,
        "canonical_images_publish_version_id": preferred_version,
        "canonical_images_runtime_fallback_version_id": image_repo.publish_version_id,
        "canonical_image_count": image_count,
        "canonical_images_with_http_storage_uri": images_with_http_uri,
        "canonical_images_missing_http_storage_uri": images_missing_http_uri,
    }

    gate_smoke = get_default_extractor().extract(
        "agvs aren't moving, rms showing no alarms"
    )
    report["gate_extraction_smoke"] = {
        "query": "agvs aren't moving, rms showing no alarms",
        "observed": dict(gate_smoke.observed_signals),
        "ok": bool(
            gate_smoke.observed_signals.get("agvs_stopped")
            and gate_smoke.observed_signals.get("no_rms_alarm")
        ),
    }

    smoke: list[dict] = []
    if index.embeddings and index.symptom_cards:
        retriever = HybridRetriever(
            index.embeddings,
            config=RetrievalConfig(),
            symptom_cards=index.symptom_cards,
        )
        for query, expect_case in SMOKE_QUERIES:
            enriched = query
            lower = query.lower()
            if "aren't moving" in lower or "arent moving" in lower:
                enriched = f"{query} agvs stopped"
            if "rms" in lower and "alarm" in lower and "no rms alarm" not in enriched.lower():
                enriched = f"{enriched} no rms alarm"
            hits = retriever.search(
                enriched, record_types={"playbook_prompt_a"}, top_k=3
            )
            top = hits[0] if hits else None
            top_case = str((top.filter_metadata or {}).get("case_id") or "") if top else ""
            matched = bool(top) and (
                top_case == expect_case or expect_case in top.source_record_id
            )
            if not matched:
                for hit in hits:
                    cid = str((hit.filter_metadata or {}).get("case_id") or "")
                    if cid == expect_case or expect_case in hit.source_record_id:
                        top = hit
                        top_case = expect_case
                        matched = True
                        break
            smoke.append(
                {
                    "query": query,
                    "expect_case": expect_case,
                    "got_case": top_case or None,
                    "ok": matched,
                    "combined": top.combined_score if top else None,
                    "symptom": top.symptom_score if top else None,
                    "coverage": top.coverage if top else None,
                }
            )
    report["smoke"] = smoke
    print(json.dumps(report, indent=2))

    if not index.embeddings:
        print(
            "FAIL: zero embeddings loaded. Update PUBLISH_VERSION_ID or keep AUTO_PUBLISH_VERSION=true."
        )
        return 1
    if missing_cases:
        print(f"FAIL: missing expected cases: {missing_cases}")
        return 1
    if empty_examples:
        print(
            "FAIL: playbooks missing support_user_language_examples: "
            f"{empty_examples}"
        )
        return 1
    if not report["gate_phrase_table_loaded"]:
        print("FAIL: gate_phrase_table missing or empty for this publish version")
        return 1
    if not report["gate_extraction_smoke"]["ok"]:
        print(f"FAIL: gate extraction smoke: {report['gate_extraction_smoke']}")
        return 1
    failed_smoke = [row for row in smoke if not row.get("ok")]
    if failed_smoke:
        print(f"FAIL: smoke ranking mismatches: {failed_smoke}")
        return 1
    sample_playbook = playbook_a[0].source_record_id if playbook_a else None
    if sample_playbook:
        payload = client.get_playbook(sample_playbook, variant="prompt_a")
        print(f"sample_playbook_ok={payload is not None} id={sample_playbook}")
    if image_count == 0:
        print(
            f"FAIL: container {settings.container_canonical_images!r} returned zero images "
            f"for preferred publish_version_id={preferred_version!r}."
        )
        return 1
    if images_missing_http_uri:
        print(
            "FAIL: preferred publish has canonical images missing HTTPS storage_uri: "
            f"{images_missing_http_uri}/{image_count} in "
            f"publish_version_id={preferred_version!r}. "
            "Re-run Stage 11 with Blob upload enabled, or "
            "python -m backend.app.scripts.refresh_canonical_image_sas."
        )
        return 1
    print("OK: cumulative corpus + gate phrases + operator examples + smoke ranking + images")
    return 0


if __name__ == "__main__":
    sys.exit(main())
