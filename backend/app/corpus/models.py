from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EmbeddingRecord:
    record_id: str
    record_type: str
    source_record_id: str
    embedded_text: str
    vector: list[float]
    embedding_model: str
    filter_metadata: dict[str, Any]


@dataclass(frozen=True)
class RelationshipLink:
    link_type: str
    source_record_id: str
    target_record_id: str
    link_confidence: str = ""
    link_rank: int = 999


@dataclass
class CorpusIndex:
    publish_version_id: str
    embeddings: list[EmbeddingRecord] = field(default_factory=list)
    links: list[RelationshipLink] = field(default_factory=list)
    symptom_cards: dict[str, dict[str, Any]] = field(default_factory=dict)

    def embeddings_by_type(self, record_type: str) -> list[EmbeddingRecord]:
        return [item for item in self.embeddings if item.record_type == record_type]
