from __future__ import annotations

from backend.app.repositories.base_repository import CosmosRepository


class ProcedureRepository(CosmosRepository):
    container_name = "procedure_dictionary"
