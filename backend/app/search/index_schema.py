from __future__ import annotations

from backend.app.config.settings import AzureKnowledgeSettings, get_settings


FILTERABLE_FIELDS = {
    "record_type",
    "dataset",
    "container_name",
    "source_cosmos_id",
    "incident_id",
    "issue_category",
    "site",
    "workflow_id",
    "procedure_id",
    "source_authority",
    "support_safe",
    "resolution_status",
    "created_at",
    "updated_at",
}


SEARCHABLE_FIELDS = {"title", "retrieval_text"}


COLLECTION_FIELDS = {"component", "symptoms", "source_refs"}


def build_search_index(settings: AzureKnowledgeSettings | None = None):
    from azure.search.documents.indexes.models import (
        HnswAlgorithmConfiguration,
        SearchField,
        SearchFieldDataType,
        SearchIndex,
        SearchableField,
        SimpleField,
        VectorSearch,
        VectorSearchProfile,
    )

    active_settings = settings or get_settings()
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True, filterable=True),
        SimpleField(name="record_type", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="dataset", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="container_name", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="source_cosmos_id", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="incident_id", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="issue_category", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="site", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="workflow_id", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="procedure_id", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="source_authority", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="support_safe", type=SearchFieldDataType.Boolean, filterable=True),
        SimpleField(name="resolution_status", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="created_at", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),
        SimpleField(name="updated_at", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),
        SearchableField(name="title", type=SearchFieldDataType.String, analyzer_name="en.lucene"),
        SearchableField(name="retrieval_text", type=SearchFieldDataType.String, analyzer_name="en.lucene"),
        SearchField(name="component", type=SearchFieldDataType.Collection(SearchFieldDataType.String), filterable=True, facetable=True),
        SearchField(name="symptoms", type=SearchFieldDataType.Collection(SearchFieldDataType.String), filterable=True, facetable=True),
        SearchField(name="source_refs", type=SearchFieldDataType.Collection(SearchFieldDataType.String), filterable=True),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=active_settings.content_vector_dimensions,
            vector_search_profile_name="phase0-vector-profile",
        ),
    ]
    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="phase0-hnsw")],
        profiles=[VectorSearchProfile(name="phase0-vector-profile", algorithm_configuration_name="phase0-hnsw")],
    )
    return SearchIndex(name=active_settings.search_index_name, fields=fields, vector_search=vector_search)
