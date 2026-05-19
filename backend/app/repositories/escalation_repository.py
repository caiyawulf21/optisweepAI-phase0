from __future__ import annotations

from backend.app.repositories.base_repository import CosmosRepository


class EscalationRepository(CosmosRepository):
    container_name = "escalation_summaries"
