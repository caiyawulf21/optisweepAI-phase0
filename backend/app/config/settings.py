from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AzureKnowledgeSettings:
    cosmos_endpoint: str | None = os.getenv("AZURE_COSMOS_ENDPOINT")
    cosmos_key: str | None = os.getenv("AZURE_COSMOS_KEY")
    cosmos_database_name: str = os.getenv("AZURE_COSMOS_DATABASE_NAME", "optisweep_knowledge_phase0")
    search_endpoint: str | None = os.getenv("AZURE_SEARCH_ENDPOINT")
    search_key: str | None = os.getenv("AZURE_SEARCH_KEY")
    search_index_name: str = os.getenv("AZURE_SEARCH_INDEX_NAME", "idx-optisweep-phase0-knowledge")
    storage_account_url: str | None = os.getenv("AZURE_STORAGE_ACCOUNT_URL")
    storage_connection_string: str | None = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    raw_artifacts_container: str = os.getenv("AZURE_RAW_ARTIFACTS_CONTAINER", "raw-source-artifacts")
    processed_artifacts_container: str = os.getenv("AZURE_PROCESSED_ARTIFACTS_CONTAINER", "processed-source-artifacts")
    content_vector_dimensions: int = int(os.getenv("AZURE_SEARCH_VECTOR_DIMENSIONS", "1536"))

    def require_cosmos(self) -> None:
        missing = [name for name, value in {"AZURE_COSMOS_ENDPOINT": self.cosmos_endpoint, "AZURE_COSMOS_KEY": self.cosmos_key}.items() if not value]
        if missing:
            raise ValueError(f"Missing Cosmos DB settings: {', '.join(missing)}")

    def require_search(self) -> None:
        missing = [name for name, value in {"AZURE_SEARCH_ENDPOINT": self.search_endpoint, "AZURE_SEARCH_KEY": self.search_key}.items() if not value]
        if missing:
            raise ValueError(f"Missing Azure AI Search settings: {', '.join(missing)}")

    def require_storage(self) -> None:
        if not self.storage_connection_string and not self.storage_account_url:
            raise ValueError("Missing Blob Storage settings: AZURE_STORAGE_CONNECTION_STRING or AZURE_STORAGE_ACCOUNT_URL")


def get_settings() -> AzureKnowledgeSettings:
    return AzureKnowledgeSettings()
