# App agent handoff — entry-scoped playbook scoring (Jul 13, 2026; cumulative republish Jul 21)

**Audience:** OptiSweep AI app-repo coding agent  
**Ingestion repo:** `optisweepAI-ingestion`  
**Read with:** `docs/cosmos_data_map.md`, `docs/retrieval_algorithms.md`, `backend/app/retrieval/hybrid_retriever.py`

---

## Point the app here
    10|
| Setting | Value |
|---------|-------|
| `PUBLISH_VERSION_ID` | `publish_20260722_000304_b57a7153` |
| Manifest | `shared_pipeline_stages/data/output/shared/stage_11_cosmos_publish/publish_manifest.json` |
| Embedding model (query + docs) | `text-embedding-3-small` (must match Cosmos `embedding_model`) |
| Cosmos | Already published (`Uploaded to Cosmos: True`) — reload index for this version |

Containers (unchanged env names): `COSMOS_CONTAINER_PLAYBOOKS_A` / `_B`, `COSMOS_CONTAINER_RUNBOOKS`, `COSMOS_CONTAINER_RELATIONSHIP_LINKS`, etc.

    20|Playbook `embedded_text` in this version is **entry-scoped only** (title + `observed_entry_symptoms` + `support_user_language_examples`). Do not expect fat narrative blobs.

**Cumulative corpus (required):** newest publish must retain prior cases (at least `218550`, `223554`, `228086`, `228723`). Do not pin the app to an old version to paper over a thin publish. Verify with `python -m backend.app.scripts.verify_cosmos_corpus`.

**Operator speech lives on playbook cards** for retrieval scoring. **First-turn symptoms** live in Cosmos `gate_phrase_tables` (`id=gate_phrases`, same `publish_version_id`). Keys are symptom ids (whatever ingest publishes), not a CAT taxonomy. On corpus reload the app installs `KeywordSignalExtractor.from_phrases(...)` from that doc; committed YAML is **fallback only**. Root-cause classification is deferred (future ML/DL), not part of the gate.

---

## What ingestion changed

1. **Stage 8 embed text** (`shared_pipeline_stages/stage_8/playbook_retrieval.py` → `build_playbook_retrieval_text`)  
   Playbook vectors = title + entry symptoms + user-language examples. Dropped: summary, systems list, node/recovery language.

2. **Stage 5 / Stage 8 operator-language enrichment**  
   Require short operator speech in `support_user_language_examples` (e.g. `"AGVs stopped"`, `"robots stopped"`, `"nothing is moving"`, `"AGVs aren't moving"`, `"rms showing no alarms"`).

3. **Stage 11 cumulative publish**  
   Assemble → merge prior corpus + enrich all playbooks → gate + smoke → `data/output/cosmos_publish`. `publish_cosmos` forces `scope=all` so newest partitions are not thin pilots.

4. **Runtime scoring reference** (`backend/app/retrieval/hybrid_retriever.py`, `docs/retrieval_algorithms.md`)  
   Symptom boost uses phrase containment + damped coverage (see critique below).

---
## Test results (`"agvs stopped"`, real Azure embeddings, post-republish)

Raw components (before dampening fix) on live Stage 10 vectors:

| Variant | Top playbook | cosine | jaccard | raw best-phrase | phrase coverage |
|---------|--------------|--------|---------|-----------------|-----------------|
| A | `playbook_incident_228086_site_wide_motion_stoppage_service_recovery` | ~0.51 | ~0.04 | **1.00** (exact example) | ~0.31 |
| A | 228723 pairing | ~0.41 | ~0.02 | ~0.08 | ~0.12 |
| B | `playbook_incident_228086_site_stoppage_optisweep_recovery` | ~0.49 | ~0.04 | **1.00** | ~0.35 |
| B | 228723 / WCS | ≤0.31 hybrid | — | 0 | 0 |

**Before ingestion change:** sparse query scored ~0.01 (fat doc + missing operator phrases).  
**After:** cosine ~0.5; exact example phrase hit; stoppage clearly ranks above pairing.

With **damped** symptom formula (`0.70 * best + 0.30 * coverage`), re-measured:

| Variant | Top | combined | cosine | symptom | coverage |
|---------|-----|----------|--------|---------|----------|
| A | 228086 stoppage | **0.79** | 0.51 | 0.79 | 0.31 |
| A | 228723 pairing | 0.30 | 0.41 | 0.09 | 0.13 |
| B | 228086 stoppage | **0.81** | 0.49 | 0.81 | 0.35 |
| B | 228723 | 0.31 | 0.45 | 0.00 | 0.00 |

Stoppage clears pin (≥0.80) and high-confidence (≥0.90) with coverage ≥0.40. Pairing stays candidates/ask — not pin. Combined is **high, not 1.0**.

Threshold philosophy (do not change to fit old 0.01):

| Band | Behavior |
|------|----------|
| `< ~0.35` | Ask symptoms / weak related |
| `~0.35–0.80` | Candidates only; user picks |
| `≥ 0.80` **and** coverage ≥ ~0.40 | Auto-pin allowed (when confirmation skipped) |
| `≥ 0.75` + coverage | High-confidence auto-pin |

---

## Product critique (implement in app)

> Confidence should **not** be exactly 1.0 when the query only matches one entry phrase. High is fine; perfect is wrong.

**Required app scoring behavior**

```python
best_phrase = max(containment(query, phrase), Jaccard(query, phrase))  # containment = |q∩p|/|p|
coverage    = (query tokens covered by any entry phrase) / (query tokens)
symptom     = 0.70 * best_phrase + 0.30 * coverage
rank_score  = max(0.7 * cosine + 0.3 * jaccard, symptom)

auto_pin = rank_score >= 0.80 and coverage >= 0.40   # or user picks
# do NOT: lower thresholds, relative-pin best-of-bad, or score = 0.5 + 0.5 * score
```

**Trace tab must show separately:** `cosine`, `jaccard`, `symptom`, `coverage`, `combined` — so SMEs see that a single exact phrase match is high (~0.75–0.85) but not absolute certainty.

Pin confidence ≠ retrieval rank: sparse speech can improve ranking and still fail the pin gate until coverage / user confirmation is enough.

---

## App work checklist

1. Set `PUBLISH_VERSION_ID=publish_20260722_000304_b57a7153` (or keep `AUTO_PUBLISH_VERSION=true`) and reload Cosmos embedding index.
2. Keep damped `symptom_overlap_score` + `entry_phrase_coverage` aligned with `backend/app/retrieval/hybrid_retriever.py`.
3. Wire pin gate: hybrid/rank ≥ 0.80 **and** coverage ≥ 0.40 (or explicit candidate pick).
4. Expose score breakdown in Trace.
5. Smoke: `"AGVs stopped"` → 228086 stoppage playbook (A and B); `"zone can't pair"` → 228723; Trace shows combined ≈ **0.79–0.81** (not 1.0) for this sparse query.
6. Confirm query embed deployment = `text-embedding-3-small`.

---

## Out of scope for this handoff

- Do not re-lower pin thresholds.
- Do not read `sample_data/` as runtime corpus (deprecated).
- Do not add Azure AI Search.
- Full narrative / `playbook_*_full` dual vectors — later; not required for Jul demo.
