from __future__ import annotations

from backend.app.repositories.base_repository import CosmosRepository


class RelationshipRepository(CosmosRepository):
    container_name = "knowledge_relationships"
