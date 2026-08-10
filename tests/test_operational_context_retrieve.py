from __future__ import annotations

from backend.app.retrieval.hybrid_retriever import (
    HybridRetriever,
    RetrievalHit,
    diversify_hits,
    mock_embed,
)
from backend.app.runtime.playbook_runtime import resolve_retrieve_record_types
from backend.app.corpus.models import EmbeddingRecord


def test_resolve_retrieve_record_types_always_includes_operational_context() -> None:
    assert "operational_context" in resolve_retrieve_record_types(None)
    assert "operational_context" in resolve_retrieve_record_types(
        ["canonical_runbook", "playbook_prompt_a"]
    )


def test_diversify_hits_reserves_operational_context_slots() -> None:
    hits = [
        RetrievalHit(
            record_id=f"runbook:{idx}",
            record_type="canonical_runbook",
            source_record_id=f"proc_{idx}",
            title=f"Runbook {idx}",
            combined_score=0.9 - (idx * 0.01),
            cosine_score=0.8,
            jaccard_score=0.2,
            filter_metadata={},
            embedded_text="runbook text",
        )
        for idx in range(5)
    ]
    hits.extend(
        [
            RetrievalHit(
                record_id="ctx:1",
                record_type="operational_context",
                source_record_id="ctx_software_stack",
                title="Software stack",
                combined_score=0.4,
                cosine_score=0.3,
                jaccard_score=0.2,
                filter_metadata={},
                embedded_text="OptiSweep WCS RMS Ignition roles",
            ),
            RetrievalHit(
                record_id="ctx:2",
                record_type="operational_context",
                source_record_id="ctx_blank_rms",
                title="Blank RMS",
                combined_score=0.35,
                cosine_score=0.25,
                jaccard_score=0.2,
                filter_metadata={},
                embedded_text="Blank RMS may mean access blocked",
            ),
        ]
    )
    selected = diversify_hits(
        hits,
        top_k=5,
        reserve_by_type={"operational_context": 2},
    )
    context_ids = {
        hit.source_record_id
        for hit in selected
        if hit.record_type == "operational_context"
    }
    assert "ctx_software_stack" in context_ids
    assert "ctx_blank_rms" in context_ids
    assert len(selected) == 5


def test_hybrid_search_includes_sample_operational_context() -> None:
    records = [
        EmbeddingRecord(
            record_id="runbook:1",
            record_type="canonical_runbook",
            source_record_id="proc_rms",
            embedded_text="Check RMS active AGV faults",
            vector=mock_embed("Check RMS active AGV faults"),
            embedding_model="mock-hash-v1",
            filter_metadata={"title": "RMS faults"},
        ),
        EmbeddingRecord(
            record_id="ctx:1",
            record_type="operational_context",
            source_record_id="ctx_optisweep_software_stack",
            embedded_text=(
                "OptiSweep software service stack WCS RMS Ignition communication path"
            ),
            vector=mock_embed(
                "OptiSweep software service stack WCS RMS Ignition communication path"
            ),
            embedding_model="mock-hash-v1",
            filter_metadata={"title": "OptiSweep software/service stack"},
        ),
    ]
    hits = HybridRetriever(records).search(
        "What is the OptiSweep software service stack?",
        record_types={"canonical_runbook", "operational_context"},
        top_k=3,
        reserve_by_type={"operational_context": 1},
    )
    assert any(hit.record_type == "operational_context" for hit in hits)
