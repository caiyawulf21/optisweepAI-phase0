from __future__ import annotations

from backend.app.graph.state import AssistantState
from backend.app.services.azure_search_client import LocalCat1RetrievalClient


def retrieval_node(state: AssistantState) -> AssistantState:
    client = LocalCat1RetrievalClient()
    results = client.search(state["user_message"], state.get("extracted_signals", {}))
    state["retrieval_results"] = results
    state["retrieval_confidence"] = max((result.confidence for result in results), default=0.0)
    state["citations"] = [result.citation for result in results]
    return state
