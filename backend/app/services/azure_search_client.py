from __future__ import annotations

import json
from pathlib import Path

from backend.app.schemas.assistant import Citation, RetrievalResult
from backend.app.schemas.incident import Cat1KnowledgeRecord
from backend.app.services.record_status import is_runtime_retrieval_record


class RetrievalClient:
    def search(self, query: str, signals: dict[str, bool], limit: int = 5) -> list[RetrievalResult]:
        raise NotImplementedError


class LocalCat1RetrievalClient(RetrievalClient):
    def __init__(self, data_path: str | Path = "data/curated/cat1_records.json") -> None:
        self.data_path = Path(data_path)

    def search(self, query: str, signals: dict[str, bool], limit: int = 5) -> list[RetrievalResult]:
        records = self._load_records()
        active_signals = {key for key, value in signals.items() if value}
        query_terms = {term.strip(".,:;!?").lower() for term in query.split() if len(term.strip(".,:;!?")) > 3}
        scored: list[tuple[float, Cat1KnowledgeRecord, list[str]]] = []

        for record in records:
            record_signals = set(record.observed_signals)
            matched_signals = sorted(active_signals.intersection(record_signals))
            text_blob = " ".join(
                [
                    record.failure_signature,
                    record.symptom_summary,
                    record.root_cause_summary or "",
                    record.resolution_summary or "",
                    record.source_notes or "",
                ]
            ).lower()
            term_hits = sum(1 for term in query_terms if term in text_blob)
            signal_score = len(matched_signals) / max(len(record_signals), 1)
            term_score = min(term_hits / 8, 0.35)
            authority_score = min(record.source_authority, 1.0) * 0.1
            confidence = min(signal_score + term_score + authority_score, 1.0)
            if confidence > 0:
                scored.append((confidence, record, matched_signals))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            RetrievalResult(
                record_id=record.record_id,
                source_case_id=record.source_case_id,
                title=record.failure_signature,
                issue_category=record.issue_category,
                failure_signature=record.failure_signature,
                matched_signals=matched_signals,
                confidence=round(confidence, 3),
                citation=Citation(
                    source_id=record.record_id,
                    title=record.failure_signature,
                    reference=record.source_case_id,
                    excerpt=record.source_notes or record.symptom_summary,
                ),
                source_notes=record.source_notes,
            )
            for confidence, record, matched_signals in scored[:limit]
        ]

    def _load_records(self) -> list[Cat1KnowledgeRecord]:
        if not self.data_path.exists():
            return []
        raw = json.loads(self.data_path.read_text(encoding="utf-8"))
        return [Cat1KnowledgeRecord(**item) for item in raw if is_runtime_retrieval_record(item)]


class AzureSearchRetrievalClient(LocalCat1RetrievalClient):
    pass
