"""Runtime models for the dynamic procedure-guidance mode.

These models are the deterministic in-memory contract used by the
fallback dynamic procedure-guidance runtime that activates when canonical
workflow confidence is below the high-confidence threshold but linked
canonical procedure evidence is strong enough to drive a guided
troubleshooting path.

Notes
-----
* ``RuntimeStepResponse`` is intentionally an INTERNAL Pydantic model.
  The wire format remains :class:`backend.app.schemas.assistant.TroubleshootResponse`;
  the dynamic procedure-guidance node serialises a ``RuntimeStepResponse``
  into the existing response shape (top-level ``mode`` field plus the new
  ``dynamic_procedure_step`` discriminator + sub-object).
* ``DynamicProcedurePath`` is ALWAYS session-only. Its ``validation_status``
  is hard-coded to ``"runtime_generated_unapproved"`` so it can never be
  confused with an approved canonical workflow YAML.
"""
from __future__ import annotations

from backend.app.schemas.runtime.models import (
    DynamicProcedurePath,
    RuntimeMode,
    RuntimePathState,
    RuntimeProcedureMatch,
    RuntimeProcedureStep,
    RuntimeRoutingDiagnostics,
    RuntimeRoutingPreview,
    RuntimeSignal,
    RuntimeStepResponse,
    RuntimeWorkflowState,
    StepResponseType,
)


__all__ = [
    "DynamicProcedurePath",
    "RuntimeMode",
    "RuntimePathState",
    "RuntimeProcedureMatch",
    "RuntimeProcedureStep",
    "RuntimeRoutingDiagnostics",
    "RuntimeRoutingPreview",
    "RuntimeSignal",
    "RuntimeStepResponse",
    "RuntimeWorkflowState",
    "StepResponseType",
]
