# Streamlit UI

Multi-page app for playbook runtime (Stage 5 / 5b).

## Run

```bash
streamlit run ui/Home.py
```

Set `API_BASE_URL=http://127.0.0.1:8000` if the backend is not local.

## Pages

| Page | File | API |
|------|------|-----|
| Home | `Home.py` | health check |
| Guided Troubleshoot | `pages/1_Guided_Troubleshoot.py` | `POST /troubleshoot` |
| Search / Chat | `pages/2_Search_Chat.py` | `POST /retrieve` |

## Tabs (Search / Chat)

| Tab | Purpose |
|-----|---------|
| Conversation | Answer + mandatory **Sources** citations + reference images + troubleshoot-style runbook panels + operational-context expanders |
| Turns | Operator timeline from retrieve interaction logs |
| Trace | Raw JSON debug (`hits`, scores, runtime_trace) |

Sidebar: backend URL, `GET /corpus/status`, optional scope filter,
session id. **Default search scope is all published Cosmos embeddings** (omit
`record_types`). Uncheck “Search all…” only to narrow types. Hybrid scores are
relative rank (`0.7×cosine + 0.3×jaccard`), not confidence percentages.

Citations are always shown in Conversation when hits exist — not only in Trace.
Runbook/context panels are additive detail under Sources.

## Tabs (Troubleshoot)

| Tab | Purpose |
|-----|---------|
| Conversation | Chat + current-node playbook summary + branch cards/buttons (colored) + runbook steps/images |
| Turns | Operator timeline from interaction logs + agent steps |
| Playbook / Runbook | Interactive playbook graph + node/runbook viewer (`GET /corpus/...`) |
| Trace | Raw JSON debug |

## Sidebar (Troubleshoot)

Shows backend URL, Prompt A/B, session id, and an **Active playbook** card
(title, id, current node, progress) from the latest troubleshoot response.

## Shared helpers

`playbook_ui.py` — HTTP wrappers for troubleshoot, retrieve, corpus status/viewer,
interaction replay, `render_runbook_panel`, `render_operational_context_panel`,
and `load_runbook_with_images`.

## Prompt A / B

Sidebar toggle on Troubleshoot → `playbook_variant` on every request.

Retrieve page: variant filters which playbook embedding type is preferred when
narrowing scope or ranking playbook hits; full-corpus search still includes both.

## Legacy UI

`streamlit_app.py` is the pre-cleanup case-triage console. Use `Home.py` + pages for playbook runtime.
