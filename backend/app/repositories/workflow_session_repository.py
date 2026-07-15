from __future__ import annotations

from backend.app.repositories.base_repository import CosmosRepository


class WorkflowSessionRepository(CosmosRepository):
    container_name = "workflow_sessions"
