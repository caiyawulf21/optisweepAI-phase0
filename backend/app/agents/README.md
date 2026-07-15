# Agents

Multi-agent runtime coordinated by LangGraph with a **single orchestrator** control plane. Implementation lives in `runtime.py`; prompts only where LLM is needed.

## Orchestrator owns narrative consistency

`orchestrator_agent` always owns the operator-facing explanation (`retrieval_confidence_reason`). Prompt: `prompts/agents/orchestrator/orchestrate_turn.md`.

**LLM rewrite is rare:** only free-text **retriage** turns (`_retriage_turn`) when `ENABLE_LLM_ORCHESTRATOR=true`. Guided button clicks, pin intros, candidate asks, branch prompts, and user playbook picks use **deterministic templates**.

Workers (`retrieval_agent`, `playbook_pin_agent`) only produce **numbers**. Orchestrator must not recompute pin/coverage or invent playbooks.

## Trace contract

Every agent appends to `state["runtime_trace"]["agents"]`:

```json
{"agent": "orchestrator_agent", "action": "template_only", "mode": "branch_prompt"}
```

Consumed by the **Turns** / **Trace** tabs in Streamlit.

## Role matrix

| Agent | LLM? | Notes |
|-------|------|-------|
| orchestrator_agent | Retriage free-text only | Templates elsewhere; lean `working_memory` on retriage |
| session_agent | No | Session R/W including `path_evidence` |
| symptom_agent | Optional | Keyword + LLM overlay when `ENABLE_LLM_SYMPTOM_EXTRACTION` (free-text entry/retriage) |
| embed_agent | No | Vector encode |
| retrieval_agent | No | Hybrid score |
| playbook_pin_agent | No | Threshold check |
| execute_agent | No | Node + runbook render (template chat text) |
| branch_agent | Free-text only | Exact button labels → deterministic; LLM only ambiguous free text when `ENABLE_LLM_BRANCH_MATCH` |
| image_agent | No | Step screen resolve |
| synthesize_agent | Optional | `/retrieve` only |

## Prompts (LLM slots)

| Agent | File | When |
|-------|------|------|
| orchestrator_agent | `prompts/agents/orchestrator/orchestrate_turn.md` | Retriage free-text narrative only |
| branch_agent | `prompts/agents/branch/match_branch.md` | Ambiguous free-text → match / retriage / probe |
| synthesize_agent | `prompts/agents/synthesize/compose_answer.md` | `/retrieve` answer |

## Lean policy

1. Prefer tools over LLM agent-to-agent chat.
2. Pass structured `state` fields, not chat transcripts, across workers.
3. Guided buttons → no branch LLM, no orchestrator LLM.
4. Persist explicit `path_evidence` (branch outcomes) across retriage with `observed_signals`.
5. Cap LLM fan-out; observe via `runtime_trace.agents`.

## Adding an agent

1. Prefer a pure function tool in `runtime.py` under orchestrator routing.
2. Wire a graph node only if control flow needs it (`playbook_graph.py`).
3. Append trace via `append_agent_trace`.
4. Add `prompts/agents/<name>/` **only** if LLM reasoning is required and flagged.
