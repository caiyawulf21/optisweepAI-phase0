"""Deterministic token-similarity prior over canonical signal vocabulary.

Phase 0 has no embedding service. Tier 3 of the symptom extraction roadmap
calls for a "semantic prior" that shortlists canonical signals likely to be
relevant to the operator's message BEFORE the LLM extractor is asked to
commit. We approximate that with a deterministic token-Jaccard score over
``signal_key + description`` vs. the operator message:

* tokens are lowercased word-character runs >= 3 characters
* a small stoplist drops the most common English connectives
* score = ``|intersection| / |union|``
* the top ``k`` signals are returned, sorted by ``(-score, key)`` for a
  stable tie-break

The scorer is **only** used when ``ENABLE_SEMANTIC_SIGNAL_PRIOR=true``
AND ``ENABLE_LLM_SYMPTOM_EXTRACTION=true``. Its output goes into the
LLM packet under ``semantically_related_signals`` so the prompt can
narrow the LLM's attention to the most relevant candidates without
removing the full vocabulary.

When real embeddings become available later, this module gets a drop-in
replacement that keeps the same ``score_signals(message, vocabulary)``
shape; nothing else has to change.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass


_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "into",
        "onto",
        "that",
        "this",
        "these",
        "those",
        "have",
        "has",
        "are",
        "was",
        "were",
        "been",
        "being",
        "but",
        "not",
        "any",
        "all",
        "how",
        "what",
        "when",
        "where",
        "why",
        "who",
        "which",
        "you",
        "your",
        "our",
        "they",
        "them",
        "their",
        "his",
        "her",
        "its",
        "after",
        "before",
        "during",
        "while",
        "than",
        "then",
        "there",
        "here",
        "about",
        "over",
        "under",
        "between",
        "by",
        "on",
        "in",
        "at",
        "of",
        "to",
        "is",
        "as",
        "be",
        "or",
        "if",
        "an",
        "it",
        "we",
        "i",
        "do",
        "did",
        "does",
        "so",
        "now",
    }
)


@dataclass(frozen=True)
class ScoredSignal:
    key: str
    description: str
    score: float


class SemanticSignalScorer:
    """Token-Jaccard scorer used as the semantic shortlist prior."""

    def __init__(
        self,
        *,
        stopwords: Iterable[str] | None = None,
        min_token_length: int = 3,
    ) -> None:
        self._stopwords = frozenset(
            (stopwords if stopwords is not None else _STOPWORDS)
        )
        self._min_token_length = max(1, min_token_length)

    def score_signals(
        self,
        message: str,
        vocabulary: Mapping[str, str],
        *,
        top_k: int = 8,
        min_score: float = 0.05,
    ) -> list[ScoredSignal]:
        """Return the top ``top_k`` signals by Jaccard similarity.

        ``vocabulary`` is ``{signal_key: description}``. Signals whose
        score falls below ``min_score`` are dropped (we'd rather under-
        shortlist than send the LLM a noisy prior). The result is
        sorted by ``(-score, key)`` for deterministic tie-break.
        """
        message_tokens = self._tokenise(message)
        if not message_tokens or not vocabulary:
            return []
        scored: list[ScoredSignal] = []
        for key, description in vocabulary.items():
            text = f"{key} {description or ''}"
            signal_tokens = self._tokenise(text)
            if not signal_tokens:
                continue
            overlap = len(message_tokens & signal_tokens)
            if overlap == 0:
                continue
            union = len(message_tokens | signal_tokens)
            score = overlap / union if union else 0.0
            if score < min_score:
                continue
            scored.append(
                ScoredSignal(key=key, description=description or "", score=score)
            )
        scored.sort(key=lambda s: (-s.score, s.key))
        return scored[:top_k]

    def _tokenise(self, text: str) -> set[str]:
        if not text:
            return set()
        tokens = {
            t
            for t in _TOKEN_RE.findall(text.lower())
            if len(t) >= self._min_token_length and t not in self._stopwords
        }
        return tokens


__all__ = ["ScoredSignal", "SemanticSignalScorer"]
