# Latency / Accuracy Sensitivity Analysis

This note summarizes the main latency knobs in the `/troubleshoot` hot path and the accuracy tradeoffs they introduce.

## Baseline observation

In the current demo configuration, the biggest latency cost is not graph execution itself. The dominant wall time comes from synchronous model calls in sequence:

1. symptom extraction
2. retrieval
3. workflow orchestration / reasoning
4. optional dynamic canonical workflow handling

The measurements taken from the current codebase showed that the retrieval and orchestration stages are the largest contributors when LLM-backed retrieval and workflow reasoning are enabled. Pure graph overhead is comparatively small.

## What `WORKFLOW_REASONING_MAX_TOOL_TURNS` changes

`backend/app/services/workflow_reasoning_agent.py` runs a bounded tool-calling loop:

- each loop can make one model call
- the model may ask for tools
- tool outputs are appended back into the conversation
- the loop repeats until the model emits a final JSON decision or the turn budget is exhausted

Reducing `WORKFLOW_REASONING_MAX_TOOL_TURNS` from `3` to `1` does two things:

- it caps the reasoning agent at one tool round-trip plus one finalization opportunity
- it prevents long tool chains when the model keeps asking for more context

Expected impact:

- lower worst-case latency
- fewer expensive LLM calls
- higher chance that the agent falls back to the deterministic baseline

Accuracy tradeoff:

- the agent has less room to inspect branches, candidates, and node context before deciding
- borderline or ambiguous routing cases are more likely to defer to baseline behavior
- this usually preserves safety, but it can reduce the chance of a model-assisted branch refinement

## What `WORKFLOW_REASONING_SINGLE_SHOT=true` changes

With `WORKFLOW_REASONING_SINGLE_SHOT=true`, the reasoning agent sends the full context packet instead of the smaller seed packet:

- `build_full_packet(context)` instead of `build_seed_payload(context)`
- more routing evidence is present in the first prompt
- the model may need fewer tool calls to reach a decision

Expected impact:

- often fewer follow-up tool requests
- better first-pass grounding
- slightly larger prompt payload per call

Accuracy tradeoff:

- can improve routing accuracy when the model benefits from full context
- can also make the prompt heavier and more expensive per call
- the net effect is usually favorable when paired with a low tool-turn cap

## Recommended low-latency profile

For the lowest practical latency while keeping the reasoning path available:

```text
WORKFLOW_REASONING_MAX_TOOL_TURNS=1
WORKFLOW_REASONING_SINGLE_SHOT=true
```

This profile is a good fit when:

- you want fast operator feedback
- you are comfortable with deterministic fallback when the model cannot decide quickly
- you prefer predictable response times over maximum model-driven routing exploration

## When to relax the settings

Increase `WORKFLOW_REASONING_MAX_TOOL_TURNS` if:

- the model frequently returns incomplete reasoning
- you see too many deterministic fallbacks on legitimate ambiguous cases
- routing quality matters more than latency for a given demo or workflow

Set `WORKFLOW_REASONING_SINGLE_SHOT=false` if:

- you want to minimize prompt size
- you are debugging the tool loop and want a smaller initial context
- you suspect the full packet is adding noise rather than clarity

## Practical interpretation

The main effect of these settings is not on correctness of the deterministic baseline. It is on how often the LLM gets a chance to override or refine that baseline before the request returns.

So the sensitivity curve looks roughly like this:

- lower tool turns: faster, more baseline fallback
- higher tool turns: slower, more chance of nuanced LLM routing
- single shot on: often better first-pass decisions, slightly larger prompt
- single shot off: smaller prompt, more dependence on follow-up tool turns

## Bottom line

If your priority is response time, the new default profile is sensible.

If your priority is maximizing model-assisted reasoning, the main knobs to turn back up are `WORKFLOW_REASONING_MAX_TOOL_TURNS` and, secondarily, `WORKFLOW_REASONING_SINGLE_SHOT=false`.
