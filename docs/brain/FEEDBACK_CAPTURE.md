# OptiSweep App — Feedback Capture & User Images

## Purpose

This app owns runtime feedback capture, turn audit in Cosmos, and user image
attachments (Azure Computer Vision). Brain mutation stays on the **ingestion**
Brain HTTP API — the app never writes `brain_*` containers directly.

Related: [`HTTP_BOUNDARY.md`](HTTP_BOUNDARY.md).

## Locked decisions

- Turn audit: Cosmos `interaction_logs` (`/session_id`), additive fields only.
- Suggestions: Cosmos `feedback_events` (`/session_id`), linked by `interaction_id`.
- Product backends: `INTERACTION_LOG_BACKEND=cosmos`, `FEEDBACK_BACKEND=cosmos` (memory for unit tests).
- Taxonomy: `sentiment` ∈ {`helpful`, `not_helpful`, `suggestion`} free-text otherwise.
- Images: Blob `user-interaction-attachments` → Azure AI Vision → `image_summary` = vision + user description → enriched runtime text.
- Optional Brain forward: when `BRAIN_HTTP_ENABLED` + `BRAIN_HTTP_FEEDBACK`, app persists locally then `POST /brain/v1/feedback`. Otherwise `brain_handoff_status` stays deferred / not forwarded.

## Flow

```text
User text + image(s)
  → POST /attachments/upload (Blob + CV + image_summary)
  → POST /troubleshoot | /retrieve with attachment_ids
  → enriched_user_message drives runtime
  → InteractionLog in Cosmos
User feedback (+ optional images)
  → same vision path
  → FeedbackEvent in Cosmos
```

## Contracts

### InteractionLog (additive)

`surface`, `playbook_id`, `runbook_id`, `node_id`, `record_ids`, `attachment_ids`, `image_summaries`, `enriched_user_message`, `feedback_event_ids`.

### FeedbackEvent

`feedback_id`, `session_id`, `interaction_id`, `surface`, `sentiment`, `about`, `targets`, `user_text`, `proposed_change`, `attachment_ids`, `image_summaries`, `context_snapshot`, `status=captured`, `brain_handoff_status=deferred`, `brain_review_id=null`.

### Attachment

`attachment_id`, blob refs, `user_description`, `vision` {caption, ocr_text, tags}, `image_summary`, `vision_status`.

## APIs

| Method | Path |
|---|---|
| POST | `/attachments/upload` |
| GET | `/attachments/{attachment_id}` |
| POST | `/attachments/summarize` |
| POST | `/feedback` |
| GET | `/feedback/sessions/{session_id}` |

Troubleshoot/retrieve responses include `interaction_id`. Requests accept `attachment_ids`.

## Env

```text
INTERACTION_LOG_BACKEND=cosmos
FEEDBACK_BACKEND=cosmos
AZURE_COSMOS_* (existing)
AZURE_STORAGE_CONNECTION_STRING or AZURE_STORAGE_ACCOUNT_URL
AZURE_USER_ATTACHMENTS_CONTAINER=user-interaction-attachments
AZURE_VISION_ENDPOINT
AZURE_VISION_KEY
```

## Brain later

Optional forward is implemented when `BRAIN_HTTP_ENABLED` + `BRAIN_HTTP_FEEDBACK`
are on (`POST /brain/v1/feedback`). App still never writes Entity/Claim/`brain_*`
storage directly. SME approval happens on the SME Review page via Brain resolve.
UI-facing loop: [`../../ui/README.md`](../../ui/README.md#brain--continuous-learning-handoff).
