from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.app.config.settings import AzureKnowledgeSettings, get_settings


RAW_CONTAINER = "raw-source-artifacts"
PROCESSED_CONTAINER = "processed-source-artifacts"


def blob_service_client(settings: AzureKnowledgeSettings | None = None) -> Any:
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient

    active_settings = settings or get_settings()
    active_settings.require_storage()
    if active_settings.storage_connection_string:
        return BlobServiceClient.from_connection_string(active_settings.storage_connection_string)
    return BlobServiceClient(active_settings.storage_account_url, credential=DefaultAzureCredential())


def artifact_blob_path(incident_id: str, file_path: str | Path, category: str = "exports", processed: bool = False) -> str:
    path = Path(file_path)
    root = "processed-source-artifacts" if processed else "raw-source-artifacts"
    return f"{root}/cat1/{incident_id}/{category}/{path.name}"


def container_and_blob_path(incident_id: str, file_path: str | Path, category: str = "exports", processed: bool = False) -> tuple[str, str]:
    path = artifact_blob_path(incident_id, file_path, category, processed)
    parts = path.split("/", 1)
    return parts[0], parts[1]


def upload_artifact(file_path: str | Path, incident_id: str, category: str = "exports", processed: bool = False, settings: AzureKnowledgeSettings | None = None) -> dict[str, str]:
    source_path = Path(file_path)
    container_name, blob_path = container_and_blob_path(incident_id, source_path, category, processed)
    service = blob_service_client(settings)
    container = service.get_container_client(container_name)
    try:
        container.create_container()
    except Exception as exc:
        if exc.__class__.__name__ != "ResourceExistsError":
            raise
    with source_path.open("rb") as data:
        container.upload_blob(name=blob_path, data=data, overwrite=True)
    return {
        "file_name": source_path.name,
        "blob_container": container_name,
        "blob_path": blob_path,
    }


def artifact_reference(file_path: str | Path, incident_id: str, category: str = "exports", processed: bool = False) -> dict[str, str]:
    source_path = Path(file_path)
    container_name, blob_path = container_and_blob_path(incident_id, source_path, category, processed)
    return {
        "file_name": source_path.name,
        "blob_container": container_name,
        "blob_path": blob_path,
    }
