from __future__ import annotations

from backend.app.repositories.base_repository import CosmosRepository


class TimelineRepository(CosmosRepository):
    container_name = "timeline_events"
