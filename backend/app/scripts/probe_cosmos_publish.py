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
    links_container = db.get_container_client(settings.container_relationship_links)
    rows = list(
        links_container.query_items(
            query=(
                "SELECT c.links FROM c WHERE c.publish_version_id = @v "
                "AND c.doc_type = 'relationship_graph'"
            ),
            parameters=[{"name": "@v", "value": version}],
            partition_key=version,
        )
    )
    artifacts: list[dict] = []
    for row in rows:
        for link in row.get("links") or []:
            if isinstance(link, dict) and link.get("link_type") == "artifact_runbook":
                artifacts.append(link)
    print("artifact_runbook_count", len(artifacts))
    print(json.dumps(artifacts[:5], indent=2))

    runbooks = db.get_container_client(settings.container_runbooks)
    sample = list(
        runbooks.query_items(
            query=(
                "SELECT TOP 3 c.payload.procedure_id, c.payload.canonical_images "
                "FROM c WHERE c.publish_version_id = @v AND c.doc_type = 'runbook'"
            ),
            parameters=[{"name": "@v", "value": version}],
            partition_key=version,
        )
    )
    print("runbook_samples", json.dumps(sample, indent=2)[:2000])

    images = db.get_container_client(settings.container_canonical_images)
    img = list(
        images.query_items(
            query=(
                "SELECT TOP 3 c.image_id, c.category, c.title, c.storage_uri FROM c "
                "WHERE c.publish_version_id = @v"
            ),
            parameters=[{"name": "@v", "value": version}],
            partition_key=version,
        )
    )
    print("canonical_images", json.dumps(img, indent=2))

    playbooks = db.get_container_client(settings.container_playbooks_a)
    pb = list(
        playbooks.query_items(
            query=(
                "SELECT c.record_id, c.payload FROM c WHERE c.publish_version_id = @v "
                "AND c.doc_type = 'playbook' AND CONTAINS(c.record_id, '228086')"
            ),
            parameters=[{"name": "@v", "value": version}],
            partition_key=version,
        )
    )
    print("228086 playbooks", [row.get("record_id") for row in pb])
    if pb:
        nodes = (pb[0].get("payload") or {}).get("nodes") or []
        if nodes:
            proc_ids = nodes[0].get("resolved_runbook_ids") or []
            print("first node runbooks", proc_ids)
            if proc_ids:
                run = list(
                    runbooks.query_items(
                        query=(
                            "SELECT c.payload FROM c WHERE c.publish_version_id = @v "
                            "AND c.doc_type = 'runbook' AND c.record_id = @p"
                        ),
                        parameters=[
                            {"name": "@v", "value": version},
                            {"name": "@p", "value": proc_ids[0]},
                        ],
                        partition_key=version,
                    )
                )
                if run:
                    payload = run[0].get("payload") or {}
                    print(
                        "runbook_images",
                        json.dumps(payload.get("canonical_images") or [], indent=2)[:2000],
                    )
                    proc_id = proc_ids[0]
                    proc_artifacts = [
                        link
                        for link in artifacts
                        if link.get("target_record_id") == proc_id
                    ]
                    print("artifact_links_for_proc", len(proc_artifacts))
                    if proc_artifacts:
                        print(json.dumps(proc_artifacts[:3], indent=2))
                        artifact_id = proc_artifacts[0]["source_record_id"]
                        sa = db.get_container_client(settings.container_source_artifacts)
                        art = list(
                            sa.query_items(
                                query=(
                                    "SELECT TOP 3 c.id, c.source_record_id, c.filter_metadata, "
                                    "c.storage_uri, c.image_id FROM c "
                                    "WHERE CONTAINS(c.id, @a) OR CONTAINS(c.source_record_id, @a)"
                                ),
                                parameters=[{"name": "@a", "value": artifact_id[:40]}],
                                enable_cross_partition_query=True,
                            )
                        )
                        print("source_artifact", json.dumps(art, indent=2)[:2000])

    ci_all = list(
        images.query_items(
            query=(
                "SELECT TOP 5 c.image_id, c.title, c.storage_uri, c.procedure_ids, c.linked_procedure_ids "
                "FROM c WHERE c.publish_version_id = @v AND ("
                "CONTAINS(c.title, 'RMS') OR CONTAINS(c.image_id, '228086')"
                ")"
            ),
            parameters=[{"name": "@v", "value": version}],
            partition_key=version,
        )
    )
    print("rms_or_228086_images", json.dumps(ci_all, indent=2))


if __name__ == "__main__":
    main()
