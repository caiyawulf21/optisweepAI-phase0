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

Curated CAT-1 records in `data/curated/cat1_records.json` provide retrieval evidence and citations. They do not contain executable workflow authority.

## Reusable Procedures And Workflows

Procedure and workflow candidates are evidence-backed draft records. The Workflow Procedure Agent can merge them into reusable records with `needs_sme_review` status, but it never marks them approved automatically.

Merges require evidence-backed overlap across incident timelines, source artifacts, raw evidence, or procedure candidates. Similar wording alone is not enough to create a reusable procedure or workflow.
