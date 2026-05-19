from __future__ import annotations

from backend.app.repositories.base_repository import CosmosRepository


class ContextRepository(CosmosRepository):
    container_name = "context_reference"
