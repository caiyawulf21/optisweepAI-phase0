# Knowledge Quality Report

Date: 2026-06-03

## Scope

This report summarizes the current quality and gaps across incidents, workflows,
procedures, images, roles, and retrieval/search documents to guide the roadmap
implementation. It is based on the current datasets and runtime mappings in the
repository.

## Data Sources Reviewed

- `data/incidents/canonical_incidents.json`
- `data/workflows/` (legacy and canonical workflow definitions)
- `data/procedures/` (procedure candidates and reusable procedures)
- `data/evidence/source_artifacts.json`
- `data/normalized/canonical_images.json`
- `data/context/context_reference.json`
- Search document mapper: `backend/app/seed/phase1_search_documents.py`
- Canonical image mapper: `backend/app/seed/canonical_images.py`
- Image lookup and ranking: `backend/app/services/canonical_image_lookup.py`
- Role seed loader: `backend/app/seed/role_seed_loader.py`

## High-Impact Gaps

### 1) Visual Evidence Semantics

- Canonical images are generated via fallback inference when no manual
  annotations exist, which produces broad or incorrect labels.
- The canonical image schema supports step/procedure links, but many records
  only link to incidents or have minimal linkage fields.
- Image ranking can surface non-representative screenshots because the linkage
  weights are only reliable when step/procedure IDs are populated.
- The RMS screenshot associated with “no active RMS faults” is a normal
  state-verification image, but current labeling is not guaranteed to preserve
  that meaning.

### 2) Role Metadata Is Not Enforced

- Role seeds exist for L1/L2/L3 and function roles, but runtime behavior does
  not consistently filter instructions based on operator role.
- Procedures and steps carry `role_required` and `support_safe`, but they are
  not used as hard gates in all runtime paths.

### 3) Workflow Maturity Is Mixed

- Legacy workflow YAMLs are used in the hot path.
- Canonical workflow artifacts and plan files exist, but are not always loaded
  due to non-recursive workflow globbing and validation status constraints.

### 4) Retrieval Quality Is Lexical-Only

- The runtime search schema supports `content_vector`, but the Phase 1 mapper
  leaves embeddings unset, so vector retrieval is not active.
- BM25 and deterministic scoring are used instead of hybrid retrieval with
  semantic matching and reranking.

## Per-Domain Findings

### Incidents

- Canonical incidents have symptom and resolution summaries, but negative
  evidence and contradictory cues are not consistently encoded as structured
  fields, which limits case similarity accuracy.

### Procedures

- Procedure candidates and reusable procedures exist, yet their linkage to
  incidents, workflow steps, and images is uneven.
- Evidence references and source artifact links vary by procedure, limiting
  grounding for dynamic guidance.

### Workflows

- Canonical workflow plans and compiled YAMLs coexist with legacy workflows,
  but the runtime primarily uses the legacy set.
- Some canonical workflows are marked `needs_review` or `promoted_for_demo`,
  which should not be treated as execution-ready.

### Images

- Many canonical images are “fallback_only” from source artifacts without
  manual annotation, which makes categories and use cases unreliable.
- `linked_step_ids` and `linked_procedure_ids` are not consistently populated,
  which weakens image ranking in step-level guidance.

### Roles

- Role seeds can enrich records, but role-specific constraints are not enforced
  uniformly across runtime modes.

### Search Documents

- `content_vector` is empty in Phase 1 documents, preventing semantic retrieval.
- Retrieval text is concatenated well, but structured features like components,
  workflow/procedure IDs, and validation status need to be used in reranking.

## Recommended Priority Fixes

1) Create a repeatable canonical image annotation prompt/agent and require
   step/procedure links for “workflow_step_support” images.
2) Enforce role gating in runtime step emission before expanding retrieval
   breadth to avoid unsafe instructions.
3) Populate embeddings and implement hybrid retrieval with structured reranking.
4) Add a separate case-first runtime for matching-case confirmation without
   replacing `/troubleshoot`.

## Planned Follow-ups

- Add validation for contradictory image labels vs. source text.
- Normalize negative evidence fields in incident summaries for better matching.
- Produce a reference glossary for components and systems (RMS/IMS/WCS/etc.).
