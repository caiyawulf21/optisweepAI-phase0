# Ingestion record types → app runtime mapping

**Cosmos storage:** Documents wrap payloads as `{ doc_type, record_id, publish_version_id, payload }`.  
Runtime always reads `payload` for playbooks and runbooks. See `docs/cosmos_data_map.md`.

## Playbook (`doc_type: "playbook"`, container A or B)

Primary orchestration document. One per incident case (Prompt A) or multiple per case (Prompt B).

| Field | App use |
|-------|---------|
| `playbook_id` | Session `active_playbook_id` |
| `case_id` | Session `active_case_id`; display only |
| `extraction_mode` | A/B filter: `one_playbook_candidate_per_incident` = Prompt A |
| `title`, `user_facing_summary` | UI header |
| `observed_entry_symptoms` | Retrieval boost + display |
| `nodes[]` | Graph execution |
| `nodes[].node_id` | Session `current_node_id` |
| `nodes[].node_type` | `diagnostic_decision`, `branching_condition`, `recovery_action`, etc. |
| `nodes[].allowed_roles` | Role gate |
| `nodes[].decision_outcomes` | Branch buttons |
| `nodes[].branches` | Deterministic next-node routing |
| `nodes[].resolved_runbook_ids` | **Primary** procedure resolution |
| `nodes[].runbook_links[]` | Fallback link metadata (confidence, rank) |

## Playbook retrieval card (`playbook_retrieval_cards.json`)

Embedded for turn-1 vector search. Not used during node execution.

| Field | App use |
|-------|---------|
| `playbook_id` | Join to playbook document |
| `observed_entry_symptoms` | Lexical boost |
| `support_user_language_examples` | Lexical boost |
| `node_retrieval_summaries[].retrieval_text` | Optional per-node search (not needed for demo) |

## Runbook (`doc_type: "runbook"`, container `COSMOS_CONTAINER_RUNBOOKS`)

Executable procedure. Loaded by `procedure_id`.

| Field | App use |
|-------|---------|
| `procedure_id` | Primary key |
| `title`, `summary`, `when_to_use` | UI context |
| `procedure_type` | `operation`, `diagnostic`, `recovery`, `reference` |
| `role_required`, `support_safe` | Step filtering |
| `steps[]` | Instruction rendering |
| `steps[].instruction`, `expected_result` | Main content |
| `steps[].screens_or_images[]` | Join to artifacts via link graph |
| `steps[].stop_or_escalate_if` | Escalation triggers |
| `escalation_guidance` | Escalation node content |

## Playbook→runbook link (`playbook_runbook_links.json`)

| Field | App use |
|-------|---------|
| `playbook_id`, `node_id` | Lookup key |
| `procedure_id` | Runbook to load |
| `link_rank` | Sort key (1 = preferred) |
| `link_confidence` | Display / logging only |

## Relationship link (`relationship_links.json`)

| `link_type` | Traversal |
|-------------|-----------|
| `playbook_runbook` | `playbook_id:node_id` → `procedure_id` |
| `artifact_runbook` | `artifact_id` → `procedure_id` (screenshots) |
| `incident_runbook` | incident record → source runbook |
| `context_runbook` | operational context → runbook (manual procedures) |

## Embedding (`doc_type: "embedding"` — in same container as parent record type)

| Field | App use |
|-------|---------|
| `record_type` | Filter: `playbook_prompt_a`, `playbook_prompt_b`, `canonical_runbook` |
| `source_record_id` | Join to playbook or runbook `record_id` |
| `embedded_text` | Lexical jaccard |
| `vector` | Cosine similarity |
| `filter_metadata` | Case ID, extraction_mode, title |
| `embedding_model` | Must match query embed deployment |

## Deprecated — delete app loaders for these

| Legacy backend artifact | Replacement |
|-------------------------|-------------|
| `root_cause_dataset.json` | Playbook retrieval + `case_id` on playbook |
| `data/workflows/canonical/*.yaml` | `canonical_playbooks.json` |
| `canonical_procedure_dictionary.json` | `canonical_runbooks.json` |
| `cat1_records.json` | Runbook embedding records |
| `signal_alias_map.yaml` | Optional keyword enrichment only |
| `canonical_images.json` | `artifact_runbook` link graph |

## ID remapping note

Per-source incident runbooks use source `procedure_id` values. Shared Stage 7 canonical runbooks may use `_canonical_v1` suffix. Playbook links reference **canonical** IDs. Use `candidate_to_procedure_mapping.json` only when bridging source Stage 8 links to canonical catalog.
