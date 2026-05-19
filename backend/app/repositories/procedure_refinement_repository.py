from __future__ import annotations

from backend.app.repositories.base_repository import CosmosRepository


class ProcedureRefinementRepository(CosmosRepository):
    container_name = "procedure_refinement_candidates"
