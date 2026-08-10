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
    playbook_match_threshold: float = 0.55
    playbook_high_confidence_threshold: float = 0.75
    playbook_pin_coverage_threshold: float = 0.25


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
    normalized = str(text or "").lower().replace("'", "").replace("’", "")
    tokens = re.findall(r"[a-z0-9]+", normalized)
    return {token for token in tokens if token not in STOPWORDS and len(token) > 1}


def token_jaccard(first_text: str, second_text: str) -> float:
    first_tokens = tokenize(first_text)
    second_tokens = tokenize(second_text)
    if not first_tokens or not second_tokens:
        return 0.0
    return len(first_tokens & second_tokens) / len(first_tokens | second_tokens)


def phrase_containment(query_text: str, phrase_text: str) -> float:
    """Fraction of phrase tokens present in the query.

    Multi-symptom operator reports must be able to fully fire a short entry
    phrase (``AGVs stopped``) without being penalized by unrelated sibling
    clauses in the same message. Symmetric Jaccard against the full query
    cannot do that.
    """
    query_tokens = tokenize(query_text)
    phrase_tokens = tokenize(phrase_text)
    if not query_tokens or not phrase_tokens:
        return 0.0
    return len(query_tokens & phrase_tokens) / len(phrase_tokens)


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
    """Fraction of entry phrases with any token overlap against the query.

    A single exact example match among many card phrases must not report
    coverage 1.0 — that would make sparse speech look like perfect certainty.
    """
    query_tokens = tokenize(query_text)
    phrases = [str(p) for p in [*symptoms, *(examples or [])] if str(p).strip()]
    if not query_tokens or not phrases:
        return 0.0
    matched = 0
    for phrase in phrases:
        phrase_tokens = tokenize(phrase)
        if phrase_tokens and query_tokens & phrase_tokens:
            matched += 1
    return matched / len(phrases)


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
        # Containment: did this entry phrase fire inside the operator report?
        # Jaccard: short query vs longer card phrase (keep sparse-query behavior).
        best = max(
            best,
            phrase_containment(query_text, phrase),
            token_jaccard(query_text, phrase),
        )
    coverage = entry_phrase_coverage(query_text, symptoms, examples)
    return 0.70 * best + 0.30 * coverage


def entry_phrase_fires(
    query_text: str,
    symptoms: list[str],
    examples: list[str] | None = None,
    *,
    min_phrase_tokens: int = 2,
) -> bool:
    """True when any multi-token entry phrase is fully contained in the query."""
    for phrase in [*symptoms, *(examples or [])]:
        text = str(phrase or "").strip()
        if not text:
            continue
        if len(tokenize(text)) < min_phrase_tokens:
            continue
        if phrase_containment(query_text, text) >= 1.0:
            return True
    return False


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
        reserve_by_type: dict[str, int] | None = None,
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
        return diversify_hits(
            hits,
            top_k=top_k,
            reserve_by_type=reserve_by_type,
        )


def diversify_hits(
    hits: list[RetrievalHit],
    *,
    top_k: int,
    reserve_by_type: dict[str, int] | None = None,
) -> list[RetrievalHit]:
    """Keep top overall hits while reserving slots for supplemental record types."""
    if top_k <= 0:
        return []
    if not hits:
        return []
    reserves = {
        str(key): max(0, int(value))
        for key, value in dict(reserve_by_type or {}).items()
        if str(key).strip() and int(value) > 0
    }
    if not reserves:
        return hits[:top_k]

    selected: list[RetrievalHit] = []
    used: set[str] = set()

    def _key(hit: RetrievalHit) -> str:
        return f"{hit.record_type}:{hit.source_record_id}:{hit.record_id}"

    reserve_total = min(sum(reserves.values()), max(0, top_k - 1))
    primary_slots = max(1, top_k - reserve_total)
    for hit in hits:
        if len(selected) >= primary_slots:
            break
        key = _key(hit)
        if key in used:
            continue
        selected.append(hit)
        used.add(key)

    for record_type, count in reserves.items():
        added = 0
        for hit in hits:
            if added >= count or len(selected) >= top_k:
                break
            if hit.record_type != record_type:
                continue
            key = _key(hit)
            if key in used:
                continue
            selected.append(hit)
            used.add(key)
            added += 1

    for hit in hits:
        if len(selected) >= top_k:
            break
        key = _key(hit)
        if key in used:
            continue
        selected.append(hit)
        used.add(key)

    selected.sort(key=lambda item: (-item.combined_score, item.source_record_id))
    return selected[:top_k]
