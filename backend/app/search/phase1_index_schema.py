"""Phase 1 Azure AI Search index schema.

Defines the *runtime* search index targeted by the Phase 1 retrieval hot
path (``RETRIEVAL_BACKEND=azure_search``). Kept intentionally separate
from :mod:`backend.app.search.index_schema` so the Phase 0 canonical
indexing pipeline keeps shipping unchanged while the Phase 1 runtime
gets a dedicated index that maps 1:1 to the Phase 1 runtime field list:

    id, container_id, record_type, incident_id, workflow_id,
    procedure_id, issue_category, component, site, source_type,
    source_refs, validation_status, retrieval_text, content_vector

Searchable text concatenated into ``retrieval_text`` upstream:
``retrieval_text``, ``symptom_summary``, ``observed_signals``,
``root_cause_summary``, ``resolution_summary``, ``resolution_steps``,
``escalation_notes``.

The default index name (``optisweep-support-knowledge-dev``) is the
Phase 1 runtime index. Override with ``--index-name`` on the CLI or by
constructing :class:`Phase1SearchIndexSpec` directly.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.app.config.settings import AzureKnowledgeSettings, get_settings


PHASE1_SEARCH_INDEX_NAME = "optisweep-support-knowledge-dev"

PHASE1_REQUIRED_FIELDS: tuple[str, ...] = (
    "id",
    "container_id",
    "record_type",
    "incident_id",
    "workflow_id",
    "procedure_id",
    "issue_category",
    "component",
    "site",
    "source_type",
    "source_refs",
    "validation_status",
    "retrieval_text",
    "content_vector",
)


PHASE1_FILTERABLE_FIELDS: frozenset[str] = frozenset(
    {
        "container_id",
        "record_type",
        "incident_id",
        "workflow_id",
        "procedure_id",
        "issue_category",
        "site",
        "source_type",
        "validation_status",
    }
)

PHASE1_COLLECTION_FIELDS: frozenset[str] = frozenset(
    {"component", "source_refs"}
)

PHASE1_SEARCHABLE_FIELDS: frozenset[str] = frozenset({"retrieval_text"})


@dataclass(frozen=True)
class Phase1SearchIndexSpec:
    """Lightweight, dependency-free spec for the Phase 1 runtime index.

    Lets the CLI emit a deterministic dry-run manifest (and lets tests
    introspect the schema) without importing ``azure-search-documents``.
    """

    index_name: str = PHASE1_SEARCH_INDEX_NAME
    vector_dimensions: int | None = None

    def field_names(self) -> tuple[str, ...]:
        return PHASE1_REQUIRED_FIELDS

    def to_manifest(self) -> dict[str, object]:
        return {
            "index_name": self.index_name,
            "fields": list(PHASE1_REQUIRED_FIELDS),
            "filterable_fields": sorted(PHASE1_FILTERABLE_FIELDS),
            "collection_fields": sorted(PHASE1_COLLECTION_FIELDS),
            "searchable_fields": sorted(PHASE1_SEARCHABLE_FIELDS),
            "vector_dimensions": self.vector_dimensions,
        }


def build_phase1_search_index(
    settings: AzureKnowledgeSettings | None = None,
    *,
    index_name: str = PHASE1_SEARCH_INDEX_NAME,
):
    """Build the live :class:`azure.search.documents.indexes.models.SearchIndex`.

    Imported lazily so the rest of the Phase 1 build (and pytest) does
    not need ``azure-search-documents`` installed.
    """
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
    vector_dims = active_settings.content_vector_dimensions

    fields = [
        SimpleField(
            name="id",
            type=SearchFieldDataType.String,
            key=True,
            filterable=True,
        ),
        SimpleField(
            name="container_id",
            type=SearchFieldDataType.String,
            filterable=True,
            facetable=True,
        ),
        SimpleField(
            name="record_type",
            type=SearchFieldDataType.String,
            filterable=True,
            facetable=True,
        ),
        SimpleField(
            name="incident_id",
            type=SearchFieldDataType.String,
            filterable=True,
            facetable=True,
        ),
        SimpleField(
            name="workflow_id",
            type=SearchFieldDataType.String,
            filterable=True,
            facetable=True,
        ),
        SimpleField(
            name="procedure_id",
            type=SearchFieldDataType.String,
            filterable=True,
            facetable=True,
        ),
        SimpleField(
            name="issue_category",
            type=SearchFieldDataType.String,
            filterable=True,
            facetable=True,
        ),
        SearchField(
            name="component",
            type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            filterable=True,
            facetable=True,
        ),
        SimpleField(
            name="site",
            type=SearchFieldDataType.String,
            filterable=True,
            facetable=True,
        ),
        SimpleField(
            name="source_type",
            type=SearchFieldDataType.String,
            filterable=True,
            facetable=True,
        ),
        SearchField(
            name="source_refs",
            type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            filterable=True,
        ),
        SimpleField(
            name="validation_status",
            type=SearchFieldDataType.String,
            filterable=True,
            facetable=True,
        ),
        SearchableField(
            name="retrieval_text",
            type=SearchFieldDataType.String,
            analyzer_name="en.lucene",
        ),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=vector_dims,
            vector_search_profile_name="phase1-vector-profile",
        ),
    ]
    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="phase1-hnsw")],
        profiles=[
            VectorSearchProfile(
                name="phase1-vector-profile",
                algorithm_configuration_name="phase1-hnsw",
            )
        ],
    )
    return SearchIndex(
        name=index_name, fields=fields, vector_search=vector_search
    )


def phase1_search_index_client(
    settings: AzureKnowledgeSettings | None = None,
):
    """Build a SearchIndexClient. Requires AZURE_SEARCH credentials."""
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents.indexes import SearchIndexClient

    active_settings = settings or get_settings()
    active_settings.require_search()
    return SearchIndexClient(
        active_settings.search_endpoint,
        AzureKeyCredential(active_settings.search_key),
    )


def phase1_search_client(
    settings: AzureKnowledgeSettings | None = None,
    *,
    index_name: str = PHASE1_SEARCH_INDEX_NAME,
):
    """Build a SearchClient against the Phase 1 runtime index."""
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient

    active_settings = settings or get_settings()
    active_settings.require_search()
    return SearchClient(
        active_settings.search_endpoint,
        index_name,
        AzureKeyCredential(active_settings.search_key),
    )


__all__ = [
    "PHASE1_COLLECTION_FIELDS",
    "PHASE1_FILTERABLE_FIELDS",
    "PHASE1_REQUIRED_FIELDS",
    "PHASE1_SEARCH_INDEX_NAME",
    "PHASE1_SEARCHABLE_FIELDS",
    "Phase1SearchIndexSpec",
    "build_phase1_search_index",
    "phase1_search_client",
    "phase1_search_index_client",
]
