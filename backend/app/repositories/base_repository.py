from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from backend.app.models.base import model_to_dict
from backend.app.repositories.cosmos_client import cosmos_container


class CosmosRepository:
    container_name: str

    def __init__(self, container: Any | None = None) -> None:
        self.container = container or cosmos_container(self.container_name)

    def upsert(self, document: BaseModel | dict[str, Any]) -> dict[str, Any]:
        return self.container.upsert_item(model_to_dict(document))

    def get(self, document_id: str, partition_key: str) -> dict[str, Any]:
        return self.container.read_item(item=document_id, partition_key=partition_key)

    def delete(self, document_id: str, partition_key: str) -> None:
        self.container.delete_item(item=document_id, partition_key=partition_key)

    def query(self, query: str, parameters: list[dict[str, Any]] | None = None, cross_partition: bool = True) -> list[dict[str, Any]]:
        return list(
            self.container.query_items(
                query=query,
                parameters=parameters or [],
                enable_cross_partition_query=cross_partition,
            )
        )
