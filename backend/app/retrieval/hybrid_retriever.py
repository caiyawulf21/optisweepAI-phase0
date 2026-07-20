from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any

from backend.app.corpus.models import EmbeddingRecord


STOPWORDS = {
    "a", "an", "and", "for", "in", "of", "on", "the", "to", "use", "using", "with",
    "tell", "me", "about", "what", "is", "are", "how", "do", "does", "please",
    "explain", "describe", "our", "your", "this", "that",
}


@dataclass(frozen=True)
class RetrievalConfig:
    vector_weight: float = 0.7
    lexical_weight: float = 0.3
    playbook_match_threshold: float = 0.80
    playbook_high_confidence_threshold: float = 0.90
    playbook_pin_coverage_threshold: float = 0.40


@dataclass
class RetrievalHit:
    record_id: str
    record_type: str
    source_record_id: str
    title: str
    combined_score: float
    cosine_score: float
    jaccard_score: float
    filter_metadata: dict[str, Any]
    embedded_text: str = ""
    symptom_score: float = 0.0
    coverage: float = 0.0


def tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return {token for token in tokens if token not in STOPWORDS and len(token) > 1}


def token_jaccard(first_text: str, second_text: str) -> float:
    first_tokens = tokenize(first_text)
    second_tokens = tokenize(second_text)
    if not first_tokens or not second_tokens:
        return 0.0
    return len(first_tokens & second_tokens) / len(first_tokens | second_tokens)


def cosine_similarity(first: list[float], second: list[float]) -> float:
    if not first or not second or len(first) != len(second):
        return 0.0
    dot = sum(a * b for a, b in zip(first, second))
    norm_a = math.sqrt(sum(a * a for a in first))
    norm_b = math.sqrt(sum(b * b for b in second))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def mock_embed(text: str, dimensions: int = 64) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = [(digest[index % len(digest)] / 127.5) - 1.0 for index in range(dimensions)]
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [value / norm for value in values]


def entry_phrase_coverage(
    query_text: str,
    symptoms: list[str],
    examples: list[str] | None = None,
) -> float:
    """Fraction of query tokens covered by any entry symptom/example phrase.

    Short operator queries (for example ``AGVs stopped``) should score high when
    those tokens appear in the playbook card, even if they touch only one of many
    symptom phrases.
    """
    query_tokens = tokenize(query_text)
    phrases = [str(p) for p in [*symptoms, *(examples or [])] if str(p).strip()]
    if not query_tokens or not phrases:
        return 0.0
    covered: set[str] = set()
    for phrase in phrases:
        phrase_tokens = tokenize(phrase)
        if phrase_tokens:
            covered |= query_tokens & phrase_tokens
    return len(covered) / len(query_tokens)


def symptom_overlap_score(
    query_text: str,
    symptoms: list[str],
    examples: list[str] | None = None,
) -> float:
    query_tokens = tokenize(query_text)
    if not query_tokens:
        return 0.0
    phrases = [str(p) for p in [*symptoms, *(examples or [])] if str(p).strip()]
    if not phrases:
        return 0.0
    best = 0.0
    for phrase in phrases:
        phrase_tokens = tokenize(phrase)
        if not phrase_tokens:
            continue
        overlap = len(query_tokens & phrase_tokens) / len(query_tokens | phrase_tokens)
        best = max(best, overlap)
    coverage = entry_phrase_coverage(query_text, symptoms, examples)
    return 0.70 * best + 0.30 * coverage


def expand_query_tokens(tokens: set[str]) -> set[str]:
    expanded = set(tokens)
    if "service" in expanded:
        expanded.add("software")
    if "software" in expanded:
        expanded.add("service")
    if "opti" in expanded:
        expanded.add("optisweep")
    if "optisweep" in expanded:
        expanded.add("opti")
    return expanded


def title_overlap_score(
    query_text: str,
    *,
    title: str,
    source_record_id: str,
    embedded_text: str,
) -> float:
    """Lexical boost from title / id / head text — resists long-doc Jaccard collapse."""
    query_tokens = expand_query_tokens(tokenize(query_text))
    if not query_tokens:
        return 0.0
    title_text = str(title or "").strip()
    if not title_text:
        title_text = str(embedded_text or "").split("\n", 1)[0].strip()
    id_text = str(source_record_id or "").replace("_", " ")
    head = str(embedded_text or "")[:280]
    title_tokens = tokenize(f"{title_text} {id_text}")
    head_tokens = tokenize(f"{title_text} {id_text} {head}")
    if not title_tokens and not head_tokens:
        return 0.0
    title_coverage = (
        len(query_tokens & title_tokens) / len(query_tokens) if title_tokens else 0.0
    )
    head_coverage = (
        len(query_tokens & head_tokens) / len(query_tokens) if head_tokens else 0.0
    )
    return 0.65 * title_coverage + 0.35 * head_coverage


def derive_record_title(
    *,
    metadata: dict[str, Any] | None,
    embedded_text: str,
    source_record_id: str,
) -> str:
    meta = metadata if isinstance(metadata, dict) else {}
    title = str(meta.get("title") or "").strip()
    if title:
        return title
    text = str(embedded_text or "").strip()
    if text:
        first = text.split("\n", 1)[0].strip()
        # Prefer the earliest instruction/punctuation boundary so ". " later in the
        # paragraph does not swallow the real title.
        cut_at: int | None = None
        for separator in (" Use ", ". ", " — ", " - "):
            idx = first.find(separator)
            if idx > 0 and (cut_at is None or idx < cut_at):
                cut_at = idx
        if cut_at is not None:
            first = first[:cut_at].strip()
        if first and len(first) <= 160:
            return first
        if first:
            return first[:157].rstrip() + "..."
    return str(source_record_id or "").strip()


class HybridRetriever:
    def __init__(
        self,
        records: list[EmbeddingRecord],
        config: RetrievalConfig | None = None,
        symptom_cards: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.records = records
        self.config = config or RetrievalConfig()
        self.symptom_cards = symptom_cards or {}

    def _aligned_query_vector(
        self,
        query_text: str,
        query_vector: list[float],
        record: EmbeddingRecord,
    ) -> list[float]:
        """Match query vector dims/model per record.

        Mixed corpuses (e.g. Azure 1536-dim playbooks + mock-hash 64-dim runbooks)
        zero out cosine when a single query vector is compared across families.
        For mock-hash records, resynthesize a mock query at the record dim.
        """
        dims = len(record.vector)
        if not dims:
            return []
        if query_vector and len(query_vector) == dims:
            return query_vector
        if record.embedding_model == "mock-hash-v1" or not query_vector:
            return mock_embed(query_text, dimensions=dims)
        return []

    def _score_record(
        self,
        query_text: str,
        query_vector: list[float],
        record: EmbeddingRecord,
    ) -> RetrievalHit:
        aligned = self._aligned_query_vector(query_text, query_vector, record)
        cosine = cosine_similarity(aligned, record.vector) if aligned else 0.0
        jaccard = token_jaccard(query_text, record.embedded_text)
        combined = self.config.vector_weight * cosine + self.config.lexical_weight * jaccard
        metadata = record.filter_metadata
        title = derive_record_title(
            metadata=metadata,
            embedded_text=record.embedded_text,
            source_record_id=record.source_record_id,
        )
        symptom_score = 0.0
        coverage = 0.0
        if record.record_type.startswith("playbook_"):
            card = self.symptom_cards.get(record.source_record_id, {})
            symptoms = list(card.get("observed_entry_symptoms") or [])
            examples = list(card.get("support_user_language_examples") or [])
            symptom_score = symptom_overlap_score(query_text, symptoms, examples)
            coverage = entry_phrase_coverage(query_text, symptoms, examples)
            combined = max(combined, symptom_score)
        else:
            coverage = title_overlap_score(
                query_text,
                title=title,
                source_record_id=record.source_record_id,
                embedded_text=record.embedded_text,
            )
            # Soft lexical uplift so short "what is OptiSweep service" queries
            # surface software/overview runbooks even when full-text Jaccard is tiny.
            if coverage > 0.0:
                combined = max(combined, 0.55 * coverage + 0.45 * cosine)
                symptom_score = coverage
        return RetrievalHit(
            record_id=record.record_id,
            record_type=record.record_type,
            source_record_id=record.source_record_id,
            title=title,
            combined_score=round(combined, 4),
            cosine_score=round(cosine, 4),
            jaccard_score=round(jaccard, 4),
            filter_metadata=metadata,
            embedded_text=record.embedded_text,
            symptom_score=round(symptom_score, 4),
            coverage=round(coverage, 4),
        )

    def search(
        self,
        query_text: str,
        *,
        query_vector: list[float] | None = None,
        record_types: set[str] | None = None,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> list[RetrievalHit]:
        vector = query_vector if query_vector is not None else mock_embed(query_text)
        hits: list[RetrievalHit] = []
        for record in self.records:
            if record_types and record.record_type not in record_types:
                continue
            hit = self._score_record(query_text, vector, record)
            if hit.combined_score >= min_score:
                hits.append(hit)
        hits.sort(key=lambda item: (-item.combined_score, item.source_record_id))
        return hits[:top_k]
