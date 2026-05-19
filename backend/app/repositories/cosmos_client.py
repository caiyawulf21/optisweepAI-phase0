from __future__ import annotations

from typing import Any

from backend.app.config.settings import AzureKnowledgeSettings, get_settings
from backend.app.repositories.container_config import CONTAINERS


def cosmos_database(settings: AzureKnowledgeSettings | None = None) -> Any:
    from azure.cosmos import CosmosClient

    active_settings = settings or get_settings()
    active_settings.require_cosmos()
    client = CosmosClient(active_settings.cosmos_endpoint, credential=active_settings.cosmos_key)
    return client.create_database_if_not_exists(id=active_settings.cosmos_database_name)


def cosmos_container(container_name: str, settings: AzureKnowledgeSettings | None = None) -> Any:
    database = cosmos_database(settings)
    return database.get_container_client(container_name)


def create_containers(settings: AzureKnowledgeSettings | None = None) -> list[dict[str, str]]:
    from azure.cosmos import PartitionKey

    database = cosmos_database(settings)
    created = []
    for definition in CONTAINERS.values():
        database.create_container_if_not_exists(id=definition.name, partition_key=PartitionKey(path=definition.partition_key))
        created.append({"container": definition.name, "partition_key": definition.partition_key})
    return created
