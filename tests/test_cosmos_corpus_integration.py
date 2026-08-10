from __future__ import annotations

import os

import pytest

from backend.app.config.env import load_local_env
from backend.app.corpus.cosmos_client import CosmosCorpusClient
from backend.app.corpus.settings import CorpusSettings


def _cosmos_e2e_enabled() -> bool:
    return os.getenv("COSMOS_E2E", "").strip().lower() in {"1", "true", "yes"}


@pytest.mark.cosmos_e2e
@pytest.mark.skipif(not _cosmos_e2e_enabled(), reason="Set COSMOS_E2E=1 with live Cosmos credentials")
def test_live_cosmos_loads_playbook_embeddings() -> None:
    load_local_env()
    settings = CorpusSettings(
        cosmos_endpoint=os.getenv("COSMOS_ENDPOINT") or os.getenv("AZURE_COSMOS_ENDPOINT", ""),
        cosmos_key=os.getenv("COSMOS_KEY") or os.getenv("AZURE_COSMOS_KEY", ""),
        cosmos_database=os.getenv("COSMOS_DATABASE") or os.getenv("AZURE_COSMOS_DATABASE_NAME", ""),
        container_runbooks=os.getenv("COSMOS_CONTAINER_RUNBOOKS", "runbooks"),
        container_playbooks_a=os.getenv("COSMOS_CONTAINER_PLAYBOOKS_A", "playbooks_prompt_a"),
        container_playbooks_b=os.getenv("COSMOS_CONTAINER_PLAYBOOKS_B", "playbooks_prompt_b"),
        container_relationship_links=os.getenv("COSMOS_CONTAINER_RELATIONSHIP_LINKS", "relationship_links"),
        container_source_artifacts=os.getenv("COSMOS_CONTAINER_SOURCE_ARTIFACTS", "source_artifacts"),
        container_operational_context=os.getenv("COSMOS_CONTAINER_OPERATIONAL_CONTEXT", "operational_context"),
        container_canonical_images=os.getenv("COSMOS_CONTAINER_CANONICAL_IMAGES", "publish_canonical_images"),
        container_gate_phrase_tables=os.getenv(
            "COSMOS_CONTAINER_GATE_PHRASE_TABLES", "gate_phrase_tables"
        ),
        publish_version_id=os.getenv("PUBLISH_VERSION_ID", ""),
        auto_publish_version=True,
        playbook_match_threshold=0.55,
        playbook_high_confidence_threshold=0.75,
        playbook_pin_coverage_threshold=0.25,
        default_playbook_variant="prompt_a",
        skip_playbook_confirmation=True,
        enable_llm_branch_match=False,
        enable_llm_retrieve_synthesis=False,
        enable_llm_orchestrator=False,
    )
    assert settings.cosmos_configured
    client = CosmosCorpusClient(settings)
    index = client.load_index(force=True)
    assert len(index.embeddings) > 0
    assert any(item.record_type.startswith("playbook_") for item in index.embeddings)
