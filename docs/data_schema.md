# Data Schema

## Conversation State

The LangGraph state tracks:

- `session_id`
- `user_message`
- `extracted_signals`
- `issue_category`
- `retrieval_results`
- `retrieval_confidence`
- `selected_workflow_id`
- `workflow_state`
- `escalation_required`
- `escalation_reason`
- `final_response`
- `citations`

## Knowledge Records

Candidate incident records in `data/curated/candidate_incident_records.json` preserve source category context and evidence from manual ingestion. They are not runtime retrieval records until explicitly promoted or approved.

Phase 0 ingestion records include `synthesis_level`, `quality_tier`, and future-synthesis eligibility fields. Fallback-generated records use `quality_tier: "fallback_review_only"`, are not eligible for cross-incident synthesis or workflow grouping, and are excluded from normal procedure/workflow candidate exports.

Approved CAT-1 runtime retrieval records may still live in `data/curated/cat1_records.json` for `LocalCat1RetrievalClient`.

## Reusable Procedures And Workflows

Procedure and workflow candidates are evidence-backed local records. Manual ingestion does not upsert them into `procedure_dictionary` or `workflow_definitions`; promotion to reusable runtime assets requires an explicit promotion path.

Merges require evidence-backed overlap across incident timelines, source artifacts, raw evidence, or procedure candidates. Similar wording alone is not enough to create a reusable procedure or workflow.

`ProcedureWorkflowCandidateAgent` can produce review-only procedure and workflow candidates from normalized incident packages. It uses Azure OpenAI to synthesize semantic procedure/workflow groups from canonical incidents, timelines, raw evidence chunks, source artifacts, taxonomy definitions, and existing procedure/workflow candidates. It is category-agnostic: `issue_category` values come from input records and taxonomy/config context, not hardcoded category branches.

Generated procedure and workflow artifacts use `validation_status: "needs_review"`. Workflow candidates also use `status: "draft"`. The agent writes generated sidecar outputs to `data/procedures/generated_procedure_candidates.json` and `data/workflows/generated_workflow_candidates.json` so existing ingestion-exported candidate files are not overwritten. The agent does not write approved runtime workflow YAML, approved workflow definitions, reusable procedures, or Dataset 0 context records.

The synthesis validator requires source candidate IDs to exist, procedure steps to carry evidence refs, workflow steps to reference generated procedures, workflow IDs to avoid case-like identifiers, generated procedures to include normalized action tuples, and restart-style procedures to keep target system/scope boundaries separate.

## Workflow Procedure Links

`data/review/workflow_procedure_links.json` stores review-only mappings from candidate workflows to candidate procedures. Each link includes:

- `link_id`
- `workflow_id`
- `procedure_id`
- `step_ids`
- `source_workflow_candidate_ids`
- `source_procedure_candidate_ids`
- `related_incidents`
- `shared_signals`
- `shared_resolution_patterns`
- `similar_root_cause_hypotheses`
- `evidence_refs`
- `image_refs`
- `rationale`
- `merge_confidence`
- `merge_risk_notes`
- `validation_status: "needs_review"`

## Review Notes

`data/review/review_notes.json` stores review-only notes for weak evidence, missing screenshots, unsafe actions, duplicate procedures, overlapping workflows, SME review questions, missing escalation boundaries, and inferred-versus-validated concerns. Each note includes:

- `note_id`
- `artifact_type`
- `artifact_id`
- `severity`
- `note`
- `recommended_review_owner`
- `evidence_refs`
