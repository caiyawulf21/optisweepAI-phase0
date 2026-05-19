from __future__ import annotations

from backend.app.repositories.base_repository import CosmosRepository


class IngestionRunRepository(CosmosRepository):
    container_name = "ingestion_runs"
