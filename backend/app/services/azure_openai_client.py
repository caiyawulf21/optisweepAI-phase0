"""Legacy shim that delegates symptom extraction to the keyword extractor.

The Phase 0 ``AzureOpenAIClient.extract_signals`` was a hardcoded substring
matcher that, despite its name, never called Azure. The substring matcher has
moved to :mod:`backend.app.services.keyword_signal_extractor` (which adds
negation handling, a YAML-driven phrase table, and component extraction).
This module is kept as a thin shim so existing imports keep working; the
runtime now goes through the keyword extractor + the optional LLM extractor
in :mod:`backend.app.tools.llm_signal_extractor`.
"""
from __future__ import annotations

import os

from backend.app.services.keyword_signal_extractor import get_default_extractor


class AzureOpenAIClient:
    def __init__(self) -> None:
        self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.api_key = os.getenv("AZURE_OPENAI_API_KEY")
        self.deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
        self.api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

    def extract_signals(self, user_message: str) -> dict[str, bool]:
        result = get_default_extractor().extract(user_message)
        return dict(result.signals)
