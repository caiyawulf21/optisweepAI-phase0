# Case-Triage Logic (Baseline-first)

## Goals
- First turn uses **root-cause baseline only**.
- Follow-up questions are **LLM-generated**.
- Case selection is explicit (one button per case).
- After case selection, route to **workflow** or **procedure**; otherwise ask follow-up.

## Flow
1. **First turn**
   - Extract symptoms.
   - Match against `data/derived/root_cause_dataset.json`.
   - Only return cases that share **at least one matching symptom**.
   - Render case cards: **Case #, Title, Symptoms, Root-cause summary**.
   - Ask: “Which case matches?” and show **one button per case** + “None match”.

2. **Case selected**
   - Persist `selected_case_id`.
   - If the case has `linked_workflow_ids_canonical`, load the workflow from
     Cosmos (`canonical_workflow_definitions`) and route **only when** the
     case confidence meets `CANONICAL_WORKFLOW_HIGH_CONFIDENCE_THRESHOLD`.
   - Otherwise, use symptom-driven procedure guidance (dynamic procedure
     guidance remains in case-triage).
   - If neither is available, ask an LLM follow-up question.

3. **None match**
   - Ask **LLM-generated follow-up** question.
   - Re-run baseline matching with the new info.
   - If still no match, continue follow-ups or fall back to procedure guidance.

4. **QA mode**
   - Always synthesize from retrieval results.
   - Provide summary + related references.

## UI Notes
- Case matches should **not** appear in citations.
- Case cards show:
  - **Case # + Title**
  - **Symptoms** (bulleted list)
  - Root-cause summary line
  - Per-case **“Match case”** button
