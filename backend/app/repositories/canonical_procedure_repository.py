from __future__ import annotations

from backend.app.repositories.base_repository import CosmosRepository


class CanonicalProcedureRepository(CosmosRepository):
    """Cosmos repository for the new canonical-only procedure container.

    Targets ``canonical_procedure_dictionary`` (partition key
    ``/procedure_type``) and stores full canonical Pydantic payloads as
    Cosmos documents keyed by ``procedure_id``. Distinct from the legacy
    ``procedure_dictionary`` container which holds the flatter
    ``Procedure`` model.
    """

    container_name = "canonical_procedure_dictionary"
