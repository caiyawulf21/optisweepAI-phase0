from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _env_truthy(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class CorpusSettings:
    cosmos_endpoint: str
    cosmos_key: str
    cosmos_database: str
    container_runbooks: str
    container_playbooks_a: str
    container_playbooks_b: str
    container_relationship_links: str
    container_source_artifacts: str
    container_operational_context: str
    container_canonical_images: str
    container_gate_phrase_tables: str
    publish_version_id: str
    auto_publish_version: bool
    playbook_match_threshold: float
    playbook_high_confidence_threshold: float
    playbook_pin_coverage_threshold: float
    default_playbook_variant: str
    skip_playbook_confirmation: bool
    enable_llm_branch_match: bool
    enable_llm_retrieve_synthesis: bool
    enable_llm_orchestrator: bool

    @property
    def cosmos_configured(self) -> bool:
        return bool(self.cosmos_endpoint and self.cosmos_key)

    @property
    def corpus_source(self) -> str:
        return "cosmos"


def get_corpus_settings() -> CorpusSettings:
    return CorpusSettings(
        cosmos_endpoint=_env("COSMOS_ENDPOINT") or _env("AZURE_COSMOS_ENDPOINT"),
        cosmos_key=_env("COSMOS_KEY") or _env("AZURE_COSMOS_KEY"),
        cosmos_database=_env("COSMOS_DATABASE")
        or _env("AZURE_COSMOS_DATABASE_NAME", "optisweep_knowledge_phase0"),
        container_runbooks=_env("COSMOS_CONTAINER_RUNBOOKS", "runbooks"),
        container_playbooks_a=_env("COSMOS_CONTAINER_PLAYBOOKS_A", "playbooks_prompt_a"),
        container_playbooks_b=_env("COSMOS_CONTAINER_PLAYBOOKS_B", "playbooks_prompt_b"),
        container_relationship_links=_env(
            "COSMOS_CONTAINER_RELATIONSHIP_LINKS", "relationship_links"
        ),
        container_source_artifacts=_env(
            "COSMOS_CONTAINER_SOURCE_ARTIFACTS", "source_artifacts"
        ),
        container_operational_context=_env(
            "COSMOS_CONTAINER_OPERATIONAL_CONTEXT", "operational_context"
        ),
        container_canonical_images=_env(
            "COSMOS_CONTAINER_CANONICAL_IMAGES", "publish_canonical_images"
        ),
        container_gate_phrase_tables=_env(
            "COSMOS_CONTAINER_GATE_PHRASE_TABLES", "gate_phrase_tables"
        ),
        publish_version_id=_env(
            "PUBLISH_VERSION_ID", "publish_20260722_000304_b57a7153"
        ),
        auto_publish_version=_env_truthy("AUTO_PUBLISH_VERSION", default=True),
        playbook_match_threshold=float(_env("PLAYBOOK_MATCH_THRESHOLD", "0.55")),
        playbook_high_confidence_threshold=float(
            _env("PLAYBOOK_HIGH_CONFIDENCE_THRESHOLD", "0.75")
        ),
        playbook_pin_coverage_threshold=float(
            _env("PLAYBOOK_PIN_COVERAGE_THRESHOLD", "0.25")
        ),
        default_playbook_variant=_env("DEFAULT_PLAYBOOK_VARIANT", "prompt_a"),
        skip_playbook_confirmation=_env_truthy("SKIP_PLAYBOOK_CONFIRMATION", default=False),
        enable_llm_branch_match=_env_truthy("ENABLE_LLM_BRANCH_MATCH", default=True),
        enable_llm_retrieve_synthesis=_env_truthy(
            "ENABLE_LLM_RETRIEVE_SYNTHESIS", default=True
        ),
        enable_llm_orchestrator=_env_truthy("ENABLE_LLM_ORCHESTRATOR", default=True),
    )
