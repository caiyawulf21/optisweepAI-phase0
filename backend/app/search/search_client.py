from __future__ import annotations

from typing import Any

from backend.app.config.settings import AzureKnowledgeSettings, get_settings


def search_index_client(settings: AzureKnowledgeSettings | None = None) -> Any:
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents.indexes import SearchIndexClient

    active_settings = settings or get_settings()
    active_settings.require_search()
    return SearchIndexClient(active_settings.search_endpoint, AzureKeyCredential(active_settings.search_key))


def search_client(settings: AzureKnowledgeSettings | None = None) -> Any:
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient

    active_settings = settings or get_settings()
    active_settings.require_search()
    return SearchClient(active_settings.search_endpoint, active_settings.search_index_name, AzureKeyCredential(active_settings.search_key))
