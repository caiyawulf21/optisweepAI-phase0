# Retrieval algorithms — Cosmos vectors, no Azure AI Search

## Architecture

```text
Startup:
  Query Cosmos → load all doc_type=embedding for active PUBLISH_VERSION_ID
  Query Cosmos → load all doc_type=relationship_graph shards, merge links[]
  Hold in memory (~2-10 MB for current corpus)

Turn 1 (no pinned playbook):
  Embed user query via Azure OpenAI (same model as Stage 10)
  Brute-force hybrid score over playbook embeddings (container A or B)
  Pin playbook on match

Turn 2+ (pinned playbook):
  Cosmos get doc_type=playbook by record_id          — O(1)
  Resolve runbook from resolved_runbook_ids or link graph — O(1)
  Cosmos get doc_type=runbook by record_id           — O(1)
  Zero vector searches
```

**There is no Azure AI Search.** Do not add it. Cosmos is the vector store.

---

## Hybrid score (mandatory)

```python
cosine  = cosine_similarity(query_vector, doc.vector)
jaccard = token_jaccard(query_text, doc.embedded_text)
combined = 0.7 * cosine + 0.3 * jaccard
```

Tokenization: lowercase alphanumeric tokens, drop stopwords (`a`, `the`, `for`, ...).  
See `backend/app/retrieval/hybrid_retriever.py` for the runtime implementation.

### Symptom phrase boost (playbooks only)

After hybrid score, compute overlap against `payload.observed_entry_symptoms` + `support_user_language_examples`.

**Do not** use raw best-phrase Jaccard alone — an exact match on one example (e.g. `"AGVs stopped"`) yields Jaccard 1.0 and falsely implies perfect confidence.

```python
best_phrase = max(token_jaccard(query, phrase) for phrase in symptoms + examples)
coverage    = matched_entry_phrases / total_entry_phrases   # phrase has any token overlap
symptom     = 0.70 * best_phrase + 0.30 * coverage
combined    = max(combined, symptom)
```

Example: `"agvs stopped"` vs stoppage card with one exact example among ~13 entry phrases → `best≈1.0`, `coverage≈0.3` → `symptom≈0.79` (high, not 1.0). More matched entry phrases raise the score toward high-confidence territory.

Hybrid / symptom is a **rank** among candidates. It is not by itself permission to auto-pin.

### Mixed embedding families (important)

Published sample/dev corpora may mix `text-embedding-3-small` (e.g. 1536-dim playbooks)
with `mock-hash-v1` (e.g. 64-dim runbooks). Comparing one query vector across both families
zeros cosine on dimension mismatch and leaves `combined ≈ 0.3 × jaccard` (~0.005–0.02 for
short queries). `HybridRetriever` re-aligns mock-hash records by synthesizing a matching-dim
mock query vector per record so runbook cosine stays meaningful.

---

## Playbook entry embed contract (ingestion Stage 8 → 10)

Sparse queries like `"agvs stopped"` score ~0.01 against fat playbook blobs because Stage 8 historically concatenated title + summary + systems + systems + recovery language into `retrieval_text` / `embedded_text`. Jaccard collapses (1–2 hits over a huge token union); cosine compares a short query to an averaged long narrative.

**Required `embedded_text` for `record_type=playbook_prompt_*`:**

```text
<title>
<observed_entry_symptoms joined>
<support_user_language_examples joined>
```

**Do not concatenate into playbook vectors:** `user_facing_summary`, node intents / node `retrieval_text`, runbook placeholders, recovery procedures, or `affected_systems_or_components` laundry lists.

Builder: `shared_pipeline_stages/stage_8/playbook_retrieval.py` → `build_playbook_retrieval_text`. Stage 10 embeds card `retrieval_text` as-is.

**Operator speech on cards (critical):** Stage 5 must put short caller phrases in `support_user_language_examples` (e.g. `"AGVs stopped"`, `"AGVs are stopped"`, `"robots stopped"`, `"nothing is moving"`). Without those phrases in the card and/or embed text, sparse operator queries never get a strong lexical/semantic hit — even with a thinner embed.

Optional later: a second `playbook_*_full` vector for SME search. Not required for v1.

After changing embed text or examples: republish Stage 10 → 11 with a new `PUBLISH_VERSION_ID`, then re-measure with Trace breakdown (`cosine`, `jaccard`, `symptom_overlap`). Expect stoppage playbooks to rise on `"agvs stopped"` without globally lowering pin thresholds.

---

## Thresholds

Keep two notions of confidence separate:

| Band / gate | Value | Behavior |
|-------------|-------|----------|
| Weak / ask | `< ~0.35` | Ask for correlated symptoms; optional weak related list |
| Candidates only | `~0.35–0.80` | Show candidates; user picks — no auto-pin (default path) |
| `PLAYBOOK_MATCH_THRESHOLD` | `0.80` | Eligible for pin **only with coverage** (below) |
| `PLAYBOOK_HIGH_CONFIDENCE_THRESHOLD` | `0.90` | High-confidence band when coverage also passes |
| `PLAYBOOK_PIN_COVERAGE_THRESHOLD` | `0.40` | Entry-phrase coverage floor for pin eligibility |
| Runbook fallback `min_score` | `0.35` | When no playbook matches |

### Pin vs rank (no fake boosts)

Do **not:** lower the pin bar to fit ~0.01 scores, relative-pin “best of a bad lot,” or inflate with `score = 0.5 + 0.5 * score`.

Do treat hybrid as rank, and gate auto-pin on entry-phrase coverage:

```python
coverage = matched_entry_phrases / total_entry_phrases
# or: fraction of query tokens covered by the entry card bag
auto_pin = hybrid >= 0.80 and coverage >= 0.40   # floor is tunable
# OR user explicitly selects a candidate
```

That stops `"AGVs stopped"` from auto-pinning a playbook that only shares the token `agvs`. Surfacing candidates / asking for more symptoms improves ranking while still failing the pin gate when coverage is thin.

Trace should expose `cosine`, `jaccard`, `symptom_overlap`, and optionally `coverage` separately.

---

## Container routing

| Step | Cosmos container | Filter |
|------|------------------|--------|
| Playbook search (variant A) | `COSMOS_CONTAINER_PLAYBOOKS_A` | `doc_type=embedding`, `record_type=playbook_prompt_a` |
| Playbook search (variant B) | `COSMOS_CONTAINER_PLAYBOOKS_B` | `record_type=playbook_prompt_b` |
| Runbook fallback | `COSMOS_CONTAINER_RUNBOOKS` | `record_type=canonical_runbook` |
| Playbook document | A or B container | `doc_type=playbook` |
| Runbook document | `COSMOS_CONTAINER_RUNBOOKS` | `doc_type=runbook` |
| Link graph | `COSMOS_CONTAINER_RELATIONSHIP_LINKS` | `doc_type=relationship_graph` |

All queries include `publish_version_id = @PUBLISH_VERSION_ID`.

---

## Node → runbook resolution (not retrieval)

**Do not vector-search for procedures.** Use precomputed links from Shared Stage 8:

1. `playbook.payload.nodes[i].resolved_runbook_ids[0]`
2. Else relationship link: `playbook_runbook`, `source_record_id = "{playbook_id}:{node_id}"`, lowest `link_rank`
3. Else `playbook.payload.nodes[i].runbook_links[0].procedure_id`

Ingestion already ran `RunbookCatalogSearch` + `link_scoring.py` offline. Runtime must not repeat this.

---

## Query embedding rules

| Rule | Detail |
|------|--------|
| Model match | Query embed deployment **must equal** `embedding_model` in Cosmos docs |
| On mismatch | Refuse startup or log fatal — cosine scores are meaningless |
| Cache | Cache query vectors per session turn hash if needed |
| No embed on turn 2+ | Session already pinned — skip embedding entirely |

---

## Latency budget

| Operation | Target |
|-----------|--------|
| Cosmos embedding index load (startup) | < 2s |
| Query embed (Azure) | < 300ms |
| Brute-force scan ~500 vectors | < 50ms |
| Playbook + runbook ID fetch | < 50ms each |
| **Turn 1 total** | < 500ms |
| **Turn 2+ total** | < 100ms |

When corpus exceeds ~5000 embeddings, add Cosmos vector index policy or shard by record_type. Still not Azure AI Search unless explicitly provisioned later.

---

## Delete these retrieval paths

| Path | Action |
|------|--------|
| `RETRIEVAL_BACKEND=local` (CAT-1) | Delete |
| `RETRIEVAL_BACKEND=azure_search` | Delete |
| `RETRIEVAL_BACKEND=local_bm25_agent` | Delete |
| `RETRIEVAL_BACKEND=local_files` / `sample_data/` | Delete |
| `root_cause_vectors` Cosmos/local index | Delete |
| `DynamicProcedureSelector` runtime scoring | Delete |
| `canonical_images.json` ranking | Delete — use link graph |

---

## Offline vs runtime (ingestion pipeline)

| Ingestion (offline) | App (runtime) |
|---------------------|---------------|
| Stage 10: embed all records → Cosmos | Load vectors from Cosmos |
| Stage 8: link playbooks to runbooks | Read `resolved_runbook_ids` / graph |
| Stage 6.5: merge runbooks | Already in canonical runbook docs |
| Stage 8 `link_scoring.py` heuristics | **Never run at request time** |

---

## Reference code

- Scoring: `backend/app/retrieval/hybrid_retriever.py`
- Queries: `docs/cosmos_corpus_queries.md`
- Storage: `docs/cosmos_data_map.md`
