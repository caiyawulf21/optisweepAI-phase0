from __future__ import annotations

from backend.app.repositories.base_repository import CosmosRepository


class IncidenceWorkflowRepository(CosmosRepository):
    container_name = "incidence_workflow_definitions"
