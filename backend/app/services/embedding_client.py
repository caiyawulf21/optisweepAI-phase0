from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib import request as urllib_request


DEFAULT_EMBEDDING_CONFIG_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "azure_openai.local.json"
)


@dataclass(frozen=True)
class EmbeddingConfig:
    endpoint: str
    api_key: str
    deployment: str
    api_version: str


def _load_config(config_path: Path | None = None) -> EmbeddingConfig | None:
    path = config_path or DEFAULT_EMBEDDING_CONFIG_PATH
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        endpoint = data.get("endpoint")
        api_key = data.get("api_key")
        deployment = data.get("embedding_deployment") or data.get(
            "embedding_model"
        )
        if endpoint and api_key and deployment:
            return EmbeddingConfig(
                endpoint=str(endpoint),
                api_key=str(api_key),
                deployment=str(deployment),
                api_version=str(data.get("api_version") or "2024-10-21"),
            )
    endpoint = os.getenv("AZURE_EMBEDDINGS_ENDPOINT") or os.getenv(
        "AZURE_OPENAI_ENDPOINT"
    )
    api_key = os.getenv("AZURE_EMBEDDINGS_API_KEY") or os.getenv(
        "AZURE_OPENAI_API_KEY"
    )
    deployment = (
        os.getenv("AZURE_EMBEDDINGS_DEPLOYMENT")
        or os.getenv("AZURE_EMBEDDINGS_MODEL")
        or os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
        or os.getenv("AZURE_OPENAI_EMBEDDING_MODEL")
    )
    if endpoint and api_key and deployment:
        return EmbeddingConfig(
            endpoint=_normalize_endpoint(endpoint),
            api_key=api_key,
            deployment=deployment,
            api_version=(
                os.getenv("AZURE_EMBEDDINGS_API_VERSION")
                or os.getenv("AZURE_OPENAI_API_VERSION")
                or "2024-10-21"
            ),
        )
    return None


def _normalize_endpoint(endpoint: str) -> str:
    cleaned = endpoint.rstrip("/")
    if cleaned.endswith("/openai/v1"):
        return cleaned[: -len("/openai/v1")]
    if cleaned.endswith("/openai"):
        return cleaned[: -len("/openai")]
    if cleaned.endswith("/openai"):
        return cleaned[: -len("/openai")]
    return cleaned


class EmbeddingClient:
    def __init__(self, config: EmbeddingConfig | None = None) -> None:
        self._config = config or _load_config()
        self._local_model_name = os.getenv("LOCAL_EMBEDDINGS_MODEL")
        self._force_local = os.getenv("FORCE_LOCAL_EMBEDDINGS", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self._local_model = None

    def available(self) -> bool:
        return self._config is not None or self._local_model_name is not None

    def azure_configured(self) -> bool:
        return self._config is not None

    def embed_texts(
        self,
        texts: Iterable[str],
        *,
        dimensions: int | None = None,
        prefer_azure: bool = True,
    ) -> list[list[float]]:
        """Embed texts.

        When Azure embeddings are configured, prefer them so query vectors match
        Cosmos ``text-embedding-3-small`` (or similar). ``LOCAL_EMBEDDINGS_MODEL``
        only runs if Azure is unavailable, prefer_azure is False, or
        FORCE_LOCAL_EMBEDDINGS=true.
        """
        use_local = bool(self._local_model_name) and (
            self._force_local or not prefer_azure or self._config is None
        )
        if use_local:
            return self._embed_local(texts)
        if self._config is None:
            if self._local_model_name:
                return self._embed_local(texts)
            raise RuntimeError("Embedding configuration is missing.")
        target_dims = dimensions
        if target_dims is None:
            env_dims = os.getenv("AZURE_EMBEDDING_DIMENSIONS") or os.getenv(
                "AZURE_SEARCH_VECTOR_DIMENSIONS"
            )
            target_dims = int(env_dims) if env_dims else None
        if "services.ai.azure.com" in self._config.endpoint:
            return self._embed_via_rest(texts, dimensions=target_dims)
        from openai import AzureOpenAI

        client = AzureOpenAI(
            azure_endpoint=self._config.endpoint,
            api_key=self._config.api_key,
            api_version=self._config.api_version,
        )
        payload = [str(text or "") for text in texts]
        kwargs: dict[str, Any] = {
            "model": self._config.deployment,
            "input": payload,
        }
        if target_dims:
            kwargs["dimensions"] = target_dims
        response = client.embeddings.create(**kwargs)
        return [list(item.embedding) for item in response.data]

    def _embed_local(self, texts: Iterable[str]) -> list[list[float]]:
        if self._local_model is None:
            from sentence_transformers import SentenceTransformer

            self._local_model = SentenceTransformer(self._local_model_name)
        embeddings = self._local_model.encode(
            [str(text or "") for text in texts], normalize_embeddings=True
        )
        return [list(row) for row in embeddings]

    def _embed_via_rest(
        self,
        texts: Iterable[str],
        *,
        dimensions: int | None = None,
    ) -> list[list[float]]:
        assert self._config is not None
        payload: dict[str, Any] = {"input": [str(text or "") for text in texts]}
        if dimensions:
            payload["dimensions"] = dimensions
        endpoint = self._config.endpoint.rstrip("/")
        if "/openai/" in endpoint:
            base = endpoint.split("/openai/")[0]
        else:
            base = endpoint
        url = (
            f"{base}/openai/deployments/{self._config.deployment}"
            f"/embeddings?api-version={self._config.api_version}"
        )
        if "/api/projects/" in endpoint:
            url = (
                f"{endpoint}/openai/deployments/{self._config.deployment}"
                f"/embeddings?api-version={self._config.api_version}"
            )
        req = urllib_request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "api-key": self._config.api_key,
            },
            method="POST",
        )
        with urllib_request.urlopen(req) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return [list(item["embedding"]) for item in body.get("data", [])]


def build_embedding_client(config_path: Path | None = None) -> EmbeddingClient:
    return EmbeddingClient(_load_config(config_path))


__all__ = ["EmbeddingClient", "build_embedding_client"]
