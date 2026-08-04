#!/usr/bin/env python3
"""Rotate-storage follow-up: refresh Blob SAS on publish_canonical_images docs."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlparse

from azure.cosmos import CosmosClient
from azure.storage.blob import (
    BlobSasPermissions,
    generate_blob_sas,
)

from backend.app.config.env import load_local_env
from backend.app.config.settings import get_settings
from backend.app.corpus.settings import get_corpus_settings


def _account_name_from_url(account_url: str) -> str:
    host = urlparse(account_url).netloc
    return host.split(".")[0]


def _blob_name_from_uri(storage_uri: str, container: str) -> str | None:
    parsed = urlparse(storage_uri)
    path = unquote(parsed.path.lstrip("/"))
    prefix = f"{container}/"
    if not path.startswith(prefix):
        return None
    return path[len(prefix) :]


def main() -> int:
    load_local_env()
    settings = get_settings()
    corpus = get_corpus_settings()
    conn = (os.getenv("AZURE_STORAGE_CONNECTION_STRING") or "").strip()
    account_url = (os.getenv("AZURE_STORAGE_ACCOUNT_URL") or settings.storage_account_url or "").strip()
    container_blob = (os.getenv("AZURE_CANONICAL_IMAGES_CONTAINER") or "canonical-images").strip()
    if not conn:
        print("FAIL: set AZURE_STORAGE_CONNECTION_STRING after key rotation")
        return 1

    account_name = ""
    account_key = ""
    for part in conn.split(";"):
        if part.startswith("AccountName="):
            account_name = part.split("=", 1)[1]
        elif part.startswith("AccountKey="):
            account_key = part.split("=", 1)[1]
    if not account_name or not account_key:
        print("FAIL: could not parse AccountName/AccountKey from connection string")
        return 1
    if not account_url:
        account_url = f"https://{account_name}.blob.core.windows.net"

    client = CosmosClient(settings.cosmos_endpoint, credential=settings.cosmos_key)
    db = client.get_database_client(settings.cosmos_database_name)
    images = db.get_container_client(corpus.container_canonical_images)
    version = (
        (os.getenv("PUBLISH_VERSION_ID") or "").strip()
        or corpus.publish_version_id
    )
    rows = list(
        images.query_items(
            query="SELECT * FROM c WHERE c.publish_version_id = @v",
            parameters=[{"name": "@v", "value": version}],
            partition_key=version,
        )
    )
    expiry = datetime.now(timezone.utc) + timedelta(days=365)
    updated = 0
    skipped = 0
    for row in rows:
        storage_uri = str(row.get("storage_uri") or "").strip()
        blob_path = str(row.get("blob_path") or "").strip()
        blob_name = blob_path or (
            _blob_name_from_uri(storage_uri, container_blob) if storage_uri else None
        )
        if not blob_name:
            skipped += 1
            continue
        sas = generate_blob_sas(
            account_name=account_name,
            container_name=container_blob,
            blob_name=blob_name,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=expiry,
        )
        new_uri = f"{account_url.rstrip('/')}/{container_blob}/{blob_name}?{sas}"
        if new_uri == storage_uri:
            skipped += 1
            continue
        row["storage_uri"] = new_uri
        images.upsert_item(row)
        updated += 1

    print(
        {
            "container": corpus.container_canonical_images,
            "publish_version_id": version,
            "docs": len(rows),
            "updated": updated,
            "skipped": skipped,
            "sas_expiry_utc": expiry.isoformat(),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
