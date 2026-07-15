from __future__ import annotations

from backend.app.repositories.base_repository import CosmosRepository


class CanonicalWorkflowRepository(CosmosRepository):
    """Cosmos repository for the new canonical-only workflow container.

    Targets ``canonical_workflow_definitions`` (partition key
    ``/issue_category``) and stores full ``CanonicalWorkflow`` Pydantic
    payloads as Cosmos documents keyed by ``workflow_id``. Distinct from
    the legacy ``workflow_definitions`` container which holds the flatter
    ``WorkflowDefinition`` model.
    """

    container_name = "canonical_workflow_definitions"
