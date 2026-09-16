# Repositories

Cosmos persistence helpers. **Playbook runtime only needs a subset.**

## Live (used by services / scripts)

| Module | Used for |
|--------|----------|
| `cosmos_client.py` | Shared Cosmos access |
| `base_repository.py` | Base class |
| `container_config.py` | Container bootstrap script |
| `canonical_image_repository.py` | Image lookups |
| `interaction_log_repository.py` | Turn audit |
| `workflow_session_repository.py` | Session persistence |
| `feedback_repository.py` | Feedback events |

## Leftover Phase-1 (deprecated — not on playbook hot path)

These container names are still listed in `container_config.py` with
`deprecated=True` for bootstrap/test compatibility. Prefer the Stage 11
publish containers (`runbooks`, `playbooks_prompt_*`, `operational_context`,
`relationship_links`, `source_artifacts`, `publish_canonical_images`,
`gate_phrase_tables`) plus app runtime containers
(`workflow_sessions`, `interaction_logs`, `feedback_events`).

Cosmos cannot rename containers in place. To retire a Phase-1 container:
export/copy if needed, stop app/ingestion references, then delete the old
container in Azure. Suggested Azure rename pattern if you must keep data:
create `deprecated_<old_name>`, copy items, then delete `<old_name>`.

`artifact_repository`, `canonical_procedure_repository`, `canonical_workflow_repository`,
`context_repository`, `escalation_repository`, `evidence_repository`,
`incident_repository`, `incidence_workflow_repository`, `procedure_repository`,
`procedure_refinement_repository`, `relationship_repository`, `timeline_repository`,
`workflow_candidate_repository`, `workflow_repository` — and most of `backend/app/models/`.

Safe cleanup candidates for a follow-up PR after confirming no external scripts import them.
