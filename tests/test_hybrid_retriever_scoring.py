from __future__ import annotations

from backend.app.corpus.models import EmbeddingRecord
from backend.app.retrieval.hybrid_retriever import (
    HybridRetriever,
    entry_phrase_coverage,
    mock_embed,
    symptom_overlap_score,
    title_overlap_score,
)


def test_exact_phrase_match_is_high_not_perfect() -> None:
    symptoms = [
        "Site reports that nothing is moving.",
        "Robotic system is reported as not responding.",
        "Small sort is not running.",
        "Totes cannot be removed from hospital.",
        "HMI or RMS appears abnormal.",
        "AGVs are reported out of sync.",
    ]
    examples = [
        "Nothing is moving.",
        "AGVs stopped",
        "robots stopped",
        "nothing is moving",
        "AGVs are stopped",
        "small sort is down",
        "hospital tote issue",
    ]
    coverage = entry_phrase_coverage("agvs stopped", symptoms, examples)
    symptom = symptom_overlap_score("agvs stopped", symptoms, examples)
    assert coverage >= 0.25
    assert symptom >= 0.70
    assert abs(symptom - (0.70 * 1.0 + 0.30 * coverage)) < 1e-6


def test_multi_symptom_query_still_fires_short_entry_phrase() -> None:
    """Full-query Jaccard collapses on comma-joined reports; containment must not."""
    symptoms = [
        "AGVs stopped",
        "nothing is moving on site",
        "site-wide robotic motion stoppage",
    ]
    examples = [
        "AGVs stopped and nothing is moving on site",
        "robots are stopped",
    ]
    query = "AGVs stopped, no RMS alarms"
    symptom = symptom_overlap_score(query, symptoms, examples)
    coverage = entry_phrase_coverage(query, symptoms, examples)
    assert symptom >= 0.75
    assert coverage < 1.0
    assert abs(symptom - (0.70 * 1.0 + 0.30 * coverage)) < 1e-6


def test_enriched_paraphrase_with_stopped_signal_stays_high() -> None:
    symptoms = [
        "AGVs stopped",
        "nothing is moving on site",
    ]
    examples = ["AGVs stopped and nothing is moving on site"]
    # Keyword gate enriches aren't-moving into agvs stopped without card hardcoding.
    query = "agvs aren't moving, rms showing no alarms agvs stopped"
    symptom = symptom_overlap_score(query, symptoms, examples)
    assert symptom >= 0.75


def test_short_query_coverage_is_query_token_based() -> None:
    symptoms = [
        "Site reports that nothing is moving.",
        "Robotic system is reported as not responding.",
        "Small sort is not running.",
        "Totes cannot be removed from hospital.",
        "HMI or RMS appears abnormal.",
        "AGVs are reported out of sync after stoppage.",
    ]
    examples: list[str] = []
    coverage = entry_phrase_coverage("agvs are stopped", symptoms, examples)
    # Query tokens agvs/are/stopped: agvs+are covered by AGV symptom (~2/3).
    assert coverage >= 0.50


def test_mixed_embedding_dims_do_not_zero_mock_cosine() -> None:
    """Azure 1536-dim query vector must not null cosine against mock 64-dim runbooks."""
    runbook_text = "Check overall system RMS for active AGV faults and tipper alarms."
    records = [
        EmbeddingRecord(
            record_id="emb_playbook",
            record_type="playbook_prompt_a",
            source_record_id="playbook_demo",
            embedded_text="Site stoppage playbook",
            vector=mock_embed("playbook demo", dimensions=1536),
            embedding_model="text-embedding-3-small",
            filter_metadata={"title": "Demo playbook"},
        ),
        EmbeddingRecord(
            record_id="emb_runbook",
            record_type="canonical_runbook",
            source_record_id="proc_check_rms_v1",
            embedded_text=runbook_text,
            vector=mock_embed(runbook_text, dimensions=64),
            embedding_model="mock-hash-v1",
            filter_metadata={"title": "Check RMS"},
        ),
    ]
    retriever = HybridRetriever(records)
    mismatched_query = mock_embed("How do I check RMS for AGV faults", dimensions=1536)
    hits = retriever.search(
        "How do I check RMS for AGV faults",
        query_vector=mismatched_query,
        record_types={"canonical_runbook"},
        top_k=1,
    )
    assert hits
    # Aligning dims must restore a non-zero cosine (hash embeds stay modest on paraphrase).
    assert hits[0].cosine_score > 0.0
    assert hits[0].combined_score > 0.3 * hits[0].jaccard_score
    # With a wrong-dim query and no alignment, cosine would be exactly 0.0.


def test_title_overlap_prefers_software_overview_over_noise() -> None:
    query = "tell me about the optisweep service"
    software = title_overlap_score(
        query,
        title="Identify The Role Of Core OptiSweep Software Components",
        source_record_id="proc_identify_the_role_of_core_optisweep_software_components_v1",
        embedded_text=(
            "Identify The Role Of Core OptiSweep Software Components Use the training "
            "source software overview slide to identify the documented role of each "
            "OptiSweep software service."
        ),
    )
    weights = title_overlap_score(
        query,
        title="Install Counter-Balance Weights and Restart the Operator Station",
        source_record_id="proc_install_counterbalance_weights_and_restart_operator_station_v1",
        embedded_text=(
            "Install Counter-Balance Weights and Restart the Operator Station "
            "Install the counter-balance weights using four M10 socket head screws."
        ),
    )
    assert software > weights
    assert software >= 0.4


def test_unrelated_single_token_stays_low() -> None:
    symptoms = [
        "Site reports that nothing is moving.",
        "Robotic system is reported as not responding.",
        "Small sort is not running.",
    ]
    examples = [
        "nothing is moving",
        "robotic system not responding",
        "small sort not running",
    ]
    coverage = entry_phrase_coverage("printer jammed", symptoms, examples)
    assert coverage < 0.25
