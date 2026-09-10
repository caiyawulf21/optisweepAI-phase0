# Graph

LangGraph wiring for the playbook runtime. Older case-triage / YAML workflow
graphs were removed; do not reintroduce them.

## Live modules

| File | Role |
|------|------|
| `playbook_graph.py` | State machine for `POST /troubleshoot` + retrieve subgraph |
| `playbook_state.py` | `PlaybookSessionSlice` persisted under `WorkflowSession.dynamic_path.playbook` |

## Entry

`backend/app/runtime/playbook_runtime.py` → `run_playbook_troubleshoot()`, `run_retrieve_chat()`.

Nodes call agents in `backend/app/agents/runtime.py`. Agent roles:
`backend/app/agents/README.md`.

## Leftover

`nodes/` is an empty legacy package (only `__init__.py`). Safe to ignore.
`state.py` is an empty stub from the pre-playbook graph.
