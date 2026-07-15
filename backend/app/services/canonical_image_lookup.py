from __future__ import annotations

from typing import Any

from backend.app.corpus.models import RelationshipLink
from backend.app.repositories.canonical_image_repository import CanonicalImageRepository


def _dedupe_key(record: dict[str, Any]) -> str:
    return str(record.get("image_id") or record.get("id") or "")


def _normalize_image(record: dict[str, Any], *, backend_base: str = "") -> dict[str, Any]:
    image_id = str(record.get("image_id") or record.get("id") or "").strip()
    storage_uri = str(record.get("storage_uri") or "").strip()
    render_uri = storage_uri
    if not render_uri and image_id and backend_base:
        render_uri = f"{backend_base.rstrip('/')}/images/{image_id}"
    return {
        "image_id": image_id,
        "title": record.get("title") or image_id,
        "description": record.get("description"),
        "category": record.get("category"),
        "use_case": record.get("use_case"),
        "storage_uri": storage_uri or None,
        "render_uri": render_uri or None,
        "source_artifact_ids": list(record.get("source_artifact_ids") or []),
        "linked_procedure_ids": list(record.get("linked_procedure_ids") or []),
        "linked_incident_ids": list(record.get("linked_incident_ids") or []),
    }


class CanonicalImageLookup:
    def __init__(self, repository: CanonicalImageRepository | None = None) -> None:
        self._repo = repository or CanonicalImageRepository()

    def get_by_image_id(self, image_id: str, *, backend_base: str = "") -> dict[str, Any] | None:
        record = self._repo.get_by_image_id(image_id)
        if not record:
            return None
        return _normalize_image(record, backend_base=backend_base)

    def resolve_for_artifacts(
        self,
        *,
        artifact_ids: list[str] | None = None,
        embedded_images: list[dict[str, Any]] | None = None,
        backend_base: str = "",
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        """Resolve only explicit screen/artifact refs (no case-wide dump)."""
        results: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add(record: dict[str, Any] | None) -> None:
            if not record:
                return
            normalized = _normalize_image(record, backend_base=backend_base)
            key = _dedupe_key(normalized)
            if not key or key in seen:
                return
            seen.add(key)
            results.append(normalized)

        for image in embedded_images or []:
            if isinstance(image, dict):
                add(image)

        for artifact_id in artifact_ids or []:
            text = str(artifact_id or "").strip()
            if not text:
                continue
            direct = self.get_by_image_id(text, backend_base=backend_base)
            if direct:
                add(direct)
                continue
            for record in self._query_by_artifact(text):
                add(record)
            if len(results) >= limit:
                break
        return results[:limit]

    def resolve_for_context(
        self,
        *,
        procedure_id: str | None = None,
        case_id: str | None = None,
        artifact_ids: list[str] | None = None,
        embedded_images: list[dict[str, Any]] | None = None,
        links: list[RelationshipLink] | None = None,
        backend_base: str = "",
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add(record: dict[str, Any] | None) -> None:
            if not record:
                return
            normalized = _normalize_image(record, backend_base=backend_base)
            key = _dedupe_key(normalized)
            if not key or key in seen:
                return
            seen.add(key)
            results.append(normalized)

        for image in embedded_images or []:
            if isinstance(image, dict):
                add(image)

        if procedure_id:
            for record in self._query_by_procedure(procedure_id):
                add(record)

        if case_id:
            for record in self._query_by_case(case_id):
                add(record)

        resolved_artifacts = list(artifact_ids or [])
        if procedure_id and links:
            for link in links:
                if link.link_type != "artifact_runbook":
                    continue
                if link.target_record_id != procedure_id:
                    continue
                if link.source_record_id:
                    resolved_artifacts.append(link.source_record_id)

        for artifact_id in resolved_artifacts:
            for record in self._query_by_artifact(artifact_id):
                add(record)

        return results[:limit]

    def _version_params(self, extra: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        params = [{"name": "@version", "value": self._repo.publish_version_id}]
        if extra:
            params.extend(extra)
        return params

    def _query_by_procedure(self, procedure_id: str) -> list[dict[str, Any]]:
        return self._repo.query(
            """
            SELECT c.image_id, c.title, c.description, c.category, c.use_case,
                   c.storage_uri, c.source_artifact_ids, c.linked_procedure_ids,
                   c.linked_incident_ids
            FROM c
            WHERE c.publish_version_id = @version
              AND ARRAY_CONTAINS(c.linked_procedure_ids, @procedure_id)
            """,
            parameters=self._version_params(
                [{"name": "@procedure_id", "value": procedure_id}]
            ),
        )

    def _query_by_case(self, case_id: str) -> list[dict[str, Any]]:
        return self._repo.query(
            """
            SELECT c.image_id, c.title, c.description, c.category, c.use_case,
                   c.storage_uri, c.source_artifact_ids, c.linked_procedure_ids,
                   c.linked_incident_ids
            FROM c
            WHERE c.publish_version_id = @version
              AND (
                ARRAY_CONTAINS(c.linked_incident_ids, @case_id)
                OR CONTAINS(c.image_id, @case_id)
                OR c.case_id = @case_id
              )
            """,
            parameters=self._version_params([{"name": "@case_id", "value": case_id}]),
        )

    def _query_by_artifact(self, artifact_id: str) -> list[dict[str, Any]]:
        short_id = artifact_id.removeprefix("artifact_")
        return self._repo.query(
            """
            SELECT c.image_id, c.title, c.description, c.category, c.use_case,
                   c.storage_uri, c.source_artifact_ids, c.linked_procedure_ids,
                   c.linked_incident_ids
            FROM c
            WHERE c.publish_version_id = @version
              AND (
                ARRAY_CONTAINS(c.source_artifact_ids, @artifact_id)
                OR CONTAINS(c.image_id, @short_id)
                OR CONTAINS(c.image_id, @artifact_id)
              )
            """,
            parameters=self._version_params(
                [
                    {"name": "@artifact_id", "value": artifact_id},
                    {"name": "@short_id", "value": short_id},
                ]
            ),
        )


def build_canonical_image_lookup() -> CanonicalImageLookup:
    return CanonicalImageLookup()
