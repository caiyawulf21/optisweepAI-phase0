# Streamlit UI

Multi-page app for playbook runtime (Stage 5 / 5b).

## Brand theme

Fortna light theme: black header with FORTNA logo, OptiSweep system hero on
Home, royal-blue primary (`#2B5CFF`), white content, Montserrat/sans-serif.
Config: `.streamlit/config.toml`. Shared CSS / banner: `ui/branding.py`.
Assets: `ui/static/fortna_logo.png`, `ui/static/optisweep_system.png`.

## Run

```bash
streamlit run ui/Home.py
```

Set `API_BASE_URL=http://127.0.0.1:8000` if the backend is not local.

## Pages

| Page | File | API |
|------|------|-----|
| Home | `Home.py` | health check |
| Guided Troubleshoot | `pages/1_Guided_Troubleshoot.py` | `POST /troubleshoot` + embedded `POST /retrieve` |
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
| Conversation | Dual pane: playbook main + Search Chat side panel (collapsible) |
| Turns | Playbook timeline + Search Chat turns (separate session ids) |
| Playbook / Runbook | Interactive playbook graph + node/runbook viewer (`GET /corpus/...`) |
| Trace | Playbook JSON + last Search Chat response + confirmed bridge events |

### Integrated Search Chat panel

On Guided Troubleshoot → Conversation:

```text
Playbook pane                         Search / Ask OptiSweep AI
(progress, node, branch buttons)      (RAG answers + citations)
```

- Search uses a distinct session id (`{troubleshoot_session_id}-search`).
- Requests send compact `search_context` (playbook/node/runbook/symptoms/signals).
- Search always includes Cosmos `operational_context` embeddings for supplemental
  grounding; the UI warns if that type is missing from `/corpus/status`.
- Surfaced playbook and runbook hits render as expandable panels (summary by default;
  preview images when available). Full node/step detail is optional on the standalone
  Search / Chat page.
- Asking a question never mutates playbook/`workflow_state`.
- If the answer maps to an allowed branch value, the UI may show
  **Use this result in current troubleshooting step** — only then is
  `POST /troubleshoot` called with that confirmed value.
- Toggle **Show Search Chat panel** in the sidebar for narrower screens.

## Sidebar (Troubleshoot)

Shows backend URL, Prompt A/B, session ids, Search Chat toggle, and an
**Active playbook** card (title, id, current node, progress) from the latest
troubleshoot response.

## Shared helpers

`playbook_ui.py` — HTTP wrappers for troubleshoot, retrieve, corpus status/viewer,
interaction replay, `render_runbook_panel`, `render_playbook_search_panel`,
`render_operational_context_panel`, `load_runbook_with_images`, Search Chat
source/hit renderers, and `build_search_context_from_troubleshoot`.

## Prompt A / B

Sidebar toggle on Troubleshoot → `playbook_variant` on every request.

Retrieve page: variant filters which playbook embedding type is preferred when
narrowing scope or ranking playbook hits; full-corpus search still includes both.

## Legacy UI

`streamlit_app.py` is the pre-cleanup case-triage console. Use `Home.py` + pages for playbook runtime.
