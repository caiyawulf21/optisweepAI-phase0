from __future__ import annotations

from backend.app.repositories.base_repository import CosmosRepository


class IncidentRepository(CosmosRepository):
    container_name = "incident_records"
