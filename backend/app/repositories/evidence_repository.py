from __future__ import annotations

from backend.app.repositories.base_repository import CosmosRepository


class EvidenceRepository(CosmosRepository):
    container_name = "raw_evidence_chunks"
