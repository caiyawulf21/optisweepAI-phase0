from __future__ import annotations

from backend.app.repositories.base_repository import CosmosRepository


class WorkflowCandidateRepository(CosmosRepository):
    container_name = "workflow_candidates"
