# Future Phase Considerations

## Purpose

This document tracks important architectural and platform directions that are
intentionally deferred until after the following milestones are achieved:

- runtime workflow validation
- guided troubleshooting UX validation
- operator usability testing
- retrieval quality validation
- Phase 0 runtime stabilization

The current priority of the project remains:

- dynamic workflow execution
- session persistence
- guided troubleshooting UX
- runtime reliability
- retrieval correctness
- deterministic escalation

The current priority is **not**:

- advanced platform sophistication

This is a future-planning document only. Nothing described here is implemented,
in progress, or scheduled. Items listed below should only be revisited after
runtime workflow validation and operator usability testing complete.

---

# Future Session Architecture

The current temporary architecture is:

```text
SESSION_BACKEND=memory
INTERACTION_LOG_BACKEND=cosmos
```

This split is intentional because:

- workflow sessions are currently transient to keep runtime iteration fast and
  simple while the troubleshooting UX is still being validated
- interaction logs persist to support audit, debugging, and demo review even
  when sessions themselves are not durable

The intended future direction is:

```text
SESSION_BACKEND=cosmos
INTERACTION_LOG_BACKEND=cosmos
```

Future goals of fully persisted sessions include:

- durable multi-turn troubleshooting sessions
- workflow resumption after backend restart
- multi-user operational support
- auditability
- workflow ownership tracking
- session analytics

Likely future session fields once durable sessions are introduced:

```json
{
  "session_id": "",
  "user_id": "",
  "tenant_id": "",
  "display_name": "",
  "role": "",
  "started_at": "",
  "last_activity_at": "",
  "active_workflow_id": "",
  "status": ""
}
```

This work is intentionally deferred until after runtime validation. Until then,
in-memory sessions plus persisted interaction logs remain the supported
configuration.

---

# Future Authentication / Identity Direction

Future production-oriented deployments are expected to integrate with:

```text
Microsoft Entra ID
```

Potential future capabilities enabled by an Entra-backed identity layer:

- authenticated support users
- role-aware workflow permissions
- workflow ownership
- operator attribution
- escalation attribution
- audit trails tied to authenticated identities
- Teams-integrated identity propagation

The current Phase 0 / demo runtime intentionally avoids enterprise authentication
complexity. Key-based local and development authentication is currently
intentional and is appropriate for the current scope of runtime, UX, and
retrieval validation.

---

# Future Deployment Architecture

The likely future deployment direction is:

```text
Frontend
→ Teams App and/or React Web UI

Backend
→ FastAPI + LangGraph

Hosting
→ Azure Container Apps / Docker containers
```

Potential future additions to the deployment surface:

- containerized runtime
- CI/CD pipeline
- managed identity
- private networking
- autoscaling
- observability stack
- production logging/monitoring

These deployment additions are intentionally deferred beyond the current
runtime validation work. They should not be pursued until after the runtime,
UX, and retrieval validation milestones above are met.

---

# Future Retrieval Architecture Considerations

Retrieval architecture may later evolve beyond the current local BM25 fallback.

The current intended direction is:

```text
Cosmos DB
=
operational persistence layer

Azure AI Search
=
production retrieval layer
```

Potential future retrieval evaluation areas:

- Cosmos-native vector retrieval
- hybrid BM25 + vector search
- semantic ranking
- embedding pipelines
- retrieval quality experimentation

These retrieval directions are intentionally deferred until after:

- workflow UX validation
- operator testing
- retrieval quality evaluation
- production runtime stabilization

---

# Future Operational Intelligence

The following areas are intentionally deferred from the current scope:

- workflow refinement loops
- interaction-driven workflow evolution
- procedure recommendation analytics
- escalation prediction
- duplicate incident detection
- graph-powered reasoning
- knowledge graph query services
- ML classifiers
- autonomous workflow generation

Current priority is validating:

- runtime usability
- deterministic troubleshooting
- operator trust
- guided workflow execution

These intelligence layers should not be introduced until after the above
validation milestones are achieved and the runtime is operationally stable.

---

# Current Recommendation

```text
The project should continue prioritizing:
- runtime workflow execution
- guided troubleshooting UX
- deterministic operational behavior
- retrieval correctness
- operator usability
- traceability

before expanding into:
- advanced retrieval sophistication
- production infrastructure hardening
- graph reasoning
- ML optimization
- autonomous behavior
```
