from __future__ import annotations

from pydantic import BaseModel


class CanonicalEvidenceReference(BaseModel):
    incident_id: str
    evidence_id: str
    source_artifact_id: str | None = None
    excerpt: str | None = None
