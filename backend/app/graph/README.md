# Graph

## `playbook_graph.py`

LangGraph state machine for `POST /troubleshoot`.

Nodes map to agents in `backend/app/agents/runtime.py`.

State type: `dict` with `PlaybookSessionSlice` at `_playbook_slice` during execution.

## `playbook_state.py`

`PlaybookSessionSlice` — slim session schema persisted under `WorkflowSession.dynamic_path.playbook`.

## Entry

`backend/app/runtime/playbook_runtime.py` → `run_playbook_troubleshoot()`, `run_retrieve_chat()`.
