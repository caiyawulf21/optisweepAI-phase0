# Playbook runtime architecture

Implemented the Cosmos-backed playbook runtime described by the app handoff references.

## Surfaces

| Surface | API | UI page |
|---------|-----|---------|
| Guided troubleshoot | `POST /troubleshoot` | `ui/pages/1_Guided_Troubleshoot.py` |
| Retrieval chatbot | `POST /retrieve` | `ui/pages/2_Search_Chat.py` |
| Corpus viewer | `GET /corpus/playbooks|runbooks/...` | Playbook/Runbook tab |

## Multi-agent model (lean orchestrator)

**One orchestrator owns the turn.** Spec workers measure; LLM agents reason only on free-text / retriage slots. Most “agents” are **tool scripts** with traces—not LLM conversations.

### Latency policy (guided path)

| Operator input | Branch LLM | Orchestrator LLM |
|----------------|------------|------------------|
| Exact branch / candidate **button** | No (deterministic) | No (template) |
| Pin intro / candidate ask / next-node prompt | — | No (template) |
| Ambiguous free text on a branch | Yes if `ENABLE_LLM_BRANCH_MATCH` | No |
| Free-text **retriage** (new symptoms) | Classify only | Yes if `ENABLE_LLM_ORCHESTRATOR` (lean `working_memory`) |
| First free-text symptom entry | — | No (template pin/candidates); symptom LLM optional |

Session keeps `observed_signals` **and** `path_evidence` (recent node outcomes) across retriage. Button clicks persist path evidence; retriage does not wipe that walk so far.

### Who explains confidence?

**`orchestrator_agent`** always owns `retrieval_confidence_reason`. Prompt: `backend/app/prompts/agents/orchestrator/orchestrate_turn.md`. Pin/coverage stay deterministic. LLM rewrite is **retriage free-text only**.

- `retrieval_agent` / `playbook_pin_agent` compute scores and pin gates (tools).
- `orchestrator_agent` publishes `explain_confidence` / `template_only` / rare `llm_compose` in the trace.

Never invent a second scorer LLM.

### Role matrix

| Name | Type | LLM? | Responsibility |
|------|------|------|----------------|
| **orchestrator_agent** | Control plane | Retriage free-text only (`ENABLE_LLM_ORCHESTRATOR`) | Templates elsewhere; lean working-memory rewrite on retriage |
| session_agent | Tool | No | Load/save session slice (`observed_signals`, `path_evidence`) |
| symptom_agent | Tool | Optional (`ENABLE_LLM_SYMPTOM_EXTRACTION`) | Keyword extract (+ optional LLM overlay on free text) |
| embed_agent | Tool | No | Azure/local/mock embeddings (dims must match Cosmos) |
| retrieval_agent | Tool | No | Hybrid search (cosine + Jaccard + symptom) |
| playbook_pin_agent | Tool | No | Apply pin thresholds (combined + coverage) |
| execute_agent | Tool | No | Resolve node + runbook + branch prompts + step images |
| branch_agent | Tool / LLM | Free-text only (`ENABLE_LLM_BRANCH_MATCH`) | Buttons → deterministic; free text → match / retriage / probe |
| image_agent | Tool | No | Resolve per-step `screens_or_images` only |
| synthesize_agent | LLM | Optional (`ENABLE_LLM_RETRIEVE_SYNTHESIS`) | `/retrieve` answer compose only |

LangGraph wires the pipeline in `backend/app/graph/playbook_graph.py`. Traces go to `runtime_trace.agents[]` (`backend/app/agents/runtime.py`).

### Lean multi-agent practices (implemented policy)

Industry pattern for production multi-agent systems (2025–2026): **prefer one orchestrator + tools** over agent-to-agent chat. Every LLM boundary multiplies tokens, latency, and inconsistency.

1. **Default to tools** for scoring, Cosmos I/O, session, pin gates, runbook render.
2. **LLM only for narrow slots**: ambiguous free-text branch classify, retriage narrative, optional retrieve synthesis, optional symptom assist—never for pin math or button paths.
3. **Structured handoffs**, not full transcripts: workers read fields on `state`; they do not re-prompt each other with chat history.
4. **One owner for user-visible narrative facts** that must stay consistent (confidence reason → orchestrator).
5. **Cap LLM fan-out**: no parallel “critic” agents on the troubleshoot path.
6. **Observe cost/latency via traces** (`runtime_trace.agents`), not by adding more reasoning agents.

Code + prompts: `backend/app/agents/README.md`.

## Routing — `/troubleshoot`

```
session_load  (session_agent)
  ├─ awaiting_candidate → pick_candidate (orchestrator)
  │     ├─ matched playbook → execute → save
  │     ├─ new symptoms → extract → retrieve/pin…
  │     └─ unclear → save (ask again)
  ├─ active_playbook + awaiting_branch → branch
  │     ├─ match → execute → save
  │     ├─ retriage (new symptoms) → extract → retrieve/pin…
  │     └─ probe → save (clarify; keep awaiting_branch)
  ├─ active_playbook → execute → save
  └─ else → extract_symptoms (symptom_agent)
        ├─ no affirmative signals → orchestrator request_symptoms → save
        └─ has symptoms → embed → hybrid → pin
              ├─ gates pass → orchestrator explain_confidence + pin → execute → save
              └─ else → orchestrator explain_confidence + present_playbook_candidates → save
```

Candidate presentation chat text stays short; confidence reason + candidate cards are shown by the UI.

Candidate selection is **deterministic** (symptom-card overlap + hybrid hits). Sparse queries may land on candidates so the operator picks a playbook or adds symptoms.

Turn 2+ with pinned playbook: **no vector search** (ID lookups only).

### Retrieval algorithm (hybrid)

```text
cosine  = cosine_similarity(query_vector, embedding.vector)   # dims must match
jaccard = token_jaccard(query_text, embedding.embedded_text)
combined = 0.7 * cosine + 0.3 * jaccard
# playbooks only:
best_phrase = max(containment(query, phrase), Jaccard(query, phrase))
coverage    = (# query tokens covered by any phrase) / (# query tokens)
symptom     = 0.70 * best_phrase + 0.30 * coverage
combined    = max(combined, symptom)
# containment = |query ∩ phrase| / |phrase|  (multi-symptom reports can fully fire a short entry phrase)
```

**Pin gate:** `combined ≥ PLAYBOOK_MATCH_THRESHOLD` (default 0.80) **and** `coverage ≥ PLAYBOOK_PIN_COVERAGE_THRESHOLD` (default 0.40), or explicit user candidate pick. Candidate-first is the default; auto-pin only when `SKIP_PLAYBOOK_CONFIRMATION=true` and both floors pass.

## Routing — `/retrieve`

```
memory(trim) → embed → hybrid(record_types) → synthesize → memory(commit)
```

Multi-turn memory uses LangChain `InMemoryChatMessageHistory` + `trim_messages`
(max 6 messages; AI text compacted). Session slots keep sticky `resolved_intent`.
Every turn re-searches with bounded user-hint enrichment from memory.
Default record types: **all published embeddings** in the loaded Cosmos index
(omit / empty `record_types`). Callers may optionally filter. Playbook hits are
citations only. Response includes `answer`, `citations`, `corpus_source`, and
`canonical_images` resolved from top runbook hits. Answers must cite sources.

## Corpus

- **Production:** Azure Cosmos Stage 11 containers (`docs/cosmos_data_map.md`)
- **Runtime corpus:** Cosmos only; local sample-data fallback has been removed.
- Images: prefer step `screens_or_images`; fall back to newest `publish_canonical_images` partition when playbook publish lagged images

## API contract extras

| Field | Owner |
|-------|--------|
| `retrieval_confidence` | retrieval / pin tools |
| `retrieval_confidence_reason` | **orchestrator_agent** |
| `workflow_state.current_node.branch_qualification_metrics` | execute (playbook outcomes only) |
| `workflow_state.path_evidence` | branch matches accumulated this session |
| `workflow_state.runbook.steps[].images` | image_agent (step screens only) |
| `runtime_trace.agents[]` | every agent append |

## UI

Guided Troubleshoot shows confidence + reason, scannable node evidence criteria, a short evidence strip above thin color-coded healthy / unhealthy / inconclusive buttons, runbook under expander with step images, and an interactive playbook graph (node click → detail dialog).
