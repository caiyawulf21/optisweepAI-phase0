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

## Leftover Phase-1 (not on playbook hot path)

`artifact_repository`, `canonical_procedure_repository`, `canonical_workflow_repository`,
`context_repository`, `escalation_repository`, `evidence_repository`,
`incident_repository`, `incidence_workflow_repository`, `procedure_repository`,
`procedure_refinement_repository`, `relationship_repository`, `timeline_repository`,
`workflow_candidate_repository`, `workflow_repository` — and most of `backend/app/models/`.

Safe cleanup candidates for a follow-up PR after confirming no external scripts import them.
