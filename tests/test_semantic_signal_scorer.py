"""Tests for the deterministic token-similarity prior."""
from __future__ import annotations

from backend.app.services.semantic_signal_scorer import (
    ScoredSignal,
    SemanticSignalScorer,
)


def test_score_signals_returns_top_k_in_deterministic_order():
    scorer = SemanticSignalScorer()
    vocab = {
        "agvs_stopped_before_tippers": "AGVs stopped before tippers heartbeat",
        "tipper_heartbeat_timeout_or_zero": "Tipper heartbeat timeout zero",
        "rms_screen_no_faults_visible": "RMS screen no faults visible",
        "hospital_tote_removal_failed": "Hospital tote removal failed",
        "completely_unrelated_signal": "Database connection retry exhausted",
    }
    results = scorer.score_signals(
        "AGVs stopped, tipper heartbeat timeout, hospital tote removal hang",
        vocab,
        top_k=3,
    )
    assert len(results) <= 3
    assert all(isinstance(r, ScoredSignal) for r in results)
    keys = [r.key for r in results]
    assert "agvs_stopped_before_tippers" in keys
    assert "tipper_heartbeat_timeout_or_zero" in keys
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_score_signals_drops_below_min_score_threshold():
    scorer = SemanticSignalScorer()
    vocab = {"unrelated_signal": "completely orthogonal vocabulary content"}
    results = scorer.score_signals(
        "AGVs stopped",
        vocab,
        top_k=5,
        min_score=0.5,
    )
    assert results == []


def test_score_signals_returns_empty_for_empty_inputs():
    scorer = SemanticSignalScorer()
    assert scorer.score_signals("", {"x": "y"}) == []
    assert scorer.score_signals("AGVs stopped", {}) == []


def test_tie_break_is_deterministic_by_key():
    scorer = SemanticSignalScorer()
    vocab = {
        "z_signal": "AGVs stopped",
        "a_signal": "AGVs stopped",
    }
    results = scorer.score_signals("AGVs stopped", vocab, top_k=2)
    assert [r.key for r in results] == ["a_signal", "z_signal"]


def test_stopwords_do_not_inflate_score():
    scorer = SemanticSignalScorer()
    vocab = {"only_stopwords_match": "the and for with from into onto"}
    results = scorer.score_signals("the and for the and", vocab)
    assert results == []
