#!/usr/bin/env python3
from __future__ import annotations

import json

from backend.app.config.env import load_local_env
from backend.app.corpus.settings import get_corpus_settings
from backend.app.repositories.cosmos_client import cosmos_database


def main() -> None:
    load_local_env()
    settings = get_corpus_settings()
    db = cosmos_database()
    version = "publish_20260712_200241_eda952f0"
    proc = "proc_check_overall_system_rms_for_system_faults_and_active_agv_faults_v1"
    runbooks = db.get_container_client(settings.container_runbooks)
    run = list(
        runbooks.query_items(
            query=(
                "SELECT c.payload FROM c WHERE c.publish_version_id = @v "
                "AND c.doc_type = 'runbook' AND c.record_id = @p"
            ),
            parameters=[{"name": "@v", "value": version}, {"name": "@p", "value": proc}],
            partition_key=version,
        )
    )
    if run:
        payload = run[0]["payload"]
        print(json.dumps({
            "procedure_id": payload.get("procedure_id"),
            "title": payload.get("title"),
            "canonical_images": payload.get("canonical_images"),
            "steps": [
                {
                    "step_number": s.get("step_number"),
                    "title": s.get("title"),
                    "canonical_images": s.get("canonical_images"),
                    "visual_evidence": s.get("visual_evidence"),
                    "screenshot_refs": s.get("screenshot_refs"),
                }
                for s in (payload.get("steps") or [])[:3]
            ],
        }, indent=2)[:4000])

    images = db.get_container_client(settings.container_canonical_images)
    linked = list(
        images.query_items(
            query=(
                "SELECT c.image_id, c.title, c.storage_uri, c.linked_procedure_ids, c.case_id "
                "FROM c WHERE c.publish_version_id = @v "
                "AND ARRAY_CONTAINS(c.linked_procedure_ids, @p)"
            ),
            parameters=[
                {"name": "@v", "value": settings.publish_version_id or version},
                {"name": "@p", "value": proc},
            ],
            partition_key=settings.publish_version_id or version,
        )
    )
    print("linked_by_procedure", json.dumps(linked, indent=2))


if __name__ == "__main__":
    main()
