from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from backend.app.schemas.canonical.evidence import CanonicalEvidenceReference
from backend.app.schemas.canonical.provenance import AgentProvenance


SignalType = Literal[
    "observation",
    "diagnostic",
    "recovery",
    "validation",
    "escalation",
]


class Signal(BaseModel):
    signal_id: str
    name: str
    signal_type: SignalType = "observation"
    description: str | None = None
    affects_components: list[str] = Field(default_factory=list)
    produced_by: list[str] = Field(default_factory=list)
    confirmed_by: list[str] = Field(default_factory=list)
    ruled_out_by: list[str] = Field(default_factory=list)
    evidence_refs: list[CanonicalEvidenceReference] = Field(default_factory=list)
    source_artifacts: list[str] = Field(default_factory=list)
    provenance: AgentProvenance
