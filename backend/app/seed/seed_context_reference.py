from __future__ import annotations

import argparse
import json

from backend.app.models.context_reference import ContextReference
from backend.app.models.base import model_to_dict
from backend.app.repositories.context_repository import ContextRepository


CONTEXT_REFERENCE_RECORDS = [
    ContextReference(
        id="ctx_glossary_optisweep",
        context_type="glossary",
        title="Optisweep",
        applies_to=["Optisweep", "WCS", "support"],
        source_authority="manual_phase0",
        retrieval_text="Optisweep is the operational system context for WCS, robot routing, sorting behavior, hospital station handling, service recovery, and support troubleshooting.",
    ),
    ContextReference(
        id="ctx_glossary_rms",
        context_type="glossary",
        title="RMS",
        applies_to=["Optisweep", "AGV", "support"],
        source_authority="manual_phase0",
        retrieval_text="RMS refers to the robot management system used to monitor robot state, AGV position, task status, and fleet behavior.",
    ),
    ContextReference(
        id="ctx_glossary_ignition",
        context_type="glossary",
        title="Ignition",
        applies_to=["Optisweep", "WCS", "controls"],
        source_authority="manual_phase0",
        retrieval_text="Ignition is an operational interface and server context that may expose WCS service state, logs, alarms, and diagnostics relevant to CAT-1 troubleshooting.",
    ),
    ContextReference(
        id="ctx_support_tiers",
        context_type="support_model",
        title="Support tiers",
        applies_to=["support", "escalation", "workflow_routing"],
        source_authority="manual_phase0",
        retrieval_text="Phase 0 distinguishes support tiers and organizational roles. Candidate evidence may mention L1, L2/L3, controls, infrastructure, DBA, DevOps, or L4 project team escalation, but user-provided overlays remain unverified until reviewed.",
    ),
]


def context_documents() -> list[dict]:
    return [model_to_dict(record) for record in CONTEXT_REFERENCE_RECORDS]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    documents = context_documents()
    if args.dry_run:
        print(json.dumps({"dry_run": True, "records": documents}, indent=2))
        return
    repository = ContextRepository()
    for document in documents:
        repository.upsert(document)
    print(json.dumps({"dry_run": False, "upserted": len(documents)}, indent=2))


if __name__ == "__main__":
    main()
