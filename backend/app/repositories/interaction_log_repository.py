from __future__ import annotations

from backend.app.repositories.base_repository import CosmosRepository


class InteractionLogRepository(CosmosRepository):
    container_name = "interaction_logs"

    def list_for_session(self, session_id: str) -> list[dict]:
        return self.query(
            "SELECT * FROM c WHERE c.session_id = @session_id ORDER BY c.timestamp ASC",
            parameters=[{"name": "@session_id", "value": session_id}],
            cross_partition=False,
        )
