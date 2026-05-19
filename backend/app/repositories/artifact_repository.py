from __future__ import annotations

from backend.app.repositories.base_repository import CosmosRepository


class ArtifactRepository(CosmosRepository):
    container_name = "source_artifacts"
