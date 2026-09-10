# Documentation

Current docs only. Historical Phase 0 plans, YAML/CAT-1 architecture notes,
status trackers, and the old `app_handoff_package/` migration bundle were
removed for handoff clarity.

## Start here

1. [`../README.md`](../README.md) — product overview, quick start, repo map
2. [`../AZURE_ACCOUNT_HANDOFF.md`](../AZURE_ACCOUNT_HANDOFF.md) — move Azure ownership / greenfield bring-up
3. [`INGESTION_DEPENDENCIES.md`](INGESTION_DEPENDENCIES.md) — Stage 11 publish, embeddings, Brain HTTP (required sibling repo)
4. [`PLAYBOOK_RUNTIME.md`](PLAYBOOK_RUNTIME.md) — LangGraph + agents for `/troubleshoot` and `/retrieve`
5. [`cosmos_data_map.md`](cosmos_data_map.md) — Cosmos containers and publish model
6. [`../ui/README.md`](../ui/README.md) — Streamlit UI, backends, Brain learning UX

## Corpus & retrieval

Depends on the **ingestion** Stage 11 publish — see
[`INGESTION_DEPENDENCIES.md`](INGESTION_DEPENDENCIES.md) before debugging empty
corpus issues in this repo alone.

| Doc | Contents |
|-----|----------|
| [`cosmos_data_map.md`](cosmos_data_map.md) | Containers, partition keys, publish version |
| [`cosmos_record_types.md`](cosmos_record_types.md) | Record / payload field mapping |
| [`cosmos_corpus_queries.md`](cosmos_corpus_queries.md) | Example Cosmos SQL |
| [`retrieval_algorithms.md`](retrieval_algorithms.md) | Hybrid scoring (no Azure AI Search) |
| [`app_agent_scoring_handoff.md`](app_agent_scoring_handoff.md) | Thresholds and scoring smoke notes |

## Brain HTTP (optional overlay)

Brain HTTP is hosted by the **ingestion** repo. This app is a client only.

| Doc | Contents |
|-----|----------|
| [`brain/HTTP_BOUNDARY.md`](brain/HTTP_BOUNDARY.md) | Locked app ↔ Brain HTTP contract |
| [`brain/FEEDBACK_CAPTURE.md`](brain/FEEDBACK_CAPTURE.md) | Local feedback/attachments + Brain handoff |

Enable with `BRAIN_HTTP_*` in `.env.example`. Defaults are **off**; publish-corpus
playbook runtime stays primary until Brain is validated in UI. Against Brain
HTTP **v4**, set `BRAIN_HTTP_TIMEOUT_SECONDS=90` (cold ~40–50s, warm ~2s).
Contract details: [`brain/HTTP_BOUNDARY.md`](brain/HTTP_BOUNDARY.md).

## Code READMEs

| Path | Focus |
|------|-------|
| [`../ui/README.md`](../ui/README.md) | Streamlit pages, backends, Brain UX, screenshots |
| [`../backend/app/agents/README.md`](../backend/app/agents/README.md) | Agent roles + lean LLM policy |
| [`../backend/app/graph/README.md`](../backend/app/graph/README.md) | Playbook graph entry |
| [`../backend/app/corpus/README.md`](../backend/app/corpus/README.md) | Cosmos corpus module |
